"""Explicit Sunday article command; no discovery, publication, or live web access."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import article_workflow
from .workflow import WorkflowError


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="linkedin-os article", description="Private Sunday article review draft")
    command.add_argument("--brief", type=Path, help="User-supplied Sunday article brief JSON")
    command.add_argument("--models", type=Path, help="Explicit Codex model config JSON for all four roles")
    command.add_argument("--allow-model-egress", action="store_true", help="Authorize configured model calls")
    command.add_argument("--output", type=Path, help="New private run folder inside outputs/")
    command.add_argument("--dry-run", action="store_true", help="Offline fixture marker; no calls or file reads")
    return command


def _read(path: Path, label: str) -> object:
    if path.is_symlink() or not path.is_file():
        raise WorkflowError(f"Article {label} must be a regular JSON file.")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise WorkflowError(f"Article {label} contains invalid JSON.") from exc


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.dry_run:
            if args.allow_model_egress:
                raise WorkflowError("Article dry-run cannot request model egress.")
            result = article_workflow.fixture(args.output) if args.output else {
                "status": "FIXTURE_ONLY", "human_approval_status": "NOT_APPROVED",
                "publishing_status": "DISABLED", "model_calls": 0}
            print(json.dumps(result, sort_keys=True))
            return 0
        if not all((args.brief, args.models, args.output)) or not args.allow_model_egress:
            raise WorkflowError("Live article requires --brief, --models, --output, and --allow-model-egress.")
        brief = _read(args.brief, "brief")
        models = article_workflow.load_models(_read(args.models, "models"))
        result = article_workflow.run(brief, models, args.output)
        print(json.dumps({**result, "output": str(args.output)}, sort_keys=True))
        return 0 if result["status"] == "READY_FOR_HUMAN_REVIEW" else 2
    except WorkflowError as exc:
        print(f"Article blocked: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
