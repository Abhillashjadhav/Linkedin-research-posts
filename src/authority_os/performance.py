"""Validate manual publication assertions and prepare performance checkpoints."""

from __future__ import annotations

import csv
import hashlib
import hmac
import io
import json
import os
import re
import stat
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Mapping, Sequence

from . import package as approval_package, storage, workflow


MAX_PACKAGE_FILE_BYTES = 1_000_000
MAX_CSV_BYTES = 1_000_000
MAX_CSV_ROWS = 1_000
MAX_LEARNING_HOOK_CHARS = 280
MAX_LEARNING_ANGLE_CHARS = 500
MAX_LEARNING_CANDIDATE_CHARS = 20_000
MAX_LEARNING_PARAGRAPHS = 100
MAX_LEARNING_ROUTE_STAGES = 8
MAX_LEARNING_ROUTE_STAGE_CHARS = 80
CSV_FIELDS = (
    "package_id",
    "candidate_id",
    "published_at",
    "checkpoint",
    "channel",
    "observed_at",
    *storage.PERFORMANCE_METRICS,
)
_MANIFEST_FIELDS = {
    "schema_version",
    "package_id",
    "created_at",
    "mode",
    "topic_slug",
    "goal",
    "output_format",
    "weekly_slot",
    "revision_count",
    "review_status",
    "human_approval_status",
    "publishing_status",
    "eligible_candidate_ids",
    "recommended_candidate_id",
    "manual_fact_verification_required",
    "files",
}
_EVALUATION_FIELDS = {
    "schema_version",
    "scorecards",
    "ranking",
    "score_leader_id",
    "revision_count",
    "revision_candidate_id",
    "gate_results",
    "eligible_candidate_ids",
    "recommended_candidate_id",
    "review_status",
    "manual_fact_verification_required",
}
_GATE_RESULT_FIELDS = {
    "candidate_id",
    "gates",
    "passes_required_gates",
    "manual_fact_verification_required",
}
_GATE_FIELDS = {"status", "reason_codes"}
_LEARNING_DOCUMENTS = frozenset(
    {"manifest.json", "evaluation.json", "brief.md", "candidates.md"}
)


def _require_secure_local_reads() -> None:
    if not all(
        (
            getattr(os, "O_DIRECTORY", 0),
            getattr(os, "O_NOFOLLOW", 0),
            getattr(os, "O_NONBLOCK", 0),
            hasattr(os, "open"),
            hasattr(os, "fstat"),
            hasattr(os, "geteuid"),
        )
    ):
        raise workflow.WorkflowError(
            "Secure local performance input reads are unavailable on this platform."
        )


def _open_directory(path: Path | str, *, directory_fd: int | None = None) -> int:
    _require_secure_local_reads()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags, dir_fd=directory_fd)
        metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError("not a directory")
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise workflow.WorkflowError(
                "Private performance directories must be owner-only (mode 0700)."
            )
        return descriptor
    except workflow.WorkflowError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise workflow.WorkflowError(
            "A required private performance directory is unavailable or unsafe."
        ) from exc


def _open_regular_file(
    filename: str,
    *,
    directory_fd: int,
    maximum_bytes: int,
) -> tuple[int, os.stat_result]:
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory_fd,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise workflow.WorkflowError(
                "A required private performance file is unavailable or unsafe."
            )
        if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
            raise workflow.WorkflowError(
                "Private performance files must be owner-only (mode 0600)."
            )
        if metadata.st_size <= 0 or metadata.st_size > maximum_bytes:
            raise workflow.WorkflowError(
                "A required private performance file is unavailable or unsafe."
            )
        return descriptor, metadata
    except workflow.WorkflowError:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise workflow.WorkflowError(
            "A required private performance file is unavailable or unsafe."
        ) from exc


