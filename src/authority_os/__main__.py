"""One fixed CLI entry point for LinkedIn Authority OS."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from datetime import date
from pathlib import Path

from . import __version__, storage, workflow


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", type=_path, default=workflow.DEFAULT_DB, help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-os",
        description="Research and draft LinkedIn posts for manual human approval.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create ignored local directories and database.")
    _add_common(init)

    doctor = subparsers.add_parser("doctor", help="Check local setup without printing secrets.")
    _add_common(doctor)

    research = subparsers.add_parser("research", help="Collect or import research signals.")
    research.add_argument("--topic", help="Optional GenAI product topic to research.")
    research.add_argument("--input", type=_path, help="Private JSON or JSONL research import.")
    research.add_argument("--dry-run", action="store_true", help="Use the offline safe fixture.")
    _add_common(research)

    draft = subparsers.add_parser("draft", help="Create a five-file human approval package.")
    draft.add_argument("--topic", help="Topic or research signal.")
    draft.add_argument("--goal", choices=sorted(workflow.GOALS), default="authority")
    draft.add_argument("--format", dest="output_format", choices=sorted(workflow.FORMATS))
    draft.add_argument("--proof-type", choices=sorted(workflow.PROOF_TYPES))
    draft.add_argument("--proof-value", help="Local artifact path or factual proof description.")
    draft.add_argument(
        "--ownership-evidence",
        action="store_true",
        help="Confirm supplied proof supports an ownership claim; never inferred.",
    )
    draft.add_argument("--dry-run", action="store_true", help="Use the offline safe fixture.")
    draft.add_argument("--output-root", type=_path, default=workflow.DEFAULT_OUTPUTS)
    _add_common(draft)

    performance = subparsers.add_parser(
        "record-performance", help="Record an explicit paid or organic checkpoint."
    )
    performance.add_argument("--csv", type=_path, help="Private CSV import.")
    performance.add_argument("--post", dest="post_id")
    performance.add_argument("--checkpoint", choices=sorted(storage.CHECKPOINTS))
    performance.add_argument("--channel", choices=sorted(storage.CHANNELS))
    performance.add_argument("--observed-at")
    for metric in storage.METRICS:
        performance.add_argument(f"--{metric.replace('_', '-')}", type=int, default=0)
    _add_common(performance)

    review = subparsers.add_parser("weekly-review", help="Summarise recorded outcomes safely.")
    review.add_argument("--output-root", type=_path, default=workflow.DEFAULT_OUTPUTS)
    _add_common(review)
    return parser


def initialise_paths(db_path: Path) -> None:
    workflow.DEFAULT_OUTPUTS.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    storage.initialise(db_path)


def command_init(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    print(f"Initialised private database: {args.db}")
    print("Publishing remains disabled.")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    failures: list[str] = []
    checks: list[tuple[str, bool, str]] = []
    checks.append(("Python 3.11+", sys.version_info >= (3, 11), sys.version.split()[0]))
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
    ignore_lines = set(ignore_file.read_text().splitlines()) if ignore_file.exists() else set()
    checks.append(("privacy ignore rules", required_ignores <= ignore_lines, "configured"))
    try:
        initialise_paths(args.db)
        checks.append(("private SQLite schema", True, "ready"))
    except Exception:
        checks.append(("private SQLite schema", False, "unavailable"))
    checks.append(("optional Claude CLI", shutil.which("claude") is not None, "optional"))

    for name, passed, detail in checks:
        label = "OK" if passed else ("WARN" if name == "optional Claude CLI" else "FAIL")
        print(f"[{label}] {name}: {detail}")
        if not passed and name != "optional Claude CLI":
            failures.append(name)
    print("[OK] credential handling: values were not inspected or printed")
    print("[OK] LinkedIn publishing: no command exists")
    return 1 if failures else 0


def command_research(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    if args.dry_run and args.input:
        raise workflow.WorkflowError("Choose either --dry-run or --input, not both.")
    if args.dry_run:
        fixture = workflow.load_fixture(topic=args.topic)
        items = workflow.prepare_research_items(fixture.get("research_items", []))
        mode = "fixture"
    elif args.input:
        items = workflow.load_research_file(args.input)
        mode = "private import"
    else:
        items = workflow.run_live_research(args.topic)
        mode = "live Scout"
    inserted, duplicates = storage.insert_research_items(args.db, items)
    available = storage.list_research_items(args.db)
    if available:
        analysis = workflow.analyse_research(available, topic=args.topic)
        print(analysis["broad_discovery_note"])
    else:
        print("No defensible research items were returned; nothing was invented.")
    print(f"Research mode: {mode}; inserted={inserted}; duplicates={duplicates}.")
    return 0


def _proof_from_args(args: argparse.Namespace) -> dict[str, object]:
    if bool(args.proof_type) != bool(args.proof_value):
        raise workflow.WorkflowError("--proof-type and --proof-value must be supplied together.")
    if not args.proof_type:
        return {}
    return {
        "type": args.proof_type,
        "value": args.proof_value,
        "ownership_evidence": bool(args.ownership_evidence),
    }


def command_draft(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    recent = workflow.recent_post_texts(args.output_root)
    if args.dry_run:
        payload = workflow.load_fixture(
            topic=args.topic,
            goal=args.goal,
            output_format=args.output_format,
        )
        if args.proof_type:
            payload["proof"] = _proof_from_args(args)
        items = workflow.prepare_research_items(payload.get("research_items", []))
        storage.insert_research_items(args.db, items)
        payload["analysis_summary"] = workflow.analyse_research(
            items, topic=str(payload["topic"])
        )["broad_discovery_note"]
        completed = workflow.complete_payload(payload, recent_posts=recent)
    else:
        topic = args.topic or "current GenAI product-management signal"
        items = storage.list_research_items(args.db, topic=args.topic)
        if not items:
            items = storage.list_research_items(args.db)
        if not items:
            fresh = workflow.run_live_research(args.topic)
            storage.insert_research_items(args.db, fresh)
            items = storage.list_research_items(args.db)
        completed = workflow.run_live_draft(
            items,
            topic=topic,
            goal=args.goal,
            requested_format=args.output_format,
            proof=_proof_from_args(args),
            recent_posts=recent,
        )
    destination = workflow.write_output_package(completed, output_root=args.output_root)
    print(f"Package: {destination}")
    print(f"STATUS: {completed['status']}")
    print("No LinkedIn action was taken.")
    return 0 if completed["status"] == "READY FOR HUMAN APPROVAL" else 2


def _record_from_mapping(args: argparse.Namespace, row: dict[str, object]) -> None:
    row.setdefault("observed_at", args.observed_at or workflow.now_iso())
    storage.record_performance(args.db, row)


def command_record_performance(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    if args.csv:
        with args.csv.open(newline="", encoding="utf-8-sig") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            _record_from_mapping(args, row)
        print(f"Recorded {len(rows)} explicit channel checkpoints from private CSV input.")
        return 0
    if not args.post_id:
        print(
            "No data recorded. Supply --post, --checkpoint and --channel, or use --csv. "
            "Run `linkedin-os record-performance --help` for fields."
        )
        return 0
    if not args.checkpoint or not args.channel:
        raise workflow.WorkflowError("--checkpoint and --channel are required with --post.")
    record = {
        "post_id": args.post_id,
        "checkpoint": args.checkpoint,
        "channel": args.channel,
        "observed_at": args.observed_at or workflow.now_iso(),
        **{metric: getattr(args, metric) for metric in storage.METRICS},
    }
    storage.record_performance(args.db, record)
    print(f"Recorded {args.post_id} / {args.checkpoint} / {args.channel}.")
    return 0


def command_weekly_review(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    markdown = workflow.weekly_review_markdown(
        storage.list_performance(args.db), output_root=args.output_root
    )
    day_dir = args.output_root / date.today().isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    destination = day_dir / "weekly-review.md"
    suffix = 2
    while destination.exists():
        destination = day_dir / f"weekly-review-{suffix}.md"
        suffix += 1
    destination.write_text(markdown, encoding="utf-8")
    print(f"Weekly review: {destination}")
    print("The rubric was not changed.")
    return 0


COMMANDS = {
    "init": command_init,
    "doctor": command_doctor,
    "research": command_research,
    "draft": command_draft,
    "record-performance": command_record_performance,
    "weekly-review": command_weekly_review,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
