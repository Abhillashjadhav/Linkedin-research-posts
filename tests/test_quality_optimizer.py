"""Tests for the V1 best-so-far quality repair overlay."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import quality_cli, quality_optimizer, workflow


GATES_PASS = {
    "authority_conversion": "PASS",
    "proof": "NOT_REQUIRED",
    "honesty": "PASS",
    "citation": "PASS",
    "relevance": "PASS",
}


def candidate(
    score: int,
    axes: dict[str, int],
    *,
    candidate_id: str = "candidate-1",
    gates_pass: bool = True,
    text: str = "Grounded repair seed.",
) -> quality_cli.CandidateResult:
    gates = dict(GATES_PASS)
    reasons: tuple[str, ...] = ()
    if not gates_pass:
        gates["honesty"] = "FAIL"
        reasons = ("unsupported-factual-marker",)
    return quality_cli.CandidateResult(
        candidate_id=candidate_id,
        angle="mechanism",
        text=text,
        axes=dict(axes),
        raw_total=score,
        effective_total=score,
        band="advance-to-gates" if score >= 24 else "one-light-revision" if score >= 22 else "below-critic-bar",
        gates=gates,
        passes_required_gates=gates_pass,
        gate_reasons=reasons,
    )


def attempt(*candidates: quality_cli.CandidateResult) -> quality_cli.AttemptResult:
    return quality_cli.AttemptResult(
        candidates=tuple(candidates),
        context_lines=(),
        review_status=None,
        recommendation=None,
        package_lines=(),
    )


def attempt_output(*, axes: tuple[int, int, int, int, int], text: str) -> str:
    names = workflow.CRITIC_AXES
    score = sum(axes)
    axis_text = ",".join(f"{name}={value}" for name, value in zip(names, axes, strict=True))
    band = "advance-to-gates" if score >= 24 else "one-light-revision" if score >= 22 else "below-critic-bar"
    return (
        "Stored evidence selected for Writer: topic=test; sources=2.\n"
        "Strategy brief: goal=authority; format=text; weekly_slot=not-selected; topic=test.\n"
        "Reader: AI product leaders Problem: They need a defensible decision.\n"
        "Core hypothesis: Reliability compounds across workflow steps.\n"
        "Product decision: Set the end-to-end reliability budget first.\n"
        "Authority statement: Connect the mechanism to a falsifiable decision.\n"
        "Strategy input origin: explicit-input\n"
        "Evidence status: source_quality=sufficient; body=sufficient; recency=sufficient; "
        "stale=not-evaluated; primary_sources=1; limitations=none.\n"
        "Candidate 1: id=candidate-1; angle=mechanism; claim_ids=claim-1.\n"
        f"{text}\n\nGrounded body for the repair trajectory.\n"
        "Candidate 2: id=candidate-2; angle=decision; claim_ids=claim-1.\n"
        "Alternative decision-led draft.\n\nGrounded body.\n"
        "Candidate 3: id=candidate-3; angle=failure; claim_ids=claim-1.\n"
        "Alternative failure-mode draft.\n\nGrounded body.\n"
        f"Critic score: id=candidate-1; {axis_text}; raw_total={score}; effective_total={score}; band={band}.\n"
        "Critic score: id=candidate-2; hook_strength=4,middle_escalation=3,earned_closer=3,"
        "specificity_and_source_quality=3,voice_fidelity=3; raw_total=16; effective_total=16; band=below-critic-bar.\n"
        "Critic score: id=candidate-3; hook_strength=4,middle_escalation=3,earned_closer=3,"
        "specificity_and_source_quality=3,voice_fidelity=2; raw_total=15; effective_total=15; band=below-critic-bar.\n"
        "Critic ranking: candidate-1,candidate-2,candidate-3.\n"
        "Score leader: candidate-1; revision_count=0.\n"
        "Gate result: id=candidate-1; authority_conversion=PASS,proof=NOT_REQUIRED,honesty=PASS,"
        "citation=PASS,relevance=PASS; passes_required_gates=yes; manual_fact_verification_required=yes; reasons=.\n"
        "Gate result: id=candidate-2; authority_conversion=PASS,proof=NOT_REQUIRED,honesty=PASS,"
        "citation=PASS,relevance=PASS; passes_required_gates=yes; manual_fact_verification_required=yes; reasons=.\n"
        "Gate result: id=candidate-3; authority_conversion=PASS,proof=NOT_REQUIRED,honesty=PASS,"
        "citation=PASS,relevance=PASS; passes_required_gates=yes; manual_fact_verification_required=yes; reasons=.\n"
        "No approval package was generated. No LinkedIn action was taken.\n"
    )


class AcceptanceTests(unittest.TestCase):
    def test_22_with_axis_floor_and_gates_is_acceptable(self) -> None:
        item = candidate(
            22,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 4,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            },
        )
        self.assertTrue(quality_optimizer.candidate_is_acceptable(item))

    def test_22_with_one_three_is_not_acceptable(self) -> None:
        item = candidate(
            22,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 3,
            },
        )
        self.assertFalse(quality_optimizer.candidate_is_acceptable(item))

    def test_24_with_failed_gate_is_not_acceptable(self) -> None:
        item = candidate(
            24,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            gates_pass=False,
        )
        self.assertFalse(quality_optimizer.candidate_is_acceptable(item))

    def test_package_floor_uses_same_axis_and_gate_contract(self) -> None:
        scorecard = {
            "candidate_id": "candidate-1",
            "hook_strength": 5,
            "middle_escalation": 5,
            "earned_closer": 4,
            "specificity_and_source_quality": 4,
            "voice_fidelity": 4,
            "raw_total": 22,
            "effective_total": 22,
            "hook_cap_applied": False,
            "band": "one-light-revision",
        }
        self.assertTrue(
            quality_optimizer._scorecard_is_acceptable(  # type: ignore[attr-defined]
                scorecard, {"passes_required_gates": True}
            )
        )
        scorecard["voice_fidelity"] = 3
        self.assertFalse(
            quality_optimizer._scorecard_is_acceptable(  # type: ignore[attr-defined]
                scorecard, {"passes_required_gates": True}
            )
        )


class RepairStateTests(unittest.TestCase):
    def test_best_so_far_survives_a_later_score_regression(self) -> None:
        state = quality_optimizer.RepairState()
        first = candidate(
            18,
            {
                "hook_strength": 5,
                "middle_escalation": 4,
                "earned_closer": 3,
                "specificity_and_source_quality": 3,
                "voice_fidelity": 3,
            },
            text="Keep this stronger repair seed.",
        )
        worse = candidate(
            16,
            {
                "hook_strength": 5,
                "middle_escalation": 3,
                "earned_closer": 3,
                "specificity_and_source_quality": 3,
                "voice_fidelity": 2,
            },
            text="Do not replace the stronger seed with this regression.",
        )
        state.observe(attempt(first))
        retained = state.observe(attempt(worse))
        self.assertEqual(retained.effective_total, 18)
        self.assertEqual(retained.text, "Keep this stronger repair seed.")
        self.assertEqual(state.cycle_best_scores, [18, 16])

    def test_feedback_carries_full_best_text_scores_and_gate_failures(self) -> None:
        seed = candidate(
            18,
            {
                "hook_strength": 5,
                "middle_escalation": 4,
                "earned_closer": 3,
                "specificity_and_source_quality": 3,
                "voice_fidelity": 3,
            },
            gates_pass=False,
            text="Full candidate text must reach the next repair cycle.",
        )
        with patch.object(quality_optimizer, "_ACTIVE_STATE", quality_optimizer.RepairState()):
            feedback = quality_optimizer._quality_feedback(attempt(seed), 1)  # type: ignore[attr-defined]
        repair_seed = feedback["repair_seed"]
        self.assertIsInstance(repair_seed, dict)
        self.assertEqual(
            repair_seed["text"],  # type: ignore[index]
            "Full candidate text must reach the next repair cycle.",
        )
        self.assertIn("unsupported-factual-marker", repair_seed["gate_reasons"])  # type: ignore[index]
        self.assertEqual(feedback["quality_target"], 24)
        self.assertEqual(feedback["acceptable_floor"], 22)


class RepairPromptTests(unittest.TestCase):
    def test_retry_prompt_is_repair_not_fresh_generation(self) -> None:
        feedback = {
            "repair_seed": {
                "text": "Retain this grounded mechanism and improve it.",
                "critic_axes": {"hook_strength": 5, "voice_fidelity": 3},
                "gate_reasons": ["unsupported-factual-marker"],
            },
            "quality_target": 24,
        }
        with patch.object(workflow, "build_writer_prompt", lambda *a, **k: "BASE"):
            with quality_optimizer._writer_retry_prompt(feedback):  # type: ignore[attr-defined]
                prompt = workflow.build_writer_prompt()
        self.assertIn("QUALITY_REPAIR_CYCLE_CONTRACT", prompt)
        self.assertIn("not a fresh brainstorm", prompt)
        self.assertIn("Retain this grounded mechanism", prompt)
        self.assertIn("Aim for 24-25/25", prompt)
        self.assertIn("Never invent evidence", prompt)

    def test_integrated_dispatch_updates_the_real_command_table(self) -> None:
        def integrated_command(_args: object) -> int:
            return 7

        module = SimpleNamespace(_command_draft=integrated_command)
        original_command = quality_cli.command_draft
        original_dispatch = quality_cli.COMMANDS["draft"]
        try:
            quality_optimizer.wire_integrated_dispatch(module)
            self.assertIs(quality_cli.command_draft, integrated_command)
            self.assertIs(quality_cli.COMMANDS["draft"], integrated_command)
        finally:
            quality_cli.command_draft = original_command
            quality_cli.COMMANDS["draft"] = original_dispatch


class FourCycleConvergenceTests(unittest.TestCase):
    def test_16_to_18_to_21_to_22_returns_final_written_candidate(self) -> None:
        responses = [
            attempt_output(
                axes=(5, 3, 3, 3, 2),
                text="Cycle one is weak but grounded.",
            ),
            attempt_output(
                axes=(5, 4, 3, 3, 3),
                text="Cycle two repairs the structure.",
            ),
            attempt_output(
                axes=(5, 4, 4, 4, 4),
                text="Cycle three is close to the review floor.",
            ),
            attempt_output(
                axes=(5, 5, 4, 4, 4),
                text="Cycle four is the final acceptable written candidate.",
            ),
        ]

        def fake_legacy(_args: object) -> int:
            print(responses.pop(0), end="")
            return 0

        args = SimpleNamespace(dry_run=False, package=False, run_spec=None)
        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_legacy),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 4),
            patch.object(quality_cli, "MIN_QUALITY_SCORE", 22),
            patch.object(
                quality_cli,
                "_qualifying_candidates",
                quality_optimizer._qualifying_candidates,  # type: ignore[attr-defined]
            ),
            patch.object(
                quality_cli,
                "_quality_feedback",
                quality_optimizer._quality_feedback,  # type: ignore[attr-defined]
            ),
            patch.object(
                quality_cli,
                "_writer_retry_prompt",
                quality_optimizer._writer_retry_prompt,  # type: ignore[attr-defined]
            ),
            redirect_stdout(output),
        ):
            result = quality_optimizer._command_draft(args)  # type: ignore[attr-defined]

        rendered = output.getvalue()
        self.assertEqual(result, 0)
        self.assertIn("Quality cycle 1/4 rejected", rendered)
        self.assertIn("Quality cycle 2/4 rejected", rendered)
        self.assertIn("Quality cycle 3/4 rejected", rendered)
        self.assertIn("Quality search passed on cycle 4/4", rendered)
        self.assertIn("score=22/25", rendered)
        self.assertIn("Cycle four is the final acceptable written candidate.", rendered)
        self.assertNotIn("Cycle one is weak but grounded.", rendered)
        self.assertEqual(responses, [])


if __name__ == "__main__":
    unittest.main()
