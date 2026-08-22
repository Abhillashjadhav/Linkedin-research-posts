"""Composition root for resilient daily discovery."""

from __future__ import annotations

from . import daily_spine_cli as base
from . import momentum_parallel, thesis_accumulator

# Reuse the existing daily discovery contract while swapping only the live-web
# momentum adapter and thesis-set search strategy. All downstream privacy,
# evidence, strategy and publishing boundaries stay owned by daily_spine_cli.
base.momentum = momentum_parallel
base.base.search_theses = thesis_accumulator.search_theses

parser = base.parser
command = base.command


def main(argv: list[str] | None = None) -> int:
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
