"""Composition root for surface-first resilient daily discovery."""

from __future__ import annotations

from datetime import datetime, timezone

from . import daily_spine_cli as base
from . import discovery_runtime_tuning
from . import momentum_surface_parallel
from . import surface_scout_runtime_tuning

# Reuse the existing daily discovery contract while swapping only the live-web
# momentum adapter. All downstream thesis, privacy and publishing boundaries stay
# owned by daily_spine_cli.
discovery_runtime_tuning.install()
surface_scout_runtime_tuning.install()
base.momentum = momentum_surface_parallel

_ORIGINAL_COMMAND = base.command


def command(args):
    # Freeze the run timestamp before the base command so the trace folder and
    # downstream discovery artifacts share one reproducible run ID.
    if not args.as_of:
        args.as_of = (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
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
