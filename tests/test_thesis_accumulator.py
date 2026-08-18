"""Tests for retaining independently qualifying theses across discovery cycles."""

from __future__ import annotations

import unittest

from authority_os import daily_cli, thesis_accumulator, workflow


class ThesisAccumulatorTests(unittest.TestCase):
    def _card(self, thesis_id: str, label: str) -> dict[str, object]:
        return {
            "id": thesis_id,
            "signal_ids": ["signal-1"],
            "topic": f"Topic {label}",
            "thesis": f"Thesis {label}",
            "why_now": "Current evidence",
            "reader_problem": "Reader problem",
            "product_decision": "Product decision",
            "proof_id": "proof-repo",
            "remembered_for": "Operator judgment",
            "plain_language_summary": f"Summary {label}",
            "conversation_surface": f"Trade-off {label}",
        }

    def _score(self, thesis_id: str, total: int, simplicity: int = 5) -> dict[str, object]:
        values = {
            "audience_fit": 5,
            "distinctiveness": 5,
            "decision_strength": 5,
            "proof_fit": 5,
            "simplicity": simplicity,
        }
        while sum(values.values()) > total:
            for axis in ("proof_fit", "decision_strength", "distinctiveness", "audience_fit"):
                if values[axis] > 1 and sum(values.values()) > total:
                    values[axis] -= 1
        return {"thesis_id": thesis_id, **values, "total": sum(values.values())}

    def test_two_plus_one_qualifiers_across_cycles_succeed(self) -> None:
        cycles = [
            [self._card("thesis-1", "A"), self._card("thesis-2", "B"), self._card("thesis-3", "C")],
            [self._card("thesis-1", "D"), self._card("thesis-2", "E"), self._card("thesis-3", "F")],
        ]
        score_sets = [
            [self._score("thesis-1", 25), self._score("thesis-2", 24), self._score("thesis-3", 20)],
            [self._score("thesis-1", 23), self._score("thesis-2", 20), self._score("thesis-3", 19)],
        ]

        def generator(profile, signals, feedback):
            del profile, signals, feedback
            return cycles.pop(0)

        def critic(cards, profile, signals):
            del cards, profile, signals
            return score_sets.pop(0)

        result = thesis_accumulator.search_theses({}, [], generator=generator, critic=critic)
        self.assertEqual(len(result), 3)
        self.assertEqual([card["id"] for card in result], ["thesis-1", "thesis-2", "thesis-3"])
        self.assertTrue(all(int(card["total"]) >= daily_cli.MIN_TOTAL for card in result))
        self.assertTrue(all(int(card["scores"]["simplicity"]) >= daily_cli.MIN_SIMPLICITY for card in result))
        self.assertNotIn("Thesis C", [card["thesis"] for card in result])

    def test_fewer_than_three_qualifiers_still_fail_closed(self) -> None:
        counter = 0

        def generator(profile, signals, feedback):
            nonlocal counter
            del profile, signals, feedback
            counter += 1
            return [
                self._card("thesis-1", f"A{counter}"),
                self._card("thesis-2", f"B{counter}"),
                self._card("thesis-3", f"C{counter}"),
            ]

        def critic(cards, profile, signals):
            del profile, signals
            return [self._score(str(card["id"]), 20) for card in cards]

        with self.assertRaisesRegex(workflow.WorkflowError, "Only 0 thesis/theses"):
            thesis_accumulator.search_theses({}, [], generator=generator, critic=critic)

    def test_reused_thesis_from_previous_cycle_fails_closed(self) -> None:
        first = [self._card("thesis-1", "A"), self._card("thesis-2", "B"), self._card("thesis-3", "C")]
        second = [self._card("thesis-1", "A"), self._card("thesis-2", "D"), self._card("thesis-3", "E")]
        cycles = [first, second]

        def generator(profile, signals, feedback):
            del profile, signals, feedback
            return cycles.pop(0)

        def critic(cards, profile, signals):
            del profile, signals
            return [self._score(str(card["id"]), 20) for card in cards]

        with self.assertRaisesRegex(workflow.WorkflowError, "reused a thesis"):
            thesis_accumulator.search_theses({}, [], generator=generator, critic=critic)


if __name__ == "__main__":
    unittest.main()
