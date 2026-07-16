"""Build private, local packages for explicit human content review."""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import workflow

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised by import-isolation tests.
    fcntl = None  # type: ignore[assignment]


PACKAGE_SCHEMA_VERSION = 1
PACKAGE_FILES = {
    "manifest": "manifest.json",
    "brief": "brief.md",
    "candidates": "candidates.md",
    "evaluation": "evaluation.json",
    "sources": "sources.md",
    "final_package": "final-package.md",
}
PACKAGE_MODES = {"live", "fixture"}
REVIEW_STATUSES = {
    "READY_FOR_HUMAN_REVIEW",
    "BLOCKED",
    "FIXTURE_REVIEW_ONLY",
}
MAX_PACKAGE_BYTES = 1024 * 1024
MAX_PACKAGE_COLLISIONS = 10_000

_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_FILE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _utc_timestamp(value: datetime | None) -> tuple[datetime, str]:
    moment = datetime.now(timezone.utc) if value is None else value
    if not isinstance(moment, datetime) or moment.tzinfo is None:
        raise workflow.WorkflowError(
            "Approval package created_at must be a timezone-aware datetime."
        )
    try:
        offset = moment.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise workflow.WorkflowError(
            "Approval package created_at must be a valid UTC timestamp."
        ) from exc
    if offset is None:
        raise workflow.WorkflowError(
            "Approval package created_at must be a timezone-aware datetime."
        )
    utc = moment.astimezone(timezone.utc).replace(microsecond=0)
    return utc, utc.isoformat().replace("+00:00", "Z")


def _safe_text(value: object, *, label: str, limit: int = 10_000) -> str:
    if not isinstance(value, str) or not value.strip():
        raise workflow.WorkflowError(f"Approval package {label} must be non-blank text.")
    cleaned = value.strip()
    if len(cleaned) > limit or any(
        (
            unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
            and character not in "\n\t"
        )
        for character in cleaned
    ):
        raise workflow.WorkflowError(f"Approval package {label} is unsafe or too long.")
    return cleaned


def _markdown_literal(value: str) -> str:
    """Render untrusted prose as an indented Markdown literal block."""

    return "\n".join(f"    {line}" for line in value.splitlines())


