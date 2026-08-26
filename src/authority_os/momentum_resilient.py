"""Adaptive live-web momentum execution with visible progress."""

from __future__ import annotations

from typing import Mapping, Sequence

from . import momentum_batched as base
from . import workflow

BATCH_SIZE = 2

MOMENTUM_AXES = base.MOMENTUM_AXES
MOMENTUM_LABEL = base.MOMENTUM_LABEL
MOMENTUM_CANDIDATES = base.MOMENTUM_CANDIDATES
MOMENTUM_TOP_K = base.MOMENTUM_TOP_K
MIN_AUTHORITY_MOMENTUM = base.MIN_AUTHORITY_MOMENTUM
MIN_REACH_MOMENTUM = base.MIN_REACH_MOMENTUM
MIN_OBSERVED_AXES = base.MIN_OBSERVED_AXES
AUTHORITY_TOPIC_AXES = base.AUTHORITY_TOPIC_AXES

rank_candidates = base.rank_candidates
score_authority_fit = base.score_authority_fit
attach_authority_fit = base.attach_authority_fit
print_top = base.print_top


def _timed_out(exc: workflow.WorkflowError) -> bool:
    return "timed out" in str(exc).casefold()


def _research_adaptive(
    seeds: Sequence[Mapping[str, str]],
    *,
    days: int,
    as_of: str,
    label: str,
) -> list[dict[str, object]]:
    ids = ", ".join(str(seed["id"]) for seed in seeds)
    print(f"Momentum: researching {ids} ({len(seeds)} topic(s))...", flush=True)
    try:
        result = base.research_batch(
            seeds,
            days=days,
            as_of=as_of,
            batch_number=label,  # type: ignore[arg-type]
        )
    except workflow.WorkflowError as exc:
        if not _timed_out(exc):
            raise
        if len(seeds) == 1:
            topic_id = str(seeds[0]["id"])
            print(
                f"Momentum: {topic_id} timed out after adaptive splitting; "
                "leaving it unranked with no fabricated score.",
                flush=True,
            )
            return []
        midpoint = len(seeds) // 2
        print(f"Momentum: batch {label} timed out; splitting {ids}.", flush=True)
        return _research_adaptive(
            seeds[:midpoint],
            days=days,
            as_of=as_of,
            label=f"{label}a",
        ) + _research_adaptive(
            seeds[midpoint:],
            days=days,
            as_of=as_of,
            label=f"{label}b",
        )
    print(f"Momentum: completed {ids}.", flush=True)
    return result


