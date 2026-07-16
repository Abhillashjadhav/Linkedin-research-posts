"""One fixed CLI entry point for LinkedIn Authority OS."""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from pathlib import Path

from . import __version__, storage, workflow


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=_path, default=workflow.DEFAULT_DB, help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-os",
        description="Prepare LinkedIn research and drafts for manual human approval.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create ignored local runtime directories.")
    _add_common(init)

    doctor = subparsers.add_parser("doctor", help="Check local setup without printing secrets.")
    _add_common(doctor)

    draft = subparsers.add_parser("draft", help="Validate the offline workflow fixture.")
    draft.add_argument("--topic", help="Optional topic substituted into the fixture.")
    draft.add_argument("--dry-run", action="store_true", help="Use the offline safe fixture.")
    _add_common(draft)

    research = subparsers.add_parser("research", help="Import or validate research signals.")
    research.add_argument("--topic", help="Optional topic substituted into the fixture.")
    research.add_argument("--input", type=_path, help="Private JSON or JSONL research import.")
    research.add_argument("--dry-run", action="store_true", help="Use the offline safe fixture.")
    _add_common(research)
    return parser


def initialise_paths(db_path: Path) -> None:
    workflow.DEFAULT_OUTPUTS.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage.initialise(db_path)


def command_init(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    print(f"Initialised private research database: {args.db}")
    print("Publishing remains disabled.")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    checks: list[tuple[str, bool, str]] = [
        ("Python 3.11+", sys.version_info >= (3, 11), sys.version.split()[0]),
    ]
    for relative in (
        "data/voice/voice-guide.md",
        "data/voice/abhillash-best-posts.md",
        "data/samples/dry-run.json",
    ):
        path = workflow.REPO_ROOT / relative
        checks.append((relative, path.exists() and path.stat().st_size > 0, "present"))
    required_ignores = {
        "data/private/**",
        "*.sqlite",
        "*.db",
        ".env",
        ".env.*",
        "outputs/**",
        "!outputs/.gitkeep",
        ".agents/",
    }
    ignore_file = workflow.REPO_ROOT / ".gitignore"
    ignore_lines = set(ignore_file.read_text(encoding="utf-8").splitlines())
    checks.append(("privacy ignore rules", required_ignores <= ignore_lines, "configured"))
    try:
        initialise_paths(args.db)
        checks.append(("private research ledger", True, "ready"))
    except Exception:
        checks.append(("private research ledger", False, "unavailable"))
    checks.append(("optional Claude CLI", shutil.which("claude") is not None, "optional"))

    failures: list[str] = []
    for name, passed, detail in checks:
        label = "OK" if passed else ("WARN" if name == "optional Claude CLI" else "FAIL")
        print(f"[{label}] {name}: {detail}")
        if not passed and name != "optional Claude CLI":
            failures.append(name)
    print("[OK] credential handling: values were not inspected or printed")
    print("[OK] LinkedIn publishing: no command exists")
    return 1 if failures else 0


def command_draft(args: argparse.Namespace) -> int:
    if not args.dry_run:
        raise workflow.WorkflowError(
            "Live drafting is not available in this runtime foundation; use --dry-run."
        )
    fixture = workflow.load_fixture(topic=args.topic)
    print(
        f"Fixture envelope validated: topic={fixture['topic']}; "
        f"research_items={len(fixture['research_items'])}."
    )
    print("No approval package was generated. No LinkedIn action was taken.")
    return 0


def command_research(args: argparse.Namespace) -> int:
    if args.dry_run and args.input:
        raise workflow.WorkflowError("Choose either --dry-run or --input, not both.")
    if args.dry_run:
        fixture = workflow.load_fixture(topic=args.topic)
        items = workflow.prepare_research_items(fixture["research_items"])
        mode = "fixture"
    elif args.input:
        items = workflow.load_research_file(args.input)
        mode = "private import"
    else:
        raise workflow.WorkflowError(
            "Live research is not available yet; use --dry-run or --input."
        )
    initialise_paths(args.db)
    inserted, duplicates = storage.insert_research_items(args.db, items)
    print(f"Research mode: {mode}; inserted={inserted}; duplicates={duplicates}.")
    if not items:
        print("No defensible research items were supplied; nothing was invented.")
    return 0


COMMANDS = {
    "init": command_init,
    "doctor": command_doctor,
    "draft": command_draft,
    "research": command_research,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except sqlite3.Error:
        print("ERROR: private research database is unavailable or corrupt.", file=sys.stderr)
        return 2
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
