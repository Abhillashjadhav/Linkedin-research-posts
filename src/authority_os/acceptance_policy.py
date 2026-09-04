"""One versioned acceptance contract for every five-axis draft consumer."""

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
ACCEPTANCE_CONTRACT_VERSION = "five-axis-v2"


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


def acceptance_decision(
    scorecard: Mapping[str, object],
    *,
    hard_gates_pass: bool,
    additional_checks_pass: bool = True,
) -> dict[str, object]:
    """Evaluate the shared five-axis contract and record every shortfall.

    Callers remain responsible for deterministic checks that are specific to
    their artifact (for example anti-slop or privacy-at-write enforcement).
    """

    effective_raw = scorecard.get("effective_total")
    effective_total = effective_raw if type(effective_raw) is int else 0
    axis_failures = axis_shortfalls(scorecard)
    total_shortfall = max(0, ACCEPTABLE_QUALITY_FLOOR - effective_total)
    accepted = (
        total_shortfall == 0
        and not axis_failures
        and hard_gates_pass is True
        and additional_checks_pass is True
    )
    reasons: list[str] = []
    if total_shortfall:
        reasons.append("total_score")
    reasons.extend(axis_failures)
    if hard_gates_pass is not True:
        reasons.append("hard_gates")
    if additional_checks_pass is not True:
        reasons.append("additional_checks")
    return {
        "contract_version": ACCEPTANCE_CONTRACT_VERSION,
        "status": "PASS" if accepted else "FAIL",
        "effective_total": effective_total,
        "required_total": ACCEPTABLE_QUALITY_FLOOR,
        "total_shortfall": total_shortfall,
        "axis_shortfalls": axis_failures,
        "hard_gates_pass": hard_gates_pass is True,
        "additional_checks_pass": additional_checks_pass is True,
        "reasons": reasons,
    }


def scorecard_is_acceptable(
    scorecard: Mapping[str, object],
    *,
    hard_gates_pass: bool,
    additional_checks_pass: bool = True,
) -> bool:
    """Return whether a scorecard clears the shared acceptance contract."""

    return (
        acceptance_decision(
            scorecard,
            hard_gates_pass=hard_gates_pass,
            additional_checks_pass=additional_checks_pass,
        )["status"]
        == "PASS"
    )
