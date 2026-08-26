"""Bounded live-web execution for conversation-momentum discovery."""

from __future__ import annotations

import json
from typing import Mapping, Sequence

from . import momentum as base
from . import workflow
from .model_runtime import invoke_structured

BATCH_SIZE = 5
TOPIC_DISCOVERY_TIMEOUT = 240
MOMENTUM_BATCH_TIMEOUT = 420

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


def _topic_schema() -> dict[str, object]:
    item = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "topic": {"type": "string"},
            "why_now": {"type": "string"},
        },
        "required": ["id", "topic", "why_now"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "minItems": MOMENTUM_CANDIDATES,
                "maxItems": MOMENTUM_CANDIDATES,
                "items": item,
            }
        },
        "required": ["topics"],
        "additionalProperties": False,
    }


def _batch_schema(size: int) -> dict[str, object]:
    full_schema = base.momentum_schema()
    candidate = full_schema["properties"]["candidates"]["items"]  # type: ignore[index]
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": size,
                "maxItems": size,
                "items": candidate,
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def _validate_topic_seeds(raw: object) -> list[dict[str, str]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != MOMENTUM_CANDIDATES:
        raise workflow.WorkflowError("Momentum topic discovery must return exactly ten topics.")
    expected = {f"topic-{index}" for index in range(1, MOMENTUM_CANDIDATES + 1)}
    seen_ids: set[str] = set()
    seen_topics: set[str] = set()
    result: list[dict[str, str]] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"id", "topic", "why_now"}:
            raise workflow.WorkflowError("Momentum topic seed has an invalid schema.")
        topic_id = item["id"]
        topic = item["topic"]
        why_now = item["why_now"]
        if not isinstance(topic_id, str) or topic_id not in expected or topic_id in seen_ids:
            raise workflow.WorkflowError("Momentum topic IDs must be topic-1 through topic-10 exactly once.")
        if not isinstance(topic, str) or not topic.strip() or not isinstance(why_now, str) or not why_now.strip():
            raise workflow.WorkflowError("Momentum topic seeds need non-blank topic and why_now text.")
        normal = " ".join(topic.casefold().split())
        if normal in seen_topics:
            raise workflow.WorkflowError("Momentum topic seeds must be materially distinct.")
        seen_ids.add(topic_id)
        seen_topics.add(normal)
        result.append({"id": topic_id, "topic": topic.strip(), "why_now": why_now.strip()})
    if seen_ids != expected:
        raise workflow.WorkflowError("Momentum topic IDs are incomplete.")
    result.sort(key=lambda item: int(item["id"].split("-")[1]))
    return result


def _validate_batch(raw: object, seeds: Sequence[Mapping[str, str]]) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != len(seeds):
        raise workflow.WorkflowError("Momentum research batch returned the wrong number of candidates.")
    expected = {str(seed["id"]): str(seed["topic"]) for seed in seeds}
    seen: set[str] = set()
    result: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping):
            raise workflow.WorkflowError("Momentum research batch has an invalid candidate.")
        topic_id = item.get("id")
        topic = item.get("topic")
        if not isinstance(topic_id, str) or topic_id not in expected or topic_id in seen:
            raise workflow.WorkflowError("Momentum batch IDs must match the requested topic IDs exactly once.")
        if not isinstance(topic, str) or " ".join(topic.casefold().split()) != " ".join(expected[topic_id].casefold().split()):
            raise workflow.WorkflowError("Momentum research batch changed a discovered topic.")
        seen.add(topic_id)
        result.append(dict(item))
    if seen != set(expected):
        raise workflow.WorkflowError("Momentum research batch omitted a requested topic.")
    result.sort(key=lambda item: int(str(item["id"]).split("-")[1]))
    return result