def _metadata_token(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _read_open_regular_file(
    descriptor: int,
    metadata: os.stat_result,
) -> str:
    chunks: list[bytes] = []
    remaining = int(metadata.st_size)
    while remaining:
        chunk = os.read(descriptor, min(65_536, remaining))
        if not chunk:
            raise workflow.WorkflowError(
                "A required private performance file could not be read completely."
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1) or _metadata_token(os.fstat(descriptor)) != _metadata_token(
        metadata
    ):
        raise workflow.WorkflowError(
            "A required private performance file changed while it was read."
        )
    try:
        return b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise workflow.WorkflowError(
            "A required private performance file is not valid UTF-8."
        ) from exc


def _read_regular_file(
    filename: str,
    *,
    directory_fd: int,
    maximum_bytes: int,
) -> str:
    descriptor, metadata = _open_regular_file(
        filename,
        directory_fd=directory_fd,
        maximum_bytes=maximum_bytes,
    )
    try:
        return _read_open_regular_file(descriptor, metadata)
    finally:
        os.close(descriptor)


def _package_parts(package_id: object) -> tuple[str, str, str]:
    if not isinstance(package_id, str):
        raise workflow.WorkflowError("Performance package ID is invalid.")
    match = re.fullmatch(
        r"(\d{4}-\d{2}-\d{2})-([a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?)",
        package_id,
    )
    if match is None:
        raise workflow.WorkflowError("Performance package ID is invalid.")
    try:
        datetime.strptime(match.group(1), "%Y-%m-%d")
    except ValueError as exc:
        raise workflow.WorkflowError("Performance package ID is invalid.") from exc
    return package_id, match.group(1), match.group(2)


def _load_package_documents(
    package_id: object,
    *,
    output_root: Path | str = workflow.DEFAULT_OUTPUTS,
    _allow_test_output_root: bool = False,
    include_learning_documents: bool = False,
) -> tuple[Mapping[str, object], Mapping[str, object], dict[str, str]]:
    expected_id, date_name, directory_name = _package_parts(package_id)
    root = Path(output_root)
    if not root.is_absolute():
        raise workflow.WorkflowError("Performance output root must be absolute.")
    if root != workflow.DEFAULT_OUTPUTS and not _allow_test_output_root:
        raise workflow.WorkflowError(
            "Performance packages can only be read from the fixed local output root."
        )
    if type(include_learning_documents) is not bool:
        raise workflow.WorkflowError("Performance package read scope is invalid.")
    root_fd = date_fd = package_fd = -1
    opened_files: dict[str, tuple[int, os.stat_result]] = {}
    documents: dict[str, str] = {}
    try:
        root_fd = _open_directory(root)
        date_fd = _open_directory(date_name, directory_fd=root_fd)
        package_fd = _open_directory(directory_name, directory_fd=date_fd)
        package_metadata = os.fstat(package_fd)
        expected_files = set(approval_package.PACKAGE_FILES.values())
        try:
            entries = set(os.listdir(package_fd))
        except OSError as exc:
            raise workflow.WorkflowError(
                "The performance package inventory could not be verified."
            ) from exc
        if entries != expected_files:
            raise workflow.WorkflowError(
                "The performance package is incomplete or has an invalid inventory."
            )
        for filename in sorted(expected_files):
            opened_files[filename] = _open_regular_file(
                filename,
                directory_fd=package_fd,
                maximum_bytes=MAX_PACKAGE_FILE_BYTES,
            )
        read_names = (
            _LEARNING_DOCUMENTS
            if include_learning_documents
            else frozenset({"manifest.json", "evaluation.json"})
        )
        for filename in sorted(read_names):
            descriptor, metadata = opened_files[filename]
            documents[filename] = _read_open_regular_file(descriptor, metadata)
        try:
            entries_after = set(os.listdir(package_fd))
        except OSError as exc:
            raise workflow.WorkflowError(
                "The performance package inventory could not be verified."
            ) from exc
        if entries_after != expected_files:
            raise workflow.WorkflowError(
                "The performance package changed while it was read."
            )
        if _metadata_token(os.fstat(package_fd)) != _metadata_token(package_metadata):
            raise workflow.WorkflowError(
                "The performance package changed while it was read."
            )
        if any(
            _metadata_token(os.fstat(descriptor)) != _metadata_token(metadata)
            for descriptor, metadata in opened_files.values()
        ):
            raise workflow.WorkflowError(
                "The performance package changed while it was read."
            )
    finally:
        for descriptor, _metadata in opened_files.values():
            os.close(descriptor)
        for descriptor in (package_fd, date_fd, root_fd):
            if descriptor >= 0:
                os.close(descriptor)
    try:
        manifest = json.loads(documents["manifest.json"])
        evaluation = json.loads(documents["evaluation.json"])
    except (json.JSONDecodeError, RecursionError, KeyError) as exc:
        raise workflow.WorkflowError(
            "The performance package contains invalid JSON."
        ) from exc
    if not isinstance(manifest, Mapping) or not isinstance(evaluation, Mapping):
        raise workflow.WorkflowError("The performance package schema is invalid.")
    if manifest.get("package_id") != expected_id:
        raise workflow.WorkflowError("The performance package ID does not match its path.")
    learning_documents = {
        filename: documents[filename]
        for filename in ("brief.md", "candidates.md")
        if filename in documents
    }
    return manifest, evaluation, learning_documents


def _validate_package_context(
    package_id: object,
    candidate_id: object,
    *,
    manifest: Mapping[str, object],
    evaluation: Mapping[str, object],
) -> dict[str, object]:
    """Validate one explicit candidate against an already anchored package snapshot."""

    if set(manifest) != _MANIFEST_FIELDS or set(evaluation) != _EVALUATION_FIELDS:
        raise workflow.WorkflowError("The performance package schema is invalid.")
    if (
        manifest["schema_version"] != approval_package.PACKAGE_SCHEMA_VERSION
        or evaluation["schema_version"] != approval_package.PACKAGE_SCHEMA_VERSION
        or manifest["files"] != dict(approval_package.PACKAGE_FILES)
    ):
        raise workflow.WorkflowError("The performance package schema is unsupported.")
    if (
        manifest["mode"] != "live"
        or manifest["review_status"] != "READY_FOR_HUMAN_REVIEW"
        or evaluation["review_status"] != "READY_FOR_HUMAN_REVIEW"
        or manifest["human_approval_status"] != "NOT_APPROVED"
        or manifest["publishing_status"] != "DISABLED"
        or manifest["manual_fact_verification_required"] is not True
        or evaluation["manual_fact_verification_required"] is not True
    ):
        raise workflow.WorkflowError(
            "Performance can only be attached to a committed live review-ready package."
        )
    goal = manifest["goal"]
    if goal not in workflow.STRATEGIC_GOALS:
        raise workflow.WorkflowError("The performance package goal is invalid.")
    eligible = manifest["eligible_candidate_ids"]
    if (
        not isinstance(eligible, list)
        or not eligible
        or any(not isinstance(item, str) or not item for item in eligible)
        or len(set(eligible)) != len(eligible)
        or evaluation["eligible_candidate_ids"] != eligible
    ):
        raise workflow.WorkflowError("The performance package eligibility is invalid.")
    recommended_id = manifest["recommended_candidate_id"]
    if (
        not isinstance(recommended_id, str)
        or recommended_id != eligible[0]
        or evaluation["recommended_candidate_id"] != recommended_id
    ):
        raise workflow.WorkflowError("The performance package recommendation is invalid.")
    if not isinstance(candidate_id, str) or candidate_id not in eligible:
        raise workflow.WorkflowError(
            "The selected performance candidate is not eligible in this package."
        )
    scorecards = evaluation["scorecards"]
    if not isinstance(scorecards, Sequence) or isinstance(scorecards, (str, bytes)):
        raise workflow.WorkflowError("The performance package scorecards are invalid.")
    ranked = workflow.rank_critic_scorecards(scorecards)  # type: ignore[arg-type]
    ranking = [str(scorecard["candidate_id"]) for scorecard in ranked]
    if (
        len(ranking) != 3
        or evaluation["ranking"] != ranking
        or evaluation["score_leader_id"] != ranking[0]
        or not set(eligible).issubset(ranking)
    ):
        raise workflow.WorkflowError("The performance package ranking is invalid.")
    gates = evaluation["gate_results"]
    if not isinstance(gates, list) or not all(isinstance(item, Mapping) for item in gates):
        raise workflow.WorkflowError("The performance package gate results are invalid.")
    gates_by_id: dict[str, bool] = {}
    for gate in gates:
        if set(gate) != _GATE_RESULT_FIELDS:
            raise workflow.WorkflowError("The performance package gate results are invalid.")
        gate_id = gate.get("candidate_id")
        if not isinstance(gate_id, str) or gate_id in gates_by_id:
            raise workflow.WorkflowError("The performance package gate results are invalid.")
        gate_map = gate.get("gates")
        if (
            not isinstance(gate_map, Mapping)
            or set(gate_map) != set(workflow.GATE_ORDER)
            or gate.get("manual_fact_verification_required") is not True
        ):
            raise workflow.WorkflowError("The performance package gate results are invalid.")
        statuses: list[str] = []
        for gate_name in workflow.GATE_ORDER:
            result = gate_map[gate_name]
            if not isinstance(result, Mapping) or set(result) != _GATE_FIELDS:
                raise workflow.WorkflowError("The performance package gate results are invalid.")
            status_value = result.get("status")
            reasons = result.get("reason_codes")
            if (
                not isinstance(status_value, str)
                or status_value not in workflow.GATE_STATUSES
                or (status_value == "NOT_REQUIRED" and gate_name != "proof")
                or (
                    gate_name == "proof"
                    and (
                        (goal == "opportunity" and status_value == "NOT_REQUIRED")
                        or (goal != "opportunity" and status_value != "NOT_REQUIRED")
                    )
                )
                or not isinstance(reasons, list)
                or not reasons
                or any(not isinstance(reason, str) or not reason for reason in reasons)
                or len(reasons) != len(set(reasons))
            ):
                raise workflow.WorkflowError("The performance package gate results are invalid.")
            statuses.append(str(status_value))
        computed_pass = all(
            status == "PASS" for status in statuses if status != "NOT_REQUIRED"
        )
        if type(gate.get("passes_required_gates")) is not bool or (
            gate["passes_required_gates"] is not computed_pass
        ):
            raise workflow.WorkflowError("The performance package gate results are invalid.")
        gates_by_id[gate_id] = computed_pass
    if set(gates_by_id) != set(ranking):
        raise workflow.WorkflowError("The performance package gate results are invalid.")
    scorecards_by_id = {
        str(scorecard["candidate_id"]): scorecard for scorecard in ranked
    }
    computed_eligible = [
        ranked_id
        for ranked_id in ranking
        if scorecards_by_id[ranked_id]["band"] == "advance-to-gates"
        and gates_by_id[ranked_id]
    ]
    if eligible != computed_eligible:
        raise workflow.WorkflowError("The performance package eligibility is invalid.")
    revision_count = evaluation["revision_count"]
    revision_candidate_id = evaluation["revision_candidate_id"]
    if (
        type(revision_count) is not int
        or revision_count not in (0, 1)
        or manifest["revision_count"] != revision_count
        or (
            revision_count == 0
            and revision_candidate_id is not None
        )
        or (
            revision_count == 1
            and revision_candidate_id not in ranking
        )
    ):
        raise workflow.WorkflowError("The performance package revision metadata is invalid.")
    output_format = manifest["output_format"]
    weekly_slot = manifest["weekly_slot"]
    if goal not in workflow.STRATEGIC_GOALS:
        raise workflow.WorkflowError("The performance package goal is invalid.")
    if output_format is not None and output_format not in workflow.OUTPUT_FORMATS:
        raise workflow.WorkflowError("The performance package format is invalid.")
    if weekly_slot is not None and (
        type(weekly_slot) is not int or not 1 <= weekly_slot <= 5
    ):
        raise workflow.WorkflowError("The performance package weekly slot is invalid.")
    try:
        package_created_at = storage.normalise_performance_timestamp(
            manifest["created_at"], field="package created_at"
        )
    except ValueError as exc:
        raise workflow.WorkflowError(str(exc)) from exc
    if not package_created_at.startswith(f"{str(package_id)[:10]}T"):
        raise workflow.WorkflowError(
            "The performance package creation time does not match its ID."
        )
    selected = scorecards_by_id[candidate_id]
    return {
        "package_id": package_id,
        "candidate_id": candidate_id,
        "package_created_at": package_created_at,
        "goal": goal,
        "output_format": output_format,
        "weekly_slot": weekly_slot,
        "revision_count": revision_count,
        "was_revised": revision_count == 1 and revision_candidate_id == candidate_id,
        **{
            axis: selected[axis]
            for axis in workflow.CRITIC_AXES
        },
        "critic_raw_total": selected["raw_total"],
        "critic_effective_total": selected["effective_total"],
        "critic_hook_cap_applied": selected["hook_cap_applied"],
        "critic_band": selected["band"],
        "critic_rank": ranking.index(candidate_id) + 1,
        "is_recommended": candidate_id == recommended_id,
    }


def _bounded_learning_text(value: str, *, label: str, maximum: int) -> str:
    if (
        not value
        or value != value.strip()
        or len(value) > maximum
        or any(
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            and character not in "\n\t"
            for character in value
        )
    ):
        raise workflow.WorkflowError(
            f"The performance package {label} is invalid or unsafe."
        )
    return value


def _expect_markdown_line(lines: Sequence[str], cursor: int, expected: str) -> int:
    if cursor >= len(lines) or lines[cursor] != expected:
        raise workflow.WorkflowError("The performance package Markdown is malformed.")
    return cursor + 1


def _literal_markdown_block(
    lines: Sequence[str], cursor: int, *, label: str, maximum: int
) -> tuple[str, int]:
    literal: list[str] = []
    while cursor < len(lines) and lines[cursor].startswith("    "):
        literal.append(lines[cursor][4:])
        cursor += 1
    if not literal:
        raise workflow.WorkflowError("The performance package Markdown is malformed.")
    return (
        _bounded_learning_text("\n".join(literal), label=label, maximum=maximum),
        cursor,
    )


def _parse_candidate_markdown(
    text: str, *, expected_candidate_ids: Sequence[str]
) -> dict[str, tuple[str, str]]:
    if "\r" in text or not text.endswith("\n"):
        raise workflow.WorkflowError("The performance package Markdown is malformed.")
    lines = text.splitlines()
    cursor = _expect_markdown_line(lines, 0, "# Final candidate set")
    cursor = _expect_markdown_line(lines, cursor, "")
    candidates: dict[str, tuple[str, str]] = {}
    for index in range(1, 4):
        if cursor >= len(lines):
            raise workflow.WorkflowError("The performance package Markdown is malformed.")
        header = re.fullmatch(
            rf"## Candidate {index}: `([A-Za-z0-9][A-Za-z0-9._-]{{0,63}})`",
            lines[cursor],
        )
        if header is None or header.group(1) in candidates:
            raise workflow.WorkflowError("The performance package Markdown is malformed.")
        candidate_id = header.group(1)
        cursor += 1
        cursor = _expect_markdown_line(lines, cursor, "")
        cursor = _expect_markdown_line(lines, cursor, "Angle:")
        cursor = _expect_markdown_line(lines, cursor, "")
        angle, cursor = _literal_markdown_block(
            lines,
            cursor,
            label="candidate angle",
            maximum=MAX_LEARNING_ANGLE_CHARS,
        )
        cursor = _expect_markdown_line(lines, cursor, "")
        if cursor >= len(lines):
            raise workflow.WorkflowError("The performance package Markdown is malformed.")
        claims = re.fullmatch(r"Claim IDs: `([^`\r\n]+)`", lines[cursor])
        if claims is None:
            raise workflow.WorkflowError("The performance package Markdown is malformed.")
        claim_ids = claims.group(1).split(", ")
        if (
            not claim_ids
            or len(claim_ids) != len(set(claim_ids))
            or any(
                re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", claim_id)
                is None
                for claim_id in claim_ids
            )
        ):
            raise workflow.WorkflowError("The performance package Markdown is malformed.")
        cursor += 1
        cursor = _expect_markdown_line(lines, cursor, "")
        cursor = _expect_markdown_line(lines, cursor, "Text:")
        cursor = _expect_markdown_line(lines, cursor, "")
        candidate_text, cursor = _literal_markdown_block(
            lines,
            cursor,
            label="candidate text",
            maximum=MAX_LEARNING_CANDIDATE_CHARS,
        )
        candidates[candidate_id] = (angle, candidate_text)
        if index < 3:
            cursor = _expect_markdown_line(lines, cursor, "")
    if cursor != len(lines) or set(candidates) != set(expected_candidate_ids):
        raise workflow.WorkflowError(
            "The performance package candidates do not match its evaluation."
        )
    return candidates


def _brief_field(text: str, label: str) -> str:
    matches = re.findall(rf"(?m)^- {re.escape(label)}: `([^`\r\n]+)`$", text)
    if len(matches) != 1:
        raise workflow.WorkflowError("The performance package Markdown is malformed.")
    return matches[0]


def _parse_planned_route(
    text: str,
    *,
    package_id: object,
    goal: object,
    topic_slug: object,
) -> list[str]:
    if "\r" in text or not text.endswith("\n") or not text.startswith(
        "# Strategy brief\n\n"
    ):
        raise workflow.WorkflowError("The performance package Markdown is malformed.")
    if (
        _brief_field(text, "Package ID") != package_id
        or _brief_field(text, "Strategic goal") != goal
        or _brief_field(text, "Topic") != topic_slug
    ):
        raise workflow.WorkflowError(
            "The performance package brief does not match its manifest."
        )
    route = _brief_field(text, "Narrative route").split(" -> ")
    if (
        not 2 <= len(route) <= MAX_LEARNING_ROUTE_STAGES
        or len(route) != len(set(route))
        or any(
            len(stage) > MAX_LEARNING_ROUTE_STAGE_CHARS
            or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", stage) is None
            for stage in route
        )
    ):
        raise workflow.WorkflowError(
            "The performance package narrative route is invalid or unsafe."
        )
    if (
        not isinstance(goal, str)
        or goal not in workflow.GOAL_ROUTES
        or route != list(workflow.GOAL_ROUTES[goal]["narrative_route"])
    ):
        raise workflow.WorkflowError(
            "The performance package narrative route does not match its goal."
        )
    return route


def _learning_context_fingerprint(documents: Mapping[str, str]) -> str:
    """Hash the exact brief/candidate snapshot held by the secure package read."""

    try:
        snapshot = {
            "brief.md": documents["brief.md"],
            "candidates.md": documents["candidates.md"],
        }
    except KeyError as exc:
        raise workflow.WorkflowError(
            "The performance package learning context is incomplete."
        ) from exc
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _validate_learning_snapshot(
    *,
    manifest: Mapping[str, object],
    evaluation: Mapping[str, object],
    validated: Mapping[str, object],
    documents: Mapping[str, str],
) -> tuple[dict[str, tuple[str, str]], list[str]]:
    """Validate both hashed documents from the same held package snapshot."""

    try:
        brief_text = documents["brief.md"]
        candidate_markdown = documents["candidates.md"]
    except KeyError as exc:
        raise workflow.WorkflowError(
            "The performance package learning context is incomplete."
        ) from exc
    ranking = evaluation["ranking"]
    if not isinstance(ranking, list) or any(
        not isinstance(item, str) for item in ranking
    ):
        raise workflow.WorkflowError("The performance package ranking is invalid.")
    candidates = _parse_candidate_markdown(
        candidate_markdown,
        expected_candidate_ids=ranking,
    )
    route = _parse_planned_route(
        brief_text,
        package_id=validated["package_id"],
        goal=validated["goal"],
        topic_slug=manifest["topic_slug"],
    )
    return candidates, route


def _candidate_paragraphs(candidate_text: str) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for line in candidate_text.splitlines():
        if line.strip():
            current.append(line)
        elif current:
            paragraphs.append("\n".join(current))
            current = []
    if current:
        paragraphs.append("\n".join(current))
    if not paragraphs:
        raise workflow.WorkflowError("The performance package candidate text is invalid.")
    return paragraphs


def _hook_excerpt(first_paragraph: str) -> tuple[str, bool]:
    if len(first_paragraph) <= MAX_LEARNING_HOOK_CHARS:
        return first_paragraph, False
    boundary = MAX_LEARNING_HOOK_CHARS
    while boundary > MAX_LEARNING_HOOK_CHARS // 2 and not first_paragraph[
        boundary - 1
    ].isspace():
        boundary -= 1
    if boundary <= MAX_LEARNING_HOOK_CHARS // 2:
        boundary = MAX_LEARNING_HOOK_CHARS
    excerpt = first_paragraph[:boundary].rstrip()
    if not excerpt:
        raise workflow.WorkflowError("The performance package candidate hook is invalid.")
    return excerpt, True


