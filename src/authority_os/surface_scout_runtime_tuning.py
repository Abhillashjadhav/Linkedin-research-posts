"""Runtime tuning for shallow, bounded surface scouts."""

from __future__ import annotations

from typing import Mapping, Sequence

from . import momentum_surface_parallel as surface_runtime
from . import workflow
from .model_runtime import ModelConfig

SURFACE_TIMEOUT = 180
CONSOLIDATION_TIMEOUT = 150
MODEL = ModelConfig("codex", "gpt-5.6-sol", "medium")
_INSTALLED = False


def _shallow_schema(allowed_platforms: Sequence[str]) -> dict[str, object]:
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
        },
        "required": [
            "topic",
            "why_now",
            "platform",
            "url",
            "source",
            "published_at",
            "freshness_hours",
            "engagement_units",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": ["OBSERVED", "NO_SIGNAL", "UNAVAILABLE"],
            },
            "signals": {
                "type": "array",
                "minItems": 0,
                "maxItems": surface_runtime.SIGNALS_PER_SURFACE,
                "items": signal,
            },
            "caveat": {"type": "string"},
        },
        "required": ["status", "signals", "caveat"],
        "additionalProperties": False,
    }


def _failure_status(exc: workflow.WorkflowError) -> str:
    text = str(exc).casefold()
    if "timed out" in text or "timeout" in text:
        return "TIMEOUT"
    if "schema" in text or "invalid" in text or "malformed" in text:
        return "BAD_SCHEMA"
    return "UNAVAILABLE"


def _run_surface(
    surface: Mapping[str, object],
    *,
    topic: str | None,
    days: int,
    as_of: str,
) -> dict[str, object]:
    key = str(surface["key"])
    label = str(surface["label"])
    print(f"Surface Scout [{label}]: started.", flush=True)
    surface_runtime._trace_event(
        {
            "event": "surface_started",
            "surface": key,
            "label": label,
            "as_of": as_of,
            "timeout_seconds": SURFACE_TIMEOUT,
        }
    )
    prompt = f"""You are one shallow bounded surface scout. Search one surface area only.
Surface lane: {label}
Lane rule: {surface['instruction']}
Research window: the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, agents, evaluations, reliability, context engineering, enterprise AI, developer tooling, model economics and AI product management'}.

Return up to {surface_runtime.SIGNALS_PER_SURFACE} materially distinct current GenAI/product conversations visible on THIS SURFACE ONLY, ordered strongest first. This is a retrieval pass, not a thesis or deep momentum-analysis pass. Do not browse another source family to compensate for missing evidence.

PRIORITISE BROAD, CONSUMABLE SITUATIONS:
- Prefer situations a smart PM/AI product practitioner can understand before learning specialist infrastructure, benchmark, security, or ML-research context.
- Prefer a visible human/product consequence: cost, time, quality, customer experience, productivity, risk, team workflow, a recurring decision, a useful new capability, or an inspectable builder launch.
- Prefer topics that could support one central argument and at least one honest utility form: a concrete action, reusable artifact, or decision the reader can make differently.
- Do not equate technical sophistication with topic quality. A narrower technical development is useful only if its consequence can be stated plainly.
- Do not let large-company announcements crowd out individual/small-team launches that are inspectable and useful.
- Avoid generic obvious slogans. A topic should add something the target reader probably has not already priced in.

TWO-SENTENCE PM TEST BEFORE RETURNING A SIGNAL:
Imagine explaining the situation to a smart product manager who understands AI products but does not specialise in ML research, infrastructure, benchmarks, cybersecurity, or distributed systems. In two sentences, you should be able to communicate what changed and why that reader should care without relying on unexplained acronyms, benchmark names, vendor product names, or specialist terminology. If you cannot, demote the signal unless it is an unusually important deep-track development.

For each signal return only:
- topic: concise plain-English conversation label; do not lead with jargon when a consequence can lead instead;
- why_now: concrete current reason plus the product/human consequence in plain language;
- platform: exactly one allowed platform for this lane;
- url: representative public HTTPS URL;
- source: public author/community/publisher name;
- published_at: source timestamp when visible;
- freshness_hours: age of the newest substantive signal as of {as_of};
- engagement_units: visible public interactions excluding raw page/video views, or null if unavailable.

Social engagement may establish momentum only. It does not prove factual claims. Do NOT calculate acceleration. Do NOT perform cross-platform comparison. Do NOT rank against other surfaces. Do not invent timestamps, URLs, engagement, consequences, or popularity rankings. If this lane is unavailable or has no defensible current signal, return that honestly. Return evidence only; do not use the private authority profile and do not draft."""
    status = "UNAVAILABLE"
    caveat = "Surface Scout did not execute."
    signals: list[dict[str, object]] = []
    for attempt in range(1, surface_runtime.MAX_SURFACE_ATTEMPTS + 1):
        try:
            result = surface_runtime.invoke_structured(
                config=MODEL,
                role_prompt=surface_runtime.daily_cli._role("scout"),
                task_prompt=prompt,
                schema=_shallow_schema(surface["allowed_platforms"]),  # type: ignore[arg-type,index]
                timeout=SURFACE_TIMEOUT,
                web_search=True,
                stage_label=f"Surface Scout {label}",
            )
            raw_signals = result.get("signals")
            if isinstance(raw_signals, list):
                result = {
                    **result,
                    "signals": [
                        {**item, "acceleration_percent": None}
                        if isinstance(item, Mapping)
                        else item
                        for item in raw_signals
                    ],
                }
            validated = surface_runtime._validate_surface_result(
                result,
                surface=surface,
            )
            status = str(validated["status"])
            caveat = str(validated["caveat"])
            signals = list(validated["signals"])  # type: ignore[arg-type]
        except workflow.WorkflowError as exc:
            status = _failure_status(exc)
            caveat = str(exc)
            signals = []
        if (
            status not in {"TIMEOUT", "UNAVAILABLE"}
            or attempt == surface_runtime.MAX_SURFACE_ATTEMPTS
        ):
            break
        print(f"Surface Scout [{label}]: {status}; retrying once.", flush=True)
        surface_runtime._trace_event(
            {
                "event": "surface_retry",
                "surface": key,
                "label": label,
                "attempt": attempt + 1,
                "reason": status,
            }
        )

    payload = {
        "schema_version": 2,
        "surface": key,
        "label": label,
        "status": status,
        "signals": signals,
        "caveat": caveat,
    }
    surface_runtime._write_surface_file(key, payload)
    surface_runtime._trace_event(
        {
            "event": "surface_finished",
            "surface": key,
            "label": label,
            "status": status,
            "signal_count": len(signals),
            "timeout_seconds": SURFACE_TIMEOUT,
        }
    )
    print(f"Surface Scout [{label}]: {status} ({len(signals)} signal(s)).", flush=True)
    for signal in signals:
        print(f"  - {signal['topic']} | {signal['url']}", flush=True)
    return payload


def install() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    surface_runtime.SURFACE_TIMEOUT = SURFACE_TIMEOUT
    surface_runtime.CONSOLIDATION_TIMEOUT = CONSOLIDATION_TIMEOUT
    surface_runtime.MODEL = MODEL
    surface_runtime._run_surface = _run_surface  # type: ignore[assignment]
    _INSTALLED = True
