"""Surface-first parallel public-web scouting for daily discovery."""

from __future__ import annotations

import json
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Mapping, Sequence

from . import daily_cli, momentum, workflow
from .model_runtime import ModelConfig, invoke_structured

MAX_WORKERS = 7
SURFACE_TIMEOUT = 90
CONSOLIDATION_TIMEOUT = 60
MIN_SUCCESSFUL_SURFACES = 4
MIN_SIGNALS_FOR_CONSOLIDATION = 10
SIGNALS_PER_SURFACE = 5

MOMENTUM_AXES = momentum.MOMENTUM_AXES
MOMENTUM_LABEL = momentum.MOMENTUM_LABEL
MOMENTUM_CANDIDATES = momentum.MOMENTUM_CANDIDATES
MOMENTUM_TOP_K = momentum.MOMENTUM_TOP_K
MIN_AUTHORITY_MOMENTUM = momentum.MIN_AUTHORITY_MOMENTUM
MIN_REACH_MOMENTUM = momentum.MIN_REACH_MOMENTUM
MIN_OBSERVED_AXES = momentum.MIN_OBSERVED_AXES
AUTHORITY_TOPIC_AXES = momentum.AUTHORITY_TOPIC_AXES

rank_candidates = momentum.rank_candidates
score_authority_fit = momentum.score_authority_fit
attach_authority_fit = momentum.attach_authority_fit
print_top = momentum.print_top

MODEL = ModelConfig("codex", "gpt-5.6-sol", "high")

SURFACES: tuple[dict[str, object], ...] = (
    {
        "key": "google",
        "label": "Google Search + Trends",
        "allowed_platforms": ("Google Search", "Google Trends"),
        "instruction": "Search only public Google Search results and Google Trends/trending-topic pages or reputable pages quoting current Google Trends movement.",
    },
    {
        "key": "reddit",
        "label": "Reddit",
        "allowed_platforms": ("Reddit",),
        "instruction": "Search only public Reddit threads and visible public scores/comments. Do not use authenticated Reddit access.",
    },
    {
        "key": "hacker-news",
        "label": "Hacker News",
        "allowed_platforms": ("Hacker News",),
        "instruction": "Search only Hacker News stories and visible points/comments.",
    },
    {
        "key": "public-social",
        "label": "Public X + LinkedIn",
        "allowed_platforms": ("X/Twitter", "LinkedIn"),
        "instruction": "Search only publicly indexed X/Twitter and LinkedIn pages, snippets, quoted posts, or public trend summaries. Never authenticate or use private/session-gated access.",
    },
    {
        "key": "youtube",
        "label": "YouTube",
        "allowed_platforms": ("YouTube",),
        "instruction": "Search only public YouTube videos and visible public comments/likes. Raw views may be noted for context but must not be counted as engagement_units.",
    },
    {
        "key": "substack",
        "label": "Substack + newsletters",
        "allowed_platforms": ("Substack", "Public newsletter"),
        "instruction": "Search only public Substack posts and other public newsletters. Do not use subscriber-only or login-gated material.",
    },
    {
        "key": "primary-reporting",
        "label": "Primary sources + reporting",
        "allowed_platforms": ("Primary source", "Reputable reporting"),
        "instruction": "Search only primary company/research/standards/government sources and reputable technology/news reporting that show a current GenAI/product conversation or consequence.",
    },
)

_TRACE_DIR: Path | None = None
_TRACE_LOCK = threading.Lock()


def configure_trace_dir(folder: Path) -> None:
    global _TRACE_DIR
    target = daily_cli._under_private(folder)
    daily_cli.legacy_cli._ensure_owner_only_directory(target)
    _TRACE_DIR = target


def _trace_event(event: Mapping[str, object]) -> None:
    if _TRACE_DIR is None:
        return
    data = (json.dumps(dict(event), sort_keys=True) + "\n").encode()
    path = _TRACE_DIR / "surface-trace.jsonl"
    with _TRACE_LOCK:
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            os.write(descriptor, data)
            os.fsync(descriptor)
            os.fchmod(descriptor, 0o600)
        finally:
            os.close(descriptor)