def load_package_context(
    package_id: object,
    candidate_id: object,
    *,
    output_root: Path | str = workflow.DEFAULT_OUTPUTS,
    _allow_test_output_root: bool = False,
) -> dict[str, object]:
    """Load a committed live package and snapshot one explicit eligible candidate."""

    manifest, evaluation, documents = _load_package_documents(
        package_id,
        output_root=output_root,
        _allow_test_output_root=_allow_test_output_root,
        include_learning_documents=True,
    )
    context = _validate_package_context(
        package_id,
        candidate_id,
        manifest=manifest,
        evaluation=evaluation,
    )
    _validate_learning_snapshot(
        manifest=manifest,
        evaluation=evaluation,
        validated=context,
        documents=documents,
    )
    context["learning_context_fingerprint"] = _learning_context_fingerprint(
        documents
    )
    return context


def load_package_learning_context(
    package_id: object,
    candidate_id: object,
    *,
    expected_fingerprint: object,
    output_root: Path | str = workflow.DEFAULT_OUTPUTS,
    _allow_test_output_root: bool = False,
) -> dict[str, object]:
    """Return only bounded hook and structure context from one validated package read."""

    if not isinstance(expected_fingerprint, str) or re.fullmatch(
        r"[0-9a-f]{64}", expected_fingerprint
    ) is None:
        raise workflow.WorkflowError(
            "The performance package learning context is not provenance-anchored."
        )

    manifest, evaluation, documents = _load_package_documents(
        package_id,
        output_root=output_root,
        _allow_test_output_root=_allow_test_output_root,
        include_learning_documents=True,
    )
    validated = _validate_package_context(
        package_id,
        candidate_id,
        manifest=manifest,
        evaluation=evaluation,
    )
    if not hmac.compare_digest(
        expected_fingerprint, _learning_context_fingerprint(documents)
    ):
        raise workflow.WorkflowError(
            "The performance package learning context no longer matches its provenance anchor."
        )
    candidates, route = _validate_learning_snapshot(
        manifest=manifest,
        evaluation=evaluation,
        validated=validated,
        documents=documents,
    )
    selected_id = str(validated["candidate_id"])
    try:
        angle, candidate_text = candidates[selected_id]
    except KeyError as exc:
        raise workflow.WorkflowError(
            "The performance package candidate does not match its evaluation."
        ) from exc
    paragraphs = _candidate_paragraphs(candidate_text)
    if len(paragraphs) > MAX_LEARNING_PARAGRAPHS:
        raise workflow.WorkflowError(
            "The performance package candidate has too many paragraphs for learning."
        )
    hook_excerpt, hook_truncated = _hook_excerpt(paragraphs[0])
    if hook_excerpt == candidate_text or angle == candidate_text:
        raise workflow.WorkflowError(
            "The performance package cannot expose a privacy-bounded learning context."
        )
    return {
        "package_id": validated["package_id"],
        "candidate_id": selected_id,
        "hook_excerpt": hook_excerpt,
        "hook_excerpt_truncated": hook_truncated,
        "candidate_angle": angle,
        "structure": {
            "planned_route": route,
            "paragraph_count": len(paragraphs),
        },
    }


