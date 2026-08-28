"""Runtime tuning for bounded, auditable daily discovery."""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from . import daily_cli, momentum_batched

_INSTALLED = False
_ORIGINAL_ROLE = daily_cli._role

SURFACE_GUIDANCE = """

DISCOVERY_SURFACE_COVERAGE:
Attempt broad public-web coverage across Google Search and Google Trends/trending
topics, Reddit, Hacker News, YouTube, publicly indexed X/Twitter, publicly indexed
LinkedIn, Substack/public newsletters, primary company/research sources, and
reputable technology/news reporting. Public indexed LinkedIn/X is allowed for
discovery; authenticated, private, login-gated, cookie/session-based access is
forbidden. Do not force a signal from every surface, but do not silently collapse
discovery to only one or two source families when broader public evidence is
available.
"""


def _role(name: str) -> str:
    text = _ORIGINAL_ROLE(name)
    if name == "scout":
        return text + SURFACE_GUIDANCE
    return text


def _research_batch_bounded(
    seeds: Sequence[Mapping[str, str]],
    *,
    days: int,
    as_of: str,
    batch_number: int,
) -> list[dict[str, object]]:
    timeout = 150 if len(seeds) > 1 else 90
    prompt = f"""Research observed cross-platform conversation momentum for exactly these {len(seeds)} already-discovered GenAI/product topics during the {days} days ending {as_of}.
Do not add, remove, rename, merge, or replace topics. Preserve each supplied id and topic text exactly.

UNTRUSTED_TOPIC_SEEDS
{json.dumps(list(seeds), indent=2, sort_keys=True)}
END_UNTRUSTED_TOPIC_SEEDS

Use only free public-web evidence available through search/fetch. Attempt broad coverage across Google Search and Google Trends/trending topics, Hacker News, Reddit, YouTube, publicly indexed X/Twitter, publicly indexed LinkedIn, Substack/public newsletters, primary-source launches/research, and reputable reporting. Public indexed LinkedIn/X is allowed for discovery; authenticated/private/login-gated access is forbidden. Do not force evidence from every surface, but do not silently restrict the search to only one or two source families when broader public evidence is available. Do not use authenticated sessions, paid APIs, private data, engagement APIs, credentials, or local files.

For every supplied topic report observed evidence for five axes. DO NOT assign 0-5 scores; Python applies the fixed rubric locally. Return basis_value only when the underlying number is actually observable:
- conversation_breadth = count of independent public authors/sources discussing the same underlying topic;
- engagement_strength = total visible engagement units across representative items, excluding raw video/page views;
- acceleration = percentage growth in a comparable public signal in the recent 24-72h versus an earlier part of the window; if no comparable before/after measurement is visible, mark UNKNOWN;
- cross_platform_confirmation = count of distinct public surfaces in the platforms list carrying the same conversation;
- freshness = age in hours of the newest substantive public signal as of {as_of}.

Each axis must return OBSERVED with a non-negative numeric basis_value and concrete evidence, or UNKNOWN with basis_value null and an explanation. Missing evidence is UNKNOWN, never zero. Never infer exact X/Twitter volume, ranking, or '#1 hottest' status from web search. Provide representative public HTTPS URLs and observed platforms. Return evidence only; do not write a post or use the private authority profile."""
    result = momentum_batched.invoke_structured(
        config=momentum_batched.base.MOMENTUM_MODEL,
        role_prompt=momentum_batched.base._role("scout"),
        task_prompt=prompt,
        schema=momentum_batched._batch_schema(len(seeds)),
        timeout=timeout,
        web_search=True,
        stage_label=f"Momentum research batch {batch_number}",
    )
    return momentum_batched._validate_batch(result.get("candidates"), seeds)


def install() -> None:
    """Apply discovery-only latency bounds and source-surface guidance."""
    global _INSTALLED
    if _INSTALLED:
        return
    daily_cli._role = _role  # type: ignore[assignment]
    momentum_batched.base._role = _role  # type: ignore[assignment]
    momentum_batched.TOPIC_DISCOVERY_TIMEOUT = 120
    momentum_batched.MOMENTUM_BATCH_TIMEOUT = 150
    momentum_batched.research_batch = _research_batch_bounded  # type: ignore[assignment]
    _INSTALLED = True