def _write_surface_file(key: str, payload: Mapping[str, object]) -> None:
    if _TRACE_DIR is None:
        return
    daily_cli.write_private_json(_TRACE_DIR / f"surface-{key}.json", payload)


def _surface_schema(allowed_platforms: Sequence[str]) -> dict[str, object]:
    signal = {
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "why_now": {"type": "string"},
            "platform": {"type": "string", "enum": list(allowed_platforms)},
            "url": {"type": "string"},
            "source": {"type": "string"},
            "published_at": {"type": "string"},
            "freshness_hours": {"type": "number", "minimum": 0},
            "engagement_units": {
                "anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]
            },
            "acceleration_percent": {
                "anyOf": [{"type": "number", "minimum": 0}, {"type": "null"}]
            },
        },
        "required": [
            "topic", "why_now", "platform", "url", "source", "published_at",
            "freshness_hours", "engagement_units", "acceleration_percent",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "status": {"type": "string", "enum": ["OBSERVED", "NO_SIGNAL", "UNAVAILABLE"]},
            "signals": {
                "type": "array",
                "minItems": 0,
                "maxItems": SIGNALS_PER_SURFACE,
                "items": signal,
            },
            "caveat": {"type": "string"},
        },
        "required": ["status", "signals", "caveat"],
        "additionalProperties": False,
    }


def _cluster_schema(signal_ids: Sequence[str]) -> dict[str, object]:
    cluster = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "topic": {"type": "string"},
            "why_now": {"type": "string"},
            "signal_ids": {
                "type": "array",
                "minItems": 1,
                "maxItems": 12,
                "items": {"type": "string", "enum": list(signal_ids)},
            },
        },
        "required": ["id", "topic", "why_now", "signal_ids"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "clusters": {
                "type": "array",
                "minItems": MOMENTUM_CANDIDATES,
                "maxItems": MOMENTUM_CANDIDATES,
                "items": cluster,
            }
        },
        "required": ["clusters"],
        "additionalProperties": False,
    }


def _validate_surface_result(
    raw: object,
    *,
    surface: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != {"status", "signals", "caveat"}:
        raise workflow.WorkflowError("Surface Scout returned an invalid result.")
    status = raw["status"]
    caveat = raw["caveat"]
    signals = raw["signals"]
    if status not in {"OBSERVED", "NO_SIGNAL", "UNAVAILABLE"}:
        raise workflow.WorkflowError("Surface Scout returned an invalid status.")
    if not isinstance(caveat, str) or not caveat.strip():
        raise workflow.WorkflowError("Surface Scout caveat must be non-blank.")
    if not isinstance(signals, Sequence) or isinstance(signals, (str, bytes)):
        raise workflow.WorkflowError("Surface Scout signals must be a list.")
    if len(signals) > SIGNALS_PER_SURFACE:
        raise workflow.WorkflowError("Surface Scout returned too many signals.")
    if status == "OBSERVED" and not signals:
        raise workflow.WorkflowError("Observed Surface Scout must return at least one signal.")
    if status != "OBSERVED" and signals:
        raise workflow.WorkflowError("Unavailable/no-signal Surface Scout cannot return signals.")

    allowed = {str(value) for value in surface["allowed_platforms"]}  # type: ignore[index]
    prepared: list[dict[str, object]] = []
    seen_urls: set[str] = set()
    for index, item in enumerate(signals, start=1):
        if not isinstance(item, Mapping):
            raise workflow.WorkflowError("Surface Scout signal must be an object.")
        required = {
            "topic", "why_now", "platform", "url", "source", "published_at",
            "freshness_hours", "engagement_units", "acceleration_percent",
        }
        if set(item) != required:
            raise workflow.WorkflowError("Surface Scout signal has an invalid schema.")
        for field in ("topic", "why_now", "platform", "source", "published_at"):
            if not isinstance(item[field], str) or not str(item[field]).strip():
                raise workflow.WorkflowError("Surface Scout text fields must be non-blank.")
        if str(item["platform"]) not in allowed:
            raise workflow.WorkflowError("Surface Scout returned a platform outside its lane.")
        url = momentum._validate_public_url(item["url"])  # type: ignore[attr-defined]
        if url in seen_urls:
            continue
        seen_urls.add(url)
        freshness = item["freshness_hours"]
        if isinstance(freshness, bool) or not isinstance(freshness, (int, float)) or freshness < 0:
            raise workflow.WorkflowError("Surface Scout freshness must be non-negative.")
        for metric in ("engagement_units", "acceleration_percent"):
            value = item[metric]
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0):
                raise workflow.WorkflowError("Surface Scout numeric observations must be non-negative or null.")
        prepared.append(
            {
                "id": f"{surface['key']}-{index}",
                "surface": str(surface["key"]),
                "surface_label": str(surface["label"]),
                "topic": str(item["topic"]).strip(),
                "why_now": str(item["why_now"]).strip(),
                "platform": str(item["platform"]).strip(),
                "url": url,
                "source": str(item["source"]).strip(),
                "published_at": str(item["published_at"]).strip(),
                "freshness_hours": float(freshness),
                "engagement_units": item["engagement_units"],
                "acceleration_percent": item["acceleration_percent"],
            }
        )
    return {"status": status, "signals": prepared, "caveat": caveat.strip()}


