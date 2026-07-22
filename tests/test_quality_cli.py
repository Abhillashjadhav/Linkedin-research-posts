"""Tests for the high-bar multi-cycle draft coordinator."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import quality_cli, workflow


def attempt_output(
    *,
    first_score: int,
    first_hook: int = 5,
    first_gates: bool = True,
    first_opening: str = "First opening.",
    ready: bool = False,
) -> str:
    remaining = max(first_score - first_hook, 4)
    axis = [first_hook, 5, 5, 5, max(1, remaining - 15)]
    gates = "PASS" if first_gates else "FAIL"
    passes = "yes" if first_gates else "no"
    reason = "" if first_gates else "authority_statement_missing"
    context = (
        "Fixture envelope validated: topic=test; research_items=2.\n"
        "Strategy brief: goal=authority; format=not-selected; weekly_slot=2; topic=test.\n"
        "Reader: AI product leaders Problem: They need a defensible decision.\n"
        "Core hypothesis: Reliability compounds across workflow steps.\n"
        "Product decision: Set the end-to-end reliability budget first.\n"
        "Authority statement: Connect the mechanism to a falsifiable decision.\n"
        "Strategy input origin: synthetic-fixture\n"
        "Evidence status: source_quality=sufficient; body=sufficient; "
        "recency=sufficient; stale=not-evaluated; primary_sources=1; "
        "limitations=recent-post-similarity-not-evaluated.\n"
    )
    package = ""
    if ready:
        package = (
            "Content package: outputs/2026-07-23/topic.\n"
            "Recommended candidate for human review: candidate-1\n"
            "Review status: READY_FOR_HUMAN_REVIEW.\n"
            "Human approval status: NOT_APPROVED; manual fact verification required.\n"
            "Publishing status: DISABLED. No LinkedIn action was taken.\n"
        )
    else:
        context += "No approval package was generated. No LinkedIn action was taken.\n"
    return (
        context
        + "Candidate 1: id=candidate-1; angle=mechanism; claim_ids=claim-1.\n"
        f"{first_opening}\n\nFirst body.\n"
        "Candidate 2: id=candidate-2; angle=decision; claim_ids=claim-1.\n"
        "Second opening.\n\nSecond body.\n"
        "Candidate 3: id=candidate-3; angle=failure; claim_ids=claim-1.\n"
        "Third opening.\n\nThird body.\n"
        f"Critic score: id=candidate-1; hook_strength={axis[0]},"
        f"middle_escalation={axis[1]},earned_closer={axis[2]},"
        f"specificity_and_source_quality={axis[3]},voice_fidelity={axis[4]}; "
        f"raw_total={first_score}; effective_total={first_score}; "
        f"band={'advance-to-gates' if first_score >= 24 else 'below-critic-bar'}.\n"
        "Critic score: id=candidate-2; hook_strength=4,middle_escalation=4,"
        "earned_closer=4,specificity_and_source_quality=4,voice_fidelity=4; "
        "raw_total=20; effective_total=20; band=below-critic-bar.\n"
        "Critic score: id=candidate-3; hook_strength=3,middle_escalation=5,"
        "earned_closer=5,specificity_and_source_quality=5,voice_fidelity=5; "
        "raw_total=23; effective_total=18; band=below-critic-bar.\n"
        "Critic ranking: candidate-1,candidate-2,candidate-3.\n"
        "Score leader: candidate-1; revision_count=0.\n"
        f"Gate result: id=candidate-1; authority_conversion={gates},"
        "proof=NOT_REQUIRED,honesty=PASS,citation=PASS,relevance=PASS; "
        f"passes_required_gates={passes}; manual_fact_verification_required=yes; "
        f"reasons={reason}.\n"
        "Gate result: id=candidate-2; authority_conversion=FAIL,proof=NOT_REQUIRED,"
        "honesty=PASS,citation=PASS,relevance=PASS; passes_required_gates=no; "
        "manual_fact_verification_required=yes; reasons=authority_statement_missing.\n"
        "Gate result: id=candidate-3; authority_conversion=PASS,proof=NOT_REQUIRED,"
        "honesty=PASS,citation=PASS,relevance=PASS; passes_required_gates=yes; "
        "manual_fact_verification_required=yes; reasons=.\n"
        f"{package}"
    )


class QualityOutputTests(unittest.TestCase):
    def test_parser_connects_context_candidate_scores_and_gates(self) -> None:
        parsed = quality_cli.parse_attempt_output(
            attempt_output(first_score=24, ready=True)
        )
        self.assertEqual(len(parsed.candidates), 3)
        first = parsed.candidates[0]
        self.assertEqual(first.candidate_id, "candidate-1")
        self.assertEqual(first.effective_total, 24)
        self.assertEqual(first.axes["hook_strength"], 5)
        self.assertTrue(first.passes_required_gates)
        self.assertTrue(parsed.context_lines[0].startswith("Fixture envelope validated:"))
        self.assertTrue(any(line.startswith("Strategy brief:") for line in parsed.context_lines))
        self.assertEqual(parsed.review_status, "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(parsed.recommendation, "candidate-1")

    def test_incomplete_envelope_fails_closed(self) -> None:
        malformed = attempt_output(first_score=24).replace(
            "Gate result: id=candidate-3", "Missing gate: id=candidate-3"
        )
        with self.assertRaises(workflow.WorkflowError):
            quality_cli.parse_attempt_output(malformed)


class QualitySearchTests(unittest.TestCase):
    def _args(self, *, package: bool = False) -> SimpleNamespace:
        return SimpleNamespace(dry_run=False, package=package)

    def test_rejected_draft_text_is_hidden_and_next_high_bar_set_is_returned(self) -> None:
        responses = [
            attempt_output(
                first_score=21,
                first_opening="Rejected private prose must stay hidden.",
            ),
            attempt_output(
                first_score=24,
                first_opening="Accepted public opening.",
            ),
        ]

        def fake_command(_args: object) -> int:
            print(responses.pop(0), end="")
            return 0

        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_command),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 2),
            redirect_stdout(output),
        ):
            result = quality_cli.command_draft(self._args())

        rendered = output.getvalue()
        self.assertEqual(result, 0)
        self.assertNotIn("Rejected private prose", rendered)
        self.assertIn("Quality cycle 1/2 rejected", rendered)
        self.assertIn("Strategy brief: goal=authority", rendered)
        self.assertIn("Accepted public opening", rendered)
        self.assertIn("score=24/25", rendered)
        self.assertNotIn("Second body", rendered)
        self.assertNotIn("Third body", rendered)

    def test_score_without_required_gates_regenerates(self) -> None:
        responses = [
            attempt_output(first_score=25, first_gates=False),
            attempt_output(first_score=24, first_opening="Second-cycle opening."),
        ]

        def fake_command(_args: object) -> int:
            print(responses.pop(0), end="")
            return 0

        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_command),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 2),
            redirect_stdout(output),
        ):
            quality_cli.command_draft(self._args())
        self.assertIn("required_gates=fail", output.getvalue())
        self.assertIn("Quality search passed on cycle 2/2", output.getvalue())

    def test_live_package_requires_ready_review_and_matching_recommendation(self) -> None:
        responses = [
            attempt_output(first_score=24, ready=False),
            attempt_output(first_score=24, first_opening="Ready opening.", ready=True),
        ]

        def fake_command(_args: object) -> int:
            print(responses.pop(0), end="")
            return 0

        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_command),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 2),
            redirect_stdout(output),
        ):
            quality_cli.command_draft(self._args(package=True))
        rendered = output.getvalue()
        self.assertIn("Quality cycle 1/2 rejected", rendered)
        self.assertIn("Review status: READY_FOR_HUMAN_REVIEW", rendered)

    def test_reusing_a_rejected_opening_cannot_pass_the_next_cycle(self) -> None:
        repeated = "Do not reuse this opening."
        responses = [
            attempt_output(first_score=21, first_opening=repeated),
            attempt_output(first_score=25, first_opening=repeated),
        ]

        def fake_command(_args: object) -> int:
            print(responses.pop(0), end="")
            return 0

        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_command),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 2),
            redirect_stdout(output),
        ):
            with self.assertRaises(workflow.WorkflowError):
                quality_cli.command_draft(self._args())
        self.assertNotIn(repeated, output.getvalue())

    def test_exhaustion_returns_no_post(self) -> None:
        def fake_command(_args: object) -> int:
            print(attempt_output(first_score=21), end="")
            return 0

        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_command),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 2),
            redirect_stdout(output),
        ):
            with self.assertRaisesRegex(workflow.WorkflowError, "No post was returned"):
                quality_cli.command_draft(self._args())
        self.assertNotIn("First body", output.getvalue())
        self.assertNotIn("Strategy brief:", output.getvalue())

    def test_fixture_is_deterministic_and_runs_once(self) -> None:
        calls = 0

        def fake_command(_args: object) -> int:
            nonlocal calls
            calls += 1
            print(attempt_output(first_score=24), end="")
            return 0

        args = SimpleNamespace(dry_run=True, package=False)
        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_command),
            redirect_stdout(output),
        ):
            quality_cli.command_draft(args)
        self.assertEqual(calls, 1)
        self.assertIn("Fixture envelope validated:", output.getvalue())
        self.assertIn("No approval package was generated", output.getvalue())


class RetryPromptTests(unittest.TestCase):
    def test_retry_prompt_adds_diagnostics_and_restores_original_builder(self) -> None:
        original = workflow.build_writer_prompt
        with patch.object(
            workflow, "build_writer_prompt", lambda *args, **kwargs: "BASE"
        ):
            patched_original = workflow.build_writer_prompt
            with quality_cli._writer_retry_prompt(
                {"rejected_cycle": 1, "rejected_candidates": [{"opening": "Old"}]}
            ):
                prompt = workflow.build_writer_prompt()
                self.assertIn("QUALITY_SEARCH_RETRY_INSTRUCTION", prompt)
                self.assertIn('"rejected_cycle": 1', prompt)
                self.assertIn("Do not reuse a rejected opening", prompt)
            self.assertIs(workflow.build_writer_prompt, patched_original)
        self.assertIs(workflow.build_writer_prompt, original)


if __name__ == "__main__":
    unittest.main()