def _project_brief(
    brief: Mapping[str, object], *, mode: str
) -> dict[str, object]:
    if not isinstance(brief, Mapping):
        raise workflow.WorkflowError("Approval package brief must be an object.")
    safe = workflow._writer_brief_projection(brief)
    topic_slug = str(safe["topic_slug"])
    if (
        workflow.slugify(topic_slug) != topic_slug
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,58}[a-z0-9])?", topic_slug)
    ):
        raise workflow.WorkflowError(
            "Approval package topic slug must be one safe canonical segment."
        )
    goal = safe.get("goal")
    if goal not in workflow.STRATEGIC_GOALS:
        raise workflow.WorkflowError("Approval package needs a valid strategic goal.")
    expected_route = list(workflow.GOAL_ROUTES[str(goal)]["narrative_route"])
    if safe.get("narrative_route") != expected_route:
        raise workflow.WorkflowError(
            "Approval package narrative route does not match the strategic goal."
        )
    origin = safe.get("strategy_input_origin")
    expected_origin = "synthetic-fixture" if mode == "fixture" else "explicit-input"
    if origin != expected_origin:
        raise workflow.WorkflowError(
            "Approval package mode does not match the strategy input provenance."
        )
    output_format = brief.get("output_format")
    if output_format is not None and output_format not in workflow.OUTPUT_FORMATS:
        raise workflow.WorkflowError("Approval package output format is invalid.")
    weekly_slot = brief.get("weekly_slot")
    if weekly_slot is not None and (
        isinstance(weekly_slot, bool)
        or not isinstance(weekly_slot, int)
        or not 1 <= weekly_slot <= 5
    ):
        raise workflow.WorkflowError("Approval package weekly slot is invalid.")
    status = brief.get("evidence_status")
    if not isinstance(status, Mapping):
        raise workflow.WorkflowError("Approval package evidence status must be an object.")
    flags: dict[str, bool] = {}
    for name in (
        "source_quality_sufficient",
        "body_read_sufficient",
        "recency_sufficient",
    ):
        value = status.get(name)
        if type(value) is not bool:
            raise workflow.WorkflowError(
                "Approval package evidence status contains an invalid flag."
            )
        flags[name] = value
    stale = status.get("stale")
    if stale is not None and type(stale) is not bool:
        raise workflow.WorkflowError(
            "Approval package stale evidence status must be boolean or null."
        )
    primary_count = status.get("primary_source_count")
    if (
        isinstance(primary_count, bool)
        or not isinstance(primary_count, int)
        or primary_count < 0
    ):
        raise workflow.WorkflowError(
            "Approval package primary-source count must be non-negative."
        )
    raw_limitations = status.get("limitations")
    if not isinstance(raw_limitations, Sequence) or isinstance(
        raw_limitations, (str, bytes)
    ):
        raise workflow.WorkflowError(
            "Approval package evidence limitations must be a list."
        )
    limitations: list[str] = []
    for item in raw_limitations:
        limitation = _safe_text(item, label="evidence limitation", limit=200)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", limitation):
            raise workflow.WorkflowError(
                "Approval package evidence limitation must be a safe reason code."
            )
        limitations.append(limitation)
    analysis = safe["analysis"]
    if not isinstance(analysis, Mapping):
        raise workflow.WorkflowError("Approval package analysis must be an object.")
    return {
        "topic_slug": topic_slug,
        "goal": goal,
        "goal_purpose": _safe_text(
            safe["goal_purpose"], label="goal purpose", limit=1_000
        ),
        "narrative_route": list(safe["narrative_route"]),
        "output_format": output_format,
        "weekly_slot": weekly_slot,
        "target_reader": _safe_text(
            safe["target_reader"], label="target reader"
        ),
        "reader_problem": _safe_text(
            safe["reader_problem"], label="reader problem"
        ),
        "core_hypothesis": _safe_text(
            safe["core_hypothesis"],
            label="core hypothesis",
        ),
        "product_decision": _safe_text(
            safe["product_decision"], label="product decision"
        ),
        "authority_statement": _safe_text(
            safe["authority_statement"], label="authority statement"
        ),
        "strategy_input_origin": origin,
        "analysis": {
            name: _safe_text(analysis[name], label=f"analysis {name}")
            for name in ("why_now", "dominant_take", "missing_angle")
        },
        "evidence_status": {
            **flags,
            "stale": stale,
            "primary_source_count": primary_count,
            "limitations": limitations,
        },
    }


def _validate_review(
    review: Mapping[str, object],
    *,
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    proof: workflow.LoadedProof | None,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[str],
    str,
    int,
    str | None,
]:
    required = {
        "candidates",
        "scorecards",
        "ranking",
        "score_leader_id",
        "revision_count",
        "revision_candidate_id",
    }
    if not isinstance(review, Mapping) or set(review) != required:
        raise workflow.WorkflowError("Approval package review has an invalid schema.")
    raw_candidates = review.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(
        raw_candidates, (str, bytes)
    ):
        raise workflow.WorkflowError("Approval package candidates must be a list.")
    candidates = workflow.validate_draft_candidates(
        raw_candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,
    )
    raw_scorecards = review.get("scorecards")
    if not isinstance(raw_scorecards, Sequence) or isinstance(
        raw_scorecards, (str, bytes)
    ):
        raise workflow.WorkflowError("Approval package scorecards must be a list.")
    scorecards = [dict(scorecard) for scorecard in raw_scorecards]
    ranked = workflow.rank_critic_scorecards(scorecards)
    expected_ranking = [str(scorecard["candidate_id"]) for scorecard in ranked]
    raw_ranking = review.get("ranking")
    if (
        not isinstance(raw_ranking, Sequence)
        or isinstance(raw_ranking, (str, bytes))
        or list(raw_ranking) != expected_ranking
    ):
        raise workflow.WorkflowError(
            "Approval package ranking does not match validated Critic scores."
        )
    leader = review.get("score_leader_id")
    if leader != expected_ranking[0]:
        raise workflow.WorkflowError(
            "Approval package score leader does not match the validated ranking."
        )
    revision_count = review.get("revision_count")
    if (
        isinstance(revision_count, bool)
        or not isinstance(revision_count, int)
        or revision_count not in {0, 1}
    ):
        raise workflow.WorkflowError(
            "Approval package revision count must be zero or one."
        )
    candidate_ids = {str(candidate["id"]) for candidate in candidates}
    if set(expected_ranking) != candidate_ids:
        raise workflow.WorkflowError(
            "Approval package candidates and Critic ranking do not match."
        )
    revision_candidate_id = review.get("revision_candidate_id")
    if (revision_count == 0 and revision_candidate_id is not None) or (
        revision_count == 1 and revision_candidate_id not in candidate_ids
    ):
        raise workflow.WorkflowError(
            "Approval package revision metadata is inconsistent."
        )
    return (
        candidates,
        scorecards,
        expected_ranking,
        str(leader),
        revision_count,
        str(revision_candidate_id) if revision_candidate_id is not None else None,
    )


