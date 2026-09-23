"""Correction context reaches each existing prompt without new model calls."""

import os
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import correction_context, quality_cli, single_topic_codex, workflow
_REAL_RECORD = correction_context._record


class CorrectionPromptIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {"LINKEDIN_OS_RUN_ID": "fixture-run"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root_patch = patch.object(workflow, "REPO_ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.record = patch.object(correction_context, "_record")
        self.events = self.record.start()
        self.addCleanup(self.record.stop)
        self.store = correction_context._store_type()(self.root)
        self.rule = self.store.add("Do not call the reported test count a correctness measure.",
                                   source_ref="fixture user feedback", source_kind="user", workflow="linkedin-os")
        self.store.approve(self.rule, reviewed_by="fixture reviewer")
        self.store.add("PENDING_TEXT_SENTINEL", source_ref="fixture machine proposal")
        self.guidance = {"provenance": "reconstructed-style-guidance", "voice_guide": "Plain wording."}
        self.brief = {"goal": "authority", **{key: "fixture" for key in (
            "topic_slug", "goal_purpose", "target_reader", "reader_problem", "core_hypothesis",
            "product_decision", "authority_statement", "strategy_input_origin")},
            "narrative_route": ["fixture"], "analysis": {key: "fixture" for key in ("why_now", "dominant_take", "missing_angle")}}
        self.evidence = [{"id": "claim-1", "title": "Fixture", "claim": "The test count is 102.",
                          "source": "https://example.com/fixture", "source_quality": "primary", "body_read": True}]
        self.candidate = {"id": "candidate-1", "angle": "fixture", "text": "The reported count is 102 tests.", "claim_ids": ["claim-1"]}

    def test_writer_critic_and_revision_share_reviewed_context(self):
        writer = workflow.build_writer_prompt(brief=self.brief, evidence=self.evidence, voice_guidance=self.guidance)
        self.store.revoke(self.rule, reviewed_by="fixture reviewer")
        critic = workflow.build_critic_prompt([self.candidate], self.brief, self.evidence, voice_guidance=self.guidance)
        revision = workflow._build_writer_revision_prompt(candidate=self.candidate, scorecard={axis: 4 for axis in workflow.CRITIC_AXES},
                                                         brief=self.brief, evidence=self.evidence, voice_guidance=self.guidance)
        for prompt in (writer, critic, revision):
            self.assertIn(self.rule, prompt)
            self.assertIn("Do not call the reported test count a correctness measure.", prompt)
            self.assertNotIn("PENDING_TEXT_SENTINEL", prompt)
            self.assertNotIn("fixture user feedback", prompt)
        self.assertEqual([event.args[0] for event in self.events.call_args_list], ["writer", "critic", "writer"])
        digests = {event.args[1]["correction_digest"] for event in self.events.call_args_list}
        self.assertEqual(len(digests), 1)
        self.assertIn("score-only schema", critic)

    def test_beacon_unavailable_does_not_remove_local_corrections(self):
        with patch.object(correction_context.importlib, "import_module", side_effect=ImportError), patch.object(correction_context, "_record", _REAL_RECORD):
            result = correction_context.append_approved_context("BASE", role="writer", project_root=self.root)
        self.assertIn(self.rule, result)
        self.assertTrue(result.startswith("BASE"))

    def test_egress_consent_still_checked_before_loading_or_invocation(self):
        with patch.object(correction_context, "append_approved_context") as context, patch.object(single_topic_codex.model_runtime, "invoke_structured") as invoke:
            with self.assertRaisesRegex(workflow.WorkflowError, "explicit consent"):
                single_topic_codex._invoke_writer_codex(brief=self.brief, evidence=self.evidence, allow_model_egress=False)
            context.assert_not_called()
            invoke.assert_not_called()

    def test_invalid_registry_is_visible_and_does_not_block_workflow(self):
        self.store.registry_path.write_text("invalid JSON")
        self.store.backup_path.write_text("invalid JSON")
        with patch.object(correction_context, "_WARNED", False), patch("sys.stderr") as stderr:
            result = correction_context.append_approved_context("BASE", role="writer", project_root=self.root)
        self.assertEqual(result, "BASE")
        # Legacy draft capture treats any stderr as failure; telemetry carries
        # the degraded status without turning this into a business failure.
        self.assertFalse(stderr.write.called)
        self.assertEqual(self.events.call_args.args[1]["correction_status"], "unavailable")

    def test_literal_violations_feed_existing_revision_and_next_writer(self):
        literal_rule = self.store.add("Do not assert perfect correctness from a test count.", source_ref="fixture", source_kind="user",
                                      workflow="linkedin-os", forbidden_literal="100% correct")
        self.store.approve(literal_rule, reviewed_by="fixture reviewer")
        candidate = {**self.candidate, "text": "These tests prove it is 100% correct."}
        critic = workflow.build_critic_prompt([candidate], self.brief, self.evidence, voice_guidance=self.guidance)
        report = self.store.read_checks("fixture-run")
        self.assertEqual(report["latest"][0]["violation_count"], 1)
        self.assertFalse(report["changes_workflow_acceptance"])
        self.assertIn("unresolved literal violations", critic)
        next_writer = workflow.build_writer_prompt(brief=self.brief, evidence=self.evidence, voice_guidance=self.guidance)
        revision = workflow._build_writer_revision_prompt(candidate=candidate, scorecard={axis: 4 for axis in workflow.CRITIC_AXES},
                                                         brief=self.brief, evidence=self.evidence, voice_guidance=self.guidance)
        self.assertIn("unresolved literal violations", next_writer)
        self.assertIn("unresolved literal violations", revision)
        corrected = {**candidate, "text": "The report lists 102 tests."}
        workflow.build_critic_prompt([corrected], self.brief, self.evidence, voice_guidance=self.guidance)
        latest = self.store.read_checks("fixture-run")["latest"][0]
        self.assertEqual(latest["violation_count"], 0)
        self.assertEqual(latest["not_evaluated_count"], 1)

    def test_passing_selected_candidate_repairs_only_violation_within_existing_budget(self):
        literal_rule = self.store.add("Avoid perfect correctness claims.", source_ref="fixture", source_kind="user",
                                      workflow="linkedin-os", forbidden_literal="100% correct")
        self.store.approve(literal_rule, reviewed_by="fixture reviewer")
        def attempt(text):
            candidate = quality_cli.CandidateResult("candidate-1", "fixture", text,
                {axis: 5 for axis in workflow.CRITIC_AXES}, 25, 25, "advance-to-gates", {}, True, ())
            # An unselected loser must not trigger repair when the selected one passes.
            loser = quality_cli.CandidateResult("candidate-2", "other", "100% correct", {}, 10, 10, "below-critic-bar", {}, False, ())
            return quality_cli.AttemptResult((candidate, loser), (), "READY_FOR_HUMAN_REVIEW", "candidate-1", ())
        for texts, expected_cycles, unresolved in ((["Supported wording."], 1, False),
                                                   (["100% correct", "Supported wording."], 2, False),
                                                   (["100% correct", "100% correct"], 2, True)):
            with self.subTest(texts=texts), patch.object(quality_cli, "MAX_QUALITY_CYCLES", 2), \
                 patch.object(quality_cli, "_run_attempt", side_effect=[attempt(text) for text in texts]) as run, \
                 patch.object(quality_cli, "_qualifying_candidates", side_effect=lambda value, **kwargs: (value.candidates[0],)), \
                 patch.object(quality_cli, "_quality_feedback", return_value={}), \
                 patch.object(quality_cli, "_render_success") as render, \
                 patch("builtins.print"):
                self.assertEqual(quality_cli.command_draft(SimpleNamespace(dry_run=False, package=False)), 0)
                self.assertEqual(run.call_count, expected_cycles)
                self.assertEqual(render.call_args.args[1][0].effective_total, 25)
                report = self.store.read_checks("fixture-run")
                self.assertEqual(report["repair"]["unresolved"], unresolved)
                if expected_cycles == 2:
                    self.assertTrue(run.call_args_list[1].args[1]["correction_repair"]["requested"])


if __name__ == "__main__":
    unittest.main()
