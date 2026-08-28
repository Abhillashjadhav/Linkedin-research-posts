"""Composition root for resilient daily discovery."""

from __future__ import annotations

from . import daily_spine_cli as base
from . import discovery_runtime_tuning
from . import momentum_parallel

# Reuse the existing daily discovery contract while swapping only the live-web
# momentum adapter. All downstream thesis, privacy and publishing boundaries stay
# owned by daily_spine_cli.
discovery_runtime_tuning.install()
base.momentum = momentum_parallel

parser = base.parser
command = base.command


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