def validate_partial_candidates(
    raw: object,
    *,
    expected_ids: Sequence[str],
) -> list[dict[str, object]]:
    """Validate and locally score only topics that actually completed enrichment."""

    expected = {str(value) for value in expected_ids}
    allowed = {f"topic-{index}" for index in range(1, MOMENTUM_CANDIDATES + 1)}
    if not expected or not expected <= allowed:
        raise workflow.WorkflowError("Partial momentum validation received invalid topic IDs.")
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != len(expected):
        raise workflow.WorkflowError("Partial momentum results do not match completed topic IDs.")

    required = {
        "id",
        "topic",
        "why_now",
        "platforms",
        "representative_urls",
        "caveats",
        *MOMENTUM_AXES,
    }
    seen_ids: set[str] = set()
    seen_topics: set[str] = set()
    validated: list[dict[str, object]] = []

    for raw_candidate in raw:
        if not isinstance(raw_candidate, Mapping) or set(raw_candidate) != required:
            raise workflow.WorkflowError("Momentum candidate has an invalid schema.")
        candidate = dict(raw_candidate)
        candidate_id = candidate["id"]
        if not isinstance(candidate_id, str) or candidate_id not in expected or candidate_id in seen_ids:
            raise workflow.WorkflowError("Partial momentum result contains an unexpected topic ID.")
        seen_ids.add(candidate_id)

        for key in ("topic", "why_now", "caveats"):
            if not isinstance(candidate[key], str) or not str(candidate[key]).strip():
                raise workflow.WorkflowError(f"Momentum field {key} must be non-blank text.")
            candidate[key] = str(candidate[key]).strip()
        topic_key = base.base._normal(candidate["topic"])  # type: ignore[attr-defined]
        if topic_key in seen_topics:
            raise workflow.WorkflowError("Momentum topics must be materially distinct.")
        seen_topics.add(topic_key)

        platforms = candidate["platforms"]
        if not isinstance(platforms, Sequence) or isinstance(platforms, (str, bytes)) or not platforms:
            raise workflow.WorkflowError("Momentum platforms must be a non-empty list.")
        clean_platforms = [str(value).strip() for value in platforms]
        if any(not value for value in clean_platforms) or len(clean_platforms) != len(
            set(value.casefold() for value in clean_platforms)
        ):
            raise workflow.WorkflowError("Momentum platforms must be distinct non-blank values.")
        candidate["platforms"] = clean_platforms

        urls = candidate["representative_urls"]
        if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes)) or not urls:
            raise workflow.WorkflowError("Momentum representative_urls must be a non-empty list.")
        clean_urls = [base.base._validate_public_url(value) for value in urls]  # type: ignore[attr-defined]
        if len(clean_urls) != len(set(clean_urls)):
            raise workflow.WorkflowError("Momentum representative_urls must be distinct.")
        candidate["representative_urls"] = clean_urls

        scores: dict[str, int] = {}
        for axis in MOMENTUM_AXES:
            observation = candidate[axis]
            if not isinstance(observation, Mapping) or set(observation) != {
                "status",
                "basis_value",
                "evidence",
            }:
                raise workflow.WorkflowError("Momentum axis observation has an invalid schema.")
            status = observation["status"]
            basis = observation["basis_value"]
            evidence = observation["evidence"]
            if status not in {"OBSERVED", "UNKNOWN"} or not isinstance(evidence, str) or not evidence.strip():
                raise workflow.WorkflowError("Momentum observations need status and evidence.")
            if status == "OBSERVED":
                if isinstance(basis, bool) or not isinstance(basis, (int, float)) or basis < 0:
                    raise workflow.WorkflowError(
                        "Observed momentum evidence needs a non-negative numeric basis_value."
                    )
                reconciled_basis, reconciliation = base.base._reconcile_observed_basis(  # type: ignore[attr-defined]
                    axis,
                    basis,
                    clean_platforms,
                )
                score = base.base._score_axis(  # type: ignore[attr-defined]
                    axis,
                    float(reconciled_basis),
                )
                scores[axis] = score
                clean_evidence = evidence.strip()
                if reconciliation is not None:
                    clean_evidence = f"{clean_evidence} {reconciliation}"
                candidate[axis] = {
                    "status": "OBSERVED",
                    "basis_value": reconciled_basis,
                    "score": score,
                    "evidence": clean_evidence,
                }
            else:
                if basis is not None:
                    raise workflow.WorkflowError(
                        "Unknown momentum evidence must use basis_value=null, never a fabricated zero."
                    )
                candidate[axis] = {
                    "status": "UNKNOWN",
                    "basis_value": None,
                    "score": None,
                    "evidence": evidence.strip(),
                }

        observed_axes = len(scores)
        observed_total = sum(scores.values())
        candidate["scores"] = scores
        candidate["observed_axes"] = observed_axes
        candidate["observed_total"] = observed_total
        candidate["total"] = observed_total if observed_axes >= MIN_OBSERVED_AXES else None
        candidate["confidence"] = base.base._confidence(candidate)  # type: ignore[attr-defined]
        validated.append(candidate)

    if seen_ids != expected:
        raise workflow.WorkflowError("Partial momentum result omitted a completed topic.")
    validated.sort(key=lambda item: int(str(item["id"]).split("-")[1]))
    return validated


def finalize_enrichment(
    seeds: Sequence[Mapping[str, str]],
    enriched: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    """Keep honest partial coverage when isolated topics time out."""

    seed_ids = [str(seed["id"]) for seed in seeds]
    completed_ids = [str(item.get("id", "")) for item in enriched]
    if len(completed_ids) != len(set(completed_ids)):
        raise workflow.WorkflowError("Momentum enrichment returned duplicate topic IDs.")
    if any(topic_id not in set(seed_ids) for topic_id in completed_ids):
        raise workflow.WorkflowError("Momentum enrichment returned an unknown topic ID.")

    missing = [topic_id for topic_id in seed_ids if topic_id not in set(completed_ids)]
    if len(completed_ids) < MOMENTUM_TOP_K:
        raise workflow.WorkflowError(
            f"Only {len(completed_ids)}/{len(seed_ids)} momentum topics completed enrichment; "
            f"at least {MOMENTUM_TOP_K} completed topics are required for a defensible top-{MOMENTUM_TOP_K} ranking."
        )

    if not missing:
        print("Momentum: all 10 topics enriched; ranking locally.", flush=True)
        return base.base.validate_candidates(list(enriched))

    print(
        f"Momentum: {len(completed_ids)}/{len(seed_ids)} topics enriched; "
        f"{len(missing)} timed out and remain unranked ({', '.join(missing)}).",
        flush=True,
    )
    print(
        "Momentum: ranking uses partial coverage only; no timeout was converted to zero.",
        flush=True,
    )
    return validate_partial_candidates(enriched, expected_ids=completed_ids)


def invoke_scout(
    topic: str | None,
    days: int,
    as_of: str,
) -> list[dict[str, object]]:
    print("Momentum: discovering 10 candidate conversations...", flush=True)
    seeds = base.discover_topics(topic, days, as_of)
    print("Momentum: candidate discovery complete.", flush=True)

    enriched: list[dict[str, object]] = []
    total_batches = (MOMENTUM_CANDIDATES + BATCH_SIZE - 1) // BATCH_SIZE
    for batch_index, offset in enumerate(
        range(0, MOMENTUM_CANDIDATES, BATCH_SIZE),
        start=1,
    ):
        enriched.extend(
            _research_adaptive(
                seeds[offset : offset + BATCH_SIZE],
                days=days,
                as_of=as_of,
                label=f"{batch_index}/{total_batches}",
            )
        )

    return finalize_enrichment(seeds, enriched)
