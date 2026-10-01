"""Delivery-first regression controls for unscored, grounded Writer drafts."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import __main__ as legacy_cli
from authority_os import best_effort, daily_spine_cli, integrated_cli, quality_cli, quality_optimizer, workflow
from authority_os.model_runtime import ModelTimeoutError


def gate_result(*, honesty="PASS", citation="PASS", proof="NOT_REQUIRED"):
    return [{
        "candidate_id": "candidate-1",
        "gates": {
            "honesty": {"status": honesty, "reason_codes": []},
            "citation": {"status": citation, "reason_codes": []},
            "proof": {"status": proof, "reason_codes": []},
            "relevance": {"status": "FAIL", "reason_codes": ["reader-problem-not-reflected"]},
            "authority_conversion": {"status": "FAIL", "reason_codes": []},
        },
        "passes_required_gates": False,
    }]


CANDIDATE = {
    "id": "candidate-1", "angle": "mechanism",
    "text": "A grounded post with a usable decision.", "claim_ids": ["evidence-1"],
}
EVIDENCE = [{"id": "evidence-1", "source": "https://example.com/research"}]


class DeliveryFirstTests(unittest.TestCase):
    def setUp(self):
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA)
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / "best-effort-post.md"
        self.env = patch.dict(os.environ, {best_effort.OUTPUT_ENV: str(self.output)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def checkpoint(self, *, gates=None):
        state = quality_optimizer.RepairState()
        with (
            patch.object(quality_optimizer, "_ACTIVE_STATE", state),
            patch.object(quality_optimizer, "_ACTIVE_COMMAND_DRAFT", True),
            patch.object(workflow, "evaluate_candidate_set_gates", return_value=gates or gate_result()),
        ):
            quality_optimizer._checkpoint_validated_writer(
                [CANDIDATE], brief={}, evidence=EVIDENCE, proof=None
            )
        return state

    def test_first_critic_failure_delivers_grounded_unscored_post(self):
        state = self.checkpoint()
        self.assertIsNotNone(state.early)
        self.assertEqual(best_effort.load_checkpoint().effective_total, None)
        def fail_once(_args):
            quality_optimizer._ACTIVE_STATE.early = state.early
            raise workflow.CriticEvaluationFailure("Critic malformed score envelope")
        out = io.StringIO()
        with (
            patch.object(quality_optimizer, "_ORIGINAL_COMMAND_DRAFT", side_effect=fail_once) as run,
            patch.object(best_effort.v1_completion, "_read_jsonl", return_value=[]),
            patch.object(best_effort.v1_completion, "record_decision"),
            redirect_stdout(out),
        ):
            self.assertEqual(quality_optimizer._command_draft(SimpleNamespace()), 0)
        self.assertEqual(run.call_count, 1)
        rendered = self.output.read_text()
        self.assertIn("Critic score: `not_evaluated`", rendered)
        self.assertIn(CANDIDATE["text"], rendered)
        self.assertIn("https://example.com/research", rendered)
        self.assertIn("NOT_EVALUATED", rendered)
        self.assertIn("publishing remains disabled", out.getvalue())

    def test_timeout_after_writer_uses_checkpoint(self):
        state = self.checkpoint()
        def timeout(_args):
            quality_optimizer._ACTIVE_STATE.early = state.early
            raise ModelTimeoutError("Critic timed out")
        with (
            patch.object(quality_optimizer, "_ORIGINAL_COMMAND_DRAFT", side_effect=timeout) as run,
            patch.object(best_effort.v1_completion, "_read_jsonl", return_value=[]),
            patch.object(best_effort.v1_completion, "record_decision"),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(quality_optimizer._command_draft(SimpleNamespace()), 0)
        self.assertEqual(run.call_count, 1)
        self.assertIn("not_evaluated", self.output.read_text())

    def test_unsupported_writer_has_no_eligible_checkpoint(self):
        state = self.checkpoint(gates=gate_result(honesty="FAIL"))
        self.assertIsNone(state.early)
        self.assertFalse(best_effort.checkpoint_path().exists())
        self.assertFalse(self.output.exists())

    def test_parent_deadline_recovers_only_validated_checkpoint(self):
        self.checkpoint()
        result = daily_spine_cli.DraftingRun(124, "TIME_BUDGET_EXCEEDED", "drafting.log", ())
        with (
            patch.object(best_effort.v1_completion, "_read_jsonl", return_value=[]),
            patch.object(best_effort.v1_completion, "record_decision") as record,
            redirect_stdout(io.StringIO()),
        ):
            recovered = daily_spine_cli.recover_timed_out_draft(Path(self.temp.name), result)
        self.assertEqual(recovered.returncode, 0)
        self.assertTrue(self.output.exists())
        self.assertIn("not_evaluated", self.output.read_text())
        self.assertTrue(any(call.args[0].get("contract") == "draft_delivery" for call in record.call_args_list))

    def test_missing_checkpoint_keeps_deadline_failure(self):
        result = daily_spine_cli.DraftingRun(124, "TIME_BUDGET_EXCEEDED", "drafting.log", ())
        self.assertIs(daily_spine_cli.recover_timed_out_draft(Path(self.temp.name), result), result)

    def test_unsupported_higher_score_cannot_replace_grounded_seed(self):
        axes = dict(zip(workflow.CRITIC_AXES, (3, 4, 4, 4, 3), strict=True))
        def scored(total, honesty):
            return quality_cli.CandidateResult(
                "candidate-1", "mechanism", f"score {total}", axes,
                total, total, "below-target",
                {"honesty": honesty, "citation": "PASS", "proof": "NOT_REQUIRED"},
                honesty == "PASS", (),
            )
        safe, unsupported = scored(18, "PASS"), scored(25, "FAIL")
        def attempt(candidate):
            return quality_cli.AttemptResult((candidate,), (), None, None, ())
        state = quality_optimizer.RepairState()
        state.observe(attempt(safe))
        self.assertIs(state.observe(attempt(unsupported)), safe)
        self.assertIs(state.best_safe()[1], safe)

    def test_malformed_critic_is_classified_after_writer_validation(self):
        args = legacy_cli.build_parser().parse_args(["draft", "--dry-run"])
        with patch.object(
            workflow, "run_critic_review",
            side_effect=workflow.WorkflowError("malformed Critic score"),
        ):
            with self.assertRaisesRegex(
                workflow.CriticEvaluationFailure, "malformed Critic score"
            ):
                legacy_cli.command_draft(args)

    def test_late_malformed_advisory_preserves_scored_draft(self):
        candidate = quality_cli.CandidateResult(
            "candidate-1", "mechanism", "A grounded post.",
            dict(zip(workflow.CRITIC_AXES, (4, 3, 3, 3, 4), strict=True)),
            17, 17, "advance-to-gates",
            {"honesty": "PASS", "citation": "PASS", "proof": "NOT_REQUIRED"}, True, (),
        )
        attempt = quality_cli.AttemptResult((candidate,), (), None, None, ())
        with (
            patch.object(integrated_cli, "_active_single_selector", {"status": "PASS"}),
            patch.object(integrated_cli, "_original_qualifying", return_value=(candidate,)),
            patch.object(integrated_cli, "_record_post_quality"),
            patch.object(
                integrated_cli.resonance, "invoke_post_critic",
                side_effect=workflow.WorkflowError("Resonance stage returned an invalid score inventory."),
            ),
        ):
            with self.assertRaises(workflow.AdvisoryProviderFailure):
                integrated_cli._qualifying_candidates(
                    attempt, rejected_openings=set(), package_requested=False, fixture_mode=False
                )

    def test_late_advisory_json_shape_failures_preserve_scored_draft(self):
        candidate = quality_cli.CandidateResult(
            "candidate-1", "mechanism", "A grounded post.",
            dict(zip(workflow.CRITIC_AXES, (4, 3, 3, 3, 4), strict=True)),
            17, 17, "advance-to-gates",
            {"honesty": "PASS", "citation": "PASS", "proof": "NOT_REQUIRED"}, True, (),
        )
        attempt = quality_cli.AttemptResult((candidate,), (), None, None, ())
        for message in (
            "Campaign model stage returned invalid JSON.",
            "Campaign model stage must return one JSON object.",
        ):
            with (
                self.subTest(message=message),
                patch.object(integrated_cli, "_active_single_selector", {"status": "PASS"}),
                patch.object(integrated_cli, "_original_qualifying", return_value=(candidate,)),
                patch.object(integrated_cli, "_record_post_quality"),
                patch.object(
                    integrated_cli.resonance, "invoke_post_critic",
                    side_effect=workflow.WorkflowError(message),
                ),
            ):
                with self.assertRaisesRegex(workflow.AdvisoryProviderFailure, message):
                    integrated_cli._qualifying_candidates(
                        attempt, rejected_openings=set(), package_requested=False,
                        fixture_mode=False,
                    )

    def test_later_malformed_critic_keeps_retained_score_in_delivery_reason(self):
        candidate = quality_cli.CandidateResult(
            "candidate-1", "mechanism", "A grounded post.",
            dict(zip(workflow.CRITIC_AXES, (4, 3, 3, 3, 3), strict=True)),
            16, 16, "below-target",
            {"honesty": "PASS", "citation": "PASS", "proof": "NOT_REQUIRED"}, True, (),
        )
        attempt = quality_cli.AttemptResult((candidate,), (), None, None, ())

        def fail_later(_args):
            quality_optimizer._ACTIVE_STATE.observe(attempt)
            raise workflow.CriticEvaluationFailure("later Critic returned invalid JSON")

        with (
            patch.object(quality_optimizer, "_ORIGINAL_COMMAND_DRAFT", side_effect=fail_later),
            patch.object(best_effort, "write", return_value=self.output),
            patch.object(quality_optimizer.v1_completion, "record_decision") as record,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(quality_optimizer._command_draft(SimpleNamespace()), 0)
        reason = record.call_args.args[0]["reason"]
        self.assertIn("16/25", reason)
        self.assertNotIn("Critic score is NOT_EVALUATED", reason)

    def test_invalid_writer_is_not_rebranded_as_delivery(self):
        with patch.object(
            quality_optimizer, "_ORIGINAL_COMMAND_DRAFT",
            side_effect=workflow.WorkflowError("Writer candidate has an invalid schema"),
        ):
            with self.assertRaisesRegex(workflow.WorkflowError, "invalid schema"):
                quality_optimizer._command_draft(SimpleNamespace())
        self.assertFalse(self.output.exists())

    def test_secure_write_failure_stays_failure(self):
        early = self.checkpoint().early
        def fail_after_writer(_args):
            quality_optimizer._ACTIVE_STATE.early = early
            raise workflow.CriticEvaluationFailure("Critic failed")
        with (
            patch.object(quality_optimizer, "_ORIGINAL_COMMAND_DRAFT", side_effect=fail_after_writer),
            patch.object(best_effort, "write", side_effect=workflow.WorkflowError("private output denied")),
            redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(workflow.CriticEvaluationFailure):
                quality_optimizer._command_draft(SimpleNamespace())
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