def parse_metric(value: object, *, field: str) -> int:
    if type(value) is int:
        parsed = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
        significant = value.lstrip("0") or "0"
        if len(significant) > 19:
            raise workflow.WorkflowError(
                f"Performance metric {field} is outside the supported range."
            )
        parsed = int(significant)
    else:
        raise workflow.WorkflowError(
            f"Performance metric {field} must be an unsigned whole number."
        )
    if not 0 <= parsed <= 9_223_372_036_854_775_807:
        raise workflow.WorkflowError(
            f"Performance metric {field} is outside the supported range."
        )
    return parsed


def prepare_record(
    context: Mapping[str, object],
    *,
    published_at: object,
    checkpoint: object,
    channel: object,
    observed_at: object,
    metrics: Mapping[str, object],
    recorded_at: object | None = None,
) -> dict[str, object]:
    if set(context) != set(storage.PUBLISHED_POST_FIELDS) - {"published_at"}:
        raise workflow.WorkflowError("Performance package context is invalid.")
    if set(metrics) != set(storage.PERFORMANCE_METRICS):
        raise workflow.WorkflowError("Performance metrics have an invalid schema.")
    record = {
        **dict(context),
        "published_at": published_at,
        "checkpoint": checkpoint,
        "channel": channel,
        "observed_at": observed_at,
        **{
            metric: parse_metric(metrics[metric], field=metric)
            for metric in storage.PERFORMANCE_METRICS
        },
        "recorded_at": workflow.now_iso() if recorded_at is None else recorded_at,
    }
    try:
        return storage.validate_performance_record(record)
    except ValueError as exc:
        raise workflow.WorkflowError(str(exc)) from exc


