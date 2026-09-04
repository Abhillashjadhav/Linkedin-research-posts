"""Composition root for surface-first resilient daily discovery."""

from __future__ import annotations

from datetime import datetime, timezone

from . import daily_spine_cli as base
from . import discovery_runtime_tuning
from . import individual_launch_runtime_tuning
from . import momentum_surface_parallel
from . import surface_scout_runtime_tuning
from . import v1_consumability

# Reuse the existing daily discovery contract while swapping only the live-web
# momentum adapter. All downstream thesis, privacy and publishing boundaries stay
# owned by daily_spine_cli.
discovery_runtime_tuning.install()
surface_scout_runtime_tuning.install()
individual_launch_runtime_tuning.install()
v1_consumability.install()
base.momentum = momentum_surface_parallel

_ORIGINAL_COMMAND = base.command


def command(args):
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
    return _ORIGINAL_COMMAND(args)


# daily_spine_cli.main resolves its module-global command at runtime.
base.command = command
parser = base.parser


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
