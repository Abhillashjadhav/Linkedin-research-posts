"""Tests for Topic Value and advisory narrative-spine routing in daily discovery."""

from __future__ import annotations

import json
import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_cli, daily_spine_cli, topic_value, workflow


def profile() -> dict[str, object]:
    return {
        "target_audience": "Senior AI product leaders",
        "authority_goal": "Practical judgment for production AI",
        "proof_inventory": [
            {
                "id": "proof-repo",
                "label": "Public repository",
                "public_safe_claim": "A public repository demonstrates the workflow.",
                "evidence_type": "repository",
            }
        ],
        "avoid_topics": [],
        "recent_theses": [],
    }


def signals() -> list[dict[str, object]]:
    return [
        {
            "id": f"signal-{index}",
            "title": f"Agent reliability update {index}",
            "body": "A primary source describes a current product decision.",
            "source": "Research lab",
            "published_at": "2026-08-17T00:00:00Z",
            "source_quality": "primary",
            "canonical_url": f"https://example.com/{index}",
        }
        for index in range(1, 4)
    ]


def value_candidates() -> list[dict[str, object]]:
    return [
        {
            "id": f"topic-{index}",
            "source_ids": [f"signal-{index}"],
            "situation": f"A concrete agent reliability situation {index} changed a release decision.",
            "what_changed": "A release decision now requires inspectable evidence.",
            "who_cares": "Senior AI product leaders.",
            "reader_value_type": "DECISION_CHANGE",
            "reader_value": "A reusable release decision changes.",
            "gravity": "HIGH",
            "authority_add": "Translate the evidence into a production operating rule.",
            "brand_strip_pass": True,
            "feed_value_possible": True,
            "supports_authority_goal": True,
            "scores": {
                "reader_relevance": 5,
                "reader_value": 5,
                "gravity": 5,
                "evidence_strength": 5,
                "authority_fit": 5,
            },
            "status": "PASS",
            "diagnosis": "Strong material.",
            "total": 25,
            "priority": "FLAGSHIP",
        }
        for index in range(1, 4)
    ]


def cards() -> list[dict[str, object]]:
    spines = (
        "counterposition",
        "failure_reversal",
        "research_discovery",
    )
    return [
        {
            "id": f"thesis-{index}",
            "signal_ids": [f"signal-{index}"],
            "topic": f"Agent reliability update {index}",
            "thesis": f"Thesis {index}: autonomy should earn its next step.",
            "why_now": "A current signal makes the decision timely.",
            "reader_problem": "Leaders need a safe rollout decision.",
            "product_decision": "Require evidence before expanding autonomy.",
            "proof_id": "proof-repo",
            "remembered_for": "Connecting agent mechanics to product decisions.",
            "plain_language_summary": f"Agents should earn step {index} with evidence.",
            "conversation_surface": (
                "Autonomy versus reversibility in production systems."
            ),
            "recommended_spine": spines[index - 1],
            "spine_fit_reason": (
                "The evidence naturally exposes a decision that practitioners can challenge."
            ),
        }
        for index in range(1, 4)
    ]


