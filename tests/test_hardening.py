"""Production-boundary regression tests."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from authority_os import __main__ as cli
from authority_os import privacy, workflow


ROOT = Path(__file__).resolve().parents[1]


class ProductionBoundaryTests(unittest.TestCase):
    def test_cli_surface_is_exact_and_has_no_external_action_command(self) -> None:
        expected = {
            "init",
            "doctor",
            "privacy-check",
            "research",
            "draft",
            "record-performance",
            "weekly-review",
        }
        self.assertEqual(set(cli.COMMANDS), expected)
        forbidden = {"publish", "schedule", "approve", "message", "comment", "post"}
        for command in cli.COMMANDS:
            with self.subTest(command=command):
                self.assertTrue(forbidden.isdisjoint(command.split("-")))

    def test_runtime_has_no_linkedin_or_browser_client_surface(self) -> None:
        files = sorted((ROOT / "src" / "authority_os").glob("*.py")) + [
            ROOT / "bin" / "linkedin-os"
        ]
        forbidden = (
            "api." + "linkedin" + ".com",
            "linkedin" + ".com/" + "rest/",
            "linkedin" + ".com/" + "v2/",
            "import " + "playwright",
            "from " + "playwright",
            "import " + "selenium",
            "from " + "selenium",
            "import " + "pyautogui",
            "from " + "pyautogui",
            "import " + "requests",
            "import " + "httpx",
            "urllib." + "request",
            "http." + "client",
        )
        for path in files:
            text = path.read_text(encoding="utf-8").casefold()
            for token in forbidden:
                with self.subTest(path=path.name, token=token):
                    self.assertNotIn(token.casefold(), text)

    def test_zero_runtime_dependencies_are_preserved(self) -> None:
        requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
        active = [
            line
            for line in requirements.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        self.assertEqual(active, [])

    def test_ci_runs_aggregate_check_without_schedule_or_write_permission(self) -> None:
        config = (ROOT / ".github" / "workflows" / "test.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("make check", config)
        self.assertIn("contents: read", config)
        self.assertIn("timeout-minutes:", config)
        self.assertIn('python-version: ["3.11", "3.14"]', config)
        self.assertNotRegex(config, r"(?m)^\s*schedule\s*:")
        self.assertNotRegex(config, r"uses:\s+[^\s]+@v\d")
        pins = re.findall(r"uses:\s+[^\s]+@([0-9a-f]{40})", config)
        self.assertEqual(len(pins), 2)

    def test_repository_privacy_gate_passes_the_real_candidate_inventory(self) -> None:
        self.assertEqual(privacy.scan_repository(workflow.REPO_ROOT), [])

    def test_package_and_learning_language_preserve_manual_boundary(self) -> None:
        package_source = (ROOT / "src" / "authority_os" / "package.py").read_text(
            encoding="utf-8"
        )
        learning_source = (ROOT / "src" / "authority_os" / "learning.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('"human_approval_status": "NOT_APPROVED"', package_source)
        self.assertIn('"publishing_status": "DISABLED"', package_source)
        self.assertNotIn("write_text", learning_source)
        self.assertIn("rubric_mutated", learning_source)


if __name__ == "__main__":
    unittest.main()
