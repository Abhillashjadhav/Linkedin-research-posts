"""Bounded thesis search that preserves individually qualifying cards across cycles."""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from . import daily_cli as base
from . import daily_spine_cli as spine
from . import workflow

Generator = Callable[
    [Mapping[str, object], Sequence[Mapping[str, object]], Mapping[str, object] | None],
    list[dict[str, object]],
]
Critic = Callable[
    [Sequence[Mapping[str, object]], Mapping[str, object], Sequence[Mapping[str, object]]],
    list[dict[str, object]],
]


def _qualifies(card: Mapping[str, object]) -> bool:
    scores = card.get("scores")
    return (
        isinstance(scores, Mapping)
        and int(card.get("total", 0)) >= base.MIN_TOTAL
        and int(scores.get("simplicity", 0)) >= base.MIN_SIMPLICITY
    )


def _rank_key(card: Mapping[str, object]) -> tuple[int, int, str]:
    scores = card.get("scores")
    distinctiveness = int(scores.get("distinctiveness", 0)) if isinstance(scores, Mapping) else 0
    return (-int(card.get("total", 0)), -distinctiveness, base._normal(card.get("thesis", "")))


def search_theses(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    *,
    generator: Generator | None = None,
    critic: Critic | None = None,
) -> list[dict[str, object]]:
    """Collect three distinct qualifying theses without requiring a perfect same-cycle set."""

    generate = generator or spine.generate_cards
    score = critic or base.score_cards
    feedback: Mapping[str, object] | None = None
    seen: set[str] = set()
    accepted: list[dict[str, object]] = []

    for cycle in range(1, base.MAX_CYCLES + 1):
        cards = generate(profile, signals, feedback)
        normalised = [base._normal(card["thesis"]) for card in cards]
        if len(set(normalised)) != len(normalised) or any(value in seen for value in normalised):
            raise workflow.WorkflowError("Thesis generator reused a previously evaluated thesis.")

        score_by_id = {
            str(item["thesis_id"]): item
            for item in score(cards, profile, signals)
        }
        combined: list[dict[str, object]] = []
        for card in cards:
            thesis_id = str(card["id"])
            scorecard = score_by_id[thesis_id]
            combined.append(
                {
                    **card,
                    "scores": {axis: int(scorecard[axis]) for axis in base.AXES},
                    "total": int(scorecard["total"]),
                }
            )
        combined.sort(key=_rank_key)
        seen.update(normalised)
        accepted.extend(card for card in combined if _qualifies(card))

        if len(accepted) >= 3:
            accepted.sort(key=_rank_key)
            chosen = accepted[:3]
            return [
                {**card, "id": f"thesis-{index}"}
                for index, card in enumerate(chosen, start=1)
            ]

        rejected = [card for card in combined if not _qualifies(card)]
        feedback = {
            "cycle": cycle,
            "required_total": base.MIN_TOTAL,
            "required_simplicity": base.MIN_SIMPLICITY,
            "accepted_count": len(accepted),
            "accepted": [
                {
                    "thesis": card["thesis"],
                    "scores": card["scores"],
                    "total": card["total"],
                }
                for card in accepted
            ],
            "rejected": [
                {
                    "id": card["id"],
                    "thesis": card["thesis"],
                    "conversation_surface": card["conversation_surface"],
                    "scores": card["scores"],
                    "total": card["total"],
                }
                for card in rejected
            ],
        }

    raise workflow.WorkflowError(
        "Fewer than three distinct theses cleared the locked authority bar after the bounded search. "
        "Improve the audience, proof inventory or signals."
    )
