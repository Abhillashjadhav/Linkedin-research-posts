from __future__ import annotations

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import authority_os.__main__ as cli
from authority_os import storage, workflow


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.db = self.root / "private" / "authority_os.sqlite"
        self.outputs = self.root / "outputs"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_cli(self, arguments: list[str]) -> tuple[int, str, str]:
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = cli.main(arguments)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_dry_run_without_credentials_creates_complete_package(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            workflow, "invoke_claude", side_effect=AssertionError("network/model call forbidden")
        ):
            code, stdout, stderr = self.run_cli(
                [
                    "draft",
                    "--dry-run",
                    "--goal",
                    "authority",
                    "--db",
                    str(self.db),
                    "--output-root",
                    str(self.outputs),
                ]
            )
        self.assertEqual(code, 0, stderr)
        self.assertIn("STATUS: READY FOR HUMAN APPROVAL", stdout)
        packages = list(self.outputs.glob("*/*"))
        self.assertEqual(len(packages), 1)
        self.assertEqual(
            {path.name for path in packages[0].iterdir()},
            {"brief.md", "candidates.md", "critic.json", "final-package.md", "sources.md"},
        )
        final = (packages[0] / "final-package.md").read_text()
        self.assertIn("FIXTURE MODE", final)
        self.assertIn("Do not publish", final)
        self.assertIn("STATUS: READY FOR HUMAN APPROVAL", final)
        critic = json.loads((packages[0] / "critic.json").read_text())
        self.assertEqual(len(critic["results"]), 3)
        self.assertLessEqual(critic["revision_count"], 1)

    def test_all_three_goals_work_in_fixture_mode(self) -> None:
        for goal in ("reach", "authority", "opportunity"):
            with self.subTest(goal=goal):
                goal_root = self.root / goal
                code, stdout, stderr = self.run_cli(
                    [
                        "draft",
                        "--dry-run",
                        "--topic",
                        "PM-agent-OS",
                        "--goal",
                        goal,
                        "--db",
                        str(goal_root / "db.sqlite"),
                        "--output-root",
                        str(goal_root / "outputs"),
                    ]
                )
                self.assertEqual(code, 0, stderr)
                self.assertIn("READY FOR HUMAN APPROVAL", stdout)
                candidates = next((goal_root / "outputs").glob("*/*/candidates.md")).read_text()
                self.assertIn("PM-agent-OS", candidates)

    def test_partial_proof_arguments_fail_before_creating_state(self) -> None:
        code, _stdout, stderr = self.run_cli(
            [
                "draft",
                "--dry-run",
                "--proof-value",
                "orphaned proof value",
                "--db",
                str(self.db),
                "--output-root",
                str(self.outputs),
            ]
        )
        self.assertEqual(code, 2)
        self.assertIn("must be supplied together", stderr)
        self.assertFalse(self.db.exists())

    def test_default_live_draft_does_not_send_stored_research_to_model(self) -> None:
        cli.initialise_paths(self.db)
        stored = workflow.prepare_research_items(
            [
                {
                    "canonical_url": "https://private-import.example.org/stored",
                    "title": "Stored private import",
                    "body": "PRIVATE-STORED-SENTINEL",
                    "source": "Private import",
                    "author": "Local user",
                    "published_at": "2026-07-16T00:00:00Z",
                    "source_quality": "primary",
                }
            ]
        )
        storage.insert_research_items(self.db, stored)
        fresh = workflow.prepare_research_items(
            [
                {
                    "canonical_url": "https://public.example.org/fresh",
                    "title": "Fresh public Scout result",
                    "body": "Fresh public evidence.",
                    "source": "Public source",
                    "author": "Public author",
                    "published_at": "2026-07-16T01:00:00Z",
                    "source_quality": "primary",
                }
            ]
        )
        completed = workflow.complete_payload(workflow.load_fixture())
        with mock.patch.object(workflow, "run_live_research", return_value=fresh), mock.patch.object(
            workflow, "run_live_draft", return_value=completed
        ) as draft_call:
            code, stdout, stderr = self.run_cli(
                [
                    "draft",
                    "--goal",
                    "authority",
                    "--db",
                    str(self.db),
                    "--output-root",
                    str(self.outputs),
                ]
            )
        self.assertEqual(code, 0, stderr)
        self.assertEqual(draft_call.call_args.args[0], fresh)
        self.assertNotIn("PRIVATE-STORED-SENTINEL", json.dumps(draft_call.call_args.args[0]))
        self.assertIn("Stored/private research was not sent", stdout)

    def test_doctor_handles_missing_private_data_and_redacts_environment(self) -> None:
        sentinel = "SUPER-SECRET-SENTINEL-VALUE"
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": sentinel}, clear=True):
            code, stdout, stderr = self.run_cli(["doctor", "--db", str(self.db)])
        self.assertEqual(code, 0, stderr)
        self.assertNotIn(sentinel, stdout + stderr)
        self.assertIn("values were not inspected or printed", stdout)
        self.assertTrue(self.db.exists())

    def test_init_is_idempotent(self) -> None:
        first = self.run_cli(["init", "--db", str(self.db)])
        second = self.run_cli(["init", "--db", str(self.db)])
        self.assertEqual(first[0], 0)
        self.assertEqual(second[0], 0)
        self.assertTrue(self.db.exists())

    def test_record_performance_without_input_is_safe_noop(self) -> None:
        code, stdout, stderr = self.run_cli(
            ["record-performance", "--db", str(self.db)]
        )
        self.assertEqual(code, 0, stderr)
        self.assertIn("No data recorded", stdout)

    def test_weekly_review_with_no_data_is_honest(self) -> None:
        code, stdout, stderr = self.run_cli(
            [
                "weekly-review",
                "--db",
                str(self.db),
                "--output-root",
                str(self.outputs),
            ]
        )
        self.assertEqual(code, 0, stderr)
        review = next(self.outputs.glob("*/weekly-review.md")).read_text()
        self.assertIn("Insufficient performance data", review)
        self.assertIn("no winner was invented", review)
        self.assertIn("rubric was not changed", review)

    def test_no_publish_surface_exists(self) -> None:
        self.assertEqual(
            set(cli.COMMANDS),
            {"init", "doctor", "research", "draft", "record-performance", "weekly-review"},
        )
        runtime = "\n".join(
            path.read_text(errors="ignore")
            for base in (workflow.REPO_ROOT / "src", workflow.REPO_ROOT / "bin")
            for path in base.rglob("*")
            if path.is_file()
        ).casefold()
        forbidden = (
            "api." + "linkedin.com",
            "linkedin.com/" + "v2/",
            "linkedin.com/" + "rest/",
            "ugc" + "posts",
            "selen" + "ium",
            "play" + "wright",
            "pyauto" + "gui",
        )
        self.assertFalse(any(token in runtime for token in forbidden))

    def test_gitignore_protects_private_and_generated_probes(self) -> None:
        probes = [
            "data/private/probe.csv",
            "probe.sqlite",
            "probe.db",
            ".env",
            ".env.local",
            "outputs/probe.md",
            ".agents/skills/probe.md",
        ]
        for probe in probes:
            with self.subTest(probe=probe):
                result = subprocess.run(
                    ["git", "check-ignore", "-q", probe], cwd=workflow.REPO_ROOT
                )
                self.assertEqual(result.returncode, 0)

    def test_ci_has_no_schedule(self) -> None:
        workflow_text = (workflow.REPO_ROOT / ".github/workflows/test.yml").read_text()
        self.assertNotIn("schedule:", workflow_text)
        self.assertIn("push:", workflow_text)
        self.assertIn("pull_request:", workflow_text)

    def test_required_command_forms_parse(self) -> None:
        parser = cli.build_parser()
        forms = [
            ["init"],
            ["doctor"],
            ["research"],
            ["draft"],
            ["draft", "--goal", "reach"],
            ["draft", "--goal", "authority"],
            ["draft", "--goal", "opportunity"],
            ["draft", "--topic", "PM-agent-OS", "--goal", "opportunity"],
            ["draft", "--allow-model-egress"],
            ["record-performance"],
            ["weekly-review"],
        ]
        for form in forms:
            with self.subTest(form=form):
                self.assertEqual(parser.parse_args(form).command, form[0])


if __name__ == "__main__":
    unittest.main()
