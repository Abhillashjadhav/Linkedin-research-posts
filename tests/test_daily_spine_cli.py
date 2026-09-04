"""Tests for Topic Value and advisory narrative-spine routing in daily discovery."""

from __future__ import annotations

import json
import io
import os
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli, topic_value, workflow


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
    def test_dashboard_versions_report_the_live_v2_critic_rubric(self) -> None:
        versions = daily_spine_cli.evaluator_versions()
        rubrics = versions["rubrics"]
        self.assertIn("critic-rubric-v2.json", rubrics)
        self.assertNotIn("critic-rubric-v1.json", rubrics)
        self.assertEqual(
            versions["acceptance"],
            {
                "contract_version": "five-axis-v2",
                "floor": 18,
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

    def test_failed_thesis_search_persists_every_score_and_best_overall(self) -> None:
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
            with self.assertRaisesRegex(workflow.WorkflowError, "No thesis cleared"):
                daily_spine_cli.search_theses(
                    profile(),
                    signals(),
                    trace_path=trace_path,
                )

        payload = write.call_args.args[1]
        self.assertEqual(payload["outcome"], "FAIL")
        self.assertEqual(len(payload["cycles"][0]["candidates"]), 3)
        self.assertEqual(payload["best_overall"]["id"], "thesis-1")
        self.assertEqual(
            payload["best_overall"]["rejection_reasons"],
            ["total 21/25 is below 23/25"],
        )

    def test_topic_scope_prefers_momentum_then_authority_fallback(self) -> None:
        candidates = [
            {
                "id": "topic-1",
                "momentum_eligible": False,
                "observed_axes": 4,
                "authority_fit": {"total": 23},
            },
            {
                "id": "topic-2",
                "momentum_eligible": False,
                "observed_axes": 4,
                "authority_fit": {"total": 19},
            },
        ]
        selected, route = daily_spine_cli.select_topic_scope(candidates)
        self.assertEqual([item["id"] for item in selected], ["topic-1"])
        self.assertEqual(route, "authority-fit fallback")

        candidates[1]["momentum_eligible"] = True
        selected, route = daily_spine_cli.select_topic_scope(candidates)
        self.assertEqual([item["id"] for item in selected], ["topic-2"])
        self.assertEqual(route, "momentum-qualified")

        candidates[1]["momentum_eligible"] = False
        inventory = [
            {
                "topic": "Retained topic",
                "status": "AVAILABLE",
                "combined_total": 42,
            }
        ]
        selected, route = daily_spine_cli.select_topic_scope(candidates, inventory)
        self.assertEqual([item["topic"] for item in selected], ["Retained topic"])
        self.assertEqual(route, "rolling seven-day inventory")

    def test_generate_post_is_explicitly_opt_in(self) -> None:
        parsed = daily_spine_cli.parser().parse_args(
            [
                "--profile",
                "data/private/authority-profile.json",
                "--generate-post",
            ]
        )
        self.assertTrue(parsed.generate_post)

    def test_thursday_is_exposed_as_authority_week_slot_three(self) -> None:
        parsed = daily_spine_cli.parser().parse_args(
            ["--profile", "data/private/authority-profile.json", "--week-slot", "3"]
        )
        self.assertEqual(parsed.week_slot, 3)
        with self.assertRaises(SystemExit):
            daily_spine_cli.parser().parse_args(
                ["--profile", "data/private/authority-profile.json", "--week-slot", "4"]
            )

    def test_candidate_inventory_keeps_every_topic_at_or_above_40(self) -> None:
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
        self.assertEqual([item["topic"] for item in retained], ["Qualified topic"])
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
