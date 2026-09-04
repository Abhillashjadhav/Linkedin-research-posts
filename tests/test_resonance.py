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
    scores: dict[str, int] | None = None,
    model_status: str | None = None,
    narrowed: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
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
        "diagnosis": "The supplied packaging follows from the evidence.",
    }
    if model_status is not None:
        payload["status"] = model_status
    if narrowed:
        payload["evidence_bounded_thesis"] = (
            "Simultaneous-loss tests reveal whether a release gate handles overlapping disruption."
        )
        payload["evidence_bounded_product_decision"] = (
            "Require a simultaneous-loss test before release."
        )
    return payload


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

    def test_python_is_the_only_selector_status_owner(self):
        invoker = Mock(return_value=selector_payload(model_status="BLOCKED"))

        result = resonance.invoke_selector(day(), selected_topic(), invoker=invoker)

        self.assertEqual(invoker.call_count, 1)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["claim_support"], "SUPPORTED")
        self.assertEqual(result["status_owner"], "python-deterministic-selector-v1")
        self.assertEqual(result["shortfalls"], [])
        self.assertNotIn("status", resonance.SELECTOR_SCHEMA["properties"])
        self.assertNotIn("status", resonance.SELECTOR_SCHEMA["required"])

    def test_selector_prompt_supports_broad_faithful_packaging(self):
        invoker = Mock(return_value=selector_payload())

        resonance.invoke_selector(day(), selected_topic(), invoker=invoker)

        task_prompt = invoker.call_args.args[3].casefold()
        self.assertIn("supported abstraction", task_prompt)
        self.assertIn("key failure modes", task_prompt)
        self.assertIn("major, production, or customer-impacting failures require evidence", task_prompt)

    def test_model_pass_cannot_turn_failing_scores_into_a_pass(self):
        failing = {
            "recognition": 3,
            "attention_trigger": 5,
            "situation_specificity": 5,
            "proof_value": 5,
            "payoff": 5,
        }
        invoker = Mock(return_value=selector_payload(scores=failing, model_status="PASS"))

        result = resonance.invoke_selector(day(), selected_topic(), invoker=invoker)

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["claim_support"], "SUPPORTED")
        self.assertEqual(
            result["shortfalls"],
            ["recognition=3/5 below 4/5 by 1"],
        )
        self.assertEqual(
            resonance.selector_failure_summary(result),
            "recognition=3/5 below 4/5 by 1",
        )

    def test_narrowing_uses_bounded_schema_without_a_proof_score_gate(self):
        invoker = Mock(return_value=selector_payload(narrowed=True))

        result = resonance.invoke_selector(
            day(),
            selected_topic(),
            narrow_to_evidence=True,
            invoker=invoker,
        )

        schema = invoker.call_args.args[4]
        prompt = invoker.call_args.args[3]
        self.assertIn("NARROW_TO_EVIDENCE", prompt)
        self.assertIn("evidence_bounded_thesis", schema["required"])
        self.assertIn("evidence_bounded_product_decision", schema["required"])
        self.assertTrue(result["narrowed_to_evidence"])
        self.assertEqual(result["original_locked_thesis"], day()["thesis"])
        self.assertEqual(result["status"], "PASS")
        self.assertNotIn("proof_value", resonance.SELECTOR_FLOORS)

    def test_proof_value_score_does_not_duplicate_the_claim_support_decision(self):
        failing = dict(selector_payload(narrowed=True))
        scores = dict(failing["scores"])
        scores["proof_value"] = 3
        failing["scores"] = scores

        result = resonance.invoke_selector(
            day(),
            selected_topic(),
            narrow_to_evidence=True,
            invoker=Mock(return_value=failing),
        )

        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["shortfalls"], [])

    def test_unsupported_claim_names_the_two_recovery_choices(self):
        unsupported = selector_payload()
        unsupported["supports_locked_thesis"] = False

        result = resonance.invoke_selector(
            day(),
            selected_topic(),
            invoker=Mock(return_value=unsupported),
        )

        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["claim_support"], "UNSUPPORTED")
        self.assertEqual(
            result["shortfalls"],
            ["claim_support=UNSUPPORTED; choose NARROW or MORE EVIDENCE"],
        )

    def test_selected_topic_is_reused_without_an_upstream_scorecard(self):
        selected = resonance.selected_topic_value_from_day(day())

        self.assertEqual(selected["id"], "selected-thesis")
        self.assertEqual(selected["status"], "PASS")
        self.assertEqual(selected["priority"], "NOT_REEVALUATED")


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

    def test_enrich_day_replaces_strategy_fields_only_when_narrowing_is_explicit(self):
        original = day()
        selector = {
            **selector_payload(narrowed=True),
            "status": "PASS",
            "narrowed_to_evidence": True,
            "topic_value": selected_topic(),
        }

        enriched = resonance.enrich_day(original, selector)

        self.assertEqual(enriched["thesis"], selector["evidence_bounded_thesis"])
        self.assertEqual(
            enriched["product_decision"],
            selector["evidence_bounded_product_decision"],
        )
        self.assertEqual(enriched["evidence"], original["evidence"])


if __name__ == "__main__":
    unittest.main()
