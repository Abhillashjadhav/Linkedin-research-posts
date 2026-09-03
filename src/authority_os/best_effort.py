"""Best-effort selection when no candidate clears the locked bar.

Four exhausted cycles currently return nothing. That is correct for safety and
wrong for operations: the day produces no post at all, and the work is lost.

This module keeps the safety contract intact and relaxes only the quality bar.
Honesty, citation, proof, privacy and relevance gates stay hard-blocking; the
24/25 score, the 5/5 hook and residual anti-slop findings become a *shortfall
report* attached to the best surviving candidate.

The result is never READY_FOR_HUMAN_REVIEW. It is BEST_EFFORT: a post the owner
can finish in minutes, with the exact gap named, instead of an empty day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping, Sequence

MIN_SCORE = 24
MIN_HOOK = 5

# Gates that may never be waived. A candidate failing any of these is discarded
# outright: shipping an unsupported claim is worse than shipping nothing.
BLOCKING_GATES = frozenset({"honesty", "citation", "proof", "privacy", "relevance"})

# Quality bars that become shortfalls rather than rejections.
SOFT_BARS = ("score", "hook", "anti_slop")


@dataclass(frozen=True, slots=True)
class Shortfall:
    bar: str
    observed: object
    required: object
    gap: float
    fix_hint: str


@dataclass(frozen=True, slots=True)
class BestEffort:
    candidate_id: str
    cycle: int
    effective_total: int
    hook_strength: int
    shortfalls: tuple[Shortfall, ...] = field(default=())

    @property
    def total_gap(self) -> float:
        return round(sum(s.gap for s in self.shortfalls), 3)


def _blocking_failure(gates: Mapping[str, Mapping[str, object]]) -> str | None:
    for name, value in gates.items():
        if name in BLOCKING_GATES and str(value.get("status")) == "FAIL":
            return name
    return None


def _shortfalls(score: Mapping[str, object], slop: Sequence[Mapping[str, str]]) -> tuple[Shortfall, ...]:
    out: list[Shortfall] = []
    total = int(score.get("effective_total", 0))
    if total < MIN_SCORE:
        out.append(Shortfall("score", total, MIN_SCORE, float(MIN_SCORE - total),
                             "Raise the weakest axis; the Critic scorecard names which."))
    hook = int(score.get("hook_strength", 0))
    if hook < MIN_HOOK:
        out.append(Shortfall("hook", hook, MIN_HOOK, float(MIN_HOOK - hook),
                             "Replace line 1 with a concrete reader problem plus its payoff."))
    if slop:
        codes = ", ".join(sorted({str(f.get("code")) for f in slop}))
        out.append(Shortfall("anti_slop", len(slop), 0, float(len(slop)),
                             f"Remove the flagged phrasing: {codes}."))
    return tuple(out)


def select(
    cycles: Sequence[Mapping[str, object]],
) -> BestEffort | None:
    """Pick the candidate closest to the bar that breaks no blocking gate.

    ``cycles`` is a sequence of ``{"cycle": int, "scores": [...],
    "gates": {candidate_id: {...}}, "anti_slop": {candidate_id: [...]}}``.
    """
    best: BestEffort | None = None
    for entry in cycles:
        cycle = int(entry.get("cycle", 0))
        gates = entry.get("gates") or {}
        slop = entry.get("anti_slop") or {}
        for score in entry.get("scores") or []:
            candidate_id = str(score.get("candidate_id"))
            candidate_gates = gates.get(candidate_id) or {}
            if _blocking_failure(candidate_gates) is not None:
                continue
            found = _shortfalls(score, slop.get(candidate_id) or [])
            option = BestEffort(
                candidate_id=candidate_id,
                cycle=cycle,
                effective_total=int(score.get("effective_total", 0)),
                hook_strength=int(score.get("hook_strength", 0)),
                shortfalls=found,
            )
            if best is None or (option.total_gap, -option.effective_total) < (best.total_gap, -best.effective_total):
                best = option
    return best


def package(result: BestEffort | None) -> dict[str, object]:
    """The trace fragment a best-effort day writes instead of an empty BLOCKED."""
    if result is None:
        return {
            "status": "BLOCKED",
            "reason": "No candidate cleared all four high-bar cycles, and every candidate failed a blocking gate.",
            "human_approval_status": "NOT_APPROVED",
            "publishing_status": "DISABLED",
        }
    return {
        "status": "BEST_EFFORT",
        "reason": (
            f"No candidate cleared the locked bar in four cycles. Candidate "
            f"{result.candidate_id} from cycle {result.cycle} came closest and breaks no "
            f"blocking gate."
        ),
        "candidate_id": result.candidate_id,
        "cycle": result.cycle,
        "effective_total": result.effective_total,
        "hook_strength": result.hook_strength,
        "total_gap": result.total_gap,
        "shortfalls": [
            {"bar": s.bar, "observed": s.observed, "required": s.required,
             "gap": s.gap, "fix_hint": s.fix_hint}
            for s in result.shortfalls
        ],
        "human_approval_status": "NOT_APPROVED",
        "publishing_status": "DISABLED",
        "manual_fact_verification_required": True,
        "warning": (
            "This post did not clear the quality bar. It is safe to publish only after "
            "the shortfalls above are closed by hand."
        ),
    }
