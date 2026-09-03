"""Rank topics by measured distribution instead of vetoing them on judgement.

The Scout already measures distribution: it reports observed counts and Python
maps them through fixed bands. Topic Value then re-judged those topics with an
uncalibrated model against a feasible region covering 4.4% of its own score
space, so a day with eight candidates produced nothing roughly 70% of the time.

This module inverts that. Only ``evidence_strength`` still hard-gates, because
it is checkable rather than a matter of taste: no body-read evidence means no
post. Every other axis becomes a ranked shortfall. A day therefore always yields
the best available topic, and the reason it is not better is recorded rather
than lost.

Weak topics are still caught downstream by the Critic, the honesty and citation
gates, and the week contract's slot gates. A blocked topic is caught by nothing,
because it produces nothing.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

from . import topic_value

# The one axis that still blocks. Evidence is verifiable; relevance is not.
BLOCKING_AXIS = "evidence_strength"
BLOCKING_MINIMUM = 3

# Retained as targets, not vetoes: a shortfall against each is reported.
TARGETS: dict[str, int] = {
    "reader_relevance": 4,
    "reader_value": 4,
    "gravity": 2,
    "evidence_strength": 3,
    "authority_fit": 3,
}
TARGET_TOTAL = topic_value.TOPIC_VALUE_MIN_TOTAL


@dataclass(frozen=True, slots=True)
class AxisShortfall:
    axis: str
    observed: int
    target: int

    @property
    def gap(self) -> int:
        return self.target - self.observed


@dataclass(frozen=True, slots=True)
class Selection:
    topic_id: str
    topic: str
    momentum_total: int | None
    topic_value_total: int
    status: str                       # SELECTED | SELECTED_BELOW_TARGET | BLOCKED
    reason_code: str
    shortfalls: tuple[AxisShortfall, ...] = field(default=())
    rank: int = 0

    @property
    def total_gap(self) -> int:
        return sum(s.gap for s in self.shortfalls)


def _scores(candidate: Mapping[str, object]) -> dict[str, int]:
    raw = candidate.get("scores")
    if not isinstance(raw, Mapping):
        return {}
    return {axis: int(raw.get(axis, 0)) for axis in topic_value.TOPIC_VALUE_AXES}


def _momentum_total(candidate: Mapping[str, object]) -> int | None:
    value = candidate.get("total")
    return int(value) if type(value) is int else None


def shortfalls_for(scores: Mapping[str, int]) -> tuple[AxisShortfall, ...]:
    found = [
        AxisShortfall(axis, scores.get(axis, 0), target)
        for axis, target in TARGETS.items()
        if scores.get(axis, 0) < target
    ]
    found.sort(key=lambda s: (-s.gap, s.axis))
    return tuple(found)


def rank(candidates: Sequence[Mapping[str, object]]) -> list[Selection]:
    """Order every candidate. Only missing evidence removes one from play."""
    out: list[Selection] = []
    for candidate in candidates:
        scores = _scores(candidate)
        total = sum(scores.values())
        blocked = scores.get(BLOCKING_AXIS, 0) < BLOCKING_MINIMUM
        found = shortfalls_for(scores)
        if blocked:
            status, reason = "BLOCKED", "insufficient-body-read-evidence"
        elif found or total < TARGET_TOTAL:
            status, reason = "SELECTED_BELOW_TARGET", (found[0].axis if found else "below-target-total")
        else:
            status, reason = "SELECTED", "ok"
        out.append(Selection(
            topic_id=str(candidate.get("id", "")),
            topic=str(candidate.get("topic", "")),
            momentum_total=_momentum_total(candidate),
            topic_value_total=total,
            status=status,
            reason_code=reason,
            shortfalls=found,
        ))
    # Distribution first — that is the measured signal. Judgement breaks ties.
    out.sort(key=lambda s: (
        s.status == "BLOCKED",
        -(s.momentum_total if s.momentum_total is not None else -1),
        -s.topic_value_total,
        s.topic,
    ))
    return [
        Selection(**{**asdict(item), "shortfalls": item.shortfalls, "rank": index})
        for index, item in enumerate(out, start=1)
    ]


def select(candidates: Sequence[Mapping[str, object]]) -> Selection | None:
    """The topic the day will actually use, or None when every one lacks evidence."""
    for item in rank(candidates):
        if item.status != "BLOCKED":
            return item
    return None


def diagnostic(candidates: Sequence[Mapping[str, object]]) -> dict[str, object]:
    """Per-axis tally: which axis is actually costing you topics, run after run."""
    ranked = rank(candidates)
    tally: dict[str, int] = {axis: 0 for axis in TARGETS}
    for item in ranked:
        for shortfall in item.shortfalls:
            tally[shortfall.axis] += 1
    considered = len(ranked)
    blocked = sum(1 for item in ranked if item.status == "BLOCKED")
    at_target = sum(1 for item in ranked if item.status == "SELECTED")
    worst = max(tally, key=lambda a: (tally[a], a)) if considered else None
    return {
        "candidates": considered,
        "blocked_on_evidence": blocked,
        "at_or_above_target": at_target,
        "below_target": considered - blocked - at_target,
        "axis_shortfall_counts": tally,
        "most_limiting_axis": worst if considered and tally.get(worst, 0) else None,
        "selected_topic_id": (select(candidates) or Selection("", "", None, 0, "BLOCKED", "none")).topic_id or None,
    }