def _run_surface(surface: Mapping[str, object], *, topic: str | None, days: int, as_of: str) -> dict[str, object]:
    key = str(surface["key"])
    label = str(surface["label"])
    print(f"Surface Scout [{label}]: started.", flush=True)
    _trace_event({"event": "surface_started", "surface": key, "label": label, "as_of": as_of})
    prompt = f"""You are one bounded surface scout. Search one surface area only.
Surface lane: {label}
Lane rule: {surface['instruction']}
Research window: the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, agents, evaluations, reliability, context engineering, enterprise AI, developer tooling, model economics and AI product management'}.

Return up to {SIGNALS_PER_SURFACE} of the hottest materially distinct current GenAI/product conversations visible on THIS SURFACE ONLY, ordered strongest first. Prefer repeated current discussion, visible engagement, acceleration, and freshness. Do not browse any other source family to compensate for missing evidence. If this lane is unavailable or has no defensible current signal, return that honestly.

For each signal:
- topic: concise conversation label;
- why_now: concrete current reason;
- platform: exactly one allowed platform for this lane;
- url: representative public HTTPS URL;
- source: public author/community/publisher name;
- published_at: source timestamp when visible;
- freshness_hours: age of the newest substantive signal as of {as_of};
- engagement_units: visible public interactions excluding raw page/video views, or null if unavailable;
- acceleration_percent: comparable recent growth percentage only if directly observable, otherwise null.

Do not invent engagement, acceleration, timestamps, URLs, or popularity rankings. Return evidence only; do not use the private authority profile and do not write a post."""
    try:
        result = invoke_structured(
            config=MODEL,
            role_prompt=daily_cli._role("scout"),
            task_prompt=prompt,
            schema=_surface_schema(surface["allowed_platforms"]),  # type: ignore[arg-type,index]
            timeout=SURFACE_TIMEOUT,
            web_search=True,
            stage_label=f"Surface Scout {label}",
        )
        validated = _validate_surface_result(result, surface=surface)
    except workflow.WorkflowError as exc:
        validated = {"status": "UNAVAILABLE", "signals": [], "caveat": str(exc)}
    payload = {
        "schema_version": 1,
        "surface": key,
        "label": label,
        "status": validated["status"],
        "signals": validated["signals"],
        "caveat": validated["caveat"],
    }
    _write_surface_file(key, payload)
    _trace_event(
        {
            "event": "surface_finished",
            "surface": key,
            "label": label,
            "status": validated["status"],
            "signal_count": len(validated["signals"]),
        }
    )
    print(
        f"Surface Scout [{label}]: {validated['status']} ({len(validated['signals'])} signal(s)).",
        flush=True,
    )
    for signal in validated["signals"]:
        print(f"  - {signal['topic']} | {signal['url']}", flush=True)
    return payload