def _public_sources(
    evidence: Sequence[Mapping[str, object]],
    proof: workflow.LoadedProof | None,
) -> tuple[list[dict[str, object]], dict[str, object] | None]:
    projected = workflow._writer_evidence_projection(evidence)
    sources: list[dict[str, object]] = []
    for item in projected:
        source_id = _safe_text(item["id"], label="source ID", limit=64)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", source_id):
            raise workflow.WorkflowError(
                "Approval package source IDs must be safe machine-readable values."
            )
        sources.append(
            {
                "id": source_id,
                "title": _safe_text(item["title"], label="source title", limit=300),
                "source": _safe_text(item["source"], label="source URL", limit=2_048),
                "source_quality": item["source_quality"],
                "body_read": item["body_read"],
            }
        )
    sources.sort(key=lambda item: str(item["id"]))
    projected_proof = workflow._public_proof_projection(proof)
    if projected_proof is not None:
        projected_proof = {
            "proof_id": projected_proof["proof_id"],
            "proof_type": projected_proof["proof_type"],
            "public_claim": _safe_text(
                projected_proof["public_claim"], label="public proof claim", limit=500
            ),
            "attested_personal_sentences": [
                _safe_text(sentence, label="public proof attestation", limit=500)
                for sentence in projected_proof["attested_personal_sentences"]
            ],
        }
    return sources, projected_proof


def _package_data(
    *,
    package_id: str,
    created_at: str,
    mode: str,
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    review: Mapping[str, object],
    proof: workflow.LoadedProof | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, str]]:
    safe_brief = _project_brief(brief, mode=mode)
    if proof is not None and not isinstance(proof, workflow.LoadedProof):
        raise workflow.WorkflowError(
            "Approval package proof must come from a validated local manifest."
        )
    (
        candidates,
        scorecards,
        ranking,
        score_leader_id,
        revision_count,
        revision_candidate_id,
    ) = (
        _validate_review(review, brief=brief, evidence=evidence, proof=proof)
    )
    candidates = [
        {
            "id": candidate["id"],
            "angle": _safe_text(
                candidate["angle"], label="candidate angle", limit=500
            ),
            "text": _safe_text(
                candidate["text"], label="candidate text", limit=20_000
            ),
            "claim_ids": [
                _safe_text(claim_id, label="candidate claim ID", limit=64)
                for claim_id in candidate["claim_ids"]
            ],
        }
        for candidate in candidates
    ]
    if proof is not None and proof.fixture_mode is not (mode == "fixture"):
        raise workflow.WorkflowError(
            "Approval package mode does not match the proof provenance."
        )
    gate_results = workflow.evaluate_candidate_set_gates(
        candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,
    )
    gates_by_id = {
        str(result["candidate_id"]): result for result in gate_results
    }
    scorecards_by_id = {
        str(scorecard["candidate_id"]): scorecard for scorecard in scorecards
    }
    eligible_ids = [
        candidate_id
        for candidate_id in ranking
        if scorecards_by_id[candidate_id]["band"] == "advance-to-gates"
        and gates_by_id[candidate_id]["passes_required_gates"] is True
    ]
    recommended_id = (
        eligible_ids[0] if eligible_ids and mode == "live" else None
    )
    review_status = (
        "FIXTURE_REVIEW_ONLY"
        if mode == "fixture"
        else "READY_FOR_HUMAN_REVIEW"
        if recommended_id is not None
        else "BLOCKED"
    )
    sources, public_proof = _public_sources(evidence, proof)
    manifest: dict[str, object] = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "package_id": package_id,
        "created_at": created_at,
        "mode": mode,
        "topic_slug": safe_brief["topic_slug"],
        "goal": safe_brief["goal"],
        "output_format": safe_brief["output_format"],
        "weekly_slot": safe_brief["weekly_slot"],
        "revision_count": revision_count,
        "review_status": review_status,
        "human_approval_status": "NOT_APPROVED",
        "publishing_status": "DISABLED",
        "eligible_candidate_ids": eligible_ids,
        "recommended_candidate_id": recommended_id,
        "manual_fact_verification_required": True,
        "files": dict(PACKAGE_FILES),
    }
    evaluation: dict[str, object] = {
        "schema_version": PACKAGE_SCHEMA_VERSION,
        "scorecards": scorecards,
        "ranking": ranking,
        "score_leader_id": score_leader_id,
        "revision_count": revision_count,
        "revision_candidate_id": revision_candidate_id,
        "gate_results": gate_results,
        "eligible_candidate_ids": eligible_ids,
        "recommended_candidate_id": recommended_id,
        "review_status": review_status,
        "manual_fact_verification_required": True,
    }
    rendered = _render_files(
        manifest=manifest,
        brief=safe_brief,
        candidates=candidates,
        evaluation=evaluation,
        sources=sources,
        public_proof=public_proof,
    )
    return manifest, evaluation, rendered


