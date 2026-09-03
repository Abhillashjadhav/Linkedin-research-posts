from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import integrated_cli, workflow


def brief() -> dict[str, object]:
    return {
        "goal": "authority",
        "topic_slug": "agent-evaluation",
        "goal_purpose": "Demonstrate differentiated GenAI product judgement.",
        "target_reader": "Senior AI product leaders",
        "reader_problem": "Release decisions can outrun evidence.",
        "core_hypothesis": "No eval run should mean no release verdict.",
        "product_decision": "Require an executed eval before SHIP or HOLD.",
        "authority_statement": "Connect agent mechanics to product decisions.",
        "strategy_input_origin": "explicit",
        "narrative_route": ["incident-or-problem", "mechanism", "decision"],
        "analysis": {
            "why_now": "AI release velocity is increasing.",
            "dominant_take": "Teams optimize the model before the release contract.",
            "missing_angle": "The release gate should be unable to guess.",
        },
    }


def evidence() -> list[dict[str, object]]:
    return [
        {
            "id": "source-1",
            "title": "Agent evaluation release gate",
            "claim": "A release gate can require completed evaluation evidence before a verdict.",
            "source": "https://example.com/eval",
            "source_quality": "primary",
            "body_read": True,
        }
    ]


def topic_result() -> dict[str, object]:
    return {
        "id": "topic-1",
        "status": "PASS",
        "situation": "The release gate refuses to decide before the eval runs.",
        "reader_value_type": "DECISION_CHANGE",
        "reader_value": "A release decision gets an enforceable evidence prerequisite.",
        "gravity": "HIGH",
        "priority": "FLAGSHIP",
        "authority_add": "Turn the behavior into a production release rule.",
        "total": 25,
    }


def selector() -> dict[str, object]:
    return {
        "selected_candidate_id": "topic-1",
        "status": "PASS",
        "two_line_packaging": "The eval had not run.\nThe release gate refused to give a verdict.",
        "what_happened": "The gate withheld a release verdict until evidence existed.",
        "why_interesting": "The system cannot manufacture confidence from missing evidence.",
        "proof_type": "EVIDENCE_SOURCE",
        "proof_instruction": "Show the release-gate behavior from the supplied evidence.",
        "total": 23,
        "topic_value": topic_result(),
    }


class SingleTopicSelectionTests(unittest.TestCase):
    def test_selection_is_injected_before_writer_and_cached_across_quality_cycles(self) -> None:
        calls: list[dict[str, object]] = []

        def original_writer_prompt(*args: object, **kwargs: object) -> str:
            supplied = kwargs["brief"]
            assert isinstance(supplied, dict)
            calls.append(supplied)
            return str(supplied["analysis"]["dominant_take"])

        with patch.object(workflow, "build_writer_prompt", side_effect=original_writer_prompt), patch.object(
            integrated_cli.topic_value,
            "invoke_campaign_selector",
            return_value=topic_result(),
        ) as topic_select, patch.object(
            integrated_cli.resonance,
            "invoke_selector",
            return_value=selector(),
        ) as resonance_select:
            with integrated_cli._single_topic_selection_prompt():
                first = workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={"provenance": "measured-performance-anchors", "voice": "x"},
                    proof=None,
                )
                second = workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={"provenance": "measured-performance-anchors", "voice": "x"},
                    proof=None,
                )

        self.assertEqual(topic_select.call_count, 1)
        self.assertEqual(resonance_select.call_count, 1)
        self.assertIn("TOPIC VALUE SELECTED BEFORE WRITING", first)
        self.assertIn("FLAGSHIP", first)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)

    def test_single_topic_craft_candidate_is_rejected_when_feed_value_fails(self) -> None:
        candidate = SimpleNamespace(candidate_id="candidate-1", text="A polished post")
        integrated_cli._active_single_selector = selector()
        integrated_cli._active_resonance_diagnostics = {}
        try:
            with patch.object(
                integrated_cli,
                "_original_qualifying",
                return_value=(candidate,),
            ), patch.object(
                integrated_cli.anti_slop,
                "passes",
                return_value=True,
            ), patch.object(
                integrated_cli.resonance,
                "invoke_post_critic",
                return_value={
                    "status": "BLOCKED",
                    "total": 23,
                    "feed_value": False,
                    "value_before_ask": True,
                    "diagnosis": "The useful part lives behind a click.",
                },
            ):
                accepted = integrated_cli._qualifying_candidates(object())
            self.assertEqual(accepted, ())
            self.assertEqual(
                integrated_cli._active_resonance_diagnostics["candidate-1"]["feed_value"],
                False,
            )
        finally:
            integrated_cli._active_single_selector = None
            integrated_cli._active_resonance_diagnostics = {}


if __name__ == "__main__":
    unittest.main()