def _validate_clusters(raw: object, signals: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != MOMENTUM_CANDIDATES:
        raise workflow.WorkflowError("Surface consolidation must return exactly ten clusters.")
    available = {str(signal["id"]) for signal in signals}
    expected = {f"topic-{index}" for index in range(1, MOMENTUM_CANDIDATES + 1)}
    seen_ids: set[str] = set()
    seen_topics: set[str] = set()
    assigned: set[str] = set()
    clusters: list[dict[str, object]] = []
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != {"id", "topic", "why_now", "signal_ids"}:
            raise workflow.WorkflowError("Surface consolidation cluster has an invalid schema.")
        cluster_id = item["id"]
        if not isinstance(cluster_id, str) or cluster_id not in expected or cluster_id in seen_ids:
            raise workflow.WorkflowError("Surface consolidation IDs must be topic-1 through topic-10 exactly once.")
        seen_ids.add(cluster_id)
        topic = item["topic"]
        why_now = item["why_now"]
        if not isinstance(topic, str) or not topic.strip() or not isinstance(why_now, str) or not why_now.strip():
            raise workflow.WorkflowError("Surface consolidation topic fields must be non-blank.")
        topic_key = momentum._normal(topic)  # type: ignore[attr-defined]
        if topic_key in seen_topics:
            raise workflow.WorkflowError("Surface consolidation topics must be materially distinct.")
        seen_topics.add(topic_key)
        ids = item["signal_ids"]
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)) or not ids:
            raise workflow.WorkflowError("Surface consolidation clusters need signal IDs.")
        clean_ids = [str(value) for value in ids]
        if len(clean_ids) != len(set(clean_ids)) or any(value not in available for value in clean_ids):
            raise workflow.WorkflowError("Surface consolidation referenced invalid signal IDs.")
        if any(value in assigned for value in clean_ids):
            raise workflow.WorkflowError("One surface signal cannot belong to multiple conversation clusters.")
        assigned.update(clean_ids)
        clusters.append({"id": cluster_id, "topic": topic.strip(), "why_now": why_now.strip(), "signal_ids": clean_ids})
    if seen_ids != expected:
        raise workflow.WorkflowError("Surface consolidation topic IDs are incomplete.")
    return clusters


def _consolidate(signals: Sequence[Mapping[str, object]], *, as_of: str) -> list[dict[str, object]]:
    ids = [str(signal["id"]) for signal in signals]
    prompt = f"""Cluster these independently discovered public-web signals into exactly ten materially distinct current GenAI/product conversations.
Do not browse. Do not add facts or signals. Merge only signals that describe the same underlying conversation. Preserve the strongest current conversations and use topic-1 through topic-10 exactly once. Each input signal may be assigned to at most one cluster; unused weak/duplicate signals may be omitted. Rank the ten clusters strongest-first using only the supplied evidence: cross-surface repetition, visible engagement, observable acceleration, and freshness as of {as_of}.

UNTRUSTED_SURFACE_SIGNALS
{json.dumps(list(signals), indent=2, sort_keys=True)}
END_UNTRUSTED_SURFACE_SIGNALS
"""
    result = invoke_structured(
        config=MODEL,
        role_prompt="You consolidate supplied evidence only. Do not browse, invent, or draft.",
        task_prompt=prompt,
        schema=_cluster_schema(ids),
        timeout=CONSOLIDATION_TIMEOUT,
        web_search=False,
        stage_label="Surface Scout consolidation",
    )
    return _validate_clusters(result.get("clusters"), signals)


def _observation(status: str, basis: float | None, evidence: str) -> dict[str, object]:
    return {"status": status, "basis_value": basis, "evidence": evidence}