def _private_csv_text(
    path: Path | str,
    *,
    input_root: Path | str = workflow.DEFAULT_PRIVATE_DATA,
    _allow_test_input_root: bool = False,
) -> str:
    root = Path(input_root)
    if not root.is_absolute():
        raise workflow.WorkflowError("Performance CSV root must be absolute.")
    if root != workflow.DEFAULT_PRIVATE_DATA and not _allow_test_input_root:
        raise workflow.WorkflowError(
            "Performance CSV input must remain under the private data directory."
        )
    candidate = Path(path)
    if not candidate.is_absolute():
        candidate = workflow.REPO_ROOT / candidate
    try:
        relative = candidate.relative_to(root)
    except ValueError as exc:
        raise workflow.WorkflowError(
            "Performance CSV input must remain under the private data directory."
        ) from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise workflow.WorkflowError("Performance CSV path is invalid.")
    root_fd = current_fd = -1
    try:
        root_fd = _open_directory(root)
        current_fd = root_fd
        for part in relative.parts[:-1]:
            next_fd = _open_directory(part, directory_fd=current_fd)
            if current_fd != root_fd:
                os.close(current_fd)
            current_fd = next_fd
        return _read_regular_file(
            relative.parts[-1],
            directory_fd=current_fd,
            maximum_bytes=MAX_CSV_BYTES,
        )
    finally:
        if current_fd >= 0 and current_fd != root_fd:
            os.close(current_fd)
        if root_fd >= 0:
            os.close(root_fd)


