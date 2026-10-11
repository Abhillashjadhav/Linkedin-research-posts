"""CLI dispatch and offline fixture guardrails."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import article_cli, article_workflow

ROOT = Path(__file__).resolve().parents[1]


class ArticleCLITests(unittest.TestCase):
    def test_bin_dispatches_dry_run_without_inputs_or_model_egress(self):
        completed = subprocess.run([str(ROOT / "bin" / "linkedin-os"), "article", "--dry-run",
                                    "--brief", "/nonexistent", "--models", "/nonexistent"],
                                   cwd=ROOT, capture_output=True, text=True, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["status"], "FIXTURE_ONLY")

    def test_persisted_fixture_is_marked_and_no_model_called(self):
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as parent:
            run = Path(parent) / "fixture"
            with patch.object(article_workflow, "invoke_structured", side_effect=AssertionError("model called")):
                self.assertEqual(article_cli.main(["--dry-run", "--brief", "/nonexistent", "--models",
                                                   "/nonexistent", "--output", str(run)]), 0)
            manifest = json.loads((run / "manifest.json").read_text())
            self.assertEqual(manifest["status"], "FIXTURE_ONLY")
            self.assertEqual(manifest["review_rounds"], 0)
            self.assertEqual(json.loads((run / "review.json").read_text())["status"], "FIXTURE_ONLY")
            self.assertEqual(json.loads((run / "trace.json").read_text())["model_calls"], 0)
            self.assertEqual(manifest["publishing_status"], "DISABLED")

    def test_live_requires_all_inputs_and_consent(self):
        self.assertEqual(article_cli.main(["--brief", "/nonexistent", "--models", "/nonexistent",
                                           "--output", "outputs/test"]), 2)
        self.assertEqual(article_cli.main(["--dry-run", "--allow-model-egress"]), 2)


if __name__ == "__main__":
    unittest.main()
