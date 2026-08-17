"""Locked persistence guard for spine-performance snapshots."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
from typing import Mapping

from . import spine_feedback as base
from . import workflow


def _existing_records_locked(
    root_fd: int,
    filename: str,
    write_descriptor: int,
) -> list[dict[str, object]]:
    read_descriptor = -1
    try:
        read_descriptor = os.open(
            filename,
            os.O_RDONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=root_fd,
        )
        write_metadata = os.fstat(write_descriptor)
        read_metadata = os.fstat(read_descriptor)
        if (
            write_metadata.st_dev != read_metadata.st_dev
            or write_metadata.st_ino != read_metadata.st_ino
            or not base._valid_feedback_file(read_metadata)
        ):
            raise workflow.WorkflowError(
                "Private spine feedback file is unavailable or unsafe."
            )
        chunks: list[bytes] = []
        remaining = read_metadata.st_size
        while remaining:
            chunk = os.read(read_descriptor, min(65_536, remaining))
            if not chunk:
                raise workflow.WorkflowError(
                    "Private spine feedback file changed while reading."
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        after = os.fstat(read_descriptor)
        if (
            after.st_dev != read_metadata.st_dev
            or after.st_ino != read_metadata.st_ino
            or after.st_size != read_metadata.st_size
        ):
            raise workflow.WorkflowError(
                "Private spine feedback file changed while reading."
            )
        raw = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise workflow.WorkflowError(
            "Private spine feedback file is not valid UTF-8."
        ) from exc
    except OSError as exc:
        raise workflow.WorkflowError(
            "Private spine feedback file is unavailable or unsafe."
        ) from exc
    finally:
        if read_descriptor >= 0:
            os.close(read_descriptor)

    if not raw:
        return []
    lines = raw.splitlines()
    if len(lines) > base.MAX_RECORDS:
        raise workflow.WorkflowError("Private spine feedback has too many records.")
    records: list[dict[str, object]] = []
    for line in lines:
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError as exc:
            raise workflow.WorkflowError(
                "Private spine feedback contains invalid JSONL."
            ) from exc
        if not isinstance(parsed, Mapping):
            raise workflow.WorkflowError(
                "Private spine feedback contains an invalid record."
            )
        records.append(base.validate_record(parsed))
    return records


def _assert_context_compatible(
    existing: list[Mapping[str, object]],
    candidate: Mapping[str, object],
) -> None:
    for record in existing:
        if record["post_url"] != candidate["post_url"]:
            continue
        if any(
            record[field] != candidate[field]
            for field in base.IMMUTABLE_CONTEXT_FIELDS
        ):
            raise workflow.WorkflowError(
                "Spine performance snapshot changes immutable post context."
            )


def append_record(
    record: Mapping[str, object],
    *,
    path: Path | str = base.DEFAULT_FEEDBACK_FILE,
    private_root: Path | str = workflow.DEFAULT_PRIVATE_DATA,
    _allow_test_root: bool = False,
) -> Path:
    validated = base.validate_record(record)
    root, filename = base._feedback_location(
        path,
        private_root=private_root,
        allow_test_root=_allow_test_root,
    )
    root_fd = base._private_root(root)
    descriptor = -1
    try:
        descriptor = base._open_append_file(root_fd, filename)
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        metadata = os.fstat(descriptor)
        if not base._valid_feedback_file(metadata):
            raise workflow.WorkflowError(
                "Private spine feedback file is unavailable or unsafe."
            )
        existing = _existing_records_locked(root_fd, filename, descriptor)
        _assert_context_compatible(existing, validated)
        if len(existing) >= base.MAX_RECORDS:
            raise workflow.WorkflowError(
                "Private spine feedback has too many records."
            )
        payload = (
            json.dumps(validated, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        metadata = os.fstat(descriptor)
        if metadata.st_size + len(payload) > base.MAX_FILE_BYTES:
            raise workflow.WorkflowError(
                "Private spine feedback file reached its size limit."
            )
        base._write_all(descriptor, payload)
        os.fsync(descriptor)
    except OSError as exc:
        raise workflow.WorkflowError(
            "Private spine feedback file is unavailable or unsafe."
        ) from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(root_fd)
    return root / filename


def command_record(args: object) -> int:
    record = base.prepare_record(
        post_url=args.post_url,
        post_id=args.post_id,
        published_at=args.published_at,
        topic=args.topic,
        attention_source=args.attention_source,
        selected_spine=args.spine,
        impressions=args.impressions,
        engagements=args.engagements,
        qualified_comments=args.qualified_comments,
        reposts=args.reposts,
        saves=args.saves,
        profile_visits=args.profile_visits,
        relevant_followers=args.relevant_followers,
        is_breakout_outlier=args.breakout_outlier,
        observed_at=args.observed_at,
    )
    result_path = append_record(record)
    print(
        "Private spine performance recorded: "
        f"{result_path.relative_to(workflow.REPO_ROOT)}"
    )
    print(
        f"Spine: {record['selected_spine']}; weekday={record['weekday']}; "
        f"breakout={str(record['is_breakout_outlier']).lower()}."
    )
    print("Publishing status: DISABLED. No LinkedIn action was taken.")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = base.parser().parse_args(argv)
    try:
        return command_record(args) if args.command == "record" else base.command_review(args)
    except (workflow.WorkflowError, ValueError) as exc:
        print(f"ERROR: {exc}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