def load_csv_records(
    path: Path | str,
    *,
    recorded_at: object | None = None,
    output_root: Path | str = workflow.DEFAULT_OUTPUTS,
    input_root: Path | str = workflow.DEFAULT_PRIVATE_DATA,
    _allow_test_roots: bool = False,
) -> list[dict[str, object]]:
    text = _private_csv_text(
        path,
        input_root=input_root,
        _allow_test_input_root=_allow_test_roots,
    )
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if tuple(reader.fieldnames or ()) != CSV_FIELDS:
            raise workflow.WorkflowError("Performance CSV headers do not match the schema.")
        raw_rows = list(reader)
    except csv.Error as exc:
        raise workflow.WorkflowError("Performance CSV could not be parsed safely.") from exc
    if not raw_rows or len(raw_rows) > MAX_CSV_ROWS:
        raise workflow.WorkflowError("Performance CSV must contain 1 to 1000 rows.")
    contexts: dict[tuple[str, str], dict[str, object]] = {}
    prepared: list[dict[str, object]] = []
    batch_recorded_at = workflow.now_iso() if recorded_at is None else recorded_at
    for row in raw_rows:
        if None in row or set(row) != set(CSV_FIELDS):
            raise workflow.WorkflowError("Performance CSV rows do not match the schema.")
        package_id = row["package_id"]
        candidate_id = row["candidate_id"]
        key = (package_id, candidate_id)
        context = contexts.get(key)
        if context is None:
            context = load_package_context(
                package_id,
                candidate_id,
                output_root=output_root,
                _allow_test_output_root=_allow_test_roots,
            )
            contexts[key] = context
        prepared.append(
            prepare_record(
                context,
                published_at=row["published_at"],
                checkpoint=row["checkpoint"],
                channel=row["channel"],
                observed_at=row["observed_at"],
                metrics={metric: row[metric] for metric in storage.PERFORMANCE_METRICS},
                recorded_at=batch_recorded_at,
            )
        )
    keys = [
        (record["package_id"], record["checkpoint"], record["channel"])
        for record in prepared
    ]
    if len(keys) != len(set(keys)):
        raise workflow.WorkflowError(
            "Performance CSV contains a duplicate observation key."
        )
    return prepared
