"""Composition root for surface-first resilient daily discovery."""

from __future__ import annotations

import json
import os
import shlex
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import daily_spine_cli as base
from . import runtime_budget
from . import discovery_runtime_tuning
from . import individual_launch_runtime_tuning
from . import momentum_surface_parallel
from . import surface_scout_runtime_tuning
from . import v1_consumability
from . import v1_discovery_admission

# Reuse the existing daily discovery contract while swapping only the live-web
# momentum adapter. All downstream thesis, privacy and publishing boundaries stay
# owned by daily_spine_cli.
discovery_runtime_tuning.install()
surface_scout_runtime_tuning.install()
individual_launch_runtime_tuning.install()
v1_consumability.install()
v1_discovery_admission.install()
base.momentum = momentum_surface_parallel

_ORIGINAL_COMMAND = base.command


def _delivered(folder: Path) -> bool:
    dashboard = folder / "run-dashboard.json"
    if not dashboard.is_file() or dashboard.is_symlink():
        return False
    raw = base.base._private_json(dashboard, "Run dashboard")
    return isinstance(raw, dict) and raw.get("outcome") in {"PASS", "COMPLETED_WITH_WARNINGS"} and any(
        isinstance(check, dict)
        and check.get("stage") == "final_evals"
        and check.get("status") in {"PASS", "COMPLETED_WITH_WARNINGS"}
        for check in raw.get("checks", [])
    )


def command(args):
    invocation_started = time.time()
    # Freeze the run timestamp before the base command so the trace folder and
    # downstream discovery artifacts share one reproducible run ID.
    resume_from = getattr(args, "resume_from", None)
    if not args.as_of and resume_from is None:
        args.as_of = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    if resume_from is not None and args.output_dir is None:
        raise base.workflow.WorkflowError(
            "Resume requires --output-dir so the failed run remains unchanged."
        )
    folder = base.base._under_private(
        args.output_dir
        or base.base.OUTPUT_ROOT / args.as_of[:10] / args.as_of[11:19].replace(":", "")
    )
    base.base.legacy_cli._ensure_owner_only_directory(folder)
    momentum_surface_parallel.configure_trace_dir(folder)
    contract = json.loads(
        (base.workflow.REPO_ROOT / "config" / "linkedin-post-contract-v1.json").read_text(encoding="utf-8")
    )
    budget = contract["runtime"]["global_deadline_seconds"]
    if type(budget) is not int or budget < 1:
        raise base.workflow.WorkflowError("Approved global deadline is invalid.")
    prior_deadline = os.environ.get(runtime_budget.DEADLINE_ENV)
    os.environ[runtime_budget.DEADLINE_ENV] = str(invocation_started + budget)
    try:
        try:
            result = _ORIGINAL_COMMAND(args)
            if result != 124 and not _delivered(folder):
                runtime_budget.remaining_seconds()
        except runtime_budget.GlobalDeadlineExceeded:
            _record_deadline(folder, args, budget)
            raise
        if result == 124:
            _record_deadline(folder, args, budget)
        return result
    finally:
        if prior_deadline is None:
            os.environ.pop(runtime_budget.DEADLINE_ENV, None)
        else:
            os.environ[runtime_budget.DEADLINE_ENV] = prior_deadline


def _record_deadline(folder: Path, args, budget: int) -> None:
    """Leave a private failure record and one reproducible resume invocation."""

    dashboard_path = folder / "run-dashboard.json"
    stage = "conversation_discovery"
    if dashboard_path.is_file() and not dashboard_path.is_symlink():
        dashboard = base.base._private_json(dashboard_path, "Run dashboard")
        if isinstance(dashboard, dict) and isinstance(dashboard.get("checks"), list):
            for check in dashboard["checks"]:
                if isinstance(check, dict) and check.get("status") not in {"PASS", "COMPLETED_WITH_WARNINGS"}:
                    stage = str(check.get("stage", stage))
                    check["status"] = "TIME_BUDGET_EXCEEDED"
                    check["reason"] = "Shared daily deadline expired; completed artifacts were retained."
                    break
            dashboard["outcome"] = "TIME_BUDGET_EXCEEDED"
            dashboard["stopped_at"] = stage
            temporary = dashboard_path.with_name(f".{dashboard_path.name}.{os.getpid()}.tmp")
            payload = (json.dumps(dashboard, indent=2, sort_keys=True) + "\n").encode()
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                0o600,
            )
            try:
                offset = 0
                while offset < len(payload):
                    written = os.write(descriptor, payload[offset:])
                    if written < 1:
                        raise base.workflow.WorkflowError("Deadline dashboard write was incomplete.")
                    offset += written
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, dashboard_path)
    destination = folder.with_name(folder.name + "-resume")
    suffix = 2
    while destination.exists():
        destination = folder.with_name(f"{folder.name}-resume-{suffix}")
        suffix += 1
    run_input = base.base._private_json(folder / "run-input.json", "Run identity")
    if not isinstance(run_input, dict) or not isinstance(run_input.get("as_of"), str):
        raise base.workflow.WorkflowError("Deadline checkpoint lacks its run timestamp.")
    argv = [
        "./bin/linkedin-os", "discover", "--profile", str(args.profile),
        "--days", str(args.days), "--as-of", run_input["as_of"],
        "--db", str(args.db), "--output-dir", str(destination),
        "--resume-from", str(folder), "--allow-web-research", "--allow-model-egress",
    ]
    if args.topic is not None:
        argv.extend(["--topic", str(args.topic)])
    if args.week_slot is not None:
        argv.extend(["--week-slot", str(args.week_slot)])
    if args.generate_post:
        argv.append("--generate-post")
    resume_command = shlex.join(argv)
    base.base.write_private_json(
        folder / "deadline-checkpoint.json",
        {"status": "TIME_BUDGET_EXCEEDED", "stage": stage,
         "budget_seconds": budget, "resume_command": resume_command},
    )
    print(f"TIME_BUDGET_EXCEEDED at {stage}; completed artifacts retained.", file=sys.stderr)
    print(f"Resume command: {resume_command}", file=sys.stderr)


# daily_spine_cli.main resolves its module-global command at runtime.
base.command = command
parser = base.parser


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
