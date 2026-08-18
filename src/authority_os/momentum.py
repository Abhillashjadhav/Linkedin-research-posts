"""Free public-web conversation-momentum ranking for daily discovery."""

from __future__ import annotations

import json
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from . import workflow
from .model_runtime import ModelConfig, invoke_structured

MOMENTUM_AXES = (
    "conversation_breadth",
    "engagement_strength",
    "acceleration",
    "cross_platform_confirmation",
    "freshness",
)
MOMENTUM_LABEL = "observed cross-platform conversation momentum"
MOMENTUM_CANDIDATES = 10
MOMENTUM_TOP_K = 5
MIN_AUTHORITY_MOMENTUM = 14
MIN_REACH_MOMENTUM = 20
AUTHORITY_TOPIC_AXES = (
    "audience_fit",
    "judgment_fit",
    "proof_fit",
    "decision_surface",
    "simplicity",
)

DISCOVERY_MODEL = "gpt-5.6-sol"
MOMENTUM_MODEL = ModelConfig("codex", DISCOVERY_MODEL, "high")
AUTHORITY_TOPIC_MODEL = ModelConfig("codex", DISCOVERY_MODEL, "high")


def _role(name: str) -> str:
    path = workflow.REPO_ROOT / ".claude" / "agents" / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise workflow.WorkflowError(f"{name.title()} prompt is unavailable.") from exc
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) != 3:
            raise workflow.WorkflowError(f"{name.title()} prompt is malformed.")
        text = parts[2]
    if not text.strip():
        raise workflow.WorkflowError(f"{name.title()} prompt is blank.")
    return text.strip()


def _axis_observation_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["OBSERVED", "UNKNOWN"]},
            "score": {
                "anyOf": [
                    {"type": "integer", "minimum": 0, "maximum": 5},
                    {"type": "null"},
                ]
            },
            "evidence": {"type": "string"},
        },
        "required": ["status", "score", "evidence"],
        "additionalProperties": False,
    }


def momentum_schema() -> dict[str, object]:
    candidate = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "topic": {"type": "string"},
            "why_now": {"type": "string"},
            "platforms": {
                "type": "array", "minItems": 1, "maxItems": 8,
                "items": {"type": "string"},
            },
            "representative_urls": {
                "type": "array", "minItems": 1, "maxItems": 6,
                "items": {"type": "string"},
            },
            "caveats": {"type": "string"},
            **{axis: _axis_observation_schema() for axis in MOMENTUM_AXES},
        },
        "required": [
            "id", "topic", "why_now", "platforms", "representative_urls", "caveats",
            *MOMENTUM_AXES,
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "candidates": {
                "type": "array",
                "minItems": MOMENTUM_CANDIDATES,
                "maxItems": MOMENTUM_CANDIDATES,
                "items": candidate,
            }
        },
        "required": ["candidates"],
        "additionalProperties": False,
    }


def authority_topic_schema() -> dict[str, object]:
    score = {
        "type": "object",
        "properties": {
            "topic_id": {"type": "string"},
            **{
                axis: {"type": "integer", "minimum": 1, "maximum": 5}
                for axis in AUTHORITY_TOPIC_AXES
            },
        },
        "required": ["topic_id", *AUTHORITY_TOPIC_AXES],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "scorecards": {
                "type": "array",
                "minItems": MOMENTUM_TOP_K,
                "maxItems": MOMENTUM_TOP_K,
                "items": score,
            }
        },
        "required": ["scorecards"],
        "additionalProperties": False,
    }


