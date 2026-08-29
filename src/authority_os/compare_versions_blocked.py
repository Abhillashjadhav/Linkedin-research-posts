"""Comparison-only support for preserving blocked V0/V1 draft evidence.

Release behavior remains owned by each version's existing live CLI. This module merely
runs that CLI through a private observation hook, classifies a policy block as a valid
comparison outcome, and lets the experiment continue to the other version.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from . import compare_versions as base
from . import workflow

CAPTURE_RUNTIME = workflow.REPO_ROOT / "scripts" / "compare_capture_runtime.py"
_PRODUCT_BLOCK_MARKERS = (
    "No candidate cleared the locked",
    "Resonance Selector blocked",
    "Resonance gate blocked",
    "blocked the single-topic draft",
    "V1 contract ",
    "Craft approval cannot override",
)


@dataclass(frozen=True, slots=True)
class CapturedVersionRun:
    label: str
    ref: str
    commit_sha: str
    status: str
    exit_code: int
    package_source: str | None
    recommendation: str | None
    score_lines: tuple[str, ...]
    attempts_path: str | None
    output_dir: Path


def _private_text(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path.parent, 0o700)
        path.write_text(text, encoding="utf-8")
        os.chmod(path, 0o600)
    except OSError as exc:
        raise base.ComparisonError("Private comparison diagnostic could not be written.") from exc


def _load_diagnostics(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise base.ComparisonError("Comparison attempt diagnostics are unavailable or invalid.") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != 1
        or not isinstance(payload.get("cycles"), list)
    ):
        raise base.ComparisonError("Comparison attempt diagnostics have an invalid schema.")
    return payload


def _failed_gate_text(candidate: Mapping[str, object]) -> str:
    gates = candidate.get("gates")
    if not isinstance(gates, Mapping):
        return "unknown"
    failed = [
        f"{name}={status}"
        for name, status in gates.items()
        if str(status) not in {"PASS", "NOT_REQUIRED"}
    ]
    return ", ".join(failed) or "none"


def render_attempts_markdown(payload: Mapping[str, object], *, label: str) -> str:
    cycles = payload.get("cycles")
    if not isinstance(cycles, Sequence) or isinstance(cycles, (str, bytes)):
        raise base.ComparisonError("Comparison attempts need a cycle list.")
    lines = [
        f"# {label.upper()} private draft attempts",
        "",
        "These are observation-only comparison artifacts. A rejected candidate remains rejected.",
        "",
        f"- Runtime exit code: `{payload.get('exit_code', '')}`",
        f"- Captured cycles: `{len(cycles)}`",
        "",
    ]
    for raw_cycle in cycles:
        if not isinstance(raw_cycle, Mapping):
            continue
        cycle = raw_cycle.get("cycle", "?")
        outcome = raw_cycle.get("outcome", "UNKNOWN")
        lines.extend([f"## Cycle {cycle} — {outcome}", ""])
        candidates = raw_cycle.get("candidates")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            lines.extend(["No candidate envelope was captured.", ""])
            continue
        for raw_candidate in candidates:
            if not isinstance(raw_candidate, Mapping):
                continue
            candidate_id = str(raw_candidate.get("candidate_id", ""))
            axes = raw_candidate.get("axes")
            axis_text = (
                ", ".join(f"{name}={value}" for name, value in axes.items())
                if isinstance(axes, Mapping)
                else "unavailable"
            )
            reasons = raw_candidate.get("gate_reasons")
            reason_text = (
                ", ".join(str(item) for item in reasons)
                if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes))
                else "unavailable"
            )
            lines.extend(
                [
                    f"### {candidate_id}",
                    "",
                    f"- Angle: {raw_candidate.get('angle', '')}",
                    f"- Critic: {axis_text}; raw={raw_candidate.get('raw_total', '')}; effective={raw_candidate.get('effective_total', '')}; band={raw_candidate.get('band', '')}",
                    f"- Required gates pass: {'yes' if raw_candidate.get('passes_required_gates') is True else 'no'}",
                    f"- Failed gates: {_failed_gate_text(raw_candidate)}",
                    f"- Gate reasons: {reason_text or 'none'}",
                    "",
                    "Text:",
                    "",
                ]
            )
            text = str(raw_candidate.get("text", ""))
            if text:
                lines.extend(f"    {line}" for line in text.splitlines())
            else:
                lines.append("    <no candidate text captured>")
            lines.append("")
        feedback = raw_cycle.get("feedback")
        if isinstance(feedback, Mapping):
            lines.extend(
                [
                    "### Retry diagnostic",
                    "",
                    "```json",
                    json.dumps(dict(feedback), indent=2, sort_keys=True),
                    "```",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def _diagnostic_score_lines(payload: Mapping[str, object]) -> tuple[str, ...]:
    cycles = payload.get("cycles")
    if not isinstance(cycles, Sequence) or isinstance(cycles, (str, bytes)):
        return ()
    summaries: list[str] = []
    for raw_cycle in cycles:
        if not isinstance(raw_cycle, Mapping):
            continue
        candidates = raw_cycle.get("candidates")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            continue
        safe = [item for item in candidates if isinstance(item, Mapping)]
        if not safe:
            continue
        best = max(
            safe,
            key=lambda item: (
                int(item.get("effective_total", 0)),
                int(item.get("axes", {}).get("hook_strength", 0))
                if isinstance(item.get("axes"), Mapping)
                else 0,
                str(item.get("candidate_id", "")),
            ),
        )
        summaries.append(
            f"cycle {raw_cycle.get('cycle', '?')} best={best.get('candidate_id', '')}; "
            f"effective={best.get('effective_total', '')}/25; "
            f"required_gates={'pass' if best.get('passes_required_gates') is True else 'fail'}; "
            f"failed={_failed_gate_text(best)}"
        )
    return tuple(summaries)


def classify_draft_result(
    returncode: int,
    stdout: str,
    diagnostics: Mapping[str, object],
) -> str:
    if returncode == 0:
        return "PASS"
    cycles = diagnostics.get("cycles")
    if isinstance(cycles, list) and cycles:
        return "BLOCKED"
    if any(marker in stdout for marker in _PRODUCT_BLOCK_MARKERS):
        return "BLOCKED"
    return "ERROR"


def _run_capture(
    command: Sequence[str],
    *,
    cwd: Path,
    log_path: Path,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=dict(env),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        raise base.ComparisonError("Comparison draft observer could not start.") from exc
    _private_text(log_path, completed.stdout)
    return completed


def run_version(
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
) -> CapturedVersionRun:
    private_root = worktree / "data" / "private" / "comparison-input"
    research_dest = private_root / "research.json"
    strategy_dest = private_root / "strategy.json"
    proof_dest = private_root / "proof.json" if proof_input else None
    base._copy_private_file(research_input, research_dest)  # type: ignore[attr-defined]
    base._copy_private_file(strategy_input, strategy_dest)  # type: ignore[attr-defined]
    if proof_input is not None and proof_dest is not None:
        base._copy_private_file(proof_input, proof_dest)  # type: ignore[attr-defined]

    version_result = result_root / label
    version_result.mkdir(mode=0o700)
    os.chmod(version_result, 0o700)

    base._run(  # type: ignore[attr-defined]
        ("./bin/linkedin-os", "init"),
        cwd=worktree,
        log_path=version_result / "init.log",
    )
    base._run(  # type: ignore[attr-defined]
        base.build_research_command(
            topic=topic,
            private_research="data/private/comparison-input/research.json",
            explicit_frozen_research=True,
        ),
        cwd=worktree,
        log_path=version_result / "research.log",
    )

    draft_args = base.build_draft_command(
        topic=topic,
        goal=goal,
        private_strategy="data/private/comparison-input/strategy.json",
        output_format=output_format,
        week_slot=week_slot,
        strong_current_signal=strong_current_signal,
        private_proof=("data/private/comparison-input/proof.json" if proof_dest else None),
    )
    diagnostics_path = version_result / "attempts.json"
    draft_log = version_result / "draft.log"
    env = dict(os.environ)
    target_src = str(worktree / "src")
    existing_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        target_src + os.pathsep + existing_pythonpath
        if existing_pythonpath
        else target_src
    )
    completed = _run_capture(
        (
            sys.executable,
            str(CAPTURE_RUNTIME),
            "--label",
            label,
            "--diagnostics",
            str(diagnostics_path),
            "--frozen-research",
            "data/private/comparison-input/research.json",
            "--frozen-topic",
            topic,
            "--",
            *draft_args[1:],
        ),
        cwd=worktree,
        log_path=draft_log,
        env=env,
    )
    diagnostics = _load_diagnostics(diagnostics_path)
    status = classify_draft_result(completed.returncode, completed.stdout, diagnostics)
    if status == "ERROR":
        raise base.ComparisonError(
            f"{label.upper()} draft failed as an infrastructure/runtime error. "
            f"Inspect {draft_log}."
        )

    attempts_path: str | None = None
    cycles = diagnostics.get("cycles")
    if isinstance(cycles, list) and cycles:
        attempts_file = version_result / "attempts.md"
        _private_text(
            attempts_file,
            render_attempts_markdown(diagnostics, label=label),
        )
        attempts_path = attempts_file.name

    package_relative: str | None = None
    recommendation: str | None = None
    if status == "PASS":
        package_relative = base.extract_package_path(completed.stdout)
        package_source = worktree / package_relative
        base._copy_tree_private(  # type: ignore[attr-defined]
            package_source, version_result / "package"
        )
        recommendation, _ = base.summarize_draft_log(completed.stdout)

    eval_source = worktree / "data" / "private" / "v1-evals"
    if eval_source.is_dir():
        base._copy_tree_private(  # type: ignore[attr-defined]
            eval_source, version_result / "v1-evals"
        )

    return CapturedVersionRun(
        label=label,
        ref=ref,
        commit_sha=commit_sha,
        status=status,
        exit_code=completed.returncode,
        package_source=package_relative,
        recommendation=recommendation,
        score_lines=_diagnostic_score_lines(diagnostics),
        attempts_path=attempts_path,
        output_dir=version_result,
    )


def build_manifest(
    *,
    run_id: str,
    topic: str,
    goal: str,
    output_format: str | None,
    research_sha256: str,
    strategy_sha256: str,
    proof_sha256: str | None,
    versions: Sequence[CapturedVersionRun],
) -> dict[str, object]:
    return {
        "schema_version": 2,
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
                "status": item.status,
                "exit_code": item.exit_code,
                "package_source": item.package_source,
                "recommendation": item.recommendation,
                "score_lines": list(item.score_lines),
                "attempts_path": item.attempts_path,
            }
            for item in versions
        ],
        "winner": None,
        "winner_policy": "human-product-review-required",
    }


def render_comparison_markdown(manifest: Mapping[str, object]) -> str:
    versions = manifest.get("versions")
    if not isinstance(versions, Sequence) or isinstance(versions, (str, bytes)) or len(versions) != 2:
        raise base.ComparisonError("Comparison manifest needs exactly two version runs.")
    inputs = manifest.get("inputs")
    input_map = inputs if isinstance(inputs, Mapping) else {}
    lines = [
        "# V0 vs V1 LinkedIn quality comparison",
        "",
        "Both versions received the same research, strategy, topic, and goal.",
        "A BLOCKED result is valid product evidence; rejected prose remains rejected for release purposes.",
        "No automatic quality winner is declared.",
        "",
        f"- Topic: `{manifest.get('topic', '')}`",
        f"- Goal: `{manifest.get('goal', '')}`",
        f"- Research SHA-256: `{input_map.get('research_sha256', '')}`",
        f"- Strategy SHA-256: `{input_map.get('strategy_sha256', '')}`",
        "",
        "| Version | Ref | Commit | Outcome | Recommendation |",
        "|---|---|---|---|---|",
    ]
    for raw in versions:
        if not isinstance(raw, Mapping):
            raise base.ComparisonError("Comparison manifest version entry is malformed.")
        lines.append(
            f"| {raw.get('label', '')} | `{raw.get('ref', '')}` | "
            f"`{str(raw.get('commit_sha', ''))[:12]}` | {raw.get('status', '')} | "
            f"{raw.get('recommendation') or 'none'} |"
        )

    lines.extend(["", "## Inspect these artifacts", ""])
    for raw in versions:
        assert isinstance(raw, Mapping)
        label = str(raw.get("label", ""))
        if raw.get("package_source"):
            lines.append(f"- `{label}/package/candidates.md` — accepted final candidate set.")
        if raw.get("attempts_path"):
            lines.append(
                f"- `{label}/{raw.get('attempts_path')}` — every captured quality cycle, including rejected prose and gate reasons."
            )
        lines.append(f"- `{label}/draft.log` — authoritative runtime outcome.")
    lines.append("- `v1/v1-evals/` — V1 contract evidence when generated.")

    lines.extend(
        [
            "",
            "## Product review questions",
            "",
            "1. Did either version block? Which exact contract caused the block?",
            "2. Did the Critic score highly while deterministic gates failed? If yes, is the rubric missing an important quality dimension?",
            "3. Which version delivers a clearer single atomic value?",
            "4. Which opening earns attention without manufactured hype?",
            "5. Which body provides more useful mechanism, trade-off, or decision depth?",
            "6. Which version sounds more like the intended human voice and contains less AI-slop?",
            "7. Are factual claims easier to inspect and trace in V1?",
            "8. Would you publish either accepted candidate unchanged? Why?",
            "",
            "## Runtime summaries",
            "",
        ]
    )
    for raw in versions:
        assert isinstance(raw, Mapping)
        lines.append(f"### {str(raw.get('label', '')).upper()} — {raw.get('status', '')}")
        scores = raw.get("score_lines")
        if isinstance(scores, Sequence) and not isinstance(scores, (str, bytes)) and scores:
            lines.extend(f"- {score}" for score in scores)
        else:
            lines.append("- No quality-cycle score summary was captured.")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def install() -> None:
    """Patch only the comparison harness; product runtime modules remain untouched."""

    base._run_version = run_version  # type: ignore[attr-defined,assignment]
    base.build_manifest = build_manifest  # type: ignore[assignment]
    base.render_comparison_markdown = render_comparison_markdown  # type: ignore[assignment]