def _project_candidates(
    clusters: Sequence[Mapping[str, object]],
    signals: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    by_id = {str(signal["id"]): signal for signal in signals}
    raw: list[dict[str, object]] = []
    for cluster in clusters:
        selected = [by_id[str(signal_id)] for signal_id in cluster["signal_ids"]]  # type: ignore[index]
        platforms = list(dict.fromkeys(str(item["platform"]) for item in selected))
        urls = list(dict.fromkeys(str(item["url"]) for item in selected))[:6]
        sources = {str(item["source"]).casefold() for item in selected}
        engagements = [float(item["engagement_units"]) for item in selected if item["engagement_units"] is not None]
        accelerations = [float(item["acceleration_percent"]) for item in selected if item["acceleration_percent"] is not None]
        freshness = min(float(item["freshness_hours"]) for item in selected)
        caveats: list[str] = []
        if len(platforms) < 2:
            caveats.append("Only one public surface contributed to this cluster.")
        if not engagements:
            caveats.append("Visible engagement was unavailable.")
        if not accelerations:
            caveats.append("Comparable acceleration was unavailable.")
        raw.append(
            {
                "id": cluster["id"],
                "topic": cluster["topic"],
                "why_now": cluster["why_now"],
                "platforms": platforms,
                "representative_urls": urls,
                "caveats": " ".join(caveats) or "No material caveat beyond public-web measurement limits.",
                "conversation_breadth": _observation(
                    "OBSERVED",
                    float(len(sources)),
                    f"{len(sources)} independent public source(s) contributed to the cluster.",
                ),
                "engagement_strength": _observation(
                    "OBSERVED" if engagements else "UNKNOWN",
                    sum(engagements) if engagements else None,
                    "Summed visible public interaction units across supplied signals." if engagements else "No comparable visible engagement count was available.",
                ),
                "acceleration": _observation(
                    "OBSERVED" if accelerations else "UNKNOWN",
                    max(accelerations) if accelerations else None,
                    "Strongest directly observed comparable recent growth signal." if accelerations else "No comparable before/after growth measurement was available.",
                ),
                "cross_platform_confirmation": _observation(
                    "OBSERVED",
                    float(len(platforms)),
                    f"Observed on {len(platforms)} distinct public surface(s).",
                ),
                "freshness": _observation(
                    "OBSERVED",
                    freshness,
                    f"Newest supplied substantive signal is {freshness:g} hour(s) old.",
                ),
            }
        )
    return momentum.validate_candidates(raw)


def invoke_scout(topic: str | None, days: int, as_of: str) -> list[dict[str, object]]:
    print(f"Momentum: launching {len(SURFACES)} independent surface scouts in parallel...", flush=True)
    _trace_event({"event": "surface_scouting_started", "surface_count": len(SURFACES), "as_of": as_of})
    completed: dict[str, dict[str, object]] = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS, thread_name_prefix="surface-scout") as executor:
        futures: dict[Future[dict[str, object]], str] = {
            executor.submit(_run_surface, surface, topic=topic, days=days, as_of=as_of): str(surface["key"])
            for surface in SURFACES
        }
        for future in as_completed(futures):
            key = futures[future]
            completed[key] = future.result()

    ordered = [completed[str(surface["key"])] for surface in SURFACES]
    successful = [item for item in ordered if item["status"] == "OBSERVED"]
    signals = [signal for item in successful for signal in item["signals"]]  # type: ignore[index]
    print(
        f"Momentum: surface coverage complete: {len(successful)}/{len(SURFACES)} observed; {len(signals)} signal(s).",
        flush=True,
    )
    _trace_event(
        {
            "event": "surface_scouting_finished",
            "successful_surfaces": len(successful),
            "total_surfaces": len(SURFACES),
            "signal_count": len(signals),
        }
    )
    if len(successful) < MIN_SUCCESSFUL_SURFACES:
        raise workflow.WorkflowError(
            f"Only {len(successful)}/{len(SURFACES)} surface scouts produced evidence; at least {MIN_SUCCESSFUL_SURFACES} are required."
        )
    if len(signals) < MIN_SIGNALS_FOR_CONSOLIDATION:
        raise workflow.WorkflowError(
            f"Only {len(signals)} surface signals were collected; at least {MIN_SIGNALS_FOR_CONSOLIDATION} are required for ten-topic consolidation."
        )

    print("Momentum: consolidating surface signals into 10 conversations...", flush=True)
    clusters = _consolidate(signals, as_of=as_of)
    candidates = _project_candidates(clusters, signals)
    _trace_event({"event": "surface_consolidation_finished", "candidate_count": len(candidates)})
    print("Momentum: 10 conversations consolidated; ranking locally.", flush=True)
    return candidates
