"""Tests for the minimal offline CLI foundation."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing
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
            self.assertTrue(database.exists())

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

    def test_fixture_research_is_persisted_and_deduplicated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "private" / "authority.sqlite"
            first = run_cli("research", "--dry-run", "--db", str(database))
            second = run_cli("research", "--dry-run", "--db", str(database))
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("inserted=2; duplicates=0", first.stdout)
            self.assertIn("inserted=0; duplicates=2", second.stdout)
            self.assertIn("stale=not-evaluated", first.stdout)

    def test_short_ai_topic_is_supported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            result = run_cli(
                "research", "--dry-run", "--topic", "AI", "--db", str(database)
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Selected cluster:", result.stdout)

    def test_new_fixture_topic_is_analysed_before_stored_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            first = run_cli("research", "--dry-run", "--db", str(database))
            second = run_cli(
                "research", "--dry-run", "--topic", "AI", "--db", str(database)
            )
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertIn("Selected cluster:", second.stdout)
            self.assertIn("inserted=0; duplicates=2", second.stdout)

    def test_explicit_blank_topic_is_rejected_consistently(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            for value in ("", "   "):
                database = Path(temporary) / f"authority-{len(value)}.sqlite"
                result = run_cli(
                    "research", "--dry-run", "--topic", value, "--db", str(database)
                )
                with self.subTest(value=value):
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("value must not be blank", result.stderr)
                    self.assertFalse(database.exists())

    def test_cli_topic_selection_does_not_require_exact_word_order(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "research.json"
            database = root / "authority.sqlite"
            source.write_text(
                json.dumps(
                    [
                        {
                            "url": "https://example.com/agent",
                            "title": "Agent reliability methods",
                            "body": "A primary reliability mechanism.",
                            "source": "Primary source",
                            "published_at": "2026-07-16T00:00:00Z",
                            "source_quality": "primary",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = run_cli(
                "research",
                "--input",
                str(source),
                "--topic",
                "reliability agent",
                "--db",
                str(database),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("Selected cluster: agent-reliability", result.stdout)

    def test_unmatched_topic_does_not_commit_research_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "research.json"
            database = root / "authority.sqlite"
            source.write_text(
                json.dumps(
                    [
                        {
                            "url": "https://example.com/agent",
                            "title": "Agent reliability methods",
                            "body": "A primary reliability mechanism.",
                            "source": "Primary source",
                            "published_at": "2026-07-16T00:00:00Z",
                            "source_quality": "primary",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            result = run_cli(
                "research",
                "--input",
                str(source),
                "--topic",
                "quantum networking",
                "--db",
                str(database),
            )
            self.assertEqual(result.returncode, 2)
            with closing(sqlite3.connect(database)) as connection:
                count = connection.execute("SELECT count(*) FROM research_items").fetchone()[0]
            self.assertEqual(count, 0)

    def test_explicit_recent_posts_make_stale_status_real(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "research.json"
            recent = root / "recent.json"
            database = root / "authority.sqlite"
            title = "Agent reliability failure"
            body = "Reliability budgets compound across workflow steps. Supporting detail."
            source.write_text(
                json.dumps(
                    [
                        {
                            "url": "https://example.com/agent",
                            "title": title,
                            "body": body,
                            "source": "Primary source",
                            "published_at": "2026-07-16T00:00:00Z",
                            "source_quality": "primary",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            recent.write_text(
                json.dumps([f"{title} Reliability budgets compound across workflow steps"]),
                encoding="utf-8",
            )
            result = run_cli(
                "research",
                "--input",
                str(source),
                "--recent-posts",
                str(recent),
                "--db",
                str(database),
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("stale=yes", result.stdout)

    def test_research_missing_input_and_live_mode_fail_honestly(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "authority.sqlite"
            database = str(database_path)
            missing = run_cli(
                "research", "--input", str(Path(temporary) / "missing.json"), "--db", database
            )
            live = run_cli("research", "--db", database)
            self.assertEqual(missing.returncode, 2)
            self.assertIn("not a readable file", missing.stderr)
            self.assertEqual(live.returncode, 2)
            self.assertIn("Live research is not available", live.stderr)
            self.assertFalse(database_path.exists())

    def test_research_directory_input_is_a_safe_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            result = run_cli("research", "--input", temporary, "--db", str(database))
            self.assertEqual(result.returncode, 2)
            self.assertIn("not a readable file", result.stderr)
            self.assertNotIn("Traceback", result.stderr)
            self.assertFalse(database.exists())

    def test_corrupt_database_is_a_safe_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            database.write_bytes(b"not a sqlite database")
            for command in ("init", "research"):
                args = [command]
                if command == "research":
                    args.append("--dry-run")
                result = run_cli(*args, "--db", str(database))
                with self.subTest(command=command):
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("database is unavailable or corrupt", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)

    def test_unsupported_database_schema_is_a_safe_cli_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            with closing(sqlite3.connect(database)) as connection:
                connection.execute("PRAGMA user_version = 99")
            result = run_cli("init", "--db", str(database))
            self.assertEqual(result.returncode, 2)
            self.assertIn("Unsupported database schema 99", result.stderr)
            self.assertNotIn("Traceback", result.stderr)

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