def _render_files(
    *,
    manifest: Mapping[str, object],
    brief: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
    evaluation: Mapping[str, object],
    sources: Sequence[Mapping[str, object]],
    public_proof: Mapping[str, object] | None,
) -> dict[str, str]:
    limitations = brief["evidence_status"]["limitations"]  # type: ignore[index]
    limitations_text = ", ".join(str(item) for item in limitations) or "none"
    brief_markdown = f"""# Strategy brief

- Package ID: `{manifest['package_id']}`
- Topic: `{brief['topic_slug']}`
- Strategic goal: `{brief['goal']}`
- Output format: `{brief['output_format'] or 'not-selected'}`
- Weekly slot: `{brief['weekly_slot'] or 'not-selected'}`
- Narrative route: `{' -> '.join(str(item) for item in brief['narrative_route'])}`
- Strategy provenance: `{brief['strategy_input_origin']}`
- Evidence limitations: `{limitations_text}`

## Goal purpose

{_markdown_literal(str(brief['goal_purpose']))}

## Target reader

{_markdown_literal(str(brief['target_reader']))}

## Reader problem

{_markdown_literal(str(brief['reader_problem']))}

## Core hypothesis

{_markdown_literal(str(brief['core_hypothesis']))}

## Product decision

{_markdown_literal(str(brief['product_decision']))}

## Authority statement

{_markdown_literal(str(brief['authority_statement']))}

## Why now

{_markdown_literal(str(brief['analysis']['why_now']))}

## Dominant take

{_markdown_literal(str(brief['analysis']['dominant_take']))}

## Missing angle

{_markdown_literal(str(brief['analysis']['missing_angle']))}
"""
    candidate_sections: list[str] = ["# Final candidate set\n"]
    for index, candidate in enumerate(candidates, start=1):
        claim_ids = ", ".join(str(item) for item in candidate["claim_ids"])
        candidate_sections.append(
            f"""## Candidate {index}: `{candidate['id']}`

Angle:

{_markdown_literal(str(candidate['angle']))}

Claim IDs: `{claim_ids}`

Text:

{_markdown_literal(str(candidate['text']))}
"""
        )
    candidates_markdown = "\n".join(candidate_sections)

    source_sections: list[str] = [
        "# Public source index\n",
        "Raw source bodies and evidence claims are intentionally excluded.\n",
    ]
    for source in sources:
        source_sections.append(
            f"""## `{source['id']}`

Title:

{_markdown_literal(str(source['title']))}

- URL:

{_markdown_literal(str(source['source']))}
- Quality: `{source['source_quality']}`
- Full body read: `{'yes' if source['body_read'] else 'no'}`
"""
        )
    if public_proof is not None:
        attestations = public_proof["attested_personal_sentences"]
        attestation_text = (
            "\n".join(
                _markdown_literal(str(sentence)) for sentence in attestations
            )
            if attestations
            else "    none"
        )
        source_sections.append(
            f"""## Public-safe proof: `{public_proof['proof_id']}`

- Type: `{public_proof['proof_type']}`

Public claim:

{_markdown_literal(str(public_proof['public_claim']))}

Attested public sentences:

{attestation_text}
"""
        )
    sources_markdown = "\n".join(source_sections)

    recommended_id = manifest["recommended_candidate_id"]
    if recommended_id is not None:
        recommended = next(
            candidate for candidate in candidates if candidate["id"] == recommended_id
        )
        recommendation = f"""## Recommended candidate for human review

Candidate: `{recommended_id}`

{_markdown_literal(str(recommended['text']))}
"""
    elif manifest["mode"] == "fixture":
        recommendation = """## Recommendation

No actionable recommendation is made from synthetic fixture data. Eligible IDs in the
evaluation exist only to exercise the deterministic package contract.
"""
    else:
        recommendation = """## Recommendation

No candidate met both the Critic advancement bar and every required local gate. This
package is blocked and needs a new drafting run rather than approval.
"""
    source_index = "\n\n".join(
        f"- `{source['id']}`\n\n{_markdown_literal(str(source['source']))}"
        for source in sources
    )
    final_markdown = f"""# Human-review content package

- Review status: `{manifest['review_status']}`
- Human approval status: `NOT_APPROVED`
- Manual fact verification required: `yes`
- Scheduling status: `NOT_SCHEDULED`
- Automatic LinkedIn publishing: `DISABLED`

{recommendation}

## Sources used

{source_index}

## Human action required

- Verify every factual statement against the public sources and any supplied public proof.
- Confirm the candidate still matches the intended reader, voice, context, and format.
- Record an explicit human decision outside this runtime.
- If approved, publish manually through a separate human-controlled process.

This package records no approval, creates no schedule, and takes no LinkedIn action.
"""
    rendered = {
        "brief.md": brief_markdown.rstrip() + "\n",
        "candidates.md": candidates_markdown.rstrip() + "\n",
        "evaluation.json": json.dumps(
            evaluation, indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n",
        "sources.md": sources_markdown.rstrip() + "\n",
        "final-package.md": final_markdown.rstrip() + "\n",
        "manifest.json": json.dumps(
            manifest, indent=2, sort_keys=True, ensure_ascii=False
        )
        + "\n",
    }
    if set(rendered) != set(PACKAGE_FILES.values()):
        raise workflow.WorkflowError("Approval package file inventory is invalid.")
    total_bytes = sum(len(content.encode("utf-8")) for content in rendered.values())
    if total_bytes > MAX_PACKAGE_BYTES:
        raise workflow.WorkflowError("Approval package exceeds the local size limit.")
    return rendered


def _verify_owned_directory(
    file_descriptor: int, *, label: str, force_private: bool
) -> None:
    metadata = os.fstat(file_descriptor)
    if not stat.S_ISDIR(metadata.st_mode) or (
        hasattr(os, "geteuid") and metadata.st_uid != os.geteuid()
    ):
        raise workflow.WorkflowError(f"Approval package {label} is unsafe.")
    if force_private:
        os.fchmod(file_descriptor, 0o700)
    elif stat.S_IMODE(metadata.st_mode) & 0o077:
        raise workflow.WorkflowError(
            f"Approval package {label} must already be private."
        )


def _open_directory(
    name: str | os.PathLike[str],
    *,
    directory_fd: int | None,
    label: str,
    force_private: bool = True,
) -> int:
    try:
        descriptor = os.open(name, _DIRECTORY_FLAGS, dir_fd=directory_fd)
    except OSError as exc:
        raise workflow.WorkflowError(f"Approval package {label} is unavailable or unsafe.") from exc
    try:
        _verify_owned_directory(
            descriptor, label=label, force_private=force_private
        )
    except Exception:
        os.close(descriptor)
        raise
    return descriptor


def _create_stage(date_fd: int) -> tuple[str, int]:
    for _attempt in range(20):
        name = f".stage-{secrets.token_hex(16)}"
        try:
            os.mkdir(name, 0o700, dir_fd=date_fd)
        except FileExistsError:
            continue
        except OSError as exc:
            raise workflow.WorkflowError(
                "Approval package private staging directory could not be created."
            ) from exc
        descriptor = _open_directory(
            name, directory_fd=date_fd, label="staging directory"
        )
        return name, descriptor
    raise workflow.WorkflowError(
        "Approval package private staging name could not be reserved."
    )


def _write_all(file_descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(file_descriptor, remaining)
        if written <= 0:
            raise OSError("short package write")
        remaining = remaining[written:]


def _write_stage_files(stage_fd: int, rendered: Mapping[str, str]) -> None:
    for filename in (
        "brief.md",
        "candidates.md",
        "evaluation.json",
        "sources.md",
        "final-package.md",
        "manifest.json",
    ):
        descriptor = -1
        try:
            descriptor = os.open(
                filename,
                _FILE_FLAGS,
                0o600,
                dir_fd=stage_fd,
            )
            _write_all(descriptor, rendered[filename].encode("utf-8"))
            os.fchmod(descriptor, 0o600)
            os.fsync(descriptor)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
    os.fsync(stage_fd)


def _reserve_package_directory(date_fd: int, topic_slug: str) -> tuple[str, int]:
    for index in range(1, MAX_PACKAGE_COLLISIONS + 1):
        name = topic_slug if index == 1 else f"{topic_slug}-{index}"
        try:
            os.mkdir(name, 0o700, dir_fd=date_fd)
        except FileExistsError:
            continue
        except OSError as exc:
            raise workflow.WorkflowError(
                "Approval package final directory could not be reserved safely."
            ) from exc
        try:
            descriptor = _open_directory(
                name, directory_fd=date_fd, label="reserved final directory"
            )
        except Exception:
            try:
                os.rmdir(name, dir_fd=date_fd)
            except OSError:
                pass
            raise
        return name, descriptor
    raise workflow.WorkflowError("Approval package collision limit was reached.")


def _unlink_known_files(directory_fd: int) -> None:
    for filename in PACKAGE_FILES.values():
        try:
            os.unlink(filename, dir_fd=directory_fd)
        except FileNotFoundError:
            pass


def _publish_stage_file(
    filename: str, *, stage_fd: int, final_fd: int
) -> None:
    metadata = os.stat(filename, dir_fd=stage_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
    ):
        raise workflow.WorkflowError(
            "Approval package staging file became unsafe before publication."
        )
    os.link(
        filename,
        filename,
        src_dir_fd=stage_fd,
        dst_dir_fd=final_fd,
        follow_symlinks=False,
    )


def write_human_approval_package(
    *,
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    review: Mapping[str, object],
    proof: workflow.LoadedProof | None = None,
    mode: str,
    output_root: Path | str = workflow.DEFAULT_OUTPUTS,
    created_at: datetime | None = None,
    _allow_test_output_root: bool = False,
) -> dict[str, object]:
    """Validate and publish one no-clobber, never-approved local package."""

    if mode not in PACKAGE_MODES:
        raise workflow.WorkflowError("Approval package mode must be live or fixture.")
    if type(_allow_test_output_root) is not bool:
        raise workflow.WorkflowError(
            "Approval package test output scope must be a boolean."
        )
    if not all(
        (
            getattr(os, "O_DIRECTORY", 0),
            getattr(os, "O_NOFOLLOW", 0),
            fcntl is not None,
            hasattr(os, "link"),
            hasattr(os, "fchmod"),
            hasattr(os, "fsync"),
        )
    ):
        raise workflow.WorkflowError(
            "Approval package secure local filesystem operations are unavailable."
        )
    root = Path(output_root)
    if not root.is_absolute():
        raise workflow.WorkflowError("Approval package output root must be absolute.")
    default_root = root == workflow.DEFAULT_OUTPUTS
    if not default_root and not _allow_test_output_root:
        raise workflow.WorkflowError(
            "Approval packages can only be written under the fixed local output root."
        )
    utc, created_at_text = _utc_timestamp(created_at)
    safe_brief = _project_brief(brief, mode=mode)
    date_name = utc.date().isoformat()
    base_package_id = f"{date_name}-{safe_brief['topic_slug']}"
    manifest, evaluation, rendered = _package_data(
        package_id=base_package_id,
        created_at=created_at_text,
        mode=mode,
        brief=brief,
        evidence=evidence,
        review=review,
        proof=proof,
    )
    root_fd = date_fd = stage_fd = final_fd = -1
    stage_name: str | None = None
    final_name: str | None = None
    final_created = False
    committed = False
    try:
        root_fd = _open_directory(
            root,
            directory_fd=None,
            label="output root",
            force_private=default_root,
        )
        try:
            os.mkdir(date_name, 0o700, dir_fd=root_fd)
            os.fsync(root_fd)
        except FileExistsError:
            pass
        except OSError as exc:
            raise workflow.WorkflowError(
                "Approval package date directory could not be created safely."
            ) from exc
        date_fd = _open_directory(
            date_name, directory_fd=root_fd, label="date directory"
        )
        if fcntl is None:  # Defensive narrowing for type checkers and monkeypatch tests.
            raise workflow.WorkflowError(
                "Approval package secure local filesystem operations are unavailable."
            )
        fcntl.flock(date_fd, fcntl.LOCK_EX)
        final_name, final_fd = _reserve_package_directory(
            date_fd, str(safe_brief["topic_slug"])
        )
        final_created = True
        package_id = f"{date_name}-{final_name}"
        if package_id != base_package_id:
            manifest, evaluation, rendered = _package_data(
                package_id=package_id,
                created_at=created_at_text,
                mode=mode,
                brief=brief,
                evidence=evidence,
                review=review,
                proof=proof,
            )
        stage_name, stage_fd = _create_stage(date_fd)
        _write_stage_files(stage_fd, rendered)
        for filename in (
            "brief.md",
            "candidates.md",
            "evaluation.json",
            "sources.md",
            "final-package.md",
        ):
            _publish_stage_file(filename, stage_fd=stage_fd, final_fd=final_fd)
        os.fsync(final_fd)
        _publish_stage_file("manifest.json", stage_fd=stage_fd, final_fd=final_fd)
        committed = True
        os.fsync(final_fd)
        os.fsync(date_fd)
        try:
            _unlink_known_files(stage_fd)
            os.fsync(stage_fd)
        except OSError as exc:
            raise workflow.WorkflowError(
                "Approval package was committed but private staging cleanup was incomplete."
            ) from exc
        os.close(stage_fd)
        stage_fd = -1
        os.rmdir(stage_name, dir_fd=date_fd)
        stage_name = None
        os.close(final_fd)
        final_fd = -1
    except workflow.WorkflowError:
        raise
    except OSError as exc:
        if committed:
            raise workflow.WorkflowError(
                "Approval package was committed but durability could not be confirmed."
            ) from exc
        raise workflow.WorkflowError(
            "Approval package write failed safely before completion."
        ) from exc
    finally:
        cleanup_failed = False
        if not committed and final_fd >= 0:
            try:
                _unlink_known_files(final_fd)
            except OSError:
                cleanup_failed = True
        if stage_fd >= 0:
            try:
                _unlink_known_files(stage_fd)
            except OSError:
                cleanup_failed = True
        for descriptor in (final_fd, stage_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    cleanup_failed = True
        if stage_name is not None and date_fd >= 0:
            try:
                os.rmdir(stage_name, dir_fd=date_fd)
            except OSError:
                cleanup_failed = True
        if (
            not committed
            and final_created
            and final_name is not None
            and date_fd >= 0
        ):
            try:
                os.rmdir(final_name, dir_fd=date_fd)
            except OSError:
                cleanup_failed = True
        for descriptor in (date_fd, root_fd):
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    cleanup_failed = True
        if cleanup_failed and not committed:
            raise workflow.WorkflowError(
                "Approval package failed and private staging cleanup was incomplete."
            )
    if final_name is None:
        raise workflow.WorkflowError("Approval package did not complete.")
    return {
        "path": root / date_name / final_name,
        "manifest": manifest,
        "evaluation": evaluation,
    }
