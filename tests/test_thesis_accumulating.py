"""Regression tests for accumulating thesis selection."""

from __future__ import annotations

import unittest

from authority_os import thesis_accumulating, workflow


PROFILE: dict[str, object] = {
    "target_audience": "AI product leaders",
    "authority_goal": "Reliable enterprise AI",
    "proof_inventory": [],
    "avoid_topics": [],
    "recent_theses": [],
}
SIGNALS: list[dict[str, object]] = []


def card(label: str, slot: int) -> dict[str, object]:
    return {
        "id": f"thesis-{slot}",
        "signal_ids": ["signal-1"],
        "topic": f"Topic {label}",
        "thesis": f"Thesis {label}",
        "why_now": "Now",
        "reader_problem": "Problem",
        "product_decision": "Decision",
        "proof_id": "proof-1",
        "remembered_for": "Authority",
        "plain_language_summary": "Summary",
        "conversation_surface": "A concrete implementation trade-off",
        "recommended_spine": "Incident → Mechanism → Decision → Artifact",
        "spine_fit_reason": "The evidence exposes a concrete decision.",
    }


def scorecard(thesis_id: str, total: int, simplicity: int = 5) -> dict[str, object]:
    # Keep total controllable while satisfying the five-axis shape used by the selector.
    audience = 5
    distinctive = 5
    decision = 5
    proof = max(1, total - audience - distinctive - decision - simplicity)
    return {
        "thesis_id": thesis_id,
        "audience_fit": audience,
        "distinctiveness": distinctive,
        "decision_strength": decision,
        "proof_fit": proof,
        "simplicity": simplicity,
        "total": total,
    }


class ThesisAccumulatingTests(unittest.TestCase):
    def test_collects_individual_passes_across_cycles(self) -> None:
        cycles = [
            [card("A", 1), card("B", 2), card("C", 3)],
            [card("D", 1), card("E", 2), card("F", 3)],
        ]
        scores = [
            [scorecard("thesis-1", 24), scorecard("thesis-2", 22), scorecard("thesis-3", 21)],
            [scorecard("thesis-1", 25), scorecard("thesis-2", 24), scorecard("thesis-3", 20)],
        ]
        calls = {"generator": 0, "critic": 0}

        def generator(profile, signals, feedback):
            value = cycles[calls["generator"]]
            calls["generator"] += 1
            return value

        def critic(cards, profile, signals):
            value = scores[calls["critic"]]
            calls["critic"] += 1
            return value

        result = thesis_accumulating.search_theses(
            PROFILE,
            SIGNALS,
            generator=generator,
            critic=critic,
        )

        self.assertEqual([item["thesis"] for item in result], ["Thesis D", "Thesis A", "Thesis E"])
        self.assertEqual([item["id"] for item in result], ["thesis-1", "thesis-2", "thesis-3"])
        self.assertEqual(calls["generator"], 2)

    def test_reused_thesis_fails_closed(self) -> None:
        cycles = [
            [card("A", 1), card("B", 2), card("C", 3)],
            [card("A", 1), card("D", 2), card("E", 3)],
        ]
        calls = {"generator": 0}

        def generator(profile, signals, feedback):
            value = cycles[calls["generator"]]
            calls["generator"] += 1
            return value

        def critic(cards, profile, signals):
            return [scorecard(str(item["id"]), 20) for item in cards]

        with self.assertRaisesRegex(workflow.WorkflowError, "reused"):
            thesis_accumulating.search_theses(
                PROFILE,
                SIGNALS,
                generator=generator,
                critic=critic,
            )

    def test_fewer_than_three_passes_after_bound_fails(self) -> None:
        counter = {"cycle": 0}

        def generator(profile, signals, feedback):
            counter["cycle"] += 1
            prefix = chr(64 + counter["cycle"])
            return [card(f"{prefix}{slot}", slot) for slot in range(1, 4)]

        def critic(cards, profile, signals):
            # Only the first card of cycle one clears; all others remain below threshold.
            return [
                scorecard(str(item["id"]), 24 if counter["cycle"] == 1 and index == 0 else 20)
                for index, item in enumerate(cards)
            ]

        with self.assertRaisesRegex(workflow.WorkflowError, "Fewer than three distinct theses"):
            thesis_accumulating.search_theses(
                PROFILE,
                SIGNALS,
                generator=generator,
                critic=critic,
            )


if __name__ == "__main__":
    unittest.main()
