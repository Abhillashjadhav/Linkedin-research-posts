"""One versioned acceptance contract for every five-axis draft consumer."""

from __future__ import annotations

from types import MappingProxyType
from collections.abc import Sequence
from typing import Mapping


ACCEPTABLE_QUALITY_FLOOR = 18
MIN_HOOK_SCORE = 4
MIN_VOICE_FIDELITY_SCORE = 4

# Repair reaches every axis target before optimizing the overall total.
# Editorial findings remain advisory and never block draft delivery.
AXIS_FLOORS: Mapping[str, int] = MappingProxyType(
    {
        "hook_strength": MIN_HOOK_SCORE,
        "middle_escalation": 3,
        "earned_closer": 3,
        "specificity_and_source_quality": 3,
        "voice_fidelity": MIN_VOICE_FIDELITY_SCORE,
    }
)

HARD_GATES = frozenset({"honesty", "citation", "proof", "privacy", "relevance"})
ADVISORY_FACTUAL_WORDING_CODE = "unsupported-factual-marker"
ADVISORY_FACTUAL_WORDING_GATES = frozenset({"honesty", "citation"})
ACCEPTANCE_CONTRACT_VERSION = "five-axis-v6"


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


def repair_score_decision(
    previous: Mapping[str, object], proposed: Mapping[str, object]
) -> tuple[bool, list[str]]:
    """Reach axis targets first, then optimize total without losing a target."""
    before = axis_shortfalls(previous)
    after = axis_shortfalls(proposed)
    worsened = [
        axis for axis, item in after.items()
        if item["shortfall"] > before.get(axis, {}).get("shortfall", 0)
    ]
    if worsened:
        return False, [f"axis-target-regressed:{axis}" for axis in worsened]
    if before:
        if sum(x["shortfall"] for x in after.values()) < sum(x["shortfall"] for x in before.values()):
            return True, []
        return False, ["unmet-axis-targets-did-not-improve"]
    old_total = int(previous["effective_total"])
    new_total = int(proposed["effective_total"])
    if new_total < old_total:
        return False, [f"total-regressed-{old_total}-to-{new_total}"]
    if new_total > old_total:
        return True, []
    return False, ["no-score-improvement"]


def axis_repair_plan(axes: Mapping[str, object]) -> dict[str, object]:
    """Give both live Writer and frozen Editor concrete, bounded edit targets."""
    shortfalls = axis_shortfalls(axes)
    actions = {
        "hook_strength": "Replace the first two lines with a materially different opening: a supported concrete event or observation and its immediate reader consequence. Avoid a topic summary, generic question, or synonym-only rewrite. Preserve the passing body and closer.",
        "middle_escalation": "Edit the middle to explain the supported mechanism and its consequence; remove repetition. Preserve the passing opening and closer.",
        "earned_closer": "Edit the ending into a specific judgment or decision earned by this post. Preserve the passing opening and body; avoid a generic engagement question.",
        "specificity_and_source_quality": "Replace vague claims with precise details already supported by the supplied evidence, or narrow the claim. Never invent a fact or source.",
        "voice_fidelity": "Edit only the passages with generic, consultant, or machine-like language into plain conversational judgment using the canonical voice rubric. Never invent experience or emotion.",
    }
    return {
        "phase": "axis_targets" if shortfalls else "overall_total",
        "targets": dict(AXIS_FLOORS),
        "focus_axes": list(shortfalls),
        "preserve_axes": [axis for axis in AXIS_FLOORS if axis not in shortfalls],
        "edits": [
            {"axis": axis, **deficit, "action": actions[axis]}
            for axis, deficit in shortfalls.items()
        ],
        "instruction": (
            "Repair only below-target axes first. Do not spend an edit pushing a passing axis toward 5. "
            "Keep passing sections unchanged unless a focused repair needs a minimal connecting edit. "
            "A reduced axis deficit takes priority over total; passing scores may trade down to their targets. "
            "Once every axis reaches its target, improve the overall total only if below 18, then stop."
        ),
    }


def _gate_status_and_reasons(
    raw: object, pooled_reason_codes: Sequence[object]
) -> tuple[str, tuple[str, ...]]:
    if isinstance(raw, Mapping):
        status = str(raw.get("status", "NOT_EVALUATED"))
        raw_reasons = raw.get("reason_codes", ())
        reasons = (
            tuple(str(reason) for reason in raw_reasons)
            if isinstance(raw_reasons, Sequence)
            and not isinstance(raw_reasons, (str, bytes))
            else ()
        )
        return status, reasons
    return str(raw), tuple(str(reason) for reason in pooled_reason_codes)


def factual_wording_advisories(
    gates: Mapping[str, object], *, reason_codes: Sequence[object] = ()
) -> list[str]:
    """Return visible advisory codes without changing the raw gate evidence."""

    advisories: list[str] = []
    for name in ADVISORY_FACTUAL_WORDING_GATES:
        status, reasons = _gate_status_and_reasons(gates.get(name), reason_codes)
        if (
            status in {"FAIL", "HUMAN_REVIEW", "ADVISORY"}
            and reasons
            and set(reasons) <= {ADVISORY_FACTUAL_WORDING_CODE}
        ):
            advisories.extend(reasons)
    return list(dict.fromkeys(advisories))


def hard_candidate_gates_pass(
    gates: Mapping[str, object],
    *,
    passes_required_gates: bool | None = None,
    reason_codes: Sequence[object] = (),
    allow_factual_wording_advisory: bool = False,
) -> bool:
    """Apply the hard-gate contract, with one reason-specific wording advisory.

    The raw gate findings stay unchanged.  After a bounded rewrite attempt, only
    ``unsupported-factual-marker`` may be treated as non-blocking, and only when
    it is the complete reason for the honesty/citation failures.  Every other
    failed gate or mixed reason set remains blocking.
    """

    advisory_seen = False
    names = (set(gates) | (HARD_GATES - {"privacy"})) - {"privacy"}
    for name in names:
        status, reasons = _gate_status_and_reasons(gates.get(name), reason_codes)
        allowed = {"PASS", "NOT_REQUIRED"} if name == "proof" else {"PASS"}
        if status in allowed:
            continue
        if (
            allow_factual_wording_advisory
            and name in ADVISORY_FACTUAL_WORDING_GATES
            and status in {"FAIL", "HUMAN_REVIEW", "ADVISORY"}
            and reasons
            and set(reasons) <= {ADVISORY_FACTUAL_WORDING_CODE}
        ):
            advisory_seen = True
            continue
        return False
    if passes_required_gates is False and not advisory_seen:
        return False
    return True


def acceptance_decision(
    scorecard: Mapping[str, object],
    *,
    hard_gates_pass: bool,
    additional_checks_pass: bool = True,
) -> dict[str, object]:
    """Evaluate the shared five-axis contract and record every shortfall.

    Raw editorial checks remain visible, but cannot veto writing acceptance.
    Filesystem security and authorization are enforced separately at I/O.
    """

    effective_raw = scorecard.get("effective_total")
    effective_total = effective_raw if type(effective_raw) is int else 0
    axis_failures = axis_shortfalls(scorecard)
    total_shortfall = max(0, ACCEPTABLE_QUALITY_FLOOR - effective_total)
    accepted = (
        total_shortfall == 0
        and not axis_failures
    )
    reasons: list[str] = []
    if total_shortfall:
        reasons.append("total_score")
    reasons.extend(axis_failures)
    advisories = []
    if hard_gates_pass is not True:
        advisories.append("editorial-gate-findings")
    if additional_checks_pass is not True:
        advisories.append("additional-editorial-findings")
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
        "advisory_warnings": advisories,
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
