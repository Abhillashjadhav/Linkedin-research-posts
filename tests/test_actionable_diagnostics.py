"""Regression tests for V1 actionable diagnostics and repeated-failure fast stop."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import actionable_diagnostics, quality_cli, quality_optimizer, workflow


AXES = {
    "hook_strength": 4,
    "middle_escalation": 4,
    "earned_closer": 5,
    "specificity_and_source_quality": 4,
    "voice_fidelity": 4,
}


def candidate(score: int = 21) -> quality_cli.CandidateResult:
    return quality_cli.CandidateResult(
        candidate_id="candidate-1",
        angle="mechanism",
        text=(
            "The repository demonstrates one bounded path. "
            "A reviewer can inspect https://example.com before advancement."
        ),
        axes=dict(AXES),
        raw_total=score,
        effective_total=score,
        band="below-critic-bar",
        gates={
            "authority_conversion": "PASS",
            "proof": "NOT_REQUIRED",
            "honesty": "FAIL",
            "citation": "FAIL",
            "relevance": "PASS",
        },
        passes_required_gates=False,
        gate_reasons=(
            "authority-and-decision-reflected",
            "goal-does-not-require-proof",
            "unsupported-factual-marker",
            "unsupported-factual-marker",
            "target-audience-and-problem-reflected",
        ),
    )


def attempt(score: int = 21) -> quality_cli.AttemptResult:
    return quality_cli.AttemptResult(
        candidates=(candidate(score),),
        context_lines=(),
        review_status=None,
        recommendation=None,
        package_lines=(),
    )


class ActionableDiagnosticsTests(unittest.TestCase):
    def test_success_and_not_required_reasons_are_not_projected_as_failures(self) -> None:
        diagnostics = actionable_diagnostics._failed_reasons(candidate())  # type: ignore[attr-defined]
        codes = [item["failure_code"] for item in diagnostics]
        self.assertEqual(codes, ["unsupported-factual-marker", "unsupported-factual-marker"])
        self.assertNotIn("authority-and-decision-reflected", codes)
        self.assertNotIn("goal-does-not-require-proof", codes)
        self.assertNotIn("target-audience-and-problem-reflected", codes)
        self.assertTrue(all(set(item["gates"]) == {"honesty", "citation"} for item in diagnostics))

    def test_unsupported_failure_includes_sentence_level_repair_targets(self) -> None:
        diagnostics = actionable_diagnostics._failed_reasons(candidate())  # type: ignore[attr-defined]
        spans = diagnostics[0]["suspect_text_spans"]
        self.assertTrue(spans)
        self.assertIn("repository demonstrates one bounded path", spans[0].lower())
        self.assertIn("repair_action", diagnostics[0])

    def test_same_signature_never_stops_bounded_repair(self) -> None:
        base_feedback = {
            "repair_seed": {
                "candidate_id": "candidate-1",
                "gate_reasons": [],
            }
        }
        with (
            patch.object(actionable_diagnostics, "_LAST_SIGNATURE", None),
            patch.object(actionable_diagnostics, "_REPEAT_COUNT", 0),
            patch.object(actionable_diagnostics, "_LAST_SCORE", None),
            patch.object(
                actionable_diagnostics,
                "_ORIGINAL_QUALITY_FEEDBACK",
                return_value=base_feedback,
            ),
        ):
            first = actionable_diagnostics._quality_feedback(attempt(21), 1)  # type: ignore[attr-defined]
            self.assertEqual(first["repeated_failure_signature_count"], 1)
            for cycle in (2, 3, 4):
                repeated = actionable_diagnostics._quality_feedback(attempt(21), cycle)
                self.assertEqual(repeated["repeated_failure_signature_count"], cycle)
                self.assertIn("stalled_repair", repeated)

    def test_live_loop_repeated_findings_reaches_later_hook_repair_or_delivers(self) -> None:
        import io
        from contextlib import redirect_stdout
        from dataclasses import replace
        from types import SimpleNamespace

        stalled = replace(candidate(22), axes={
            "hook_strength": 3, "middle_escalation": 5, "earned_closer": 5,
            "specificity_and_source_quality": 5, "voice_fidelity": 4,
        })
        repaired = replace(stalled, text="A materially different opening.\nIts supported reader consequence.",
                           axes={**stalled.axes, "hook_strength": 4, "middle_escalation": 4,
                                 "earned_closer": 4}, raw_total=21, effective_total=21)
        for succeeds in (True, False):
            rows = [stalled, stalled, repaired] if succeeds else [stalled] * 4
            attempts = [replace(attempt(), candidates=(item,)) for item in rows]
            output = io.StringIO()
            with (
                patch.object(quality_cli, "_run_attempt", side_effect=attempts) as run,
                patch.object(quality_cli, "_qualifying_candidates", quality_optimizer._qualifying_candidates),
                patch.object(quality_cli, "_quality_feedback", actionable_diagnostics._quality_feedback),
                patch.object(quality_optimizer.best_effort, "write",
                             return_value=workflow.REPO_ROOT / "data/private/best-effort-post.md") as write,
                patch.object(quality_optimizer.v1_completion, "record_decision") as record,
                redirect_stdout(output),
            ):
                result = quality_optimizer._command_draft(SimpleNamespace(dry_run=False, package=False, run_spec=None))
            self.assertEqual(result, 0)
            self.assertEqual(run.call_count, 3 if succeeds else 4)
            self.assertNotIn("stopped early", output.getvalue())
            if succeeds:
                self.assertIn("Quality search passed on cycle 3/4", output.getvalue())
                self.assertIn("score=21/25", output.getvalue())
                write.assert_not_called()
            else:
                write.assert_called_once()
                self.assertEqual(record.call_args.args[0]["observed_status"], "COMPLETED_WITH_WARNINGS")

    def test_score_improvement_resets_repeat_counter(self) -> None:
        base_feedback = {"repair_seed": {"candidate_id": "candidate-1", "gate_reasons": []}}
        with (
            patch.object(actionable_diagnostics, "_LAST_SIGNATURE", None),
            patch.object(actionable_diagnostics, "_REPEAT_COUNT", 0),
            patch.object(actionable_diagnostics, "_LAST_SCORE", None),
            patch.object(
                actionable_diagnostics,
                "_ORIGINAL_QUALITY_FEEDBACK",
                return_value=base_feedback,
            ),
        ):
            actionable_diagnostics._quality_feedback(attempt(20), 1)  # type: ignore[attr-defined]
            improved = actionable_diagnostics._quality_feedback(attempt(21), 2)  # type: ignore[attr-defined]
            self.assertEqual(improved["repeated_failure_signature_count"], 1)


if __name__ == "__main__":
    unittest.main()
