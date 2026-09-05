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
    def test_blocked_selector_is_reported_as_advisory_in_final_summary(self) -> None:
        import io
        from contextlib import redirect_stdout

        def draft(_args):
            integrated_cli._active_single_topic_value = topic_result()
            integrated_cli._active_single_selector = {**selector(), "status": "BLOCKED"}
            return 0

        output = io.StringIO()
        with patch.object(integrated_cli, "_original_command_draft", draft), redirect_stdout(output):
            result = integrated_cli._command_draft(SimpleNamespace(allow_model_egress=True))
        self.assertEqual(result, 0)
        self.assertIn("Resonance Selector: BLOCKED", output.getvalue())
        self.assertIn("; advisory.", output.getvalue())
        self.assertNotIn("Resonance Selector: PASS", output.getvalue())

    def test_resonance_shortfall_does_not_block_writer(self) -> None:
        blocked = {
            **selector(),
            "status": "BLOCKED",
            "supports_locked_thesis": True,
            "scores": {
                "recognition": 3,
                "attention_trigger": 5,
                "situation_specificity": 5,
                "proof_value": 5,
                "payoff": 5,
            },
        }
        with (
            patch.object(
                integrated_cli.resonance,
                "invoke_selector",
                return_value=blocked,
            ),
        ):
            with integrated_cli._single_topic_selection_prompt():
                prompt = workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={
                        "provenance": "reconstructed-style-guidance",
                        "voice": "x",
                    },
                    proof=None,
                )
                self.assertTrue(prompt)

    def test_live_selection_uses_one_model_call_and_python_status(self) -> None:
        raw_selector = {
            "selected_candidate_id": "selected-thesis",
            "two_line_packaging": (
                "The eval had not run.\nThe release gate refused to give a verdict."
            ),
            "what_happened": "The gate withheld a release verdict until evidence existed.",
            "why_interesting": "Missing evidence could not become false confidence.",
            "supports_locked_thesis": True,
            "proof_type": "EVIDENCE_SOURCE",
            "proof_available": True,
            "proof_instruction": "Show the supplied release-gate evidence.",
            "scores": {
                "recognition": 5,
                "attention_trigger": 3,
                "situation_specificity": 4,
                "proof_value": 4,
                "payoff": 4,
            },
            "diagnosis": "The supplied packaging follows from the evidence.",
        }
        observed_briefs: list[dict[str, object]] = []

        def original_writer_prompt(*args: object, **kwargs: object) -> str:
            supplied = kwargs["brief"]
            assert isinstance(supplied, dict)
            observed_briefs.append(supplied)
            return "writer prompt"

        with (
            patch.object(workflow, "build_writer_prompt", side_effect=original_writer_prompt),
            patch.object(
                integrated_cli.resonance,
                "invoke_structured",
                return_value=dict(raw_selector),
            ) as invoke,
            patch.object(integrated_cli.resonance, "_load_role", return_value="role"),
        ):
            with integrated_cli._single_topic_selection_prompt():
                rendered = workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={
                        "provenance": "reconstructed-style-guidance",
                        "voice": "x",
                    },
                    proof=None,
                )

        self.assertEqual(rendered, "writer prompt")
        self.assertEqual(invoke.call_count, 1)
        self.assertEqual(len(observed_briefs), 1)
        prompt = invoke.call_args.kwargs["task_prompt"]
        self.assertNotIn("HUMAN_AUTHORITY_GUIDANCE", prompt)

    def test_selection_is_injected_before_writer_and_cached_across_quality_cycles(self) -> None:
        calls: list[dict[str, object]] = []

        def original_writer_prompt(*args: object, **kwargs: object) -> str:
            supplied = kwargs["brief"]
            assert isinstance(supplied, dict)
            calls.append(supplied)
            return str(supplied["analysis"]["dominant_take"])

        with patch.object(workflow, "build_writer_prompt", side_effect=original_writer_prompt), patch.object(
            integrated_cli.resonance,
            "invoke_selector",
            return_value=selector(),
        ) as resonance_select:
            with integrated_cli._single_topic_selection_prompt():
                first = workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={"provenance": "reconstructed-style-guidance", "voice": "x"},
                    proof=None,
                )
                second = workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={"provenance": "reconstructed-style-guidance", "voice": "x"},
                    proof=None,
                )

        self.assertEqual(resonance_select.call_count, 1)
        self.assertIn("TOPIC VALUE SELECTED BEFORE WRITING", first)
        self.assertIn("NOT_REEVALUATED", first)
        self.assertEqual(first, second)
        self.assertEqual(len(calls), 2)

    def test_explicit_narrowing_replaces_writer_strategy_but_keeps_evidence(self) -> None:
        observed: list[tuple[dict[str, object], list[dict[str, object]]]] = []
        narrowed_selector = {
            **selector(),
            "narrowed_to_evidence": True,
            "evidence_bounded_thesis": (
                "Simultaneous-loss tests show whether the release gate handles overlapping disruption."
            ),
            "evidence_bounded_product_decision": (
                "Require a simultaneous-loss test before release."
            ),
        }

        def original_writer_prompt(*args: object, **kwargs: object) -> str:
            supplied_brief = kwargs["brief"]
            supplied_evidence = kwargs["evidence"]
            assert isinstance(supplied_brief, dict)
            assert isinstance(supplied_evidence, list)
            observed.append((supplied_brief, supplied_evidence))
            return "writer prompt"

        with (
            patch.object(workflow, "build_writer_prompt", side_effect=original_writer_prompt),
            patch.object(
                integrated_cli.resonance,
                "invoke_selector",
                return_value=narrowed_selector,
            ) as resonance_select,
        ):
            with integrated_cli._single_topic_selection_prompt(narrow_to_evidence=True):
                workflow.build_writer_prompt(
                    brief=brief(),
                    evidence=evidence(),
                    voice_guidance={
                        "provenance": "reconstructed-style-guidance",
                        "voice": "x",
                    },
                    proof=None,
                )

        self.assertEqual(
            resonance_select.call_args.kwargs["narrow_to_evidence"],
            True,
        )
        supplied_brief, supplied_evidence = observed[0]
        self.assertEqual(
            supplied_brief["core_hypothesis"],
            narrowed_selector["evidence_bounded_thesis"],
        )
        self.assertEqual(
            supplied_brief["product_decision"],
            narrowed_selector["evidence_bounded_product_decision"],
        )
        self.assertEqual(supplied_evidence, evidence())

    def test_single_topic_craft_candidate_keeps_feed_value_as_advisory(self) -> None:
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
                accepted = integrated_cli._qualifying_candidates(
                    object(),
                    rejected_openings=set(),
                    package_requested=False,
                    fixture_mode=True,
                )
            self.assertEqual(accepted, (candidate,))
            self.assertEqual(
                integrated_cli._active_resonance_diagnostics["candidate-1"]["feed_value"],
                False,
            )
        finally:
            integrated_cli._active_single_selector = None
            integrated_cli._active_resonance_diagnostics = {}


if __name__ == "__main__":
    unittest.main()