class SpineCardTests(unittest.TestCase):
    def test_dashboard_uses_accepted_edit_when_total_ties_earlier_failure(self) -> None:
        rows = []
        for artifact, hook, accepted in (("old", 3, False), ("new", 5, True)):
            rows.extend([
                {"contract": "critic_total", "status": "PASS", "artifact_sha256": artifact,
                 "evidence": {"score": 22, "axes": {axis: hook if axis == "hook_strength" else 4 for axis in workflow.CRITIC_AXES}}},
                {"contract": "hook_strength", "status": "PASS" if accepted else "FAIL", "artifact_sha256": artifact,
                 "reason": f"hook={hook}", "evidence": {"score": hook}},
                {"contract": "candidate_acceptance", "status": "PASS" if accepted else "FAIL", "artifact_sha256": artifact},
            ])
        with redirect_stdout(io.StringIO()):
            result = daily_spine_cli.render_eval_dashboard(rows)
        hook = next(item for item in result["checks"] if item["contract"] == "hook_strength")
        self.assertEqual(hook["status"], "PASS")
        self.assertEqual(hook["evidence"]["score"], 5)

    def test_dashboard_versions_report_the_live_v2_critic_rubric(self) -> None:
        versions = daily_spine_cli.evaluator_versions()
        rubrics = versions["rubrics"]
        self.assertIn("critic-rubric-v2.json", rubrics)
        self.assertNotIn("critic-rubric-v1.json", rubrics)
        self.assertEqual(
            versions["acceptance"],
            {
                "contract_version": "five-axis-v8",
                "floor": 17,
                "axis_floors": {
                    "hook_strength": 4,
                    "middle_escalation": 3,
                    "earned_closer": 3,
                    "specificity_and_source_quality": 3,
                    "voice_fidelity": 4,
                },
            },
        )

    def test_topic_value_dashboard_observer_persists_both_labelled_stages(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=workflow.DEFAULT_PRIVATE_DATA
        ) as temporary:
            folder = Path(temporary)
            dashboard = daily_spine_cli.new_run_dashboard("observer-test")
            observer = daily_spine_cli.TopicValueDashboardObserver(
                dashboard,
                folder,
            )
            pre_gate = value_candidates()
            post_gate = value_candidates()
            for item in post_gate:
                item["v1_evals"] = {
                    "atomic_value_novelty": {
                        "contract": "atomic_value_novelty",
                        "mode": "enforce",
                        "status": "PASS",
                        "reason": "materially-new-atomic-value",
                    }
                }

            observer("pre-gate", pre_gate)
            observer("post-gate", post_gate)

            pre_path = folder / "topic-value-evaluations-pre-gate.json"
            post_path = folder / "topic-value-evaluations-post-gate.json"
            self.assertEqual(
                json.loads(pre_path.read_text())["observation_stage"], "pre-gate"
            )
            self.assertEqual(
                json.loads(post_path.read_text())["observation_stage"], "post-gate"
            )
            self.assertEqual(stat.S_IMODE(pre_path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(post_path.stat().st_mode), 0o600)
            stages = [
                item["details"]["observation_stage"]
                for item in dashboard["decisions"]
            ]
            self.assertEqual(stages.count("pre-gate"), 3)
            self.assertEqual(stages.count("post-gate"), 3)

    def test_topic_value_observation_failure_is_non_blocking_and_explicit(self) -> None:
        dashboard = daily_spine_cli.new_run_dashboard("observer-failure")
        observer = daily_spine_cli.TopicValueDashboardObserver(
            dashboard,
            workflow.DEFAULT_PRIVATE_DATA,
        )
        with patch.object(
            daily_spine_cli,
            "record_topic_value_decisions",
            side_effect=RuntimeError("dashboard disk unavailable"),
        ):
            topic_value._notify_observer(observer, "pre-gate", value_candidates())

        failure = dashboard["decisions"][-1]
        self.assertEqual(failure["decision"], "observability_failure")
        self.assertEqual(failure["status"], "UNAVAILABLE")
        self.assertIn("dashboard disk unavailable", failure["observed"])

    def test_failed_child_reason_reaches_drafting_dashboard_and_private_log(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            folder = Path(temporary)
            output = io.StringIO()
            with redirect_stdout(output):
                result = daily_spine_cli.run_drafting_child(
                    [
                        sys.executable,
                        "-c",
                        "import sys; print('ERROR: old'); print('working'); print('ERROR: x'); sys.exit(2)",
                    ],
                    cwd=workflow.REPO_ROOT,
                    folder=folder,
                )
            dashboard = daily_spine_cli.new_run_dashboard()
            daily_spine_cli.record_drafting_stage(
                dashboard,
                result,
                post_evaluated=False,
            )
            drafting = next(
                item for item in dashboard["checks"] if item["stage"] == "drafting"
            )
            log = folder / "drafting.log"
            self.assertEqual(result.returncode, 2)
            self.assertIn("ERROR: x", drafting["reason"])
            self.assertIn("ERROR: x", output.getvalue())
            self.assertEqual(
                log.read_text(encoding="utf-8"),
                "ERROR: old\nworking\nERROR: x\n",
            )
            self.assertEqual(stat.S_IMODE(os.stat(log).st_mode), 0o600)
            self.assertEqual(dashboard["drafting"]["captured_tail"][-1], "ERROR: x")

    def test_successful_child_still_marks_drafting_pass(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            result = daily_spine_cli.run_drafting_child(
                [sys.executable, "-c", "print('completed')"],
                cwd=workflow.REPO_ROOT,
                folder=Path(temporary),
            )
            dashboard = daily_spine_cli.new_run_dashboard()
            daily_spine_cli.record_drafting_stage(
                dashboard,
                result,
                post_evaluated=False,
            )
        drafting = next(
            item for item in dashboard["checks"] if item["stage"] == "drafting"
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(drafting["status"], "PASS")

    def test_delivery_warnings_survive_ledger_dashboard_and_html(self) -> None:
        from authority_os import eval_dashboard_html, v1_completion
        artifact = "a" * 64
        rows = [
            v1_completion._decision_row(
                {"contract": contract, "mode": "enforce", "status": "FAIL",
                 "reason": "voice below target", "score": 3},
                stage="quality-cycle-4", artifact_sha256=artifact,
            )
            for contract in ("voice_fidelity", "candidate_acceptance")
        ]
        rows.append(v1_completion._decision_row(
            {"contract": "draft_delivery", "mode": "diagnostic", "status": "PASS",
             "observed_status": "COMPLETED_WITH_WARNINGS", "reason": "draft delivered"},
            stage="draft-delivery", artifact_sha256=artifact,
        ))
        evaluation = daily_spine_cli.render_eval_dashboard(rows)
        dashboard = daily_spine_cli.new_run_dashboard()
        outcome = daily_spine_cli.finalize_draft_evaluation(
            dashboard, evaluation, return_code=0, failure_reason="unused",
        )
        dashboard["outcome"] = outcome
        self.assertEqual(outcome, "COMPLETED_WITH_WARNINGS")
        voice = next(c for c in evaluation["checks"] if c["contract"] == "voice_fidelity")
        self.assertEqual(voice["status"], "FAIL")
        self.assertEqual(voice["mode"], "diagnostic")
        self.assertEqual(dashboard["decisions"][-1]["status"], outcome)
        rendered = eval_dashboard_html.render_dashboard(dashboard, evaluation)
        self.assertIn('verdict incomplete">COMPLETED_WITH_WARNINGS', rendered)
        self.assertIn("No blocker recorded", rendered)
        self.assertIsNone(dashboard.get("stopped_at"))

    def test_final_evaluation_ignores_advisories_but_preserves_errors(self) -> None:
        for mode, return_code, expected in (
            ("diagnostic", 0, "PASS"), ("shadow", 0, "PASS"),
            ("enforce", 0, "FAIL"), ("diagnostic", 2, "FAIL"),
        ):
            with self.subTest(mode=mode, return_code=return_code):
                dashboard = daily_spine_cli.new_run_dashboard()
                outcome = daily_spine_cli.finalize_draft_evaluation(
                    dashboard,
                    {"checks": [{"contract": "honesty", "label": "Honesty",
                                 "status": "FAIL", "mode": mode, "reason": "finding"}]},
                    return_code=return_code, failure_reason="provider unavailable",
                )
                self.assertEqual(outcome, expected)
        dashboard = daily_spine_cli.new_run_dashboard()
        self.assertEqual(daily_spine_cli.finalize_draft_evaluation(
            dashboard, {"checks": [], "delivery_outcome": "COMPLETED_WITH_WARNINGS"},
            return_code=1, failure_reason="write failed",
        ), "FAIL")

    def test_run_dashboard_names_first_failed_stage_and_unreached_downstream(self) -> None:
        dashboard = daily_spine_cli.new_run_dashboard()
        daily_spine_cli.mark_run_stage(
            dashboard,
            "conversation_discovery",
            "PASS",
            "ranked",
            ranked_count=10,
        )
        daily_spine_cli.mark_run_stage(
            dashboard,
            "thesis_search",
            "FAIL",
            "No thesis cleared the authority bar.",
        )
        by_stage = {item["stage"]: item for item in dashboard["checks"]}
        self.assertEqual(dashboard["stopped_at"], "thesis_search")
        self.assertEqual(by_stage["conversation_discovery"]["status"], "PASS")
        self.assertEqual(by_stage["thesis_search"]["status"], "FAIL")
        self.assertEqual(by_stage["drafting"]["status"], "NOT_EVALUATED")

    def test_first_blocker_is_not_overwritten_by_a_downstream_failure(self) -> None:
        dashboard = daily_spine_cli.new_run_dashboard()
        daily_spine_cli.mark_run_stage(
            dashboard,
            "drafting",
            "FAIL",
            "ERROR: writer contract mismatch",
            expected="valid writer output",
            observed="invalid writer output",
        )
        daily_spine_cli.mark_run_stage(
            dashboard,
            "final_evals",
            "FAIL",
            "Critic was not reached",
        )

        self.assertEqual(dashboard["stopped_at"], "drafting")
        self.assertEqual(len(dashboard["decisions"]), 2)
        first = dashboard["decisions"][0]
        self.assertEqual(first["expected"], "valid writer output")
        self.assertEqual(first["observed"], "invalid writer output")
        self.assertIn("writer contract mismatch", first["reason"])

    def test_eval_dashboard_marks_unreached_stages_explicitly(self) -> None:
        dashboard = daily_spine_cli.render_eval_dashboard(
            [
                {
                    "contract": "research_trust",
                    "status": "PASS",
                    "reason": "body-read-source-present",
                }
            ]
        )
        by_contract = {
            item["contract"]: item for item in dashboard["checks"]
        }
        self.assertEqual(by_contract["research_trust"]["status"], "PASS")
        self.assertEqual(
            by_contract["reader_attention"]["status"],
            "NOT_EVALUATED",
        )
        self.assertEqual(by_contract["hook_strength"]["category"], "post_quality")

    def test_eval_dashboard_preserves_each_ledger_decision_with_threshold(self) -> None:
        dashboard = daily_spine_cli.render_eval_dashboard(
            [
                {
                    "stage": "quality-cycle-1",
                    "contract": "critic_total",
                    "status": "FAIL",
                    "reason": "critic-score-21-of-25",
                    "subject_id": "candidate-1",
                    "evidence": {"score": 21, "threshold": 22},
                },
                {
                    "stage": "quality-cycle-2",
                    "contract": "critic_total",
                    "status": "PASS",
                    "reason": "critic-score-24-of-25",
                    "subject_id": "candidate-1",
                    "evidence": {"score": 24, "threshold": 22},
                },
            ]
        )

        self.assertEqual(len(dashboard["decisions"]), 2)
        self.assertEqual(dashboard["decisions"][0]["expected"], "score >= 22 under the locked contract")
        self.assertIn("score=21", dashboard["decisions"][0]["observed"])

    def test_eval_dashboard_keeps_best_observed_post_score_across_cycles(self) -> None:
        dashboard = daily_spine_cli.render_eval_dashboard(
            [
                {"contract": "critic_total", "status": "PASS", "reason": "25", "artifact_sha256": "a" * 64, "subject_id": "candidate-3", "evidence": {"score": 25}},
                {"contract": "hook_strength", "status": "PASS", "reason": "5", "artifact_sha256": "a" * 64, "subject_id": "candidate-3", "evidence": {"score": 5}},
                {"contract": "critic_total", "status": "PASS", "reason": "22", "artifact_sha256": "b" * 64, "subject_id": "candidate-2", "evidence": {"score": 22}},
                {"contract": "hook_strength", "status": "FAIL", "reason": "4", "artifact_sha256": "b" * 64, "subject_id": "candidate-2", "evidence": {"score": 4}},
            ]
        )
        by_contract = {item["contract"]: item for item in dashboard["checks"]}
        self.assertEqual(by_contract["critic_total"]["reason"], "25")
        self.assertEqual(by_contract["hook_strength"]["reason"], "5")
        self.assertEqual(by_contract["hook_strength"]["subject_id"], "candidate-3")

    def test_eval_dashboard_keeps_all_critic_axes_and_acceptance_failures(self) -> None:
        artifact = "a" * 64
        dashboard = daily_spine_cli.render_eval_dashboard(
            [
                {
                    "contract": "critic_total",
                    "status": "PASS",
                    "reason": "critic-score-24-of-25",
                    "artifact_sha256": artifact,
                    "subject_id": "candidate-3",
                    "evidence": {
                        "score": 24,
                        "threshold": 22,
                        "cycle": 2,
                        "axes": {
                            "hook_strength": 5,
                            "middle_escalation": 5,
                            "earned_closer": 5,
                            "specificity_and_source_quality": 5,
                            "voice_fidelity": 4,
                        },
                        "failure_codes": [],
                    },
                },
                {
                    "contract": "candidate_acceptance",
                    "status": "FAIL",
                    "reason": "package-recommendation:none!=candidate:candidate-3",
                    "artifact_sha256": artifact,
                    "subject_id": "candidate-3",
                    "evidence": {
                        "failure_codes": [
                            "package-recommendation:none!=candidate:candidate-3"
                        ]
                    },
                },
            ]
        )

        self.assertEqual(len(dashboard["critic_scorecards"]), 1)
        scorecard = dashboard["critic_scorecards"][0]
        self.assertEqual(scorecard["cycle"], 2)
        self.assertEqual(scorecard["axes"]["voice_fidelity"], 4)
        self.assertIn("package-recommendation:none", scorecard["failure_codes"][0])

    def test_scorecard_requires_every_axis_floor_despite_total_pass(self) -> None:
        baseline = dict(zip(workflow.CRITIC_AXES, (4, 4, 3, 3, 4)))
        cases = [(baseline, "PASS")]
        for axis, floor in daily_spine_cli.acceptance_policy.AXIS_FLOORS.items():
            axes = {key: 5 for key in baseline}
            axes[axis] = floor - 1
            cases.append((axes, "FAIL"))
        cases.append((dict(zip(workflow.CRITIC_AXES, (3, 4, 5, 5, 4))), "FAIL"))
        for axes, expected in cases:
            with self.subTest(axes=axes), redirect_stdout(io.StringIO()):
                dashboard = daily_spine_cli.render_eval_dashboard([{
                    "contract": "critic_total", "status": "PASS",
                    "subject_id": "candidate-1", "artifact_sha256": "a" * 64,
                    "evidence": {"score": sum(axes.values()), "axes": axes},
                }])
                card = dashboard["critic_scorecards"][0]
                self.assertEqual(card["status"], expected)
                self.assertEqual(card["total_status"], "PASS")
                if expected == "FAIL":
                    self.assertTrue(card["failure_codes"])

    def test_thesis_search_keeps_a_qualifying_leader_from_a_mixed_batch(self) -> None:
        mixed_scores = [
            {
                "thesis_id": "thesis-1",
                "audience_fit": 5,
                "distinctiveness": 5,
                "decision_strength": 5,
                "proof_fit": 4,
                "simplicity": 4,
                "total": 23,
            },
            {
                "thesis_id": "thesis-2",
                "audience_fit": 5,
                "distinctiveness": 4,
                "decision_strength": 4,
                "proof_fit": 4,
                "simplicity": 4,
                "total": 21,
            },
            {
                "thesis_id": "thesis-3",
                "audience_fit": 4,
                "distinctiveness": 4,
                "decision_strength": 4,
                "proof_fit": 4,
                "simplicity": 4,
                "total": 20,
            },
        ]
        with patch.object(
            daily_spine_cli,
            "generate_cards",
            return_value=cards(),
        ) as generate, patch.object(
            daily_spine_cli.base,
            "score_cards",
            return_value=mixed_scores,
        ):
            result = daily_spine_cli.search_theses(profile(), signals())
        self.assertEqual(generate.call_count, 1)
        self.assertEqual([item["id"] for item in result], ["thesis-1"])
        self.assertEqual(result[0]["total"], 23)

    def test_below_23_thesis_is_selected_by_rank_without_a_cutoff(self) -> None:
        weak_scores = [
            {
                "thesis_id": f"thesis-{index}",
                "audience_fit": 5,
                "distinctiveness": 4,
                "decision_strength": 4,
                "proof_fit": 4,
                "simplicity": 4,
                "total": 22 - index,
            }
            for index in range(1, 4)
        ]
        trace_path = workflow.REPO_ROOT / "data/private/test-thesis-evaluations.json"
        with patch.object(
            daily_spine_cli,
            "generate_cards",
            return_value=cards(),
        ), patch.object(
            daily_spine_cli.base,
            "score_cards",
            return_value=weak_scores,
        ), patch.object(
            daily_spine_cli.base,
            "MAX_CYCLES",
            1,
        ), patch.object(
            daily_spine_cli.base,
            "write_private_json",
            return_value=trace_path,
        ) as write:
            retained = daily_spine_cli.search_theses(
                profile(), signals(), trace_path=trace_path,
            )

        payload = write.call_args.args[1]
        self.assertEqual(payload["outcome"], "PASS")
        self.assertEqual(payload["thresholds"], {})
        self.assertEqual(payload["selected_id"], "thesis-1")
        self.assertEqual(retained, [payload["best_overall"]])
        self.assertTrue(retained[0]["selected"])
        self.assertEqual(len(payload["cycles"][0]["candidates"]), 3)
        self.assertEqual(payload["best_overall"]["id"], "thesis-1")
        self.assertNotIn("rejection_reasons", payload["best_overall"])

    def test_thesis_selection_never_spends_a_second_score_cycle(self) -> None:
        scores = [
            {"thesis_id": f"thesis-{i}", **{axis: 4 for axis in daily_spine_cli.base.AXES}, "total": 20}
            for i in range(1, 4)
        ]
        worse = [
            {**score, **{axis: 3 for axis in daily_spine_cli.base.AXES}, "total": 15}
            for score in scores
        ]
        with (
            patch.object(daily_spine_cli, "generate_cards", return_value=cards()) as generate,
            patch.object(daily_spine_cli.base, "score_cards", side_effect=[scores, worse]),
            patch.object(daily_spine_cli.base, "MAX_CYCLES", 2),
            redirect_stdout(io.StringIO()),
        ):
            retained = daily_spine_cli.search_theses(profile(), signals())
        self.assertEqual(generate.call_count, 1)
        self.assertEqual(retained[0]["total"], 20)
        self.assertTrue(retained[0]["selected"])

    def test_malformed_thesis_output_still_stops(self) -> None:
        with patch.object(daily_spine_cli, "generate_cards", side_effect=workflow.WorkflowError("invalid schema")):
            with self.assertRaisesRegex(workflow.WorkflowError, "invalid schema"):
                daily_spine_cli.search_theses(profile(), signals())

    def test_thesis_warning_survives_passing_draft_but_not_execution_error(self) -> None:
        for code, expected in ((0, "COMPLETED_WITH_WARNINGS"), (2, "FAIL")):
            dashboard = daily_spine_cli.new_run_dashboard()
            daily_spine_cli.mark_run_stage(
                dashboard, "thesis_search", "COMPLETED_WITH_WARNINGS", "total 21/25 below 23/25",
            )
            outcome = daily_spine_cli.finalize_draft_evaluation(
                dashboard, {"checks": []}, return_code=code, failure_reason="provider unavailable",
            )
            self.assertEqual(outcome, expected)
            self.assertEqual(dashboard["stopped_at"], "final_evals" if code else None)

    def test_discovery_continues_into_drafting_after_one_ranked_thesis_batch(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary, ExitStack() as stack:
            root = Path(temporary)
            output = root / "run"
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile()), encoding="utf-8")
            topic = {"id": "topic-1", "topic": "Agent reliability", "total": 20,
                     "observed_axes": 5, "authority_fit": {"total": 22},
                     "representative_urls": ["https://example.com/1"]}
            resume = daily_spine_cli.DiscoveryResume(
                root / "previous", "2026-09-08T09:04:06Z", (topic,), (topic,), "momentum-qualified", (),
            )
            stack.enter_context(patch.object(daily_spine_cli, "load_discovery_resume", return_value=resume))
            stack.enter_context(patch.object(daily_spine_cli, "resolve_signal_evidence", return_value=
                daily_spine_cli.EvidenceResolution(tuple(signals()), "fixture", 0, "fixture")))
            stack.enter_context(patch.object(daily_spine_cli.base, "project_signals", return_value=signals()))
            stack.enter_context(patch.object(daily_spine_cli.base.legacy_cli, "initialise_paths"))
            stack.enter_context(patch.object(daily_spine_cli.storage, "insert_research_items", return_value=(3, 0)))
            stack.enter_context(patch.object(topic_value, "invoke_discovery_selector", return_value=value_candidates()))
            stack.enter_context(patch.object(topic_value, "project_discovery_signals", return_value=signals()))
            stack.enter_context(patch.object(daily_spine_cli, "generate_cards", return_value=cards()))
            stack.enter_context(patch.object(daily_spine_cli.base, "score_cards", return_value=[
                {"thesis_id": f"thesis-{i}", **{axis: 4 for axis in daily_spine_cli.base.AXES}, "total": 20}
                for i in range(1, 4)
            ]))
            stack.enter_context(patch.object(daily_spine_cli.base, "MAX_CYCLES", 1))
            stack.enter_context(patch.object(daily_spine_cli.v1_completion, "_read_jsonl", return_value=[]))
            stack.enter_context(patch.object(workflow, "load_voice_guidance", return_value={}))
            stack.enter_context(patch.object(daily_spine_cli.eval_dashboard_html, "open_dashboard", return_value=False))
            child = stack.enter_context(patch.object(daily_spine_cli, "run_drafting_child", return_value=
                daily_spine_cli.DraftingRun(0, "completed", "fixture.log", ())))
            stack.enter_context(redirect_stdout(io.StringIO()))
            code = daily_spine_cli.main([
                "--profile", str(profile_path), "--resume-from", str(resume.source_folder),
                "--output-dir", str(output), "--db", str(root / "db.sqlite"),
                "--allow-web-research", "--allow-model-egress", "--generate-post",
            ])
            dashboard = json.loads((output / "run-dashboard.json").read_text())
            trace = json.loads((output / "thesis-evaluations.json").read_text())
            html = (output / "eval-dashboard.html").read_text()
        self.assertEqual(code, 0)
        child.assert_called_once()
        self.assertEqual(dashboard["outcome"], "PASS")
        self.assertIsNone(dashboard["stopped_at"])
        self.assertEqual(trace["selection_policy"], "highest-score-valid-thesis")
        self.assertEqual(len(trace["cycles"]), 1)
        self.assertEqual(trace["best_overall"]["total"], 20)
        self.assertIn("no score cutoff", html)
        # The mocked child emits no eval ledger: missing critic data stays visible.
        self.assertIn("INCOMPLETE", html)
        thesis_stage = next(item for item in dashboard["checks"] if item["stage"] == "thesis_search")
        self.assertEqual(thesis_stage["status"], "PASS")

    def test_authority_timeout_preserves_topics_and_reaches_drafting(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary, ExitStack() as stack:
            root = Path(temporary)
            output = root / "run"
            profile_path = root / "profile.json"
            profile_path.write_text(json.dumps(profile()), encoding="utf-8")
            topic = {"id": "topic-1", "topic": "Agent reliability", "total": 20,
                     "observed_axes": 5, "authority_fit": {"total": 22},
                     "representative_urls": ["https://example.com/1"]}
            topic.update(why_now="Current source evidence.", confidence="HIGH",
                         platforms=["Primary source"], caveats="Fixture")
            stack.enter_context(patch.object(daily_spine_cli.momentum, "invoke_scout", return_value=[topic]))
            stack.enter_context(patch.object(daily_spine_cli.momentum, "score_authority_fit",
                side_effect=daily_spine_cli.ModelTimeoutError("Authority topic critic timed out.")))
            update_inventory = daily_spine_cli.update_candidate_inventory
            stack.enter_context(patch.object(daily_spine_cli, "update_candidate_inventory",
                side_effect=lambda rows, **kw: update_inventory(rows, **kw, path=root / "inventory.json")))
            stack.enter_context(patch.object(daily_spine_cli, "resolve_signal_evidence", return_value=
                daily_spine_cli.EvidenceResolution(tuple(signals()), "fixture", 0, "fixture")))
            stack.enter_context(patch.object(daily_spine_cli.base, "project_signals", return_value=signals()))
            stack.enter_context(patch.object(daily_spine_cli.base.legacy_cli, "initialise_paths"))
            stack.enter_context(patch.object(daily_spine_cli.storage, "insert_research_items", return_value=(3, 0)))
            stack.enter_context(patch.object(topic_value, "invoke_discovery_selector", return_value=value_candidates()))
            stack.enter_context(patch.object(topic_value, "project_discovery_signals", return_value=signals()))
            stack.enter_context(patch.object(daily_spine_cli, "generate_cards", return_value=cards()))
            stack.enter_context(patch.object(daily_spine_cli.base, "score_cards", return_value=[
                {"thesis_id": f"thesis-{i}", **{axis: 4 for axis in daily_spine_cli.base.AXES}, "total": 20}
                for i in range(1, 4)
            ]))
            stack.enter_context(patch.object(daily_spine_cli.base, "MAX_CYCLES", 1))
            stack.enter_context(patch.object(daily_spine_cli.v1_completion, "_read_jsonl", return_value=[]))
            stack.enter_context(patch.object(workflow, "load_voice_guidance", return_value={}))
            stack.enter_context(patch.object(daily_spine_cli.eval_dashboard_html, "open_dashboard", return_value=False))
            child = stack.enter_context(patch.object(daily_spine_cli, "run_drafting_child", return_value=
                daily_spine_cli.DraftingRun(0, "completed", "fixture.log", ())))
            stack.enter_context(redirect_stdout(io.StringIO()))
            code = daily_spine_cli.main([
                "--profile", str(profile_path), "--as-of", "2026-09-08T09:04:06Z",
                "--output-dir", str(output), "--db", str(root / "db.sqlite"),
                "--allow-web-research", "--allow-model-egress", "--generate-post",
            ])
            dashboard = json.loads((output / "run-dashboard.json").read_text())
            trace = json.loads((output / "thesis-evaluations.json").read_text())
            html = (output / "eval-dashboard.html").read_text()
            self.assertTrue((output / "discovery-ranked.json").exists())
            checkpoint = json.loads((output / "authority-ranking.json").read_text())
            inventory = json.loads((root / "inventory.json").read_text())
            scope = json.loads((output / "admitted-topics.json").read_text())
        self.assertEqual(code, 0)
        child.assert_called_once()
        self.assertEqual(dashboard["outcome"], "COMPLETED_WITH_WARNINGS")
        self.assertIsNone(dashboard["stopped_at"])
        self.assertEqual(trace["selection_policy"], "highest-score-valid-thesis")
        self.assertEqual(len(trace["cycles"]), 1)
        self.assertEqual(trace["best_overall"]["total"], 20)
        self.assertIn("no score cutoff", html)
        self.assertEqual(checkpoint["authority_status"], "UNAVAILABLE")
        self.assertIsNone(checkpoint["candidates"][0]["authority_fit"])
        self.assertIsNone(inventory["candidates"][0]["combined_total"])
        self.assertIn("momentum only", scope["route"])
        self.assertIn("authority scorer timed out", html)
        thesis_stage = next(item for item in dashboard["checks"] if item["stage"] == "thesis_search")
        self.assertEqual(thesis_stage["status"], "PASS")

    def test_seven_day_pool_ranks_retained_and_fresh_together_without_floors(self) -> None:
        current = [
            {"topic": "Fresh popular", "total": 15, "observed_axes": 5,
             "authority_fit": {"total": 20}, "momentum_eligible": True,
             "representative_urls": ["https://example.com/fresh"]},
            {"topic": "Quiet strong idea", "total": 11, "observed_axes": 4,
             "authority_fit": {"total": 25}, "momentum_eligible": False,
             "representative_urls": ["https://example.com/quiet"]},
        ]
        inventory = [
            {"topic": "Earlier strong idea", "status": "AVAILABLE", "combined_total": 39,
             "representative_urls": ["https://example.com/earlier"]},
            {"topic": "Already used", "status": "USED", "combined_total": 50,
             "representative_urls": ["https://example.com/used"]},
            {"topic": "No evidence leads", "status": "AVAILABLE", "combined_total": 50},
        ]
        selected, route = daily_spine_cli.select_topic_scope(current, inventory)
        self.assertEqual(route, "ranked seven-day pool")
        self.assertEqual([item["topic"] for item in selected], [
            "Earlier strong idea", "Quiet strong idea", "Fresh popular",
        ])

    def test_small_pool_with_unknown_engagement_uses_common_authority_basis(self) -> None:
        topics = [{"topic": "Primary finding", "total": None,
                   "authority_fit": {"total": 22}, "representative_urls": ["https://example.com/primary"]},
                  {"topic": "Popular weaker finding", "total": 25,
                   "authority_fit": {"total": 18}, "representative_urls": ["https://example.com/other"]}]
        selected, route = daily_spine_cli.select_topic_scope(topics)
        self.assertEqual([item["topic"] for item in selected], ["Primary finding", "Popular weaker finding"])
        self.assertIn("authority only", route)
        self.assertIsNone(selected[0]["momentum_total"])
        self.assertIsNone(selected[0]["combined_total"])

    def test_live_theses_do_not_require_an_author_proof_inventory(self) -> None:
        raw_profile = profile()
        del raw_profile["proof_inventory"]
        validated = daily_cli.validate_profile(raw_profile)
        grounded = [{**card, "proof_id": "NOT_REQUIRED"} for card in cards()]
        with patch.object(daily_cli, "invoke_structured", return_value={"cards": grounded}) as invoke:
            selected = daily_spine_cli.generate_cards(validated, signals(), None)
        self.assertEqual(len(selected), 3)
        self.assertNotIn("proof_inventory", invoke.call_args.kwargs["task_prompt"])
        self.assertEqual(invoke.call_args.kwargs["schema"]["properties"]["cards"]["items"]["properties"]["proof_id"]["enum"], ["NOT_REQUIRED"])

    def test_inventory_retains_six_day_candidate_and_excludes_eight_day_candidate(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            path = Path(temporary) / "inventory.json"
            def entry(topic, timestamp):
                return {"topic": topic, "last_seen_at": timestamp,
                        "status": "AVAILABLE", "combined_total": 30,
                        "representative_urls": ["https://example.com/" + topic]}
            path.write_text(json.dumps({"candidates": [
                entry("six-days-old", "2026-09-02T09:00:00Z"),
                entry("eight-days-old", "2026-08-31T09:00:00Z"),
                entry("future", "2026-09-09T09:00:00Z"),
            ]}))
            _, retained = daily_spine_cli.update_candidate_inventory(
                [], as_of="2026-09-08T09:00:00Z", days=7, path=path,
            )
        self.assertEqual([item["topic"] for item in retained], ["six-days-old"])

    def test_generate_post_is_explicitly_opt_in(self) -> None:
        parsed = daily_spine_cli.parser().parse_args(
            [
                "--profile",
                "data/private/authority-profile.json",
                "--generate-post",
            ]
        )
        self.assertTrue(parsed.generate_post)
        self.assertEqual(parsed.days, 7)

    def test_thursday_is_exposed_as_authority_week_slot_three(self) -> None:
        parsed = daily_spine_cli.parser().parse_args(
            ["--profile", "data/private/authority-profile.json", "--week-slot", "3"]
        )
        self.assertEqual(parsed.week_slot, 3)
        with self.assertRaises(SystemExit):
            daily_spine_cli.parser().parse_args(
                ["--profile", "data/private/authority-profile.json", "--week-slot", "4"]
            )

    def test_candidate_inventory_keeps_scored_topics_below_40(self) -> None:
        candidates = [
            {
                "topic": "Qualified topic",
                "why_now": "Current evidence.",
                "total": 18,
                "authority_fit": {"total": 23},
                "representative_urls": ["https://example.com/qualified"],
            },
            {
                "topic": "Below floor",
                "why_now": "Current evidence.",
                "total": 16,
                "authority_fit": {"total": 23},
                "representative_urls": ["https://example.com/below"],
            },
        ]
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            daily_spine_cli.base,
            "_under_private",
            side_effect=lambda value: Path(value),
        ):
            target = Path(temporary) / "inventory.json"
            _, retained = daily_spine_cli.update_candidate_inventory(
                candidates,
                as_of="2026-09-02T12:00:00Z",
                days=7,
                path=target,
            )
            payload = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual([item["topic"] for item in retained], ["Qualified topic", "Below floor"])
        self.assertEqual(payload["candidates"][0]["combined_total"], 41)

    def test_extended_card_contract_accepts_only_stable_spines(self) -> None:
        validated = daily_spine_cli.validate_cards(cards(), signals(), profile())
        self.assertEqual(validated[0]["recommended_spine"], "counterposition")

        invalid = cards()
        invalid[0]["recommended_spine"] = "viral_story"
        with self.assertRaisesRegex(workflow.WorkflowError, "recommended_spine"):
            daily_spine_cli.validate_cards(invalid, signals(), profile())

    def test_spine_reason_is_required_and_bounded(self) -> None:
        blank = cards()
        blank[0]["spine_fit_reason"] = ""
        with self.assertRaisesRegex(workflow.WorkflowError, "spine_fit_reason"):
            daily_spine_cli.validate_cards(blank, signals(), profile())

        long = cards()
        long[0]["spine_fit_reason"] = "x" * 321
        with self.assertRaisesRegex(workflow.WorkflowError, "spine_fit_reason"):
            daily_spine_cli.validate_cards(long, signals(), profile())

    def test_three_corroborating_sources_survive_thesis_and_drafting_handoff(self) -> None:
        supplied = cards()
        supplied[0]["signal_ids"] = ["signal-1", "signal-2", "signal-3"]
        retained = daily_spine_cli.validate_cards(supplied, signals(), profile())
        manifest = daily_spine_cli.base.evidence_manifest_for(retained[0], signals(), signals())
        self.assertEqual(manifest["source_urls"], [f"https://example.com/{i}" for i in range(1, 4)])
        self.assertEqual(daily_spine_cli._schema("cards")["properties"]["cards"]["items"]["properties"]["signal_ids"]["maxItems"], 7)

    def test_missing_authority_uses_a_common_momentum_basis_without_zero_imputation(self) -> None:
        selected, route = daily_spine_cli.select_topic_scope([
            {"topic": "Unscored authority", "total": 15, "authority_fit": None,
             "representative_urls": ["https://example.com/one"]},
            {"topic": "Known authority", "total": 10, "authority_fit": {"total": 25},
             "representative_urls": ["https://example.com/two"]},
        ])
        self.assertIn("momentum only", route)
        self.assertEqual(selected[0]["topic"], "Unscored authority")
        self.assertIsNone(selected[0]["combined_total"])
        self.assertEqual(selected[1]["combined_total"], 35)

    def test_schema_exposes_exact_five_spines(self) -> None:
        schema = daily_spine_cli._schema("cards")
        enum = schema["properties"]["cards"]["items"]["properties"][
            "recommended_spine"
        ]["enum"]
        self.assertEqual(tuple(enum), daily_spine_cli.CONTENT_SPINES)

    def test_generation_marks_spine_as_advisory_not_weekday_routing(self) -> None:
        with patch.object(
            daily_spine_cli.base,
            "invoke_structured",
            return_value={"cards": cards()},
        ) as invoke:
            result = daily_spine_cli.generate_cards(profile(), signals(), None)
        self.assertEqual(len(result), 3)
        prompt = str(invoke.call_args.kwargs["task_prompt"]).casefold()
        self.assertIn("spine is advisory only", prompt)
        self.assertIn("do not force a template", prompt)
        self.assertIn("do not draft a post", prompt)
        self.assertIn("weekday", prompt)

    def test_thesis_generation_receives_only_topic_value_selected_signals(self) -> None:
        selected = topic_value.project_discovery_signals(signals(), value_candidates())
        self.assertTrue(all("topic_value" in signal for signal in selected))
        with patch.object(
            daily_spine_cli.base,
            "invoke_structured",
            return_value={"cards": cards()},
        ) as invoke:
            daily_spine_cli.generate_cards(profile(), selected, None)
        prompt = str(invoke.call_args.kwargs["task_prompt"]).casefold()
        self.assertIn("topic-value-selected signals", prompt)
        self.assertIn("preserve that selected reader value", prompt)
        self.assertIn("flagship", prompt)

    def test_downstream_strategy_contract_remains_five_fields(self) -> None:
        card = daily_spine_cli.validate_cards(cards(), signals(), profile())[0]
        strategy = daily_spine_cli.base.strategy_for(card, profile())
        self.assertEqual(
            set(strategy),
            {
                "target_reader",
                "reader_problem",
                "core_hypothesis",
                "product_decision",
                "authority_statement",
            },
        )
        self.assertNotIn("recommended_spine", strategy)

    def test_thesis_evidence_manifest_carries_only_selected_source_urls(self) -> None:
        card = daily_spine_cli.validate_cards(cards(), signals(), profile())[0]
        card["signal_ids"] = ["signal-1", "signal-2"]
        items = [
            {
                "canonical_url": signal["canonical_url"],
                "content_hash": f"{index:064x}",
            }
            for index, signal in enumerate(signals(), start=1)
        ]
        manifest = daily_spine_cli.base.evidence_manifest_for(
            card,
            signals(),
            items,
        )
        self.assertEqual(manifest["thesis_id"], "thesis-1")
        self.assertEqual(manifest["display_topic"], card["topic"])
        self.assertEqual(
            manifest["source_urls"],
            ["https://example.com/1", "https://example.com/2"],
        )
        self.assertEqual(manifest["schema_version"], 2)
        self.assertNotIn("evidence", manifest)


if __name__ == "__main__":
    unittest.main()