def _normal(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _validate_public_url(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise workflow.WorkflowError("Momentum evidence URLs must be non-blank HTTPS URLs.")
    url = value.strip()
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise workflow.WorkflowError("Momentum evidence URLs must be public HTTPS URLs.")
    return url


def _confidence(candidate: Mapping[str, object]) -> str:
    observed = sum(
        1
        for axis in MOMENTUM_AXES
        if isinstance(candidate.get(axis), Mapping)
        and candidate[axis].get("status") == "OBSERVED"  # type: ignore[index]
    )
    platforms = candidate.get("platforms")
    urls = candidate.get("representative_urls")
    platform_count = len(platforms) if isinstance(platforms, list) else 0
    url_count = len(urls) if isinstance(urls, list) else 0
    if observed == 5 and platform_count >= 3 and url_count >= 3:
        return "HIGH"
    if observed >= 4 and platform_count >= 2 and url_count >= 2:
        return "MEDIUM"
    return "LOW"


def validate_candidates(raw: object) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != MOMENTUM_CANDIDATES:
        raise workflow.WorkflowError("Momentum Scout must return exactly ten candidate topics.")
    expected = {f"topic-{index}" for index in range(1, MOMENTUM_CANDIDATES + 1)}
    required = {"id", "topic", "why_now", "platforms", "representative_urls", "caveats", *MOMENTUM_AXES}
    seen_ids: set[str] = set()
    seen_topics: set[str] = set()
    validated: list[dict[str, object]] = []
    for raw_candidate in raw:
        if not isinstance(raw_candidate, Mapping) or set(raw_candidate) != required:
            raise workflow.WorkflowError("Momentum candidate has an invalid schema.")
        candidate = dict(raw_candidate)
        candidate_id = candidate["id"]
        if not isinstance(candidate_id, str) or candidate_id not in expected or candidate_id in seen_ids:
            raise workflow.WorkflowError("Momentum topic IDs must be topic-1 through topic-10 exactly once.")
        seen_ids.add(candidate_id)
        for key in ("topic", "why_now", "caveats"):
            if not isinstance(candidate[key], str) or not str(candidate[key]).strip():
                raise workflow.WorkflowError(f"Momentum field {key} must be non-blank text.")
            candidate[key] = str(candidate[key]).strip()
        topic_key = _normal(candidate["topic"])
        if topic_key in seen_topics:
            raise workflow.WorkflowError("Momentum topics must be materially distinct.")
        seen_topics.add(topic_key)

        platforms = candidate["platforms"]
        if not isinstance(platforms, Sequence) or isinstance(platforms, (str, bytes)) or not platforms:
            raise workflow.WorkflowError("Momentum platforms must be a non-empty list.")
        clean_platforms = [str(value).strip() for value in platforms]
        if any(not value for value in clean_platforms) or len(clean_platforms) != len(set(value.casefold() for value in clean_platforms)):
            raise workflow.WorkflowError("Momentum platforms must be distinct non-blank values.")
        candidate["platforms"] = clean_platforms

        urls = candidate["representative_urls"]
        if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes)) or not urls:
            raise workflow.WorkflowError("Momentum representative_urls must be a non-empty list.")
        clean_urls = [_validate_public_url(value) for value in urls]
        if len(clean_urls) != len(set(clean_urls)):
            raise workflow.WorkflowError("Momentum representative_urls must be distinct.")
        candidate["representative_urls"] = clean_urls

        scores: dict[str, int] = {}
        all_observed = True
        for axis in MOMENTUM_AXES:
            observation = candidate[axis]
            if not isinstance(observation, Mapping) or set(observation) != {"status", "score", "evidence"}:
                raise workflow.WorkflowError("Momentum axis observation has an invalid schema.")
            status = observation["status"]
            score = observation["score"]
            evidence = observation["evidence"]
            if status not in {"OBSERVED", "UNKNOWN"} or not isinstance(evidence, str) or not evidence.strip():
                raise workflow.WorkflowError("Momentum observations need status and evidence.")
            if status == "OBSERVED":
                if type(score) is not int or not 0 <= score <= 5:
                    raise workflow.WorkflowError("Observed momentum scores must be integers from 0 to 5.")
                scores[axis] = int(score)
            else:
                if score is not None:
                    raise workflow.WorkflowError("Unknown momentum evidence must use score=null, never zero.")
                all_observed = False
            candidate[axis] = {"status": status, "score": score, "evidence": evidence.strip()}
        candidate["scores"] = scores
        candidate["total"] = sum(scores.values()) if all_observed else None
        candidate["confidence"] = _confidence(candidate)
        validated.append(candidate)
    if seen_ids != expected:
        raise workflow.WorkflowError("Momentum topic IDs are incomplete.")
    return validated


def rank_candidates(
    candidates: Sequence[Mapping[str, object]],
    *,
    minimum: int = MIN_AUTHORITY_MOMENTUM,
) -> list[dict[str, object]]:
    ranked: list[dict[str, object]] = []
    for candidate in candidates:
        item = dict(candidate)
        total = item.get("total")
        item["momentum_eligible"] = type(total) is int and int(total) >= minimum
        ranked.append(item)
    confidence_rank = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}
    ranked.sort(
        key=lambda item: (
            -(int(item["total"]) if type(item.get("total")) is int else -1),
            -confidence_rank.get(str(item.get("confidence")), 0),
            str(item["topic"]).casefold(),
        )
    )
    for index, item in enumerate(ranked, start=1):
        item["momentum_rank"] = index
        item["momentum_threshold"] = minimum
    return ranked


def invoke_scout(topic: str | None, days: int, as_of: str) -> list[dict[str, object]]:
    prompt = f"""Find exactly ten materially distinct GenAI/product conversation topics with observable public momentum during the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, agents, evaluations, reliability, context engineering, enterprise AI, developer tooling, model economics and AI product management'}.
Use only free public-web evidence available through search/fetch. Inspect multiple independent surfaces where observable: Google Trends public pages, Hacker News, Reddit, YouTube, publicly indexed X/Twitter or LinkedIn pages/search snippets, primary-source launches/research, and reputable reporting. Do not use authenticated sessions, paid APIs, private data, engagement APIs, credentials, or local files.

For every topic score these five axes from 0-5 ONLY when public evidence is actually observable:
- conversation_breadth: independent authors/sources discussing the same topic;
- engagement_strength: visible comments/upvotes/views/likes/reposts or comparable public interaction;
- acceleration: evidence that discussion increased in the recent 24-72h versus an earlier part of the window;
- cross_platform_confirmation: the same conversation appears on independent public surfaces;
- freshness: substantive conversation is active now, not merely historically relevant.

Each axis must return status OBSERVED with an integer score and concrete evidence, or status UNKNOWN with score null and an explanation. Missing engagement or trend data is UNKNOWN, never zero. Never infer exact X/Twitter volume, ranking, or '#1 hottest' status from web search. Provide representative public HTTPS URLs and the observed platforms. Use topic-1 through topic-10 exactly once. Return evidence and scores only; do not write a post or use the private authority profile."""
    result = invoke_structured(
        config=MOMENTUM_MODEL,
        role_prompt=_role("scout"),
        task_prompt=prompt,
        schema=momentum_schema(),
        timeout=420,
        web_search=True,
        stage_label="Momentum Scout",
    )
    return validate_candidates(result.get("candidates"))


