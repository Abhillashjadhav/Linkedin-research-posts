from __future__ import annotations

import unittest

from authority_os import resonance


class ResonanceThresholdTests(unittest.TestCase):
    def test_selector_requires_recognition_and_situation_specificity(self):
        scores = {
            "recognition": 3,
            "attention_trigger": 5,
            "situation_specificity": 5,
            "proof_value": 5,
            "payoff": 5,
        }
        self.assertFalse(resonance.selector_passes(scores, supports_locked_thesis=True))

        scores["recognition"] = 5
        scores["situation_specificity"] = 3
        self.assertFalse(resonance.selector_passes(scores, supports_locked_thesis=True))

    def test_selector_does_not_require_shock_or_numeric_specificity(self):
        scores = {
            "recognition": 5,
            "attention_trigger": 3,
            "situation_specificity": 4,
            "proof_value": 4,
            "payoff": 4,
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

    def test_post_gate_hard_blocks_missing_feed_value(self):
        scores = {
            "stop_power": 5,
            "five_second_comprehension": 5,
            "payoff_distance": 4,
            "shareability": 4,
            "proof_proximity": 4,
        }
        self.assertFalse(resonance.post_passes(scores, feed_value=False))
        self.assertFalse(resonance.post_passes(scores, value_before_ask=False))
        self.assertTrue(
            resonance.post_passes(
                scores,
                feed_value=True,
                value_before_ask=True,
            )
        )


class ResonanceProjectionTests(unittest.TestCase):
    def test_enrich_day_moves_topic_value_packaging_and_proof_before_writer(self):
        day = {
            "dominant_take": "Original interpretation",
            "missing_angle": "Original gap",
            "artifact_policy": "Use an artifact only when useful",
        }
        topic_result = {
            "status": "PASS",
            "situation": "The agent completed every task after changing the goal.",
            "reader_value_type": "DECISION_CHANGE",
            "reader_value": "Completion cannot be accepted without goal integrity.",
            "gravity": "HIGH",
            "priority": "FLAGSHIP",
            "authority_add": "Turn the failure into a release rule.",
        }
        selector = {
            "status": "PASS",
            "two_line_packaging": "The agent completed every task.\nIt had also changed the goal.",
            "what_happened": "The agent changed the goal before declaring completion.",
            "why_interesting": "Completion and outcome integrity diverged.",
            "proof_type": "TERMINAL_RUN",
            "proof_instruction": "Show the real trace where the goal digest changes.",
            "topic_value": topic_result,
        }
        enriched = resonance.enrich_day(day, selector)
        self.assertIn("TOPIC VALUE SELECTED BEFORE WRITING", enriched["dominant_take"])
        self.assertIn("DECISION_CHANGE", enriched["dominant_take"])
        self.assertIn("GRAVITY: HIGH", enriched["dominant_take"])
        self.assertIn("The agent completed every task.", enriched["dominant_take"])
        self.assertIn("SELECTED SITUATION", enriched["missing_angle"])
        self.assertIn("situation first, insight second", enriched["missing_angle"])
        self.assertIn("PROOF PLAN DECIDED BEFORE DRAFTING", enriched["artifact_policy"])
        self.assertIn("FEED VALUE RULE", enriched["artifact_policy"])


if __name__ == "__main__":
    unittest.main()
