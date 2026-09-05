"""One versioned acceptance contract for every five-axis draft consumer."""

from __future__ import annotations

from types import MappingProxyType
from collections.abc import Sequence
from typing import Mapping


ACCEPTABLE_QUALITY_FLOOR = 18
MIN_HOOK_SCORE = 4
MIN_VOICE_FIDELITY_SCORE = 4

# All five axes remain scored and contribute to the 18/25 total. Only hook and
# voice have independent floors; the other three axes may trade off inside the
# total. Hard factual gates remain separate and cannot be offset by score.
AXIS_FLOORS: Mapping[str, int] = MappingProxyType(
    {
        "hook_strength": MIN_HOOK_SCORE,
        "voice_fidelity": MIN_VOICE_FIDELITY_SCORE,
    }
)

HARD_GATES = frozenset({"honesty", "citation", "proof", "privacy", "relevance"})
ADVISORY_FACTUAL_WORDING_CODE = "unsupported-factual-marker"
ADVISORY_FACTUAL_WORDING_GATES = frozenset({"honesty", "citation"})
ACCEPTANCE_CONTRACT_VERSION = "five-axis-v4"


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
