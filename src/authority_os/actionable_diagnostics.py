"""V1-only actionable failure diagnostics and non-blocking repeated-failure feedback.

The legacy gate envelope flattens PASS, NOT_REQUIRED, and FAIL reason strings into one
list. That made the repair loop treat success markers as failures. This overlay keeps
raw editorial findings visible while projecting only failure reasons into repair feedback,
adds sentence-level repair targets for unsupported-claim failures, and changes repair guidance when a failure repeats. The bounded loop owns exhaustion.
"""

from __future__ import annotations

import re
from typing import Mapping

from . import quality_cli, quality_optimizer, workflow

_INSTALLED = False
_LAST_SIGNATURE: tuple[tuple[str, str], ...] | None = None
_REPEAT_COUNT = 0
_LAST_SCORE: int | None = None
_ORIGINAL_QUALITY_FEEDBACK = quality_optimizer._quality_feedback  # type: ignore[attr-defined]

_FAILURE_REASON_GATES: dict[str, tuple[str, ...]] = {
    "authority-statement-not-reflected": ("authority_conversion",),
    "product-decision-not-reflected": ("authority_conversion",),
    "unsupported-personal-or-ownership-claim": ("honesty",),
    "title-only-claim": ("honesty",),
    "unknown-claim-id": ("citation",),
    "title-only-evidence": ("citation",),
    "community-only-evidence": ("citation",),
    "unsupported-factual-marker": ("honesty", "citation"),
    "untraceable-incident": ("honesty", "citation"),
    "unsupported-source-url": ("honesty", "citation"),
    "target-reader-not-reflected": ("relevance",),
    "reader-problem-not-reflected": ("relevance",),
}

_REPAIR_ACTIONS = {
    "authority-statement-not-reflected": "Rewrite one supported sentence so the supplied authority statement is explicit.",
    "product-decision-not-reflected": "Rewrite one supported sentence so the supplied product decision is explicit.",
    "unsupported-personal-or-ownership-claim": "Remove the personal/ownership claim unless it is explicitly attested by proof.",
    "title-only-claim": "Replace the title-derived assertion with a claim supported by body-read evidence, or remove it.",
    "unknown-claim-id": "Use only claim IDs present in the selected evidence envelope.",
    "title-only-evidence": "Ground the claim in body-read evidence rather than title text alone.",
    "community-only-evidence": "Do not use community/social discovery material as factual evidence; narrow or remove the claim.",
    "unsupported-factual-marker": "Narrow or remove the unsupported factual assertion; do not add new facts to repair it.",
    "untraceable-incident": "Remove the incident framing unless the selected evidence directly traces the incident.",
    "unsupported-source-url": "Remove the URL or use only a URL already supported by the selected evidence/proof envelope.",
    "target-reader-not-reflected": "Make the supplied target reader explicit without inventing a new audience.",
    "reader-problem-not-reflected": "Make the supplied reader problem explicit without broadening the claim.",
}

_FACTUAL_HINT = re.compile(
    r"\b(?:is|are|was|were|has|have|does|did|will|can|cannot|compiles?|drives?|verif(?:y|ies|ied)|records?|demonstrates?|proves?|supports?|implements?|produces?|creates?|establishes?)\b",
    re.IGNORECASE,
)


def _failed_reasons(candidate: quality_cli.CandidateResult) -> list[dict[str, object]]:
    failed_gates = {name for name, status in candidate.gates.items() if status == "FAIL"}
    diagnostics: list[dict[str, object]] = []
    for reason in candidate.gate_reasons:
        possible = _FAILURE_REASON_GATES.get(reason, ())
        gates = [gate for gate in possible if gate in failed_gates]
        if not gates:
            continue
        spans: list[str] = []
        if reason in {"unsupported-factual-marker", "untraceable-incident", "unsupported-source-url"}:
            for sentence in workflow._candidate_sentences(candidate.text):  # type: ignore[attr-defined]
                if reason == "unsupported-source-url" and "http" not in sentence:
                    continue
                if reason != "unsupported-source-url" and not _FACTUAL_HINT.search(sentence):
                    continue
                spans.append(sentence.strip())
                if len(spans) == 3:
                    break
        diagnostics.append(
            {
                "gates": gates,
                "failure_code": reason,
                "suspect_text_spans": spans,
                "evidence_ids": "not-exposed-by-current-quality-envelope",
                "repair_action": _REPAIR_ACTIONS[reason],
            }
        )
    return diagnostics


def _signature(candidate: quality_cli.CandidateResult) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (gate, str(item["failure_code"]))
            for item in _failed_reasons(candidate)
            for gate in item["gates"]  # type: ignore[index]
        )
    )


def _quality_feedback(attempt: quality_cli.AttemptResult, cycle: int) -> dict[str, object]:
    global _LAST_SIGNATURE, _REPEAT_COUNT, _LAST_SCORE
    if cycle == 1:
        _LAST_SIGNATURE = None
        _REPEAT_COUNT = 0
        _LAST_SCORE = None

    feedback = dict(_ORIGINAL_QUALITY_FEEDBACK(attempt, cycle))
    seed = max(attempt.candidates, key=quality_optimizer._candidate_rank)  # type: ignore[attr-defined]
    repair_seed = feedback.get("repair_seed")
    retained = quality_optimizer._state().best
    if retained is not None and isinstance(repair_seed, Mapping) and repair_seed.get("text") == retained.text:
        seed = retained
    diagnostics = _failed_reasons(seed)
    signature = _signature(seed)
    score = seed.effective_total

    if signature and signature == _LAST_SIGNATURE and (_LAST_SCORE is None or score <= _LAST_SCORE):
        _REPEAT_COUNT += 1
    else:
        _REPEAT_COUNT = 1 if signature else 0
    _LAST_SIGNATURE = signature
    _LAST_SCORE = score

    repair_seed = feedback.get("repair_seed")
    if isinstance(repair_seed, dict):
        repair_seed["gate_reasons"] = [item["failure_code"] for item in diagnostics]
        repair_seed["actionable_gate_diagnostics"] = diagnostics
    feedback["actionable_gate_diagnostics"] = diagnostics
    feedback["repeated_failure_signature_count"] = _REPEAT_COUNT

    if _REPEAT_COUNT >= 2:
        feedback["stalled_repair"] = (
            "Repeated findings are advisory. Use a materially different targeted edit; "
            "continue within the four-cycle budget and deliver the best draft on exhaustion."
        )
    return feedback


def install() -> None:
    """Install after provider routing and before quality_optimizer.install()."""

    global _INSTALLED
    if _INSTALLED:
        return
    quality_optimizer._quality_feedback = _quality_feedback  # type: ignore[attr-defined,assignment]
    _INSTALLED = True
