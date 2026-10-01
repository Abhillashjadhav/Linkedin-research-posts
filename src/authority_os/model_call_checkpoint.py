"""Private, run-bound replay of completed structured model calls.

A returned JSON result is reusable only after durable recording. A failed
call followed by later completed work is also recorded and replayed to retain
an existing optional-stage fallback. A terminal failed or interrupted call is
retried; this is not an exactly-once provider guarantee.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Mapping

from . import daily_cli, workflow


SOURCE_ENV = "LINKEDIN_OS_MODEL_CACHE_SOURCE"
OUTPUT_ENV = "LINKEDIN_OS_MODEL_CACHE_OUTPUT"
INPUT_ENV = "LINKEDIN_OS_MODEL_CACHE_INPUT_SHA256"
_sequence = 0


def _digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _identity(folder: Path) -> tuple[str, str]:
    run_folder = daily_cli._under_private(folder.parent)
    identity = daily_cli._private_json(run_folder / "run-input.json", "Model cache run identity")
    expected = os.environ.get(INPUT_ENV)
    if (
        not isinstance(identity, Mapping)
        or not isinstance(identity.get("run_id"), str)
        or identity.get("input_fingerprint") != expected
        or not isinstance(expected, str)
        or len(expected) != 64
    ):
        raise workflow.WorkflowError("Model cache run input or identity changed.")
    return str(identity["run_id"]), str(run_folder.resolve())


def _read_record(folder: Path, ordinal: int, request_sha: str) -> dict[str, object] | None:
    path = daily_cli._under_private(folder / f"call-{ordinal:06d}.json")
    if not path.exists():
        return None
    if path.is_symlink():
        raise workflow.WorkflowError("Model call checkpoint must not be a symlink.")
    run_id, run_directory = _identity(folder)
    record = daily_cli._private_json(path, "Model call checkpoint")
    if (
        not isinstance(record, Mapping)
        or record.get("schema_version") != 1
        or record.get("ordinal") != ordinal
        or record.get("request_sha256") != request_sha
        or record.get("run_id") != run_id
        or record.get("run_directory") != run_directory
        or record.get("status") not in {"RETURNED", "RAISED"}
    ):
        raise workflow.WorkflowError("Model call checkpoint no longer matches its request or response.")
    if record["status"] == "RETURNED":
        if not isinstance(record.get("response"), dict) or record.get("response_sha256") != _digest(record["response"]):
            raise workflow.WorkflowError("Model call checkpoint no longer matches its request or response.")
    elif (
        record.get("exception_type") not in {"WorkflowError", "ModelTimeoutError"}
        or not isinstance(record.get("message"), str)
        or record.get("failure_sha256") != _digest({
            "exception_type": record.get("exception_type"), "message": record.get("message")
        })
    ):
        raise workflow.WorkflowError("Model call checkpoint no longer matches its request or response.")
    return dict(record)


def _validate_cache_prefix(folder: Path) -> int:
    """Reject every gap before replay or a fresh provider invocation."""

    target = daily_cli._under_private(folder)
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise workflow.WorkflowError("Model cache directory is unsafe.")
    if not target.exists():
        return 0
    _identity(target)
    indices: list[int] = []
    for path in target.iterdir():
        if path.name.startswith(".call-") and path.name.endswith(".tmp"):
            continue  # Interrupted, never-published temporary output.
        match = re.fullmatch(r"call-(\d{6})\.json", path.name)
        if not match or path.is_symlink() or not path.is_file():
            raise workflow.WorkflowError("Model cache contains an unsafe checkpoint entry.")
        indices.append(int(match.group(1)))
    if sorted(indices) != list(range(1, len(indices) + 1)):
        raise workflow.WorkflowError("Model cache has a missing earlier call checkpoint.")
    return len(indices)


def _write_record(
    folder: Path, ordinal: int, request_sha: str,
    *, response: Mapping[str, object] | None = None,
    failure: tuple[str, str] | None = None,
    replayed_from_run_id: str | None = None,
) -> None:
    if (response is None) == (failure is None):
        raise workflow.WorkflowError("Model checkpoint needs one completed outcome.")
    target = daily_cli._under_private(folder)
    daily_cli.legacy_cli._ensure_owner_only_directory(target)
    run_id, run_directory = _identity(target)
    path = target / f"call-{ordinal:06d}.json"
    if path.exists():
        raise workflow.WorkflowError("Model call checkpoint already exists in this run.")
    record = {
        "schema_version": 1, "ordinal": ordinal,
        "run_id": run_id, "run_directory": run_directory,
        "request_sha256": request_sha,
        "status": "RETURNED" if response is not None else "RAISED",
        "replayed_from_run_id": replayed_from_run_id,
    }
    if response is not None:
        record.update(response_sha256=_digest(response), response=dict(response))
    else:
        assert failure is not None
        kind, message = failure
        record.update(
            exception_type=kind, message=message,
            failure_sha256=_digest({"exception_type": kind, "message": message}),
        )
    payload = (json.dumps(record, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    temporary = target / f".call-{ordinal:06d}-{os.getpid()}.tmp"
    descriptor = os.open(
        temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written < 1:
                raise workflow.WorkflowError("Model call checkpoint write was incomplete.")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory_fd = os.open(target, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def begin_call(request: Mapping[str, object]) -> tuple[int, str, dict[str, object] | None, tuple[str, str] | None] | None:
    """Return a validated prior result for this exact ordinal and request, if any."""

    output = os.environ.get(OUTPUT_ENV)
    if not output:
        return None
    global _sequence
    _sequence += 1
    ordinal = _sequence
    request_sha = _digest(dict(request))
    output_path = Path(output)
    if _validate_cache_prefix(output_path) != ordinal - 1:
        raise workflow.WorkflowError("Model cache output is missing a completed earlier call.")
    source = os.environ.get(SOURCE_ENV)
    if source:
        source_count = _validate_cache_prefix(Path(source))
        record = _read_record(Path(source), ordinal, request_sha)
        if record is not None:
            source_run_id, _source_directory = _identity(Path(source))
            if record["status"] == "RETURNED":
                response = dict(record["response"])
                _write_record(
                    output_path, ordinal, request_sha, response=response,
                    replayed_from_run_id=source_run_id,
                )
                return ordinal, request_sha, response, None
            if source_count > ordinal:
                failure = (str(record["exception_type"]), str(record["message"]))
                _write_record(
                    output_path, ordinal, request_sha, failure=failure,
                    replayed_from_run_id=source_run_id,
                )
                return ordinal, request_sha, None, failure
            # A terminal failed call has no later evidence of a completed
            # fallback path. It is the first incomplete call and may be retried.
    return ordinal, request_sha, None, None


def finish_call(token: tuple[int, str, dict[str, object] | None, tuple[str, str] | None] | None, response: Mapping[str, object]) -> None:
    if token is not None and token[2] is None and token[3] is None:
        output = os.environ.get(OUTPUT_ENV)
        if not output:
            raise workflow.WorkflowError("Model call cache output disappeared before checkpoint.")
        _write_record(Path(output), token[0], token[1], response=response)


def fail_call(
    token: tuple[int, str, dict[str, object] | None, tuple[str, str] | None] | None,
    error: workflow.WorkflowError,
) -> None:
    """Persist a handled model failure so later completed calls remain contiguous."""

    if token is None or token[2] is not None or token[3] is not None:
        return
    from .model_runtime import ModelTimeoutError

    output = os.environ.get(OUTPUT_ENV)
    if not output:
        raise workflow.WorkflowError("Model call cache output disappeared before checkpoint.")
    kind = "ModelTimeoutError" if isinstance(error, ModelTimeoutError) else "WorkflowError"
    _write_record(Path(output), token[0], token[1], failure=(kind, str(error)))


def reset_sequence_for_tests() -> None:
    global _sequence
    _sequence = 0
