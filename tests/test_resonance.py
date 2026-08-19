from __future__ import annotations

import unittest

from authority_os import resonance


class ResonanceThresholdTests(unittest.TestCase):
    def test_selector_requires_recognition_and_tension(self):
        scores = {
            "recognition": 3,
            "tension": 5,
            "payoff": 5,
            "proof": 5,
            "only_us": 5,
        }
        self.assertFalse(resonance.selector_passes(scores, supports_locked_thesis=True))

    def test_selector_can_pass_without_numeric_specificity(self):
        scores = {
            "recognition": 5,
            "tension": 5,
            "payoff": 4,
            "proof": 4,
            "only_us": 4,
        }
        self.assertTrue(resonance.selector_passes(scores, supports_locked_thesis=True))

    def test_post_gate_cannot_average_away_comprehension(self):
        scores = {
            "stop_power": 5,
            "five_second_comprehension": 3,
            "payoff_distance": 5,
            "shareability": 5,
            "proof_proximity": 5,
        }
        self.assertFalse(resonance.post_passes(scores))

    def test_post_gate_passes_balanced_resonance(self):
        scores = {
            "stop_power": 4,
            "five_second_comprehension": 5,
            "payoff_distance": 4,
            "shareability": 4,
            "proof_proximity": 4,
        }
        self.assertTrue(resonance.post_passes(scores))


class ResonanceProjectionTests(unittest.TestCase):
    def test_enrich_day_moves_packaging_and_proof_before_writer(self):
        day = {
            "dominant_take": "Original interpretation",
            "missing_angle": "Original gap",
            "artifact_policy": "Use an artifact only when useful",
        }
        selector = {
            "status": "PASS",
            "two_line_packaging": "The agent completed every task.\nIt had also changed the goal.",
            "what_happened": "The agent changed the goal before declaring completion.",
            "why_interesting": "Completion and outcome integrity diverged.",
            "proof_type": "TERMINAL_RUN",
            "proof_instruction": "Show the real trace where the goal digest changes.",
        }
        enriched = resonance.enrich_day(day, selector)
        self.assertIn("FIVE-SECOND PACKAGING", enriched["dominant_take"])
        self.assertIn("The agent completed every task.", enriched["dominant_take"])
        self.assertIn("SELECTED EVENT", enriched["missing_angle"])
        self.assertIn("PROOF PLAN DECIDED BEFORE DRAFTING", enriched["artifact_policy"])
        self.assertIn("TERMINAL_RUN", enriched["artifact_policy"])


if __name__ == "__main__":
    unittest.main()
