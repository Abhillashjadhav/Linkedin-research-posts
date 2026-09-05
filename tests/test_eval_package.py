"""Focused tests for frozen-package evaluation-only execution."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from authority_os import __main__ as cli
from authority_os import acceptance_policy, eval_package, workflow


def _candidate(index: int) -> dict[str, object]:
    return {
        "id": f"candidate-{index}",
        "angle": f"Angle {index}",
        "text": f"A direct human opening for candidate {index}.\n\nThe consequence is clear.",
        "claim_ids": ["source-1"],
    }


def _gate(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "gates": {
            name: {
                "status": "NOT_REQUIRED" if name == "proof" else "PASS",
                "reason_codes": ["test-pass"],
            }
            for name in workflow.GATE_ORDER
        },
        "passes_required_gates": True,
        "manual_fact_verification_required": True,
    }


def _failed_honesty_gate(candidate_id: str) -> dict[str, object]:
    gate = _gate(candidate_id)
    gate["gates"]["honesty"] = {  # type: ignore[index]
        "status": "FAIL",
        "reason_codes": ["unsupported-factual-marker"],
    }
    gate["passes_required_gates"] = False
    return gate


def _evaluated_result(
    values: tuple[int, int, int, int, int],
    *,
    hard_gates_pass: bool = True,
) -> dict[str, object]:
    axes = dict(zip(workflow.CRITIC_AXES, values, strict=True))
    total = sum(values)
    scorecard: dict[str, object] = {
        "candidate_id": "candidate-2",
        **axes,
        "raw_total": total,
        "effective_total": total,
    }
    gates = _gate("candidate-2") if hard_gates_pass else _failed_honesty_gate("candidate-2")
    return {
        "candidate_id": "candidate-2",
        "candidate": _candidate(2),
        "scorecard": scorecard,
        "gates": gates,
        "factual_support_diagnostics": [],
        "anti_slop_findings": [],
        "acceptance": acceptance_policy.acceptance_decision(
            scorecard,
            hard_gates_pass=hard_gates_pass,
        ),
    }


def _repair_context() -> dict[str, object]:
    candidates = [_candidate(index) for index in range(1, 4)]
    brief = {
        "goal": "authority",
        "topic_slug": "topic",
        "goal_purpose": "purpose",
        "narrative_route": ["incident", "decision"],
        "target_reader": "product leaders",
        "reader_problem": "unclear ownership",
        "core_hypothesis": "ownership changes reliability",
        "product_decision": "name the owner",
        "authority_statement": "clear ownership matters",
        "strategy_input_origin": "explicit-input",
        "analysis": {
            "why_now": "now",
            "dominant_take": "common take",
            "missing_angle": "missing decision",
        },
    }
    evidence = [
        {
            "id": "source-1",
            "title": "Source",
            "claim": "Grounded claim",
            "source": "https://example.com/source",
            "source_quality": "primary",
            "body_read": True,
        }
    ]
    return {
        "package_path": workflow.REPO_ROOT / "outputs" / "2026-09-04" / "topic",
        "manifest": {"package_id": "2026-09-04-topic"},
        "brief": brief,
        "evidence": evidence,
        "proof": None,
        "all_candidates": candidates,
        "selected_candidates": [candidates[1]],
    }


def _raw_score(values: tuple[int, int, int, int, int]) -> list[dict[str, object]]:
    return [
        {
            "candidate_id": "candidate-2",
            **dict(zip(workflow.CRITIC_AXES, values, strict=True)),
        }
    ]


class EvalPackageTests(unittest.TestCase):
    def test_hook_target_repair_beats_higher_total_with_stalled_hook(self) -> None:
        before = _evaluated_result((3, 5, 5, 5, 4))
        after = _evaluated_result((4, 4, 4, 5, 4))
        self.assertEqual(eval_package._monotonic_edit_decision(before, after), (True, []))
        self.assertEqual(after["acceptance"]["status"], "PASS")
        plan = eval_package._repair_feedback(2, before)["axis_repair_plan"]
        self.assertEqual(plan["focus_axes"], ["hook_strength"])
        self.assertEqual(plan["phase"], "axis_targets")
        self.assertIn("first two lines", plan["edits"][0]["target_anchor"])
        self.assertEqual(set(plan["preserve_axes"]), set(workflow.CRITIC_AXES) - {"hook_strength"})
        self.assertEqual(eval_package._repair_feedback(3, after)["axis_repair_plan"]["focus_axes"], [])

    def test_better_passing_axes_do_not_mask_stalled_hook(self) -> None:
        before = _evaluated_result((3, 4, 4, 4, 4))
        polished = _evaluated_result((3, 5, 5, 5, 4))
        accepted, reasons = eval_package._monotonic_edit_decision(before, polished)
        self.assertFalse(accepted)
        self.assertIn("unmet-axis-targets-did-not-improve", reasons)

    def test_screenshot_candidate_advances_despite_new_editorial_findings(self) -> None:
        previous = _evaluated_result((3, 5, 5, 5, 4))
        proposed = _evaluated_result((5, 4, 5, 4, 4), hard_gates_pass=False)
        proposed["anti_slop_findings"] = [{"code": "new-slop", "excerpt": "A phrase"}]
        accepted, reasons = eval_package._monotonic_edit_decision(previous, proposed)
        self.assertTrue(accepted)
        self.assertEqual(reasons, [])
        self.assertEqual(proposed["acceptance"]["status"], "PASS")
        self.assertFalse(proposed["gates"]["passes_required_gates"])

    def test_four_attempt_exhaustion_delivers_without_claiming_score_pass(self) -> None:
        context = _repair_context()
        captured = {}
        calls = []
        def edit(candidate, *_args, **_kwargs):
            calls.append(candidate)
            return {**candidate, "text": "another edit"}
        def persist(**kwargs):
            captured.update(kwargs)
            return tuple(workflow.REPO_ROOT / name for name in ("eval.json", "run.json", "eval.html")) + (False,)
        with (
            patch.object(eval_package, "_load_context", return_value=context),
            patch.object(eval_package, "_rubric_identity", return_value={"rubric_id": "test", "sha256": "a" * 64}),
            patch.object(workflow, "evaluate_candidate_set_gates", side_effect=lambda candidates, **kwargs: [_failed_honesty_gate(c["id"]) for c in candidates]),
            patch.object(workflow, "candidate_factual_support_diagnostics", return_value=[]),
            patch.object(workflow, "validate_draft_candidates", side_effect=lambda candidates, **kwargs: candidates),
        ):
            result = eval_package.command(
                SimpleNamespace(allow_model_egress=True, repair=True, candidate="candidate-2"),
                persist=persist, editor=edit,
                score_provider=lambda *args, **kwargs: _raw_score((3, 4, 5, 4, 3)),
            )
        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 3)
        self.assertEqual(len(captured["repair_history"]), 4)
        self.assertEqual(captured["results"][0]["acceptance"]["status"], "FAIL")
        self.assertEqual(captured["results"][0]["candidate"]["text"], context["selected_candidates"][0]["text"])

    def test_total_only_shortfall_is_named_in_progressive_feedback(self) -> None:
        result = _evaluated_result((4, 3, 3, 3, 4))

        feedback = eval_package._repair_feedback(2, result)

        self.assertEqual(feedback["current_total"], 17)
        self.assertEqual(feedback["required_total"], 18)
        self.assertEqual(feedback["total_shortfall"], 1)
        self.assertEqual(feedback["axis_shortfalls"], {})

    def test_higher_total_cannot_lose_a_met_axis_target(self) -> None:
        previous = _evaluated_result((4, 4, 4, 4, 4))
        for axes in ((3, 5, 5, 5, 4), (4, 5, 5, 5, 3)):
            with self.subTest(axes=axes):
                proposed = _evaluated_result(axes)
                accepted, reasons = eval_package._monotonic_edit_decision(previous, proposed)
                self.assertFalse(accepted)
                self.assertTrue(reasons[0].startswith("axis-target-regressed:"))
                self.assertEqual(proposed["acceptance"]["status"], "FAIL")

    def test_equal_total_can_advance_when_a_mandatory_shortfall_or_gate_improves(self) -> None:
        cases = (
            (
                _evaluated_result((3, 4, 5, 4, 3)),
                _evaluated_result((4, 3, 5, 4, 3)),
            ),
            (
                _evaluated_result((4, 4, 4, 4, 4), hard_gates_pass=False),
                _evaluated_result((4, 4, 4, 4, 4), hard_gates_pass=True),
            ),
        )
        for previous, proposed in cases:
            with self.subTest(previous=previous["scorecard"], proposed=proposed["scorecard"]):
                accepted, reasons = eval_package._monotonic_edit_decision(
                    previous, proposed
                )
                self.assertTrue(accepted)
                self.assertEqual(reasons, [])

    def test_lower_total_is_rejected_even_when_a_hard_gate_improves(self) -> None:
        previous = _evaluated_result((4, 5, 5, 5, 4), hard_gates_pass=False)
        proposed = _evaluated_result((4, 5, 5, 4, 4), hard_gates_pass=True)

        accepted, reasons = eval_package._monotonic_edit_decision(previous, proposed)

        self.assertFalse(accepted)
        self.assertIn("total-regressed-23-to-22", reasons)

    def test_voice_shortfall_gets_the_exact_canonical_repair_standard(self) -> None:
        scorecard = {
            "candidate_id": "candidate-2",
            "hook_strength": 4,
            "middle_escalation": 4,
            "earned_closer": 5,
            "specificity_and_source_quality": 4,
            "voice_fidelity": 3,
            "effective_total": 20,
        }
        result = {
            "scorecard": scorecard,
            "acceptance": {
                "axis_shortfalls": {
                    "voice_fidelity": {
                        "observed": 3,
                        "required": 4,
                        "shortfall": 1,
                    }
                }
            },
            "gates": _gate("candidate-2"),
            "factual_support_diagnostics": [],
            "anti_slop_findings": [],
        }

        feedback = eval_package._repair_feedback(2, result)
        standard = feedback["voice_repair_standard"]

        self.assertEqual(standard["current_score"], 3)
        self.assertEqual(standard["required_score"], 4)
        self.assertIn("AI scaffolding", standard["level_3"])
        self.assertIn("directly publishable", standard["level_4"])
        self.assertIn("stacked punchy fragments", standard["short_emphasis_rule"])
        self.assertIn(
            "It didn't misunderstand the rule",
            standard["calibration_examples"]["5"],
        )

    def test_parser_exposes_required_eval_only_inputs(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "eval-package",
                "--package",
                "outputs/2026-09-04/topic",
                "--strategy-input",
                "strategy.json",
                "--evidence-manifest",
                "data/private/evidence.json",
                "--db",
                "data/private/authority.sqlite",
                "--allow-model-egress",
            ]
        )

        self.assertEqual(args.command, "eval-package")
        self.assertIsNone(args.candidate)
        self.assertTrue(args.allow_model_egress)
        self.assertFalse(args.repair)

    def test_parser_exposes_explicit_progressive_repair(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "eval-package",
                "--package",
                "outputs/2026-09-04/topic",
                "--strategy-input",
                "strategy.json",
                "--evidence-manifest",
                "data/private/evidence.json",
                "--db",
                "data/private/authority.sqlite",
                "--allow-model-egress",
                "--candidate",
                "candidate-2",
                "--repair",
            ]
        )

        self.assertTrue(args.repair)
        self.assertEqual(args.candidate, "candidate-2")

    def test_command_calls_critic_once_and_never_calls_writer_or_revision(self) -> None:
        candidates = [_candidate(index) for index in range(1, 4)]
        brief = {
            "goal": "authority",
            "topic_slug": "topic",
            "goal_purpose": "purpose",
            "narrative_route": ["incident", "decision"],
            "target_reader": "product leaders",
            "reader_problem": "unclear ownership",
            "core_hypothesis": "ownership changes reliability",
            "product_decision": "name the owner",
            "authority_statement": "clear ownership matters",
            "strategy_input_origin": "explicit-input",
            "analysis": {
                "why_now": "now",
                "dominant_take": "common take",
                "missing_angle": "missing decision",
            },
        }
        evidence = [
            {
                "id": "source-1",
                "title": "Source",
                "claim": "Grounded claim",
                "source": "https://example.com/source",
                "source_quality": "primary",
                "body_read": True,
            }
        ]
        raw_scores = [
            {
                "candidate_id": candidate["id"],
                **{axis: 5 for axis in workflow.CRITIC_AXES},
            }
            for candidate in candidates
        ]
        context = {
            "package_path": workflow.REPO_ROOT / "outputs" / "2026-09-04" / "topic",
            "manifest": {"package_id": "2026-09-04-topic"},
            "brief": brief,
            "evidence": evidence,
            "proof": None,
            "all_candidates": candidates,
            "selected_candidates": candidates,
        }
        captured: dict[str, object] = {}

        def persist(**kwargs: object) -> tuple[Path, Path, Path, bool]:
            captured.update(kwargs)
            return (
                workflow.REPO_ROOT / "eval.json",
                workflow.REPO_ROOT / "run.json",
                workflow.REPO_ROOT / "eval.html",
                False,
            )

        args = SimpleNamespace(allow_model_egress=True)
        with (
            patch.object(eval_package, "_load_context", return_value=context),
            patch.object(
                eval_package,
                "_rubric_identity",
                return_value={"path": "config/current.json", "rubric_id": "current", "sha256": "a" * 64},
            ),
            patch.object(workflow, "invoke_critic", return_value=raw_scores) as critic,
            patch.object(
                workflow,
                "evaluate_candidate_set_gates",
                return_value=[_gate(str(candidate["id"])) for candidate in candidates],
            ),
            patch.object(workflow, "invoke_writer", side_effect=AssertionError("Writer called")),
            patch.object(
                workflow,
                "invoke_writer_revision",
                side_effect=AssertionError("Writer revision called"),
            ),
            patch.object(
                workflow,
                "run_critic_review",
                side_effect=AssertionError("revision review called"),
            ),
        ):
            self.assertEqual(eval_package.command(args, persist=persist), 0)

        critic.assert_called_once()
        self.assertEqual(critic.call_args.args[0], candidates)
        results = captured["results"]
        self.assertIsInstance(results, list)
        self.assertTrue(all(item["acceptance"]["status"] == "PASS" for item in results))
        self.assertEqual(
            results[0]["acceptance"]["contract_version"],
            acceptance_policy.ACCEPTANCE_CONTRACT_VERSION,
        )

    def test_progressive_repair_stops_before_editor_when_baseline_passes(self) -> None:
        context = _repair_context()
        captured: dict[str, object] = {}

        def persist(**kwargs: object) -> tuple[Path, Path, Path, bool]:
            captured.update(kwargs)
            return (
                workflow.REPO_ROOT / "eval.json",
                workflow.REPO_ROOT / "run.json",
                workflow.REPO_ROOT / "eval.html",
                False,
            )

        args = SimpleNamespace(
            allow_model_egress=True, repair=True, candidate="candidate-2"
        )
        editor = Mock(side_effect=AssertionError("editor called"))
        with (
            patch.object(eval_package, "_load_context", return_value=context),
            patch.object(
                eval_package,
                "_rubric_identity",
                return_value={
                    "path": "config/current.json",
                    "rubric_id": "current",
                    "sha256": "a" * 64,
                },
            ),
            patch.object(
                workflow,
                "evaluate_candidate_set_gates",
                return_value=[
                    _gate(str(candidate["id"]))
                    for candidate in context["all_candidates"]
                ],
            ),
            patch.object(
                workflow, "candidate_factual_support_diagnostics", return_value=[]
            ),
        ):
            result = eval_package.command(
                args,
                persist=persist,
                score_provider=lambda *_args, **_kwargs: _raw_score((4, 4, 4, 3, 4)),
                editor=editor,
            )

        self.assertEqual(result, 0)
        editor.assert_not_called()
        self.assertEqual(len(captured["repair_history"]), 1)

    def test_progressive_repair_keeps_one_monotonic_candidate_lineage(self) -> None:
        context = _repair_context()
        scores = iter(
            (
                _raw_score((3, 4, 5, 4, 3)),
                _raw_score((4, 3, 5, 4, 3)),
                _raw_score((4, 4, 5, 4, 3)),
                _raw_score((4, 4, 5, 4, 4)),
            )
        )
        editor_inputs: list[str] = []
        edit_number = 0
        captured: dict[str, object] = {}

        def score_provider(*_args: object, **_kwargs: object):
            return next(scores)

        def editor(candidate: object, *_args: object, **_kwargs: object):
            nonlocal edit_number
            self.assertIsInstance(candidate, dict)
            editor_inputs.append(str(candidate["text"]))
            edit_number += 1
            return {
                **candidate,
                "text": f"progressive revision {edit_number}",
            }

        def persist(**kwargs: object) -> tuple[Path, Path, Path, bool]:
            captured.update(kwargs)
            return (
                workflow.REPO_ROOT / "eval.json",
                workflow.REPO_ROOT / "run.json",
                workflow.REPO_ROOT / "eval.html",
                False,
            )

        args = SimpleNamespace(
            allow_model_egress=True, repair=True, candidate="candidate-2"
        )
        with (
            patch.object(eval_package, "_load_context", return_value=context),
            patch.object(
                eval_package,
                "_rubric_identity",
                return_value={
                    "path": "config/current.json",
                    "rubric_id": "current",
                    "sha256": "a" * 64,
                },
            ),
            patch.object(
                workflow,
                "evaluate_candidate_set_gates",
                return_value=[
                    _gate(str(candidate["id"]))
                    for candidate in context["all_candidates"]
                ],
            ),
            patch.object(
                workflow, "candidate_factual_support_diagnostics", return_value=[]
            ),
            patch.object(
                workflow,
                "validate_draft_candidates",
                side_effect=lambda candidates, **_kwargs: [
                    dict(candidate) for candidate in candidates
                ],
            ),
        ):
            result = eval_package.command(
                args,
                persist=persist,
                score_provider=score_provider,
                editor=editor,
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(editor_inputs), 3)
        self.assertEqual(editor_inputs[0], _candidate(2)["text"])
        self.assertEqual(editor_inputs[1], "progressive revision 1")
        self.assertEqual(editor_inputs[2], "progressive revision 1")
        history = captured["repair_history"]
        self.assertEqual(len(history), 4)
        self.assertTrue(history[1]["accepted_as_next_seed"])
        self.assertIn(
            "monotonic-improvement",
            history[1]["editorial_decision_reasons"],
        )
        self.assertFalse(history[2]["accepted_as_next_seed"])
        self.assertTrue(history[3]["accepted_as_next_seed"])
        final = captured["results"][0]
        self.assertEqual(final["candidate_id"], "candidate-2")
        self.assertEqual(final["scorecard"]["effective_total"], 21)
        self.assertEqual(final["acceptance"]["status"], "PASS")

    def test_unsupported_wording_gets_one_advisory_rewrite(self) -> None:
        context = _repair_context()
        captured: dict[str, object] = {}

        def persist(**kwargs: object) -> tuple[Path, Path, Path, bool]:
            captured.update(kwargs)
            return (
                workflow.REPO_ROOT / "eval.json",
                workflow.REPO_ROOT / "run.json",
                workflow.REPO_ROOT / "eval.html",
                False,
            )

        def editor(candidate: object, *_args: object, **_kwargs: object):
            self.assertIsInstance(candidate, dict)
            return {**candidate, "text": "A grounded edit that still fails honesty."}

        args = SimpleNamespace(
            allow_model_egress=True, repair=True, candidate="candidate-2"
        )
        with (
            patch.object(eval_package, "_load_context", return_value=context),
            patch.object(
                eval_package,
                "_rubric_identity",
                return_value={
                    "path": "config/current.json",
                    "rubric_id": "current",
                    "sha256": "a" * 64,
                },
            ),
            patch.object(
                workflow,
                "evaluate_candidate_set_gates",
                side_effect=lambda candidates, **_kwargs: [
                    _failed_honesty_gate(str(candidate["id"]))
                    for candidate in candidates
                ],
            ),
            patch.object(
                workflow, "candidate_factual_support_diagnostics", return_value=[]
            ),
            patch.object(
                workflow,
                "validate_draft_candidates",
                side_effect=lambda candidates, **_kwargs: [
                    dict(candidate) for candidate in candidates
                ],
            ),
        ):
            result = eval_package.command(
                args,
                persist=persist,
                score_provider=lambda *_args, **_kwargs: _raw_score((4, 5, 5, 5, 4)),
                editor=editor,
            )

        self.assertEqual(result, 0)
        history = captured["repair_history"]
        self.assertEqual(len(history), 2)
        self.assertFalse(history[1]["accepted_as_next_seed"])
        self.assertEqual(captured["results"][0]["candidate"]["text"], context["selected_candidates"][0]["text"])
        self.assertEqual(history[0]["acceptance"]["status"], "PASS")
        self.assertTrue(history[0]["acceptance"]["advisory_warnings"])
        self.assertFalse(captured["results"][0]["gates"]["passes_required_gates"])
        self.assertEqual(captured["results"][0]["acceptance"]["status"], "PASS")

    def test_rubric_identity_hashes_the_current_loaded_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rubric_path = Path(temporary) / "rubric.json"
            raw = json.dumps({"rubric_id": "current-test"}).encode("utf-8")
            rubric_path.write_bytes(raw)
            with (
                patch.object(workflow, "CRITIC_RUBRIC_PATH", rubric_path),
                patch.object(workflow, "critic_scoring_system_prompt") as loader,
            ):
                identity = eval_package._rubric_identity()

        loader.assert_called_once_with()
        self.assertEqual(identity["rubric_id"], "current-test")
        self.assertEqual(identity["sha256"], hashlib.sha256(raw).hexdigest())

    def test_acceptance_identity_is_the_approved_file_not_a_parallel_target(self) -> None:
        identity = eval_package._acceptance_identity()

        self.assertEqual(identity["status"], "APPROVED")
        self.assertEqual(
            identity["minimum_total"], acceptance_policy.ACCEPTABLE_QUALITY_FLOOR
        )
        self.assertEqual(identity["axis_floors"], dict(acceptance_policy.AXIS_FLOORS))
        self.assertNotIn("quality_target", identity)
        contract_path = workflow.REPO_ROOT / str(identity["path"])
        self.assertEqual(identity["sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
