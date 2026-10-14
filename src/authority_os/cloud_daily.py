"""Run the real Authority OS discovery and high-bar draft pipeline on a cloud runner."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import workflow

RUN_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,96}")
DEFAULT_CLOUD_PROFILE = workflow.REPO_ROOT / "data" / "cloud" / "authority-profile.json"


def _run_id(value: str) -> str:
    if RUN_ID_RE.fullmatch(value) is None:
        raise argparse.ArgumentTypeError("run-id must contain only letters, numbers, dot, dash or underscore")
    return value


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    path.chmod(0o600)


def _run(command: Sequence[str], *, stdout_path: Path, stderr_path: Path, timeout: int) -> int:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        completed = subprocess.run(
            list(command),
            cwd=workflow.REPO_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=stdout,
            stderr=stderr,
            text=True,
            check=False,
            timeout=timeout,
            env=os.environ.copy(),
        )
    stdout_path.chmod(0o600)
    stderr_path.chmod(0o600)
    return completed.returncode


def _load_theses(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError("Cloud discovery did not produce a readable thesis package.") from exc
    if not isinstance(payload, Mapping):
        raise workflow.WorkflowError("Cloud thesis package has an invalid schema.")
    theses = payload.get("theses")
    if not isinstance(theses, list) or len(theses) != 3:
        raise workflow.WorkflowError("Cloud production requires exactly three cleared theses.")
    result: list[dict[str, object]] = []
    expected = {"thesis-1", "thesis-2", "thesis-3"}
    seen: set[str] = set()
    for item in theses:
        if not isinstance(item, Mapping):
            raise workflow.WorkflowError("Cloud thesis package contains an invalid card.")
        thesis_id = item.get("id")
        topic = item.get("topic")
        if not isinstance(thesis_id, str) or thesis_id not in expected or thesis_id in seen:
            raise workflow.WorkflowError("Cloud thesis IDs must be thesis-1 through thesis-3 exactly once.")
        if not isinstance(topic, str) or not topic.strip():
            raise workflow.WorkflowError("Cloud thesis topic must be non-blank.")
        seen.add(thesis_id)
        result.append(dict(item))
    if seen != expected:
        raise workflow.WorkflowError("Cloud thesis package is incomplete.")
    result.sort(key=lambda item: str(item["id"]))
    return result


def execute(run_id: str, *, profile_path: Path = DEFAULT_CLOUD_PROFILE, days: int = 7) -> int:
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise workflow.WorkflowError(
            "OPENAI_API_KEY is required for cloud execution. Configure it as a GitHub Actions secret before running the scheduled workflow."
        )
    if not profile_path.is_file():
        raise workflow.WorkflowError("Tracked public-safe cloud authority profile is unavailable.")

    private_root = workflow.REPO_ROOT / "data" / "private"
    run_root = private_root / "cloud-daily" / run_id
    discovery_root = run_root / "discovery"
    logs_root = run_root / "logs"
    run_root.mkdir(parents=True, exist_ok=False)
    run_root.chmod(0o700)
    discovery_root.mkdir(mode=0o700)
    logs_root.mkdir(mode=0o700)

    private_profile = run_root / "authority-profile.json"
    shutil.copyfile(profile_path, private_profile)
    private_profile.chmod(0o600)
    db_path = run_root / "research.sqlite"

    created_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    manifest: dict[str, object] = {
        "schema_version": 1,
        "run_id": run_id,
        "created_at": created_at,
        "publishing_status": "DISABLED",
        "human_review_required": True,
        "discovery_status": "NOT_RUN",
        "drafts": [],
    }
    _write_json(run_root / "manifest.json", manifest)

    discover_command = [
        "./bin/linkedin-os",
        "discover",
        "--profile",
        private_profile.relative_to(workflow.REPO_ROOT).as_posix(),
        "--days",
        str(days),
        "--output-dir",
        discovery_root.relative_to(workflow.REPO_ROOT).as_posix(),
        "--db",
        db_path.relative_to(workflow.REPO_ROOT).as_posix(),
        "--allow-web-research",
        "--allow-model-egress",
    ]
    print("Cloud production: running conversation discovery and thesis selection.", flush=True)
    discovery_code = _run(
        discover_command,
        stdout_path=logs_root / "discovery.stdout.log",
        stderr_path=logs_root / "discovery.stderr.log",
        timeout=3600,
    )
    manifest["discovery_status"] = "PASS" if discovery_code == 0 else "BLOCKED"
    manifest["discovery_returncode"] = discovery_code
    _write_json(run_root / "manifest.json", manifest)
    if discovery_code != 0:
        print("Cloud production: discovery blocked; no drafts were attempted.", flush=True)
        return discovery_code

    theses = _load_theses(discovery_root / "theses.json")
    draft_results: list[dict[str, object]] = []
    for index, card in enumerate(theses, start=1):
        thesis_id = str(card["id"])
        topic = str(card["topic"])
        strategy = discovery_root / f"strategy-{thesis_id}.json"
        if not strategy.is_file():
            raise workflow.WorkflowError("Cloud discovery omitted a required strategy file.")
        print(f"Cloud production: drafting {index}/3 ({thesis_id}).", flush=True)
        draft_command = [
            "./bin/linkedin-os",
            "draft",
            "--topic",
            topic,
            "--goal",
            "authority",
            "--format",
            "text",
            "--strategy-input",
            strategy.relative_to(workflow.REPO_ROOT).as_posix(),
            "--db",
            db_path.relative_to(workflow.REPO_ROOT).as_posix(),
            "--allow-model-egress",
            "--package",
        ]
        stdout_path = logs_root / f"draft-{index}.stdout.log"
        stderr_path = logs_root / f"draft-{index}.stderr.log"
        code = _run(draft_command, stdout_path=stdout_path, stderr_path=stderr_path, timeout=3600)
        draft_results.append(
            {
                "rank": index,
                "thesis_id": thesis_id,
                "topic": topic,
                "returncode": code,
                "status": "READY_FOR_HUMAN_REVIEW" if code == 0 else "BLOCKED",
                "stdout": stdout_path.relative_to(run_root).as_posix(),
                "stderr": stderr_path.relative_to(run_root).as_posix(),
            }
        )
        print(
            f"Cloud production: {thesis_id} {'cleared' if code == 0 else 'blocked'} the high-bar draft pipeline.",
            flush=True,
        )

    manifest["drafts"] = draft_results
    manifest["overall_status"] = (
        "READY_FOR_HUMAN_REVIEW"
        if any(item["status"] == "READY_FOR_HUMAN_REVIEW" for item in draft_results)
        else "BLOCKED"
    )
    _write_json(run_root / "manifest.json", manifest)
    print(f"Cloud production bundle: {run_root.relative_to(workflow.REPO_ROOT)}", flush=True)
    print("Publishing status: DISABLED. Human review is required.", flush=True)
    return 0 if manifest["overall_status"] == "READY_FOR_HUMAN_REVIEW" else 2


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m authority_os.cloud_daily")
    result.add_argument("--run-id", type=_run_id, required=True)
    result.add_argument("--profile", type=Path, default=DEFAULT_CLOUD_PROFILE)
    result.add_argument("--days", type=int, default=7, choices=range(1, 31))
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        return execute(args.run_id, profile_path=args.profile, days=args.days)
    except (workflow.WorkflowError, OSError, subprocess.TimeoutExpired, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
