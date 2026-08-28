"""Stable local entry point for the V0/V1 comparison runner.

A fresh clone may have the frozen baseline only as an origin-tracking ref. Keep the
comparison implementation unchanged and resolve the requested ref against both the
local namespace and the matching ``origin/`` namespace before starting model work.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Sequence

from . import compare_versions as base


def resolve_ref(root: Path, ref: str) -> str:
    """Resolve an exact commit from a local ref or its origin-tracking counterpart."""

    if not isinstance(ref, str) or not ref.strip():
        raise base.ComparisonError("Comparison Git refs must be non-blank.")
    cleaned = ref.strip()
    candidates = [cleaned]
    if not cleaned.startswith("origin/"):
        candidates.append(f"origin/{cleaned}")

    for candidate in dict.fromkeys(candidates):
        try:
            completed = subprocess.run(
                ["git", "rev-parse", "--verify", f"{candidate}^{{commit}}"],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
        except OSError as exc:
            raise base.ComparisonError("Git could not resolve the comparison refs.") from exc
        sha = completed.stdout.strip()
        if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", sha):
            return sha

    remote_hint = cleaned if cleaned.startswith("origin/") else f"origin/{cleaned}"
    raise base.ComparisonError(
        f"Comparison ref {cleaned!r} was not found locally or as {remote_hint!r}. "
        "Run `git fetch origin` and retry."
    )


def main(argv: Sequence[str] | None = None) -> int:
    # run_comparison reads resolve_ref from the compare_versions module at runtime.
    base.resolve_ref = resolve_ref  # type: ignore[assignment]
    return base.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
