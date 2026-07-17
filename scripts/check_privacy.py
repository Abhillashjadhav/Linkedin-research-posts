"""Compatibility wrapper for the single Authority OS privacy-check command."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from authority_os.__main__ import main


if __name__ == "__main__":
    raise SystemExit(main(["privacy-check"]))
