"""Regression tests for scheduled cloud Authority OS execution."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import cloud_daily, privacy, workflow

ROOT = Path(__file__).resolve().parents[1]


class CloudDailyTests(unittest.TestCase):
    def test_cloud_execution_requires_api_key_before_model_work(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(workflow.WorkflowError, "OPENAI_API_KEY"):
                cloud_daily.execute("test-run")

    def test_thesis_package_requires_exactly_three_cards(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "theses.json"
            payload = {
                "theses": [
                    {"id": f"thesis-{index}", "topic": f"Topic {index}"}
                    for index in range(1, 4)
                ]
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            cards = cloud_daily._load_theses(path)
            self.assertEqual([card["id"] for card in cards], ["thesis-1", "thesis-2", "thesis-3"])

            payload["theses"].pop()
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(workflow.WorkflowError, "exactly three"):
                cloud_daily._load_theses(path)

    def test_only_reviewed_daily_workflow_is_schedule_allowlisted(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / ".gitignore").write_text(
                "\n".join(sorted(privacy.REQUIRED_IGNORES)) + "\n",
                encoding="utf-8",
            )
            safe = root / ".github" / "workflows" / "daily-production.yml"
            safe.parent.mkdir(parents=True)
            safe.write_text("on:\n  schedule:\n    - cron: '30 22 * * *'\n", encoding="utf-8")
            unsafe = safe.with_name("other-scheduled.yml")
            unsafe.write_text("on:\n  schedule:\n    - cron: '30 22 * * *'\n", encoding="utf-8")

            safe_findings = privacy.scan_repository(
                root, candidates=[".github/workflows/daily-production.yml"]
            )
            unsafe_findings = privacy.scan_repository(
                root, candidates=[".github/workflows/other-scheduled.yml"]
            )

        self.assertNotIn("scheduled-workflow", "\n".join(safe_findings))
        self.assertIn("scheduled-workflow", "\n".join(unsafe_findings))

    def test_cloud_workflow_runs_real_repo_cli_and_never_publishes(self) -> None:
        config = (ROOT / ".github" / "workflows" / "daily-production.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("schedule:", config)
        self.assertIn("workflow_dispatch:", config)
        self.assertIn("OPENAI_API_KEY", config)
        self.assertIn("authority_os.cloud_daily", config)
        self.assertIn("contents: read", config)
        self.assertIn("upload-artifact", config)
        self.assertNotIn("linkedin.com", config.casefold())


if __name__ == "__main__":
    unittest.main()
