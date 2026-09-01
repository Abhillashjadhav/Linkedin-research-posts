from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from authority_os import monitoring_export, v1_completion, workflow


def context() -> dict[str, str]:
    return {
        "run_id": "linkedin-production-1",
        "comparison_run_id": "linkedin-approved-1",
        "observed_at": "2026-08-30T12:00:00Z",
        "product_version": "release-1",
        "use_case_version": "linkedin-authority-v1",
        "deployment_id": "commit-1",
        "model_provider": "openai",
        "model_name": "configured-model",
        "model_snapshot": "snapshot-1",
        "prompt_version": "prompt-1",
        "config_version": "config-1",
        "toolset_version": "tools-1",
        "evaluator_version": "eval-1",
        "rubric_version": "rubric-1",
        "golden_dataset_version": "golden-1",
        "production_cohort": "production",
        "since": "2026-08-30T11:00:00Z",
        "through": "2026-08-30T13:00:00Z",
    }


class MonitoringExportTests(unittest.TestCase):
    def test_export_contains_only_redacted_facts_and_opaque_identity(self) -> None:
        private_text = "Candidate hook with personal@example.com and private source body"
        rows = [
            {
                "schema_version": 1,
                "recorded_at": "2026-08-30T12:00:00Z",
                "contract": "research_trust",
                "stage": "topic-value",
                "mode": "enforce",
                "status": "PASS",
                "reason": "body-read-source-present",
                "subject_id": "candidate-1",
                "artifact_sha256": "a" * 64,
                "evidence": {"private_text": private_text},
            },
            {
                "schema_version": 1,
                "recorded_at": "2026-08-30T12:00:00Z",
                "contract": "claim_body_support",
                "stage": "topic-value",
                "mode": "shadow",
                "status": "FAIL",
                "reason": "number-not-supported",
                "subject_id": "candidate-1",
                "artifact_sha256": "a" * 64,
                "evidence": {},
            },
        ]
        exported = monitoring_export.build_normalized_export(context(), rows)
        rendered = json.dumps(exported)
        self.assertNotIn(private_text, rendered)
        self.assertNotIn("personal@example.com", rendered)
        case = exported["cases"][0]
        self.assertEqual(case["case_type"], "topic-value")
        self.assertTrue(str(case["case"]["case_id"]).startswith("linkedin-"))
        self.assertEqual(
            {item["definition_id"] for item in case["checks"]},
            {"research-trust", "claim-body-support"},
        )

    def test_context_is_strict_and_timezone_aware(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "context.json"
            invalid = context()
            invalid["extra"] = "not-allowed"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                monitoring_export.load_context(path)

            invalid = context()
            invalid["observed_at"] = "2026-08-30T12:00:00"
            path.write_text(json.dumps(invalid), encoding="utf-8")
            with self.assertRaises(workflow.WorkflowError):
                monitoring_export.load_context(path)

    def test_private_writer_refuses_overwrite_and_non_private_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "v1-evals"
            root.mkdir()
            with mock.patch.object(v1_completion, "STATE_ROOT", root):
                target = root / "monitoring-run.json"
                monitoring_export._write_private(target, {"safe": True})
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
                with self.assertRaises(workflow.WorkflowError):
                    monitoring_export._write_private(target, {"safe": True})
                with self.assertRaises(workflow.WorkflowError):
                    monitoring_export._write_private(
                        Path(temporary) / "outside.json", {"safe": True}
                    )


if __name__ == "__main__":
    unittest.main()
