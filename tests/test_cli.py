"""Tests for the minimal offline CLI foundation."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "linkedin-os"


def run_cli(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(CLI), *args],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


class MinimalCliTests(unittest.TestCase):
    def test_single_entry_point_is_executable(self) -> None:
        self.assertTrue(CLI.is_file())
        self.assertTrue(os.access(CLI, os.X_OK))

    def test_init_is_idempotent_without_private_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "private" / "authority.sqlite"
            first = run_cli("init", "--db", str(database))
            second = run_cli("init", "--db", str(database))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertTrue(database.parent.is_dir())
            self.assertFalse(database.exists())

    def test_doctor_redacts_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            secret = "sentinel-secret-that-must-not-appear"
            environment = dict(os.environ, ANTHROPIC_API_KEY=secret, LINKEDIN_TOKEN=secret)
            result = run_cli(
                "doctor",
                "--db",
                str(Path(temporary) / "state" / "authority.sqlite"),
                env=environment,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(secret, result.stdout + result.stderr)
            self.assertIn("values were not inspected", result.stdout)

    def test_offline_fixture_execution_needs_no_credentials(self) -> None:
        environment = {
            key: value
            for key, value in os.environ.items()
            if "TOKEN" not in key and "KEY" not in key and "CLAUDE" not in key
        }
        result = run_cli("draft", "--dry-run", "--topic", "PM agent OS", env=environment)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fixture envelope validated: topic=PM agent OS", result.stdout)
        self.assertIn("No approval package was generated", result.stdout)

    def test_live_drafting_fails_honestly_until_implemented(self) -> None:
        result = run_cli("draft")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Live drafting is not available", result.stderr)

    def test_no_publish_surface_exists(self) -> None:
        help_result = run_cli("--help")
        combined = (help_result.stdout + help_result.stderr).casefold()
        self.assertEqual(help_result.returncode, 0)
        for forbidden in ("publish", "comment", "message", "schedule"):
            with self.subTest(command=forbidden):
                self.assertNotIn(f"{{{forbidden}}}", combined)
                result = run_cli(forbidden)
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
