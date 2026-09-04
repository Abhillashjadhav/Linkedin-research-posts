from __future__ import annotations

import unittest
from unittest.mock import Mock

from authority_os import resonance


def selected_topic() -> dict[str, object]:
    return {
        "id": "topic-1",
        "status": "PASS",
        "situation": "The release gate refused to decide before the eval ran.",
    }


def day() -> dict[str, object]:
    return {
        "thesis": "No eval run should mean no release verdict.",
        "target_reader": "Senior AI product leaders",
        "reader_problem": "Release decisions can outrun evidence.",
        "product_decision": "Require an executed eval before a release verdict.",
        "artifact_policy": "Use the supplied source.",
        "evidence": [{"id": "source-1", "claim": "The eval did not run."}],
    }


def selector_payload(
    *,
    status: str,
    scores: dict[str, int] | None = None,
) -> dict[str, object]:
    return {
        "selected_candidate_id": "topic-1",
        "two_line_packaging": "The eval had not run.\nThe gate refused a verdict.",
        "what_happened": "The release gate withheld its verdict.",
        "why_interesting": "Missing evidence could not become false confidence.",
        "supports_locked_thesis": True,
        "proof_type": "EVIDENCE_SOURCE",
        "proof_available": True,
        "proof_instruction": "Show the supplied release-gate evidence.",
        "scores": scores
        or {
            "recognition": 5,
            "attention_trigger": 3,
            "situation_specificity": 4,
            "proof_value": 4,
            "payoff": 4,
        },
        "status": status,
        "diagnosis": "The model supplied a status independently of its scores.",
    }


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

    def test_status_conflict_reports_both_decisions_and_every_score(self):
        invoker = Mock(return_value=selector_payload(status="BLOCKED"))

        with self.assertRaises(resonance.SelectorStatusConflict) as raised:
            resonance.invoke_selector(day(), selected_topic(), invoker=invoker)

        message = str(raised.exception)
        self.assertIn("model_status=BLOCKED", message)
        self.assertIn("computed_status=PASS", message)
        self.assertIn("total=20/25", message)
        self.assertIn("recognition=5", message)

    def test_human_guidance_retries_once_and_python_owns_final_status(self):
        invoker = Mock(
            side_effect=[
                selector_payload(status="BLOCKED"),
                selector_payload(status="BLOCKED"),
            ]
        )
        provider = Mock(
            return_value=(
                "Make the authority judgment explicit: a release process must be "
                "unable to manufacture a verdict when the eval did not run."
            )
        )

        result = resonance.invoke_selector(
            day(),
            selected_topic(),
            invoker=invoker,
            human_guidance_provider=provider,
        )

        self.assertEqual(invoker.call_count, 2)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["model_status"], "BLOCKED")
        self.assertIs(result["status_normalized"], True)
        self.assertIs(result["human_guidance_applied"], True)
        second_task = invoker.call_args_list[1].args[3]
        self.assertIn("HUMAN_AUTHORITY_GUIDANCE", second_task)
        self.assertIn("unable to manufacture a verdict", second_task)

    def test_human_guidance_cannot_turn_failing_scores_into_a_pass(self):
        failing = {
            "recognition": 3,
            "attention_trigger": 5,
            "situation_specificity": 5,
            "proof_value": 5,
            "payoff": 5,
        }
        invoker = Mock(
            side_effect=[
                selector_payload(status="PASS", scores=failing),
                selector_payload(status="PASS", scores=failing),
            ]
        )

        result = resonance.invoke_selector(
            day(),
            selected_topic(),
            invoker=invoker,
            human_guidance_provider=Mock(return_value="Preserve the release decision."),
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["model_status"], "PASS")
        self.assertIs(result["human_guidance_applied"], True)


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
