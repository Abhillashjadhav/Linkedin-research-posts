"""Local, human-entered outcome observations for Sunday article runs."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Mapping, Sequence

from . import article_contract, workflow


DECISIONS = ("accepted_light_edits", "accepted_substantial_edits", "rejected")
DEFAULT_FEEDBACK_DIR = workflow.DEFAULT_OUTPUTS / "article-feedback"
MAX_RECORDS = 5_000
MAX_FILE_BYTES = 32_768
RECORD_FIELDS = frozenset({
    "schema_version", "run", "article_sha256", "manifest_sha256", "decision",
    "edit_minutes", "substantial_rewrites", "hook_replacements",
    "factual_corrections", "notes", "recorded_at",
})


class _MissingFeedbackDirectory(Exception):
    """The requested directory has not yet been created by a record command."""


def _error(message: str) -> workflow.WorkflowError:
    return workflow.WorkflowError(message)


def _strict_json(raw: str, label: str) -> dict[str, object]:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise _error(f"{label} has duplicate JSON keys.")
            result[key] = value
        return result

    try:
        parsed = json.loads(raw, object_pairs_hook=pairs,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, json.JSONDecodeError) as exc:
        raise _error(f"{label} must contain valid finite JSON.") from exc
    if not isinstance(parsed, dict):
        raise _error(f"{label} must contain a JSON object.")
    return parsed


def _relative_under_outputs(path: Path | str, *, label: str) -> tuple[Path, str]:
    raw = Path(path)
    if ".." in raw.parts:
        raise _error(f"{label} must stay under ignored outputs.")
    absolute = Path(os.path.abspath(raw if raw.is_absolute() else workflow.REPO_ROOT / raw))
    try:
        relative = absolute.relative_to(workflow.DEFAULT_OUTPUTS)
    except ValueError as exc:
        raise _error(f"{label} must stay under ignored outputs.") from exc
    if not relative.parts:
        raise _error(f"{label} must name a directory under ignored outputs.")
    return absolute, relative.as_posix()


def _read_artifact(path: Path, label: str) -> tuple[dict[str, object], bytes]:
    _, raw, _ = workflow._read_validated_local_text(
        path, root=workflow.DEFAULT_OUTPUTS, label=label
    )
    return _strict_json(raw, label), raw.encode("utf-8")


def _run_identity(run: Path | str) -> tuple[str, str, str]:
    path, relative = _relative_under_outputs(run, label="Article run")
    brief, _ = _read_artifact(path / "brief.json", "Article brief")
    article, _ = _read_artifact(path / "article.json", "Article")
    manifest, manifest_bytes = _read_artifact(path / "manifest.json", "Article manifest")
    if manifest.get("status") == "FIXTURE_ONLY":
        raise _error("Fixture-only output cannot receive a real acceptance decision.")
    if (
        manifest.get("contract_version") != "sunday-article-v1"
        or manifest.get("status") != "READY_FOR_HUMAN_REVIEW"
        or manifest.get("human_approval_status") != "NOT_APPROVED"
        or manifest.get("publishing_status") != "DISABLED"
        or manifest.get("article_file") != "article.json"
    ):
        raise _error("Article manifest does not describe a completed live review run.")
    validated_brief = article_contract.validate_brief(brief)
    digest = article_contract.article_hash(article, validated_brief)
    if manifest.get("artifact_sha256") != digest:
        raise _error("Article has changed since its manifest was written.")
    if manifest.get("topic_id") != validated_brief["topic_id"]:
        raise _error("Article manifest topic does not match the brief.")
    return relative, digest, hashlib.sha256(manifest_bytes).hexdigest()


def _count(value: object, field: str) -> int:
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        parsed = int(value)
    else:
        raise _error(f"{field} must be a non-negative whole number.")
    if not 0 <= parsed <= 1_000_000:
        raise _error(f"{field} exceeds the supported range.")
    return parsed


def _minutes(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise _error("edit_minutes must be a finite non-negative number.")
    try:
        parsed = float(value)
    except ValueError as exc:
        raise _error("edit_minutes must be a finite non-negative number.") from exc
    if not math.isfinite(parsed) or not 0 <= parsed <= 1_000_000:
        raise _error("edit_minutes must be a finite non-negative number up to 1000000.")
    return parsed


def _validate_record(record: Mapping[str, object]) -> dict[str, object]:
    if not isinstance(record, Mapping) or set(record) != RECORD_FIELDS:
        raise _error("Article feedback has an invalid schema.")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise _error("Article feedback schema version is unsupported.")
    _, relative = _relative_under_outputs(record["run"], label="Recorded run")
    if record["run"] != f"outputs/{relative}":
        raise _error("Recorded run must use its canonical outputs path.")
    for field in ("article_sha256", "manifest_sha256"):
        if not isinstance(record[field], str) or re.fullmatch(r"[a-f0-9]{64}", record[field]) is None:
            raise _error(f"{field} must be a SHA-256 digest.")
    if record["decision"] not in DECISIONS:
        raise _error("Article feedback decision is unsupported.")
    edits = _count(record["substantial_rewrites"], "substantial_rewrites")
    hooks = _count(record["hook_replacements"], "hook_replacements")
    corrections = _count(record["factual_corrections"], "factual_corrections")
    if record["decision"] == "accepted_light_edits" and (edits or hooks):
        raise _error("Light edits cannot include substantial rewrites or hook replacements.")
    notes = record["notes"]
    if not isinstance(notes, str) or len(notes) > 2000 or any(ord(c) < 32 and c not in "\n\t" for c in notes):
        raise _error("notes must be text of at most 2000 characters.")
    recorded = record["recorded_at"]
    if not isinstance(recorded, str):
        raise _error("recorded_at must be a UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    except ValueError as exc:
        raise _error("recorded_at must be a UTC timestamp.") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise _error("recorded_at must be a UTC timestamp.")
    return {
        **record, "edit_minutes": _minutes(record["edit_minutes"]),
        "substantial_rewrites": edits, "hook_replacements": hooks,
        "factual_corrections": corrections,
    }


def _directory(path: Path | str, *, create: bool) -> tuple[Path, int]:
    target, relative = _relative_under_outputs(path, label="Feedback directory")
    if not hasattr(os, "O_NOFOLLOW") or os.name != "posix":
        raise _error("Secure feedback storage requires POSIX no-follow file operations.")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
    root = -1
    current = -1
    success = False
    try:
        root = os.open(workflow.DEFAULT_OUTPUTS, flags)
        current = root
        parts = relative.split("/")
        for index, component in enumerate(parts):
            if index:
                parent = os.fstat(current)
                if parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700:
                    raise _error("Feedback parent directory must be owner-only (0700).")
            if create and index == len(parts) - 1:
                try:
                    os.mkdir(component, 0o700, dir_fd=current)
                except FileExistsError:
                    pass
            try:
                next_fd = os.open(component, flags, dir_fd=current)
            except FileNotFoundError:
                if not create:
                    raise _MissingFeedbackDirectory from None
                raise
            if current != root:
                os.close(current)
            current = next_fd
        metadata = os.fstat(current)
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
            raise _error("Feedback directory must be owner-only (0700).")
        success = True
        return target, current
    except OSError as exc:
        raise _error("Feedback directory is unavailable or unsafe.") from exc
    finally:
        if not success and current >= 0 and current != root:
            os.close(current)
        if root >= 0 and (root != current or not success):
            os.close(root)


def _read_feedback(fd: int, filename: str) -> dict[str, object]:
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0),
            dir_fd=fd,
        )
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or stat.S_IMODE(before.st_mode) != 0o600 or before.st_size > MAX_FILE_BYTES):
            raise _error("Feedback record is unavailable or unsafe.")
        raw = b""
        while len(raw) < before.st_size:
            chunk = os.read(descriptor, before.st_size - len(raw))
            if not chunk:
                raise _error("Feedback record changed while reading.")
            raw += chunk
        after = os.fstat(descriptor)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns):
            raise _error("Feedback record changed while reading.")
        return _validate_record(_strict_json(raw.decode("utf-8"), "Feedback record"))
    except FileNotFoundError:
        raise
    except (OSError, UnicodeDecodeError) as exc:
        raise _error("Feedback record is unavailable or unsafe.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def record_feedback(
    run: Path | str, *, decision: str, edit_minutes: object,
    substantial_rewrites: object, hook_replacements: object,
    factual_corrections: object, notes: str = "",
    feedback_dir: Path | str = DEFAULT_FEEDBACK_DIR,
) -> tuple[Path, bool]:
    relative, article_digest, manifest_digest = _run_identity(run)
    record = _validate_record({
        "schema_version": 1, "run": f"outputs/{relative}",
        "article_sha256": article_digest, "manifest_sha256": manifest_digest,
        "decision": decision, "edit_minutes": edit_minutes,
        "substantial_rewrites": substantial_rewrites,
        "hook_replacements": hook_replacements, "factual_corrections": factual_corrections,
        "notes": notes,
        "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    target, fd = _directory(feedback_dir, create=True)
    filename = hashlib.sha256(relative.encode("utf-8")).hexdigest() + ".json"
    temporary = "." + uuid.uuid4().hex + ".tmp"
    temp_fd = -1
    try:
        try:
            existing = _read_feedback(fd, filename)
        except FileNotFoundError:
            existing = None
        if existing is not None:
            if {k: v for k, v in existing.items() if k != "recorded_at"} == {k: v for k, v in record.items() if k != "recorded_at"}:
                return target / filename, False
            raise _error("This run already has conflicting feedback; its history cannot be overwritten.")
        if len([name for name in os.listdir(fd) if name.endswith(".json")]) >= MAX_RECORDS:
            raise _error("Feedback directory has too many records.")
        payload = (json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(payload) > MAX_FILE_BYTES:
            raise _error("Feedback record is too large.")
        temp_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        offset = 0
        while offset < len(payload):
            written = os.write(temp_fd, payload[offset:])
            if written < 1:
                raise _error("Feedback record could not be written completely.")
            offset += written
        os.fsync(temp_fd)
        os.close(temp_fd)
        temp_fd = -1
        try:
            os.link(temporary, filename, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
        except FileExistsError:
            existing = _read_feedback(fd, filename)
            if {k: v for k, v in existing.items() if k != "recorded_at"} == {k: v for k, v in record.items() if k != "recorded_at"}:
                return target / filename, False
            raise _error("This run already has conflicting feedback; its history cannot be overwritten.")
        os.fsync(fd)
        return target / filename, True
    except OSError as exc:
        raise _error("Feedback record could not be stored safely.") from exc
    finally:
        if temp_fd >= 0:
            os.close(temp_fd)
        try:
            os.unlink(temporary, dir_fd=fd)
        except FileNotFoundError:
            pass
        os.close(fd)


def load_records(feedback_dir: Path | str = DEFAULT_FEEDBACK_DIR) -> list[dict[str, object]]:
    try:
        _, fd = _directory(feedback_dir, create=False)
    except _MissingFeedbackDirectory:
        return []
    try:
        names = sorted(name for name in os.listdir(fd) if name.endswith(".json"))
        if len(names) > MAX_RECORDS:
            raise _error("Feedback directory has too many records.")
        records = [_read_feedback(fd, name) for name in names]
        for name, record in zip(names, records):
            relative = str(record["run"])[len("outputs/"):]
            if name != hashlib.sha256(relative.encode("utf-8")).hexdigest() + ".json":
                raise _error("Feedback filename does not match its run.")
        return records
    finally:
        os.close(fd)


def summarise(records: Sequence[Mapping[str, object]]) -> dict[str, object]:
    validated = [_validate_record(record) for record in records]
    runs = [str(record["run"]) for record in validated]
    if len(set(runs)) != len(runs):
        raise _error("Duplicate feedback for one run cannot be summarised.")
    light = sum(record["decision"] == "accepted_light_edits" for record in validated)
    return {
        "reviewed_runs": len(validated),
        "accepted_light_edits": light,
        "accepted_substantial_edits": sum(record["decision"] == "accepted_substantial_edits" for record in validated),
        "rejected": sum(record["decision"] == "rejected" for record in validated),
        "accepted_light_edits_rate": round(light / len(validated), 4) if validated else None,
        "median_edit_minutes": median(float(record["edit_minutes"]) for record in validated) if validated else None,
        "median_substantial_rewrites": median(int(record["substantial_rewrites"]) for record in validated) if validated else None,
        "median_hook_replacements": median(int(record["hook_replacements"]) for record in validated) if validated else None,
        "median_factual_corrections": median(int(record["factual_corrections"]) for record in validated) if validated else None,
        "factual_review_pass": None,
        "human_approval_granted": False,
        "publishing_status": "DISABLED",
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="python -m authority_os.article_feedback")
    commands = result.add_subparsers(dest="command", required=True)
    record = commands.add_parser("record", help="Record one human article decision locally.")
    record.add_argument("--run", required=True)
    record.add_argument("--decision", choices=DECISIONS, required=True)
    record.add_argument("--edit-minutes", required=True)
    for field in ("substantial-rewrites", "hook-replacements", "factual-corrections"):
        record.add_argument("--" + field, required=True)
    record.add_argument("--notes", default="")
    summary = commands.add_parser("summary", help="Summarise observed human feedback.")
    for command in (record, summary):
        command.add_argument("--feedback-dir", default=str(DEFAULT_FEEDBACK_DIR))
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "record":
            path, created = record_feedback(
                args.run, decision=args.decision, edit_minutes=args.edit_minutes,
                substantial_rewrites=args.substantial_rewrites,
                hook_replacements=args.hook_replacements,
                factual_corrections=args.factual_corrections, notes=args.notes,
                feedback_dir=args.feedback_dir,
            )
            print(json.dumps({"record": str(path.relative_to(workflow.REPO_ROOT)), "created": created}, sort_keys=True))
        else:
            print(json.dumps(summarise(load_records(args.feedback_dir)), sort_keys=True))
        return 0
    except (workflow.WorkflowError, ValueError, TypeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