def discover_topics(topic: str | None, days: int, as_of: str) -> list[dict[str, str]]:
    prompt = f"""Find exactly ten materially distinct GenAI/product conversations that appear active during the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, agents, evaluations, reliability, context engineering, enterprise AI, developer tooling, model economics and AI product management'}.
Use free public-web search only. This first pass is intentionally shallow: identify the ten candidate conversations and give one concise why_now signal for each. Do not collect the full five-axis momentum scorecard yet. Prefer topics with repeated independent discussion rather than a single viral post. Because the channel teaches practical GenAI, when defensible reserve at least three seeds for recent capabilities launched by named independent builders or small teams that have both a public creator demo video and a runnable public repository or product. Those seeds still need observable repeated discussion and receive no momentum exception. Do not force a launch seed when the demo, runnable artifact, attribution, recency, or public conversation is missing. Do not use authenticated sessions, paid APIs, private data, credentials, or local files. Use topic-1 through topic-10 exactly once. Return topic seeds only; do not write a post or use the private authority profile."""
    result = invoke_structured(
        config=base.MOMENTUM_MODEL,
        role_prompt=base._role("scout"),
        task_prompt=prompt,
        schema=_topic_schema(),
        timeout=TOPIC_DISCOVERY_TIMEOUT,
        web_search=True,
        stage_label="Momentum topic discovery",
    )
    return _validate_topic_seeds(result.get("topics"))


def research_batch(
    seeds: Sequence[Mapping[str, str]],
    *,
    days: int,
    as_of: str,
    batch_number: int,
) -> list[dict[str, object]]:
    prompt = f"""Research observed cross-platform conversation momentum for exactly these {len(seeds)} already-discovered GenAI/product topics during the {days} days ending {as_of}.
Do not add, remove, rename, merge, or replace topics. Preserve each supplied id and topic text exactly.

UNTRUSTED_TOPIC_SEEDS
{json.dumps(list(seeds), indent=2, sort_keys=True)}
END_UNTRUSTED_TOPIC_SEEDS

Use only free public-web evidence available through search/fetch. Inspect multiple independent surfaces where observable: Google Trends public pages, Hacker News, Reddit, YouTube, publicly indexed X/Twitter or LinkedIn pages/search snippets, primary-source launches/research, and reputable reporting. Do not use authenticated sessions, paid APIs, private data, engagement APIs, credentials, or local files.

For every supplied topic report observed evidence for five axes. DO NOT assign 0-5 scores; Python applies the fixed rubric locally. Return basis_value only when the underlying number is actually observable:
- conversation_breadth = count of independent public authors/sources discussing the same underlying topic;
- engagement_strength = total visible engagement units across representative items, excluding raw video/page views;
- acceleration = percentage growth in a comparable public signal in the recent 24-72h versus an earlier part of the window; if no comparable before/after measurement is visible, mark UNKNOWN;
- cross_platform_confirmation = count of distinct public surfaces in the platforms list carrying the same conversation;
- freshness = age in hours of the newest substantive public signal as of {as_of}.

For a capability-launch seed, include the creator-controlled launch source, runnable artifact, and original demo-video page among representative_urls when each is publicly observable. A creator demo is one primary launch source, not independent confirmation; score breadth and cross-platform confirmation only from genuinely independent public discussion.

Each axis must return OBSERVED with a non-negative numeric basis_value and concrete evidence, or UNKNOWN with basis_value null and an explanation. Missing evidence is UNKNOWN, never zero. Never infer exact X/Twitter volume, ranking, or '#1 hottest' status from web search. Provide representative public HTTPS URLs and observed platforms. Return evidence only; do not write a post or use the private authority profile."""
    result = invoke_structured(
        config=base.MOMENTUM_MODEL,
        role_prompt=base._role("scout"),
        task_prompt=prompt,
        schema=_batch_schema(len(seeds)),
        timeout=MOMENTUM_BATCH_TIMEOUT,
        web_search=True,
        stage_label=f"Momentum research batch {batch_number}",
    )
    return _validate_batch(result.get("candidates"), seeds)


def invoke_scout(topic: str | None, days: int, as_of: str) -> list[dict[str, object]]:
    seeds = discover_topics(topic, days, as_of)
    enriched: list[dict[str, object]] = []
    for offset in range(0, MOMENTUM_CANDIDATES, BATCH_SIZE):
        batch = seeds[offset : offset + BATCH_SIZE]
        enriched.extend(
            research_batch(
                batch,
                days=days,
                as_of=as_of,
                batch_number=(offset // BATCH_SIZE) + 1,
            )
        )
    return base.validate_candidates(enriched)
