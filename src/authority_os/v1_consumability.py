"""V1-only consumability tuning without adding another model stage.

This module preserves the existing seven surface scouts, Topic Value, Resonance,
and Writer/Critic pipeline. It changes two things only:

* consolidation is instructed to preserve broad, consequence-led opportunities rather
  than rewarding technical density by itself;
* the final Resonance assessment is augmented with one deterministic hook-entry check
  so a technically strong post cannot pass when the first two lines are too costly to enter.

The module is installed only by V1 live entry points. V0 is untouched.
"""

from __future__ import annotations

import json
import re
from typing import Mapping, Sequence

from . import momentum_surface_parallel as surface
from . import resonance, workflow

_INSTALLED = False

# Terms are not banned from a post. They are expensive entry terms: if several are
# required before the reader sees a consequence, the hook is doing specialist setup.
_SPECIALIST_ENTRY_TERMS = frozenset(
    {
        "benchmark",
        "contamination",
        "orchestration",
        "inference",
        "accelerator",
        "gpu",
        "cpu",
        "mcp",
        "rag",
        "embedding",
        "fine-tuning",
        "alignment",
        "context window",
        "sparse attention",
        "model routing",
        "runtime enforcement",
    }
)

# At least one plain consequence/action signal should be visible in the first two
# non-blank lines. This is intentionally broad and deterministic; the LLM still owns
# taste via Resonance stop_power.
_CONSEQUENCE_TERMS = frozenset(
    {
        "cost",
        "spend",
        "budget",
        "money",
        "time",
        "faster",
        "slow",
        "quality",
        "customer",
        "user",
        "risk",
        "safe",
        "trust",
        "fail",
        "failure",
        "stop",
        "pause",
        "break",
        "ship",
        "launch",
        "team",
        "work",
        "decision",
        "decide",
        "approve",
        "reject",
        "product",
        "better",
        "worse",
        "save",
        "avoid",
        "learn",
        "use",
        "test",
        "check",
        "prove",
    }
)


def hook_entry_check(post_text: str) -> dict[str, object]:
    """Cheap behavioural gate for the first two non-blank lines.

    This is not a style score. It only asks whether the opening is short enough,
    consequence-bearing, and not dependent on a pile of specialist terms/acronyms.
    """

    if not isinstance(post_text, str) or not post_text.strip():
        return {"status": "BLOCKED", "reason_codes": ["hook-empty"], "excerpt": ""}

    lines = [line.strip() for line in post_text.splitlines() if line.strip()]
    opening_lines = lines[:2]
    opening = " ".join(opening_lines)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", opening)
    lowered = opening.casefold()
    acronyms = re.findall(r"\b[A-Z][A-Z0-9-]{1,7}\b", opening)
    specialist_hits = sorted(term for term in _SPECIALIST_ENTRY_TERMS if term in lowered)
    consequence_hits = sorted(term for term in _CONSEQUENCE_TERMS if re.search(rf"\b{re.escape(term)}\b", lowered))

    reasons: list[str] = []
    if len(words) > 60:
        reasons.append("hook-entry-too-long")
    if len(acronyms) > 2:
        reasons.append("hook-entry-acronym-load")
    if len(specialist_hits) > 2:
        reasons.append("hook-entry-specialist-load")
    if not consequence_hits:
        reasons.append("hook-entry-no-plain-consequence")

    return {
        "status": "PASS" if not reasons else "BLOCKED",
        "reason_codes": reasons,
        "word_count": len(words),
        "acronyms": acronyms,
        "specialist_terms": specialist_hits,
        "consequence_terms": consequence_hits,
        "excerpt": opening[:400],
    }


def _consolidate(signals: Sequence[Mapping[str, object]], *, as_of: str) -> list[dict[str, object]]:
    ids = [str(signal["id"]) for signal in signals]
    prompt = f"""Cluster these independently discovered public-web signals into exactly {surface.MOMENTUM_CANDIDATES} materially distinct current GenAI/product conversations.
Do not browse. Do not add facts or signals. Merge only signals that describe the same underlying conversation. Each input signal may be assigned to at most one cluster; unused weak/duplicate signals may be omitted.

Selection goal: preserve conversations that can become useful, widely enterable product content without becoming generic. Rank the clusters using the supplied evidence and these priorities:
1. a concrete consequence a smart PM/AI product practitioner can understand in plain English;
2. a real product/team/customer/cost/quality/risk decision or a useful inspectable capability;
3. something non-obvious enough to teach the reader one step beyond what they likely already know;
4. one central argument rather than several parallel evidence threads;
5. cross-surface repetition, visible engagement, and freshness as of {as_of}.

Do not reward technical sophistication by itself. Do not let a famous vendor name substitute for reader consequence. Individual/small-team launches can rank highly when they are inspectable and useful even with lower raw engagement. Preserve at most one unusually important deep-track conversation whose consequence is not yet broadly legible; the remaining clusters should be understandable without specialist prerequisite knowledge.

Write each topic as a concise plain-English situation. In why_now, state what changed and why the target reader should care. Avoid unexplained acronyms and specialist terminology when the same consequence can be stated plainly.

Social/community popularity is momentum evidence only, not factual corroboration.

Use topic-1 through topic-{surface.MOMENTUM_CANDIDATES} exactly once.

UNTRUSTED_SURFACE_SIGNALS
{json.dumps(list(signals), indent=2, sort_keys=True)}
END_UNTRUSTED_SURFACE_SIGNALS
"""
    result = surface.invoke_structured(
        config=surface.MODEL,
        role_prompt=(
            "You consolidate supplied evidence only. Do not browse, invent, draft, or reward jargon. "
            "Preserve one central reader-relevant situation per cluster."
        ),
        task_prompt=prompt,
        schema=surface._cluster_schema(ids),  # type: ignore[attr-defined]
        timeout=surface.CONSOLIDATION_TIMEOUT,
        web_search=False,
        stage_label="Surface Scout consolidation",
    )
    return surface._validate_clusters(result.get("clusters"), signals)  # type: ignore[attr-defined]


def install() -> None:
    """Install V1-only consumability tuning after existing V1 layers."""

    global _INSTALLED
    if _INSTALLED:
        return

    # Surface-first discovery remains seven independent workers. Only the non-web
    # consolidation objective changes.
    surface._consolidate = _consolidate  # type: ignore[assignment]

    base_post_critic = resonance.invoke_post_critic

    def post_critic_with_entry_gate(
        post_text: str,
        selector: Mapping[str, object],
        *,
        invoker=resonance._default_invoker,  # type: ignore[attr-defined]
    ) -> dict[str, object]:
        assessment = dict(base_post_critic(post_text, selector, invoker=invoker))
        entry = hook_entry_check(post_text)
        assessment["hook_entry"] = entry
        if entry["status"] == "BLOCKED":
            assessment["status"] = "BLOCKED"
            existing = str(assessment.get("diagnosis", "")).strip()
            reasons = ", ".join(str(code) for code in entry["reason_codes"])
            assessment["diagnosis"] = (
                f"Hook entry failed deterministic consumability checks ({reasons}). "
                + existing
            ).strip()
        return assessment

    resonance.invoke_post_critic = post_critic_with_entry_gate  # type: ignore[assignment]
    _INSTALLED = True
