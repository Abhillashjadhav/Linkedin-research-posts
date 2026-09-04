"""Named V1 acceptance thresholds shared by evaluation and fallback reporting."""

from __future__ import annotations

from types import MappingProxyType
from typing import Mapping


ACCEPTABLE_QUALITY_FLOOR = 18
MIN_HOOK_SCORE = 4
MIN_MIDDLE_ESCALATION_SCORE = 3
MIN_EARNED_CLOSER_SCORE = 3
MIN_SPECIFICITY_AND_SOURCE_QUALITY_SCORE = 3
MIN_VOICE_FIDELITY_SCORE = 4

# Earned closer remains in acceptance by owner decision. Across two independent
# calibration runs it measured inverted (owner flops 3.73 versus winners 3.33),
# so it is a candidate for demotion only after a held-out set exists.
AXIS_FLOORS: Mapping[str, int] = MappingProxyType(
    {
        "hook_strength": MIN_HOOK_SCORE,
        "middle_escalation": MIN_MIDDLE_ESCALATION_SCORE,
        "earned_closer": MIN_EARNED_CLOSER_SCORE,
        "specificity_and_source_quality": MIN_SPECIFICITY_AND_SOURCE_QUALITY_SCORE,
        "voice_fidelity": MIN_VOICE_FIDELITY_SCORE,
    }
)

HARD_GATES = frozenset({"honesty", "citation", "proof", "privacy", "relevance"})


def axis_shortfalls(axes: Mapping[str, object]) -> dict[str, dict[str, int]]:
    """Return every missing axis floor with its exact deficit."""

    shortfalls: dict[str, dict[str, int]] = {}
    for axis, required in AXIS_FLOORS.items():
        raw = axes.get(axis, 0)
        observed = int(raw) if type(raw) is int else 0
        if observed < required:
            shortfalls[axis] = {
                "observed": observed,
                "required": required,
                "shortfall": required - observed,
            }
    return shortfalls


def hard_candidate_gates_pass(gates: Mapping[str, object]) -> bool:
    """Require every candidate-level hard gate; privacy is enforced at artifact write."""

    for name in HARD_GATES - {"privacy"}:
        raw = gates.get(name, "NOT_EVALUATED")
        status = raw.get("status", "NOT_EVALUATED") if isinstance(raw, Mapping) else raw
        allowed = {"PASS", "NOT_REQUIRED"} if name == "proof" else {"PASS"}
        if str(status) not in allowed:
            return False
    return True
