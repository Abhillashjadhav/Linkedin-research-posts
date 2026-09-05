"""Tests for the V1 best-so-far quality repair overlay."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import quality_cli, quality_optimizer, v1_completion, workflow


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
        band="advance-to-gates" if score >= 18 else "below-critic-bar",
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
    band = "advance-to-gates" if score >= 18 else "below-critic-bar"
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
    def test_named_acceptance_constants_match_the_owner_decision(self) -> None:
        self.assertEqual(quality_optimizer.ACCEPTABLE_QUALITY_FLOOR, 18)
        self.assertEqual(quality_optimizer.MIN_HOOK_SCORE, 4)
        self.assertEqual(
            dict(quality_optimizer.AXIS_FLOORS),
            {"hook_strength": 4, "voice_fidelity": 4},
        )
        self.assertEqual(quality_optimizer.MIN_VOICE_FIDELITY_SCORE, 4)

    def test_21_with_five_four_four_four_four_advances(self) -> None:
        item = candidate(
            21,
            {
                "hook_strength": 5,
                "middle_escalation": 4,
                "earned_closer": 4,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            },
        )
        self.assertTrue(quality_optimizer.candidate_is_acceptable(item))

    def test_18_with_hook_five_voice_four_and_other_axes_three_advances(self) -> None:
        item = candidate(
            18,
            {
                "hook_strength": 5,
                "middle_escalation": 3,
                "earned_closer": 3,
                "specificity_and_source_quality": 3,
                "voice_fidelity": 4,
            },
        )
        self.assertTrue(quality_optimizer.candidate_is_acceptable(item))

    def test_voice_below_four_never_advances_even_with_high_total(self) -> None:
        for score, axes in (
            (
                19,
                {
                    "hook_strength": 5,
                    "middle_escalation": 4,
                    "earned_closer": 4,
                    "specificity_and_source_quality": 4,
                    "voice_fidelity": 2,
                },
            ),
            (
                18,
                {
                    "hook_strength": 4,
                    "middle_escalation": 4,
                    "earned_closer": 4,
                    "specificity_and_source_quality": 4,
                    "voice_fidelity": 2,
                },
            ),
        ):
            with self.subTest(score=score):
                self.assertFalse(
                    quality_optimizer.candidate_is_acceptable(candidate(score, axes))
                )

    def test_perfect_25_with_failed_honesty_gate_advances_with_finding(self) -> None:
        item = candidate(
            25,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 5,
            },
            gates_pass=False,
        )
        self.assertTrue(quality_optimizer.candidate_is_acceptable(item))

    def test_advisory_label_cannot_turn_honesty_into_a_pass(self) -> None:
        item = candidate(
            25,
            {axis: 5 for axis in workflow.CRITIC_AXES},
        )
        softened = dict(item.gates)
        softened["honesty"] = "HUMAN_REVIEW"
        item = quality_cli.CandidateResult(
            candidate_id=item.candidate_id,
            angle=item.angle,
            text=item.text,
            axes=item.axes,
            raw_total=item.raw_total,
            effective_total=item.effective_total,
            band=item.band,
            gates=softened,
            passes_required_gates=True,
            gate_reasons=("unsupported-factual-marker",),
        )
        self.assertTrue(quality_optimizer.candidate_is_acceptable(item))

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
            "band": "advance-to-gates",
        }
        self.assertTrue(
            quality_optimizer._scorecard_is_acceptable(  # type: ignore[attr-defined]
                scorecard,
                {"passes_required_gates": True, "gates": dict(GATES_PASS)},
            )
        )
        scorecard["voice_fidelity"] = 3
        self.assertFalse(
            quality_optimizer._scorecard_is_acceptable(  # type: ignore[attr-defined]
                scorecard,
                {"passes_required_gates": True, "gates": dict(GATES_PASS)},
            )
        )

    def test_package_gate_shape_uses_nested_original_statuses(self) -> None:
        scorecard = {
            "hook_strength": 5,
            "middle_escalation": 3,
            "earned_closer": 3,
            "specificity_and_source_quality": 3,
            "voice_fidelity": 4,
            "effective_total": 18,
        }
        nested = {
            "passes_required_gates": True,
            "gates": {
                name: {"status": status}
                for name, status in GATES_PASS.items()
            },
        }
        self.assertTrue(
            quality_optimizer._scorecard_is_acceptable(scorecard, nested)  # type: ignore[attr-defined]
        )
        nested["gates"]["honesty"] = {"status": "FAIL"}
        self.assertTrue(
            quality_optimizer._scorecard_is_acceptable(scorecard, nested)  # type: ignore[attr-defined]
        )


class RepairStateTests(unittest.TestCase):
    def test_lower_total_cannot_replace_seed_even_when_hard_gates_improve(self) -> None:
        state = quality_optimizer.RepairState()
        higher_total = candidate(
            23,
            {
                "hook_strength": 4,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            gates_pass=False,
            text="Keep the higher-total seed while its factual gate is repaired.",
        )
        lower_total = candidate(
            22,
            {
                "hook_strength": 4,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            },
            gates_pass=True,
            text="Do not replace the seed with a lower-total edit.",
        )

        state.observe(attempt(higher_total))
        retained = state.observe(attempt(lower_total))

        self.assertEqual(retained.effective_total, 23)
        self.assertEqual(
            retained.text,
            "Keep the higher-total seed while its factual gate is repaired.",
        )

    def test_highest_total_with_voice_three_is_rejected_and_recorded(self) -> None:
        high = candidate(
            22,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 3,
            },
            candidate_id="candidate-high",
        )
        acceptable = candidate(
            18,
            {
                "hook_strength": 5,
                "middle_escalation": 3,
                "earned_closer": 3,
                "specificity_and_source_quality": 3,
                "voice_fidelity": 4,
            },
            candidate_id="candidate-acceptable",
        )
        batch = attempt(high, acceptable)
        with (
            patch.object(quality_optimizer, "_ORIGINAL_RUN_ATTEMPT", return_value=batch),
            patch.object(quality_optimizer.v1_completion, "record_decision") as record,
        ):
            observed = quality_optimizer._run_attempt(SimpleNamespace(), None)  # type: ignore[attr-defined]

        qualified = quality_optimizer._qualifying_candidates(  # type: ignore[attr-defined]
            observed,
            rejected_openings=set(),
            package_requested=False,
            fixture_mode=True,
        )
        self.assertEqual([item.candidate_id for item in qualified], ["candidate-acceptable"])
        voice = next(
            call.args[0]
            for call in record.call_args_list
            if call.args[0]["contract"] == "voice_fidelity"
            and call.kwargs["subject_id"] == "candidate-high"
        )
        self.assertEqual(voice["status"], "FAIL")
        self.assertEqual(voice["shortfall"], 1)
        self.assertIn("short-by-1", voice["reason"])

    def test_unsupported_wording_is_advisory_on_every_iteration(self) -> None:
        item = candidate(
            21,
            {
                "hook_strength": 4,
                "middle_escalation": 4,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            },
            gates_pass=False,
        )
        batch = attempt(item)

        strict = quality_optimizer._qualifying_candidates(  # type: ignore[attr-defined]
            batch,
            rejected_openings=set(),
            package_requested=False,
            fixture_mode=True,
            allow_factual_wording_advisory=False,
        )
        after_rewrite = quality_optimizer._qualifying_candidates(  # type: ignore[attr-defined]
            batch,
            rejected_openings=set(),
            package_requested=False,
            fixture_mode=True,
            allow_factual_wording_advisory=True,
        )

        self.assertEqual(strict, (item,))
        self.assertEqual(after_rewrite, (item,))

    def test_run_attempt_records_every_candidate_critic_scorecard(self) -> None:
        first = candidate(
            24,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            candidate_id="candidate-1",
        )
        second = candidate(
            20,
            {
                "hook_strength": 4,
                "middle_escalation": 4,
                "earned_closer": 4,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            },
            candidate_id="candidate-2",
            gates_pass=False,
        )
        with (
            patch.object(
                quality_optimizer,
                "_ORIGINAL_RUN_ATTEMPT",
                return_value=attempt(first, second),
            ),
            patch.object(quality_optimizer.v1_completion, "record_decision") as record,
        ):
            result = quality_optimizer._run_attempt(  # type: ignore[attr-defined]
                SimpleNamespace(), {"rejected_cycle": 1}
            )

        self.assertEqual(result.candidates, (first, second))
        recorded = [call.args[0] for call in record.call_args_list]
        critic_decisions = [
            decision for decision in recorded if decision["contract"] == "critic_total"
        ]
        gate_decisions = [
            decision for decision in recorded if str(decision["contract"]).startswith("gate_")
        ]
        self.assertEqual(len(critic_decisions), 2)
        self.assertEqual(len(gate_decisions), 10)
        axis_decisions = [
            decision for decision in recorded if decision["contract"] in workflow.CRITIC_AXES
        ]
        self.assertEqual(len(axis_decisions), 10)
        first_decision, second_decision = critic_decisions
        self.assertEqual(first_decision["contract"], "critic_total")
        self.assertEqual(first_decision["cycle"], 2)
        self.assertEqual(first_decision["score"], 24)
        self.assertEqual(first_decision["axes"]["voice_fidelity"], 4)
        self.assertEqual(second_decision["status"], "PASS")
        self.assertEqual(second_decision["gates"], {"honesty": "FAIL"})
        self.assertNotIn("unsupported-factual-marker", second_decision["failure_codes"])
        self.assertIn("unsupported-factual-marker", second_decision["advisory_codes"])
        advisory_honesty = next(
            call.args[0]
            for call in record.call_args_list
            if call.args[0]["contract"] == "gate_honesty"
            and call.args[0]["status"] == "PASS"
            and call.kwargs["subject_id"] == "candidate-2"
        )
        self.assertEqual(advisory_honesty["observed_status"], "FAIL")
        self.assertEqual(advisory_honesty["mode"], "diagnostic")
        self.assertIn(
            "unsupported-factual-marker", advisory_honesty["advisory_codes"]
        )

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

    def test_higher_total_can_trade_off_voice_during_repair(self) -> None:
        state = quality_optimizer.RepairState()
        voice_pass = candidate(
            21,
            {
                "hook_strength": 5,
                "middle_escalation": 4,
                "earned_closer": 4,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            },
            text="Keep the candidate that clears the values gate.",
        )
        voice_fail = candidate(
            22,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 3,
            },
            text="Do not trade voice away for one more total point.",
        )
        state.observe(attempt(voice_pass))
        retained = state.observe(attempt(voice_fail))
        self.assertEqual(retained.text, voice_fail.text)
        self.assertEqual(retained.axes["voice_fidelity"], 3)

    def test_higher_total_can_trade_off_hook_during_repair(self) -> None:
        state = quality_optimizer.RepairState()
        hook_pass = candidate(
            21,
            {
                "hook_strength": 4,
                "middle_escalation": 4,
                "earned_closer": 4,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            text="Keep the candidate whose hook clears the mandatory floor.",
        )
        hook_fail = candidate(
            22,
            {
                "hook_strength": 3,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            text="Do not trade away the hook floor for a higher total.",
        )

        state.observe(attempt(hook_pass))
        retained = state.observe(attempt(hook_fail))

        self.assertEqual(retained.text, hook_fail.text)
        self.assertEqual(retained.axes["hook_strength"], 3)

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
        self.assertEqual(repair_seed["weak_axes"], {"voice_fidelity": 3})  # type: ignore[index]
        self.assertEqual(
            repair_seed["passing_axes"],  # type: ignore[index]
            {"hook_strength": 5},
        )
        self.assertEqual(
            repair_seed["preserve_axes"],  # type: ignore[index]
            ["hook_strength"],
        )
        self.assertNotIn("quality_target", feedback)
        self.assertEqual(feedback["acceptable_floor"], 18)
        self.assertEqual(
            feedback["axis_floors"],
            {"hook_strength": 4, "voice_fidelity": 4},
        )

    def test_feedback_attaches_exact_anti_slop_findings_to_retained_seed(self) -> None:
        seed = candidate(
            21,
            {
                "hook_strength": 4,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 3,
            },
            text="What most people miss is the safety layer.",
        )
        with patch.object(quality_optimizer, "_ACTIVE_STATE", quality_optimizer.RepairState()):
            feedback = quality_optimizer._quality_feedback(attempt(seed), 1)  # type: ignore[attr-defined]
        repair_seed = feedback["repair_seed"]
        self.assertEqual(  # type: ignore[index]
            repair_seed["anti_slop_findings"],
            [
                {
                    "code": "faux-insight",
                    "excerpt": "What most people miss is the safety layer.",
                }
            ],
        )


class RepairPromptTests(unittest.TestCase):
    def test_retry_prompt_is_repair_not_fresh_generation(self) -> None:
        feedback = {
            "repair_seed": {
                "text": "Retain this grounded mechanism and improve it.",
                "critic_axes": {"hook_strength": 5, "voice_fidelity": 3},
                "gate_reasons": ["unsupported-factual-marker"],
            },
        }
        with patch.object(workflow, "build_writer_prompt", lambda *a, **k: "BASE"):
            with quality_optimizer._writer_retry_prompt(feedback):  # type: ignore[attr-defined]
                prompt = workflow.build_writer_prompt()
        self.assertIn("QUALITY_REPAIR_CYCLE_CONTRACT", prompt)
        self.assertIn("not a fresh brainstorm", prompt)
        self.assertIn("Retain this grounded mechanism", prompt)
        self.assertIn("Do not chase 5/5", prompt)
        self.assertIn("Stop once the shared acceptance contract passes", prompt)
        self.assertIn("Never invent evidence", prompt)
        self.assertIn("Supported abstraction", prompt)
        self.assertIn("must not add severity, prevalence, causality, scope, materiality", prompt)

    def test_voice_three_gets_targeted_human_voice_repair(self) -> None:
        feedback = {
            "repair_seed": {
                "text": "Keep this grounded draft and repair its voice.",
                "critic_axes": {
                    "hook_strength": 4,
                    "middle_escalation": 5,
                    "earned_closer": 5,
                    "specificity_and_source_quality": 4,
                    "voice_fidelity": 3,
                },
                "gate_reasons": ["anti-slop:decorative-list"],
                "anti_slop_findings": [
                    {"code": "decorative-list", "excerpt": "First. Second. Third."}
                ],
            }
        }
        with patch.object(workflow, "build_writer_prompt", lambda *a, **k: "BASE"):
            with quality_optimizer._writer_retry_prompt(feedback):  # type: ignore[attr-defined]
                prompt = workflow.build_writer_prompt()
        self.assertIn("VOICE_FIDELITY_REPAIR_REQUIRED", prompt)
        self.assertIn("voice_fidelity=3/5", prompt)
        self.assertIn("conversational product leader", prompt)
        self.assertIn("consultant-memo language", prompt)
        self.assertIn("Preserve its supported incident", prompt)
        self.assertIn("smallest plain-language or cadence edit", prompt)
        self.assertIn("question, conditional, proposed test, or recommendation", prompt)
        self.assertIn("Do not invent a personal experience", prompt)
        self.assertIn("ANTI_SLOP_REPAIR_REQUIRED", prompt)
        self.assertIn("smallest excerpt", prompt)

    def test_passing_voice_does_not_add_voice_repair_contract(self) -> None:
        feedback = {
            "repair_seed": {
                "text": "This candidate already sounds human.",
                "critic_axes": {"hook_strength": 4, "voice_fidelity": 4},
            }
        }
        with patch.object(workflow, "build_writer_prompt", lambda *a, **k: "BASE"):
            with quality_optimizer._writer_retry_prompt(feedback):  # type: ignore[attr-defined]
                prompt = workflow.build_writer_prompt()
        self.assertNotIn("VOICE_FIDELITY_REPAIR_REQUIRED", prompt)

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
    def test_voice_gate_keeps_18_out_but_21_advances_on_cycle_three(self) -> None:
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
        ]

        def fake_legacy(_args: object) -> int:
            print(responses.pop(0), end="")
            return 0

        args = SimpleNamespace(dry_run=False, package=False, run_spec=None)
        output = io.StringIO()
        with (
            patch.object(quality_cli.legacy_cli, "command_draft", fake_legacy),
            patch.object(quality_cli, "MAX_QUALITY_CYCLES", 4),
            patch.object(quality_cli, "MIN_QUALITY_SCORE", 18),
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
        self.assertNotIn("Quality cycle 3/4 rejected", rendered)
        self.assertIn("Quality search passed on cycle 3/4", rendered)
        self.assertIn("score=21/25", rendered)
        self.assertIn("Cycle three is close to the review floor.", rendered)
        self.assertNotIn("Cycle one is weak but grounded.", rendered)
        self.assertEqual(responses, [])

    def test_exhaustion_returns_best_overall_candidate_for_human_review(self) -> None:
        best = candidate(
            24,
            {
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            text="The retained best overall candidate.",
        )
        best_attempt = quality_cli.AttemptResult(
            candidates=(best,),
            context_lines=(),
            review_status="READY_FOR_HUMAN_REVIEW",
            recommendation="candidate-1",
            package_lines=("Content package: data/private/content-packages/best",),
        )

        def exhaust(_args: object) -> int:
            quality_optimizer._state().observe(best_attempt)  # type: ignore[attr-defined]
            raise workflow.WorkflowError(
                "No candidate cleared the locked 22/25 quality and safety bar after 4 cycle(s)."
            )

        output = io.StringIO()
        with (
            patch.object(quality_optimizer, "_ORIGINAL_COMMAND_DRAFT", exhaust),
            patch.object(
                quality_optimizer.best_effort,
                "write",
                return_value=workflow.REPO_ROOT / "data/private/run/best-effort-post.md",
            ) as write,
            patch.object(v1_completion, "record_decision") as record,
            redirect_stdout(output),
        ):
            result = quality_optimizer._command_draft(SimpleNamespace())  # type: ignore[attr-defined]

        self.assertEqual(result, 0)
        rendered = output.getvalue()
        self.assertIn("best overall=candidate-1 score=24/25", rendered)
        self.assertNotIn("The retained best overall candidate.", rendered)
        self.assertIn("best-effort-post.md", rendered)
        self.assertIn("COMPLETED_WITH_WARNINGS", rendered)
        write.assert_called_once()
        self.assertEqual(record.call_args.args[0]["observed_status"], "COMPLETED_WITH_WARNINGS")
        self.assertEqual(record.call_args.kwargs["artifact_sha256"], v1_completion._sha256_text(best.text))


if __name__ == "__main__":
    unittest.main()
