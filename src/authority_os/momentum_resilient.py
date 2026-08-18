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
            raise workflow.WorkflowError(
                f"Momentum research timed out for {seeds[0]['id']} after adaptive splitting."
            ) from None
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

    print("Momentum: all 10 topics enriched; ranking locally.", flush=True)
    return base.base.validate_candidates(enriched)
