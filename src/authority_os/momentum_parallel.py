"""Parallel adaptive live-web momentum execution with visible progress."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import Mapping, Sequence

from . import momentum_resilient as base

BATCH_SIZE = 2
MAX_WORKERS = 3

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


def invoke_scout(
    topic: str | None,
    days: int,
    as_of: str,
) -> list[dict[str, object]]:
    print("Momentum: discovering 10 candidate conversations...", flush=True)
    seeds = base.base.discover_topics(topic, days, as_of)
    print("Momentum: candidate discovery complete.", flush=True)

    batches: list[tuple[int, Sequence[Mapping[str, str]]]] = []
    for batch_index, offset in enumerate(
        range(0, MOMENTUM_CANDIDATES, BATCH_SIZE),
        start=1,
    ):
        batches.append((batch_index, seeds[offset : offset + BATCH_SIZE]))

    print(
        f"Momentum: enriching {len(batches)} batches with up to {MAX_WORKERS} parallel workers...",
        flush=True,
    )

    completed: dict[int, list[dict[str, object]]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="momentum") as executor:
        futures: dict[Future[list[dict[str, object]]], int] = {
            executor.submit(
                base._research_adaptive,
                batch,
                days=days,
                as_of=as_of,
                label=f"{batch_index}/{len(batches)}",
            ): batch_index
            for batch_index, batch in batches
        }
        try:
            for future in as_completed(futures):
                batch_index = futures[future]
                completed[batch_index] = future.result()
                print(
                    f"Momentum: batch {batch_index}/{len(batches)} finished.",
                    flush=True,
                )
        except Exception:
            for future in futures:
                future.cancel()
            raise

    enriched: list[dict[str, object]] = []
    for batch_index, _batch in batches:
        enriched.extend(completed[batch_index])

    return base.finalize_enrichment(seeds, enriched)
