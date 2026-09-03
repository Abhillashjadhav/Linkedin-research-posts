from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from authority_os import storage, v1_completion, workflow


class V1CompletionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name) / "v1-evals"
        self.state_patch = mock.patch.object(v1_completion, "STATE_ROOT", self.root)
        self.state_patch.start()
        self.run_id_patch = mock.patch.object(v1_completion, "_PROCESS_RUN_ID", "")
        self.run_id_patch.start()
        self.env_patch = mock.patch.dict("os.environ", {}, clear=False)
        self.env_patch.start()
        os.environ.pop(v1_completion.RUN_ID_ENV, None)

    def tearDown(self) -> None:
        self.env_patch.stop()
        self.run_id_patch.stop()
        self.state_patch.stop()
        self.temp.cleanup()

    def test_calibration_policy_is_shadow_and_bounded(self) -> None:
        config = v1_completion.load_calibration_config()
        settings = config["critic_reproducibility"]
        self.assertEqual(settings["mode"], "shadow")
        self.assertEqual(settings["sample"], "once-per-command")
        self.assertEqual(settings["max_axis_delta"], 1)

    def test_review_ready_atomic_value_is_not_published_history_until_promoted(self) -> None:
        post = "A concrete post that cleared the existing resonance gate."
        topic = {
            "id": "topic-1",
            "status": "PASS",
            "source_ids": ["signal-1"],
            "atomic_value": "Use one explicit state checkpoint to locate the first broken handoff in an agent workflow.",
        }
        v1_completion.record_review_ready_binding(post, topic)

        self.assertEqual(v1_completion.load_published_atomic_values(), [])
        artifact = v1_completion._sha256_text(post)
        promoted = v1_completion.promote_binding(
            artifact,
            package_id="2026-08-28-agent-state",
            candidate_id="candidate-1",
        )
        self.assertTrue(promoted)
        self.assertEqual(
            v1_completion.load_published_atomic_values(),
            [topic["atomic_value"]],
        )
        published = v1_completion.load_published_atomic_records()[0]
        self.assertEqual(published["package_id"], "2026-08-28-agent-state")
        self.assertEqual(published["candidate_id"], "candidate-1")
        self.assertEqual(published["artifact_sha256"], artifact)

    def test_decision_ledger_attributes_contract_stage_and_artifact(self) -> None:
        artifact = "a" * 64
        v1_completion.record_decision(
            {
                "contract": "solution_plausibility",
                "mode": "shadow",
                "status": "FAIL",
                "reason": "missing implementation mechanism",
                "judge_status": "FAIL",
            },
            stage="resonance-post",
            subject_id="candidate-2",
            artifact_sha256=artifact,
        )
        rows = v1_completion._read_jsonl(
            self.root / v1_completion.DECISION_LEDGER_NAME
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["schema_version"], 2)
        self.assertTrue(str(rows[0]["run_id"]).startswith("linkedin-"))
        self.assertEqual(rows[0]["contract"], "solution_plausibility")
        self.assertEqual(rows[0]["stage"], "resonance-post")
        self.assertEqual(rows[0]["subject_id"], "candidate-2")
        self.assertEqual(rows[0]["artifact_sha256"], artifact)

    def test_inherited_run_id_groups_parent_and_child_decisions(self) -> None:
        run_id = v1_completion.begin_run("linkedin-one-run")
        self.assertEqual(run_id, "linkedin-one-run")
        with mock.patch.object(v1_completion, "_PROCESS_RUN_ID", ""):
            self.assertEqual(v1_completion.current_run_id(), "linkedin-one-run")

    def test_reproducibility_is_recorded_but_never_becomes_a_release_gate(self) -> None:
        first = [
            {
                "candidate_id": "candidate-1",
                **{axis: 4 for axis in workflow.CRITIC_AXES},
            }
        ]
        second = [
            {
                "candidate_id": "candidate-1",
                **{
                    axis: (5 if axis == "hook_strength" else 4)
                    for axis in workflow.CRITIC_AXES
                },
            }
        ]
        v1_completion._record_reproducibility(first, second, runtime="test")
        row = v1_completion._read_jsonl(
            self.root / v1_completion.DECISION_LEDGER_NAME
        )[0]
        self.assertEqual(row["contract"], "critic_reproducibility")
        self.assertEqual(row["mode"], "shadow")
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["evidence"]["max_axis_disagreement"], 1)

    def test_empty_reproducibility_sample_is_blocked_not_reported_stable(self) -> None:
        v1_completion._record_reproducibility([], [], runtime="test-empty")
        row = v1_completion._read_jsonl(
            self.root / v1_completion.DECISION_LEDGER_NAME
        )[0]
        self.assertEqual(row["contract"], "critic_reproducibility")
        self.assertEqual(row["mode"], "shadow")
        self.assertEqual(row["status"], "BLOCKED")

    def test_critic_validator_records_complete_scorecard_as_diagnostic(self) -> None:
        candidates = [
            {
                "id": "candidate-1",
                "angle": "decision",
                "text": "A grounded draft for human review.",
                "claim_ids": ["source-1"],
            }
        ]
        raw = [
            {
                "candidate_id": "candidate-1",
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 4,
            }
        ]
        validated = v1_completion._critic_validator_v1(raw, candidates)
        row = v1_completion._read_jsonl(
            self.root / v1_completion.DECISION_LEDGER_NAME
        )[0]
        self.assertEqual(validated[0]["effective_total"], 23)
        self.assertEqual(row["contract"], "critic_total")
        self.assertEqual(row["mode"], "shadow")
        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["evidence"]["effective_total"], 23)
        self.assertEqual(row["evidence"]["band"], "one-light-revision")
        self.assertIs(row["evidence"]["hook_cap_applied"], False)
        self.assertEqual(row["evidence"]["axes"]["voice_fidelity"], 4)

    def test_calibration_snapshot_combines_leading_and_lagging_signals_without_mutating_rubric(self) -> None:
        v1_completion.record_decision(
            {
                "contract": "research_trust",
                "mode": "enforce",
                "status": "PASS",
                "reason": "body-read source present",
            },
            stage="topic-value",
            subject_id="topic-1",
        )
        metrics_one = {metric: 1 for metric in storage.PERFORMANCE_METRICS}
        metrics_three = {metric: 3 for metric in storage.PERFORMANCE_METRICS}
        rows = [
            {
                "package_id": "2026-08-01-one",
                "checkpoint": "72h",
                "channel": "organic",
                **metrics_one,
            },
            {
                "package_id": "2026-08-08-two",
                "checkpoint": "72h",
                "channel": "organic",
                **metrics_three,
            },
        ]
        snapshot = v1_completion.build_calibration_snapshot(
            rows,
            as_of="2026-08-28T00:00:00+00:00",
        )
        self.assertEqual(snapshot["contract_decisions"]["research_trust"]["PASS"], 1)
        self.assertEqual(snapshot["organic_72h_posts"], 2)
        self.assertEqual(snapshot["organic_72h_metric_medians"]["impressions"], 2.0)
        self.assertIs(snapshot["rubric_mutated"], False)
        self.assertIs(snapshot["human_product_review_required"], True)

    def test_completion_state_never_changes_v0_sqlite_schema(self) -> None:
        db_path = Path(self.temp.name) / "authority_os.sqlite"
        storage.initialise(db_path)
        before = storage.inspect_database_health(db_path)

        v1_completion.record_decision(
            {
                "contract": "reader_attention",
                "mode": "shadow",
                "status": "PASS",
                "reason": "existing resonance gate passed",
            },
            stage="resonance-post",
        )
        after = storage.inspect_database_health(db_path)

        self.assertEqual(before, after)
        self.assertEqual(after["schema_version"], 4)


if __name__ == "__main__":
    unittest.main()
