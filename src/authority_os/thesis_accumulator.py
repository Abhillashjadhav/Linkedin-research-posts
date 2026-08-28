"""Accumulate independently qualifying discovery theses across bounded cycles."""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from . import daily_cli as base
from . import workflow


def search_theses(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    generator: Callable[[Mapping[str, object], Sequence[Mapping[str, object]], Mapping[str, object] | None], list[dict[str, object]]] = base.generate_cards,
    critic: Callable[[Sequence[Mapping[str, object]], Mapping[str, object], Sequence[Mapping[str, object]]], list[dict[str, object]]] = base.score_cards,
) -> list[dict[str, object]]:
    """Keep high-bar theses instead of discarding them with weaker siblings."""

    feedback: Mapping[str, object] | None = None
    seen: set[str] = set()
    accepted: list[dict[str, object]] = []

    for cycle in range(1, base.MAX_CYCLES + 1):
        cards = generator(profile, signals, feedback)
        current_keys = [base._normal(card["thesis"]) for card in cards]
        if any(key in seen for key in current_keys):
            raise workflow.WorkflowError("Thesis generator reused a thesis from an earlier cycle.")
        seen.update(current_keys)

        scores = {
            str(score["thesis_id"]): score
            for score in critic(cards, profile, signals)
        }
        combined = [
            {
                **card,
                "scores": {
                    axis: int(scores[str(card["id"])][axis])
                    for axis in base.AXES
                },
                "total": int(scores[str(card["id"])]["total"]),
            }
            for card in cards
        ]
        combined.sort(
            key=lambda card: (
                -int(card["total"]),
                -int(card["scores"]["distinctiveness"]),  # type: ignore[index]
                str(card["id"]),
            )
        )

        cycle_accepted = [
            card
            for card in combined
            if int(card["total"]) >= base.MIN_TOTAL
            and int(card["scores"]["simplicity"]) >= base.MIN_SIMPLICITY  # type: ignore[index]
        ]
        for card in cycle_accepted:
            if len(accepted) < 3:
                accepted.append(card)

        if len(accepted) >= 3:
            accepted.sort(
                key=lambda card: (
                    -int(card["total"]),
                    -int(card["scores"]["distinctiveness"]),  # type: ignore[index]
                    base._normal(card["thesis"]),
                )
            )
            result: list[dict[str, object]] = []
            for index, card in enumerate(accepted[:3], start=1):
                result.append({**card, "id": f"thesis-{index}"})
            return result

        feedback = {
            "cycle": cycle,
            "required_total": base.MIN_TOTAL,
            "required_simplicity": base.MIN_SIMPLICITY,
            "accepted_so_far": [
                {
                    "thesis": card["thesis"],
                    "conversation_surface": card["conversation_surface"],
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
                for card in combined
                if card not in cycle_accepted
            ],
            "required_next_action": (
                f"Keep already-qualified theses fixed conceptually and create new, materially distinct theses until three total clear {base.MIN_TOTAL}/25 with simplicity >= {base.MIN_SIMPLICITY}/5."
            ),
        }

    raise workflow.WorkflowError(
        f"Only {len(accepted)} thesis/theses cleared the authority bar after {base.MAX_CYCLES} cycle(s); three are required before drafting."
    )