def validate_authority_scores(
    raw: object,
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != len(candidates):
        raise workflow.WorkflowError("Authority topic critic must score every momentum candidate.")
    expected = [str(candidate["id"]) for candidate in candidates]
    required = {"topic_id", *AUTHORITY_TOPIC_AXES}
    by_id: dict[str, dict[str, object]] = {}
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != required:
            raise workflow.WorkflowError("Authority topic scorecard has an invalid schema.")
        topic_id = item["topic_id"]
        if not isinstance(topic_id, str) or topic_id not in expected or topic_id in by_id:
            raise workflow.WorkflowError("Authority topic scorecard has an invalid ID.")
        score: dict[str, object] = {"topic_id": topic_id}
        for axis in AUTHORITY_TOPIC_AXES:
            if type(item[axis]) is not int or not 1 <= int(item[axis]) <= 5:
                raise workflow.WorkflowError("Authority topic scores must be integers from 1 to 5.")
            score[axis] = int(item[axis])
        score["total"] = sum(int(score[axis]) for axis in AUTHORITY_TOPIC_AXES)
        by_id[topic_id] = score
    if set(by_id) != set(expected):
        raise workflow.WorkflowError("Authority topic critic omitted a candidate.")
    return [by_id[topic_id] for topic_id in expected]


def score_authority_fit(
    candidates: Sequence[Mapping[str, object]],
    profile: Mapping[str, object],
) -> list[dict[str, object]]:
    prompt = f"""Score each momentum-ranked topic from 1 to 5 on exactly {', '.join(AUTHORITY_TOPIC_AXES)}. Keep this separate from conversation momentum; do not change momentum order or infer popularity. Audience fit means relevance to the target audience. Judgment fit means the topic permits a differentiated operator judgment rather than news summary. Proof fit means the supplied public-safe proof inventory can support a natural implementation connection without inventing adoption. Decision surface means the topic exposes a concrete product choice/trade-off. Simplicity means the core idea can be explained to a non-engineer. Return scores only; do not browse, rewrite, select, or draft.
UNTRUSTED_PROFILE
{json.dumps(dict(profile), indent=2, sort_keys=True)}
END_UNTRUSTED_PROFILE
UNTRUSTED_MOMENTUM_TOPICS
{json.dumps(list(candidates), indent=2, sort_keys=True)}
END_UNTRUSTED_MOMENTUM_TOPICS"""
    result = invoke_structured(
        config=AUTHORITY_TOPIC_MODEL,
        role_prompt="You are a strict authority-fit critic. Popularity and authority fit are separate. Score only.",
        task_prompt=prompt,
        schema=authority_topic_schema(),
        timeout=420,
        web_search=False,
        stage_label="Authority topic critic",
    )
    return validate_authority_scores(result.get("scorecards"), candidates)


def attach_authority_fit(
    candidates: Sequence[Mapping[str, object]],
    scores: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_id = {str(score["topic_id"]): score for score in scores}
    result: list[dict[str, object]] = []
    for candidate in candidates:
        item = dict(candidate)
        score = by_id.get(str(item["id"]))
        if score is None:
            raise workflow.WorkflowError("Authority fit is missing for a momentum candidate.")
        item["authority_fit"] = {
            "scores": {axis: int(score[axis]) for axis in AUTHORITY_TOPIC_AXES},
            "total": int(score["total"]),
        }
        result.append(item)
    return result


def print_top(candidates: Sequence[Mapping[str, object]]) -> None:
    print(f"Top {MOMENTUM_TOP_K} topics by {MOMENTUM_LABEL} (not an exact X/Twitter ranking):")
    for item in candidates[:MOMENTUM_TOP_K]:
        total = item.get("total")
        total_text = f"{total}/25" if type(total) is int else "UNKNOWN"
        authority = item.get("authority_fit")
        authority_total = authority.get("total") if isinstance(authority, Mapping) else None
        authority_text = f"{authority_total}/25" if type(authority_total) is int else "n/a"
        eligible = "eligible" if item.get("momentum_eligible") is True else "below/unknown"
        print(
            f"#{item['momentum_rank']} {item['topic']} — momentum={total_text}; "
            f"authority_fit={authority_text}; confidence={item['confidence']}; {eligible}."
        )
        print(f"Why now: {item['why_now']}")
        print(f"Platforms: {', '.join(str(value) for value in item['platforms'])}")
        print(f"Caveat: {item['caveats']}")
