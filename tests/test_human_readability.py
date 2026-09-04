from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import human_readability, model_runtime, workflow


class HumanReadabilityContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = workflow.load_fixture()
        items = workflow.prepare_research_items(fixture["research_items"])
        analysis_items, _ = workflow.deduplicate_analysis_items(items, ())
        analysis = workflow.analyse_research(
            analysis_items,
            topic=str(fixture["topic"]),
            as_of=workflow.parse_published_at(str(fixture["as_of"])),
        )
        selected = analysis["pass_2"]["selected"]
        cls.brief = workflow.build_strategy_brief(
            selected,
            strategy_inputs=fixture["strategy_inputs"],
            strategy_input_origin="synthetic-fixture",
            goal="authority",
            output_format="text",
            week_slot=None,
            strong_current_signal=False,
        )
        cls.evidence = workflow.build_drafting_evidence(
            items,
            topic_slug=str(cls.brief["topic_slug"]),
        )
        cls.candidates = workflow.validate_draft_candidates(
            fixture["draft_candidates"]["authority"],
            brief=cls.brief,
            evidence=cls.evidence,
        )

    def test_task_freezes_problem_benefit_hook_and_simple_human_body_target(self) -> None:
        task = human_readability._task(  # type: ignore[attr-defined]
            self.candidates,
            self.brief,
            self.evidence,
            None,
        )
        self.assertIn("LINE 1 MUST pair", task)
        self.assertIn("concrete reader problem", task)
        self.assertIn("immediate benefit", task)
        self.assertIn("already-supplied public", task)
        self.assertIn("one primary human problem or decision", task)
        self.assertIn("Emotion must come from truthful consequence", task)
        self.assertIn("minimum technical mechanism", task)

    def test_live_editor_task_targets_human_voice_without_invented_experience(self) -> None:
        task = human_readability._task(  # type: ignore[attr-defined]
            self.candidates,
            self.brief,
            self.evidence,
            None,
        )
        self.assertIn("conversational product leader", task)
        self.assertIn("consultant producing a release memo", task)
        self.assertIn("question, conditional, proposed test, or recommendation", task)
        self.assertIn("never turn it into a fact or personal experience", task)

    def test_narrative_schema_disallows_drop_in_single_topic_pass(self) -> None:
        schema = human_readability._narrative_schema()  # type: ignore[attr-defined]
        result_item = schema["properties"]["results"]["items"]  # type: ignore[index]
        statuses = result_item["properties"]["status"]["enum"]  # type: ignore[index]
        self.assertEqual(statuses, ["EDITED", "UNCHANGED"])

    def test_edit_candidates_preserves_grounded_unchanged_set(self) -> None:
        payload = {
            "results": [
                {
                    "id": candidate["id"],
                    "status": "UNCHANGED",
                    "edited_text": candidate["text"],
                    "claim_ids": candidate["claim_ids"],
                    "diagnosis": "Already plain enough.",
                    "repeatable_sentence": "",
                }
                for candidate in self.candidates
            ]
        }
        edited = human_readability.edit_candidates(
            self.candidates,
            brief=self.brief,
            evidence=self.evidence,
            invoker=lambda *_args, **_kwargs: payload,
        )
        self.assertEqual(edited, self.candidates)

    def test_provider_failure_falls_back_to_grounded_writer_candidates(self) -> None:
        def failing_invoker(*_args, **_kwargs):
            raise workflow.WorkflowError("Single-topic Narrative Editor timed out.")

        edited = human_readability.edit_candidates(
            self.candidates,
            brief=self.brief,
            evidence=self.evidence,
            invoker=failing_invoker,
        )
        self.assertEqual(edited, self.candidates)

    def test_malformed_provider_envelope_falls_back_to_writer_candidates(self) -> None:
        edited = human_readability.edit_candidates(
            self.candidates,
            brief=self.brief,
            evidence=self.evidence,
            invoker=lambda *_args, **_kwargs: {"results": []},
        )
        self.assertEqual(edited, self.candidates)

    def test_claim_id_mutation_is_rejected_per_candidate_without_crashing_run(self) -> None:
        results = []
        for index, candidate in enumerate(self.candidates):
            claim_ids = list(candidate["claim_ids"])
            if index == 0:
                claim_ids = ["not-a-real-source"]
            results.append(
                {
                    "id": candidate["id"],
                    "status": "UNCHANGED",
                    "edited_text": candidate["text"],
                    "claim_ids": claim_ids,
                    "diagnosis": "Attempted mutation.",
                    "repeatable_sentence": "",
                }
            )

        edited = human_readability.edit_candidates(
            self.candidates,
            brief=self.brief,
            evidence=self.evidence,
            invoker=lambda *_args, **_kwargs: {"results": results},
        )
        self.assertEqual(edited[0], self.candidates[0])
        self.assertEqual(edited[1:], self.candidates[1:])

    def test_live_editor_invoker_uses_extended_bounded_timeout(self) -> None:
        observed: dict[str, object] = {}

        def fake_structured(**kwargs):
            observed.update(kwargs)
            return {"results": []}

        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "max")
        with patch.object(model_runtime, "invoke_structured", side_effect=fake_structured):
            result = human_readability._live_editor_invoker(  # type: ignore[attr-defined]
                "narrative_editor",
                config,
                "role",
                "task",
                {"type": "object"},
            )
        self.assertEqual(result, {"results": []})
        self.assertEqual(observed["timeout"], human_readability.EDITOR_TIMEOUT_SECONDS)
        self.assertGreater(human_readability.EDITOR_TIMEOUT_SECONDS, 180)
        self.assertEqual(observed["stage_label"], "Single-topic Narrative Editor")
        self.assertIs(observed["config"], config)
        self.assertIs(observed["web_search"], False)

    def test_run_critic_review_routes_narrative_output_before_critic(self) -> None:
        marker = [dict(candidate) for candidate in self.candidates]
        marker[0] = {**marker[0], "text": str(marker[0]["text"]).replace("The", "A", 1)}
        observed: dict[str, object] = {}

        def fake_edit(*_args, **_kwargs):
            return marker

        def fake_original(candidates, *_args, **_kwargs):
            observed["candidates"] = candidates
            return {"ok": True}

        with (
            patch.object(human_readability, "edit_candidates", side_effect=fake_edit),
            patch.object(
                human_readability,
                "_ORIGINAL_RUN_CRITIC_REVIEW",
                side_effect=fake_original,
            ),
        ):
            result = human_readability._run_critic_review(  # type: ignore[attr-defined]
                self.candidates,
                self.brief,
                self.evidence,
                lambda _items: [],
                lambda _candidate, _scorecard: {},
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(observed["candidates"], marker)

    def test_non_authority_goal_is_not_narrative_edited_here(self) -> None:
        other = dict(self.brief)
        other["goal"] = "reach"
        with patch.object(
            workflow,
            "validate_draft_candidates",
            return_value=[dict(candidate) for candidate in self.candidates],
        ):
            edited = human_readability.edit_candidates(
                self.candidates,
                brief=other,
                evidence=self.evidence,
                invoker=lambda *_args, **_kwargs: self.fail("invoker should not run"),
            )
        self.assertEqual(edited, self.candidates)


class HumanReadabilityAssetTests(unittest.TestCase):
    def test_v1_critic_anchors_require_relevant_problem_benefit_hook(self) -> None:
        root = Path(__file__).resolve().parents[1]
        rubric = json.loads((root / "config" / "critic-rubric-v1.json").read_text())
        axes = rubric["axes"]
        self.assertIn("Line 1 pairs", axes["hook_strength"]["4"])
        self.assertIn("target-reader problem", axes["hook_strength"]["4"])
        self.assertIn("immediate benefit", axes["hook_strength"]["4"])
        self.assertIn("recognizes the problem as relevant", axes["hook_strength"]["5"])
        self.assertIn("human or team consequence", axes["middle_escalation"]["4"])
        self.assertIn("technical-spec", axes["voice_fidelity"]["1"])
        self.assertIn("emotionally natural", axes["voice_fidelity"]["5"])

    def test_resonance_requires_immediate_human_payoff_not_technical_polish(self) -> None:
        root = Path(__file__).resolve().parents[1]
        role = (root / ".claude" / "agents" / "resonance_critic.md").read_text()
        self.assertIn("line 1 pair", role)
        self.assertIn("target-reader problem", role)
        self.assertIn("immediate benefit", role)
        self.assertIn("technically sophisticated", role)
        self.assertIn("truthful stakes", role)
        self.assertIn("without clicking", role)

    def test_narrative_editor_preserves_a_hook_but_simplifies_its_language(self) -> None:
        root = Path(__file__).resolve().parents[1]
        role = (root / ".claude" / "agents" / "narrative_editor.md").read_text()
        self.assertIn("strong problem-first hook structure", role)
        self.assertIn("Line 1 must pair", role)
        self.assertIn("immediate benefit", role)
        self.assertIn("compelling because it is relevant", role)
        self.assertIn("one primary human problem", role)
        self.assertIn("Translate every necessary technical mechanism", role)
        self.assertIn("conversational product leader", role)
        self.assertIn("consultant writing a", role)
        self.assertIn("Exact imitation of the author's speech is not required", role)

    def test_launcher_and_comparison_wire_only_live_v1(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "bin" / "linkedin-os").read_text()
        capture = (root / "scripts" / "compare_capture_runtime.py").read_text()
        self.assertEqual(launcher.count("human_readability.install()"), 1)
        self.assertIn('if args.label == "v1":', capture)
        self.assertEqual(capture.count("human_readability.install()"), 1)


if __name__ == "__main__":
    unittest.main()
