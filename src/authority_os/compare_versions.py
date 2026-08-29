"""Run one controlled local V0 vs V1 quality comparison.

The comparison is deliberately local-only. The same research import, strategy input,
topic, goal, and optional proof are copied into two detached Git worktrees. Each
version receives its own private SQLite database and output directory. Results are
copied back under ignored ``data/private/v0-v1-comparisons``.

This helper never publishes, records performance, changes a Git ref, or declares a
quality winner. It exists to make a PM-facing side-by-side review reproducible.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import workflow

DEFAULT_V0_REF = "baseline/v0-pre-eval-v1"
DEFAULT_V1_REF = "main"
COMPARISON_ROOT = workflow.DEFAULT_PRIVATE_DATA / "v0-v1-comparisons"
VALID_GOALS = tuple(workflow.STRATEGIC_GOALS)
VALID_FORMATS = tuple(workflow.OUTPUT_FORMATS)
_PACKAGE_LINE = re.compile(r"(?m)^Content package:\s+([^\r\n]+)$")
_RECOMMENDATION_LINE = re.compile(
    r"(?m)^Recommended candidate for human review:\s+([^\r\n]+)$"
)
_SCORE_LINE = re.compile(
    r"(?m)^Critic score:\s+id=([^;]+);\s+(.*?);\s+raw_total=(\d+);\s+"
    r"effective_total=(\d+);\s+band=([^.]+)\.\s*$"
)


class ComparisonError(RuntimeError):
    """Safe, actionable comparison-runner failure."""


@dataclass(frozen=True, slots=True)
class VersionRun:
    label: str
    ref: str
    commit_sha: str
    package_source: str
    recommendation: str | None
    score_lines: tuple[str, ...]
    output_dir: Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ComparisonError("Comparison input could not be read.") from exc
    return digest.hexdigest()


def _regular_input(path: Path | str, *, label: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    try:
        metadata = candidate.stat()
    except OSError as exc:
        raise ComparisonError(f"{label} is unavailable.") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0:
        raise ComparisonError(f"{label} must be a non-empty regular file.")
    return candidate


def _run(
    command: Sequence[str],
    *,
    cwd: Path,
    log_path: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        raise ComparisonError("A required local comparison command could not start.") from exc
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            log_path.write_text(completed.stdout, encoding="utf-8")
            os.chmod(log_path, 0o600)
        except OSError as exc:
            raise ComparisonError("Comparison log could not be written privately.") from exc
    if check and completed.returncode != 0:
        raise ComparisonError(
            f"Comparison command failed with exit code {completed.returncode}. "
            f"Inspect {log_path.name if log_path else 'the local command output'}."
        )
    return completed


def _git(root: Path, *arguments: str) -> str:
    completed = _run(("git", *arguments), cwd=root)
    if completed.returncode != 0:
        raise ComparisonError("Git could not prepare the controlled comparison.")
    return completed.stdout.strip()


def resolve_ref(root: Path, ref: str) -> str:
    if not isinstance(ref, str) or not ref.strip():
        raise ComparisonError("Comparison Git refs must be non-blank.")
    sha = _git(root, "rev-parse", "--verify", f"{ref.strip()}^{{commit}}")
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise ComparisonError("Comparison Git ref did not resolve to one commit.")
    return sha


def build_research_command(*, topic: str, private_research: str) -> tuple[str, ...]:
    return (
        "./bin/linkedin-os",
        "research",
        "--input",
        private_research,
        "--topic",
        topic,
    )


def build_draft_command(
    *,
    topic: str,
    goal: str,
    private_strategy: str,
    output_format: str | None = None,
    week_slot: int | None = None,
    strong_current_signal: bool = False,
    private_proof: str | None = None,
) -> tuple[str, ...]:
    command: list[str] = [
        "./bin/linkedin-os",
        "draft",
        "--topic",
        topic,
        "--goal",
        goal,
        "--strategy-input",
        private_strategy,
        "--allow-model-egress",
        "--package",
    ]
    if output_format:
        command.extend(("--format", output_format))
    if week_slot is not None:
        command.extend(("--week-slot", str(week_slot)))
    if strong_current_signal:
        command.append("--strong-current-signal")
    if private_proof:
        command.extend(("--proof-manifest", private_proof))
    return tuple(command)


def extract_package_path(stdout: str) -> str:
    matches = _PACKAGE_LINE.findall(stdout)
    if len(matches) != 1:
        raise ComparisonError("Draft output did not identify exactly one content package.")
    value = matches[0].strip()
    if not value or Path(value).is_absolute() or ".." in Path(value).parts:
        raise ComparisonError("Draft output returned an unsafe content-package path.")
    return value


def summarize_draft_log(stdout: str) -> tuple[str | None, tuple[str, ...]]:
    recommendation_matches = _RECOMMENDATION_LINE.findall(stdout)
    recommendation = (
        recommendation_matches[0].strip() if len(recommendation_matches) == 1 else None
    )
    score_lines = tuple(
        f"{candidate.strip()}: {axes.strip()}; raw={raw}; effective={effective}; band={band.strip()}"
        for candidate, axes, raw, effective, band in _SCORE_LINE.findall(stdout)
    )
    return recommendation, score_lines


def _copy_private_file(source: Path, destination: Path) -> None:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        shutil.copyfile(source, destination)
        os.chmod(destination, 0o600)
    except OSError as exc:
        raise ComparisonError("Comparison input could not be staged privately.") from exc


def _copy_tree_private(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ComparisonError("Expected comparison package directory is unavailable.")
    try:
        shutil.copytree(source, destination)
        for root, directories, files in os.walk(destination):
            os.chmod(root, 0o700)
            for name in directories:
                os.chmod(Path(root) / name, 0o700)
            for name in files:
                os.chmod(Path(root) / name, 0o600)
    except OSError as exc:
        raise ComparisonError("Comparison package could not be copied privately.") from exc


def _prepare_result_root(root: Path) -> None:
    try:
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        os.chmod(root, 0o700)
    except OSError as exc:
        raise ComparisonError("Comparison result directory could not be created.") from exc


def _provider_preflight() -> None:
    missing = [name for name in ("codex",) if shutil.which(name) is None]
    if missing:
        raise ComparisonError(
            "Live comparison requires the Codex CLI used by both comparison versions. Missing: "
            + ", ".join(missing)
            + ". Authenticate them locally before running the comparison."
        )


def _install_worktree(root: Path, *, sha: str, destination: Path) -> None:
    completed = _run(
        ("git", "worktree", "add", "--detach", str(destination), sha),
        cwd=root,
        check=False,
    )
    if completed.returncode != 0:
        raise ComparisonError("Git could not create an isolated comparison worktree.")


def _remove_worktree(root: Path, destination: Path) -> None:
    _run(
        ("git", "worktree", "remove", "--force", str(destination)),
        cwd=root,
        check=False,
    )


def _run_version(
    *,
    label: str,
    ref: str,
    commit_sha: str,
    worktree: Path,
    result_root: Path,
    research_input: Path,
    strategy_input: Path,
    proof_input: Path | None,
    topic: str,
    goal: str,
    output_format: str | None,
    week_slot: int | None,
    strong_current_signal: bool,
) -> VersionRun:
    private_root = worktree / "data" / "private" / "comparison-input"
    research_dest = private_root / "research.json"
    strategy_dest = private_root / "strategy.json"
    proof_dest = private_root / "proof.json" if proof_input else None
    _copy_private_file(research_input, research_dest)
    _copy_private_file(strategy_input, strategy_dest)
    if proof_input is not None and proof_dest is not None:
        _copy_private_file(proof_input, proof_dest)

    version_result = result_root / label
    version_result.mkdir(mode=0o700)
    os.chmod(version_result, 0o700)

    _run(("./bin/linkedin-os", "init"), cwd=worktree, log_path=version_result / "init.log")
    _run(
        build_research_command(
            topic=topic,
            private_research="data/private/comparison-input/research.json",
        ),
        cwd=worktree,
        log_path=version_result / "research.log",
    )
    draft_log = version_result / "draft.log"
    completed = _run(
        build_draft_command(
            topic=topic,
            goal=goal,
            private_strategy="data/private/comparison-input/strategy.json",
            output_format=output_format,
            week_slot=week_slot,
            strong_current_signal=strong_current_signal,
            private_proof=(
                "data/private/comparison-input/proof.json" if proof_dest else None
            ),
        ),
        cwd=worktree,
        log_path=draft_log,
    )
    package_relative = extract_package_path(completed.stdout)
    package_source = worktree / package_relative
    _copy_tree_private(package_source, version_result / "package")

    eval_source = worktree / "data" / "private" / "v1-evals"
    if eval_source.is_dir():
        _copy_tree_private(eval_source, version_result / "v1-evals")

    recommendation, score_lines = summarize_draft_log(completed.stdout)
    return VersionRun(
        label=label,
        ref=ref,
        commit_sha=commit_sha,
        package_source=package_relative,
        recommendation=recommendation,
        score_lines=score_lines,
        output_dir=version_result,
    )


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def build_manifest(
    *,
    run_id: str,
    topic: str,
    goal: str,
    output_format: str | None,
    research_sha256: str,
    strategy_sha256: str,
    proof_sha256: str | None,
    versions: Sequence[VersionRun],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "topic": topic,
        "goal": goal,
        "output_format": output_format,
        "inputs": {
            "research_sha256": research_sha256,
            "strategy_sha256": strategy_sha256,
            "proof_sha256": proof_sha256,
        },
        "versions": [
            {
                "label": item.label,
                "ref": item.ref,
                "commit_sha": item.commit_sha,
                "package_source": item.package_source,
                "recommendation": item.recommendation,
                "score_lines": list(item.score_lines),
            }
            for item in versions
        ],
        "winner": None,
        "winner_policy": "human-product-review-required",
    }


def render_comparison_markdown(manifest: Mapping[str, object]) -> str:
    versions = manifest.get("versions")
    if not isinstance(versions, Sequence) or len(versions) != 2:
        raise ComparisonError("Comparison manifest needs exactly two version runs.")
    lines = [
        "# V0 vs V1 LinkedIn quality comparison",
        "",
        "This is a controlled comparison: both versions received the same research, strategy, topic, and goal.",
        "No automatic winner is declared; review the writing and eval evidence side by side.",
        "",
        f"- Topic: `{manifest.get('topic', '')}`",
        f"- Goal: `{manifest.get('goal', '')}`",
        f"- Research SHA-256: `{manifest.get('inputs', {}).get('research_sha256', '') if isinstance(manifest.get('inputs'), Mapping) else ''}`",
        f"- Strategy SHA-256: `{manifest.get('inputs', {}).get('strategy_sha256', '') if isinstance(manifest.get('inputs'), Mapping) else ''}`",
        "",
        "| Version | Ref | Commit | Recommendation |",
        "|---|---|---|---|",
    ]
    for raw in versions:
        if not isinstance(raw, Mapping):
            raise ComparisonError("Comparison manifest version entry is malformed.")
        lines.append(
            f"| {raw.get('label', '')} | `{raw.get('ref', '')}` | `{str(raw.get('commit_sha', ''))[:12]}` | "
            f"{raw.get('recommendation') or 'none'} |"
        )
    lines.extend(
        [
            "",
            "## Inspect these artifacts",
            "",
            "- `v0/package/candidates.md` — V0 final candidate set.",
            "- `v1/package/candidates.md` — V1 final candidate set.",
            "- `v0/draft.log` and `v1/draft.log` — stage output and Critic scores.",
            "- `v1/v1-evals/` — V1 contract evidence when generated.",
            "",
            "## Product review questions",
            "",
            "1. Which version delivers a clearer single atomic value?",
            "2. Which opening earns attention without manufactured hype?",
            "3. Which body provides more useful mechanism, trade-off, or decision depth?",
            "4. Which version sounds more like the intended human voice and contains less AI-slop?",
            "5. Are factual claims easier to inspect and trace in V1?",
            "6. Did V1 block or reshape anything that V0 would have allowed? Was that improvement justified?",
            "7. Would you publish either candidate unchanged? Why?",
            "",
            "## Critic summaries",
            "",
        ]
    )
    for raw in versions:
        assert isinstance(raw, Mapping)
        lines.append(f"### {raw.get('label', '')}")
        scores = raw.get("score_lines")
        if isinstance(scores, Sequence) and not isinstance(scores, (str, bytes)) and scores:
            lines.extend(f"- {score}" for score in scores)
        else:
            lines.append("- No parsable Critic score lines were captured.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_comparison(args: argparse.Namespace) -> Path:
    root = workflow.REPO_ROOT
    research = _regular_input(args.research, label="Research input")
    strategy = _regular_input(args.strategy, label="Strategy input")
    proof = _regular_input(args.proof, label="Proof input") if args.proof else None
    if args.goal == "opportunity" and proof is None:
        raise ComparisonError("Opportunity comparison requires --proof.")
    if args.week_slot is not None and not 1 <= args.week_slot <= 5:
        raise ComparisonError("--week-slot must be between 1 and 5.")
    _provider_preflight()

    v0_sha = resolve_ref(root, args.v0_ref)
    v1_sha = resolve_ref(root, args.v1_ref)
    if v0_sha == v1_sha:
        raise ComparisonError("V0 and V1 refs resolve to the same commit.")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_root = COMPARISON_ROOT / run_id
    _prepare_result_root(result_root)

    manifest: dict[str, object]
    with tempfile.TemporaryDirectory(prefix="linkedin-os-v0-v1-") as temporary:
        temp_root = Path(temporary)
        worktrees = {
            "v0": (args.v0_ref, v0_sha, temp_root / "v0"),
            "v1": (args.v1_ref, v1_sha, temp_root / "v1"),
        }
        installed: list[Path] = []
        runs: list[VersionRun] = []
        try:
            for _label, (_ref, sha, path) in worktrees.items():
                _install_worktree(root, sha=sha, destination=path)
                installed.append(path)
            for label in ("v0", "v1"):
                ref, sha, path = worktrees[label]
                runs.append(
                    _run_version(
                        label=label,
                        ref=ref,
                        commit_sha=sha,
                        worktree=path,
                        result_root=result_root,
                        research_input=research,
                        strategy_input=strategy,
                        proof_input=proof,
                        topic=args.topic,
                        goal=args.goal,
                        output_format=args.output_format,
                        week_slot=args.week_slot,
                        strong_current_signal=args.strong_current_signal,
                    )
                )
        finally:
            for path in reversed(installed):
                _remove_worktree(root, path)

    manifest = build_manifest(
        run_id=run_id,
        topic=args.topic,
        goal=args.goal,
        output_format=args.output_format,
        research_sha256=_sha256_file(research),
        strategy_sha256=_sha256_file(strategy),
        proof_sha256=_sha256_file(proof) if proof else None,
        versions=runs,
    )
    try:
        manifest_path = result_root / "comparison.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.chmod(manifest_path, 0o600)
        markdown_path = result_root / "comparison.md"
        markdown_path.write_text(render_comparison_markdown(manifest), encoding="utf-8")
        os.chmod(markdown_path, 0o600)
    except OSError as exc:
        raise ComparisonError("Comparison summary could not be written privately.") from exc
    return result_root


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compare-v0-v1",
        description=(
            "Run the same private LinkedIn research/strategy input through frozen V0 and current V1, "
            "then save a local side-by-side package comparison."
        ),
    )
    parser.add_argument("--research", required=True, help="Research JSON/JSONL input used for both versions.")
    parser.add_argument("--strategy", required=True, help="Strategy JSON input used for both versions.")
    parser.add_argument("--topic", required=True, help="Exact comparison topic supplied to both versions.")
    parser.add_argument("--goal", choices=VALID_GOALS, default="authority")
    parser.add_argument("--format", dest="output_format", choices=VALID_FORMATS)
    parser.add_argument("--week-slot", type=int)
    parser.add_argument("--strong-current-signal", action="store_true")
    parser.add_argument("--proof", help="Private proof manifest; required for opportunity comparisons.")
    parser.add_argument("--v0-ref", default=DEFAULT_V0_REF)
    parser.add_argument("--v1-ref", default=DEFAULT_V1_REF)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_comparison(args)
    except ComparisonError as exc:
        print(f"Comparison failed: {exc}", file=sys.stderr)
        return 1
    try:
        display = result.relative_to(workflow.REPO_ROOT).as_posix()
    except ValueError:
        display = str(result)
    print(f"V0 vs V1 comparison complete: {display}/comparison.md")
    print("The comparison is local/private. No publication or performance record was created.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
