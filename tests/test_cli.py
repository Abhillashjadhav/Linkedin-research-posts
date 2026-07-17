"""Tests for the minimal offline CLI foundation."""

from __future__ import annotations

import io
import json
import os
import re
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import __main__ as cli


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


def performance_context(*, package_created_at: str = "2026-07-16T00:00:00Z") -> dict[str, object]:
    return {
        "package_id": "2026-07-16-agent-reliability",
        "candidate_id": "candidate-1",
        "package_created_at": package_created_at,
        "goal": "authority",
        "output_format": None,
        "weekly_slot": 2,
        "revision_count": 0,
        "was_revised": False,
        "hook_strength": 5,
        "middle_escalation": 5,
        "earned_closer": 5,
        "specificity_and_source_quality": 5,
        "voice_fidelity": 5,
        "critic_raw_total": 25,
        "critic_effective_total": 25,
        "critic_hook_cap_applied": False,
        "critic_band": "advance-to-gates",
        "critic_rank": 1,
        "is_recommended": True,
    }


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

    def test_private_directory_upgrade_and_symlink_rejection_are_no_follow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing"
            existing.mkdir(mode=0o755)
            cli._ensure_owner_only_directory(existing)
            self.assertEqual(existing.stat().st_mode & 0o777, 0o700)

            target = Path(temporary) / "target"
            target.mkdir(mode=0o755)
            linked = Path(temporary) / "linked"
            linked.symlink_to(target, target_is_directory=True)
            with self.assertRaises(cli.workflow.WorkflowError):
                cli._ensure_owner_only_directory(linked)
            self.assertEqual(target.stat().st_mode & 0o777, 0o755)

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
        self.assertIn("Strategy brief: goal=authority; format=not-selected", result.stdout)
        self.assertIn("Reader: AI product leaders", result.stdout)
        self.assertIn("Core hypothesis:", result.stdout)
        self.assertIn("Product decision:", result.stdout)
        self.assertIn("Authority statement:", result.stdout)
        self.assertIn("Strategy input origin: synthetic-fixture", result.stdout)
        self.assertIn(
            "Evidence status: source_quality=sufficient; body=sufficient; "
            "recency=sufficient; stale=not-evaluated; primary_sources=1; "
            "limitations=recent-post-similarity-not-evaluated",
            result.stdout,
        )
        self.assertIn("No approval package was generated", result.stdout)

    def test_fixture_research_cannot_feed_a_live_approval_package(self) -> None:
        fixture = cli.workflow.load_fixture()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "authority.sqlite"
            strategy = root / "strategy.json"
            strategy.write_text(
                json.dumps(fixture["strategy_inputs"]), encoding="utf-8"
            )
            imported = run_cli(
                "research", "--dry-run", "--db", str(database)
            )
            attempted = run_cli(
                "draft",
                "--package",
                "--strategy-input",
                str(strategy),
                "--allow-model-egress",
                "--db",
                str(database),
            )
        self.assertEqual(imported.returncode, 0, imported.stderr)
        self.assertIn("Research mode: fixture", imported.stdout)
        self.assertEqual(attempted.returncode, 2)
        self.assertIn(
            "fixture and unverified rows are ineligible",
            attempted.stderr,
        )
        self.assertNotIn("READY_FOR_HUMAN_REVIEW", attempted.stdout)
        self.assertNotIn("Recommended candidate", attempted.stdout)

    def test_live_draft_migrates_and_quarantines_a_v1_ledger(self) -> None:
        fixture = cli.workflow.load_fixture()
        prepared = cli.workflow.prepare_research_items(fixture["research_items"])[0]
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "legacy.sqlite"
            strategy = root / "strategy.json"
            strategy.write_text(
                json.dumps(fixture["strategy_inputs"]), encoding="utf-8"
            )
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE research_items (
                        id INTEGER PRIMARY KEY,
                        canonical_url TEXT NOT NULL UNIQUE,
                        title TEXT NOT NULL,
                        body TEXT NOT NULL,
                        source TEXT NOT NULL,
                        author TEXT NOT NULL DEFAULT '',
                        published_at TEXT NOT NULL,
                        source_quality TEXT NOT NULL,
                        content_hash TEXT NOT NULL UNIQUE,
                        fetched_at TEXT NOT NULL
                    );
                    PRAGMA user_version = 1;
                    """
                )
                connection.execute(
                    """
                    INSERT INTO research_items (
                        canonical_url, title, body, source, author, published_at,
                        source_quality, content_hash, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tuple(
                        prepared[field]
                        for field in (
                            "canonical_url",
                            "title",
                            "body",
                            "source",
                            "author",
                            "published_at",
                            "source_quality",
                            "content_hash",
                            "fetched_at",
                        )
                    ),
                )
            attempted = run_cli(
                "draft",
                "--package",
                "--strategy-input",
                str(strategy),
                "--allow-model-egress",
                "--db",
                str(database),
            )
            with closing(sqlite3.connect(database)) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                origin = connection.execute(
                    "SELECT evidence_origin FROM research_items"
                ).fetchone()[0]
        self.assertEqual(attempted.returncode, 2)
        self.assertIn("fixture and unverified rows are ineligible", attempted.stderr)
        self.assertNotIn("unavailable or corrupt", attempted.stderr)
        self.assertEqual(version, 3)
        self.assertEqual(origin, "legacy-unverified")

    def test_draft_accepts_an_arbitrary_short_explicit_topic(self) -> None:
        result = run_cli("draft", "--dry-run", "--topic", "Go")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Fixture envelope validated: topic=Go", result.stdout)
        self.assertIn("Strategy brief: goal=authority", result.stdout)

    def test_fixture_can_write_one_explicit_review_only_package(self) -> None:
        result = run_cli(
            "draft",
            "--dry-run",
            "--package",
            "--topic",
            "fixture package integration",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        match = re.search(r"(?m)^Content package: (outputs/[^\n]+)$", result.stdout)
        self.assertIsNotNone(match)
        assert match is not None
        package_path = ROOT / match.group(1)
        try:
            self.assertTrue(package_path.is_dir())
            manifest = json.loads((package_path / "manifest.json").read_text())
            self.assertEqual(manifest["mode"], "fixture")
            self.assertEqual(manifest["review_status"], "FIXTURE_REVIEW_ONLY")
            self.assertEqual(manifest["human_approval_status"], "NOT_APPROVED")
            self.assertEqual(manifest["publishing_status"], "DISABLED")
            self.assertIsNone(manifest["recommended_candidate_id"])
            self.assertEqual(len(list(package_path.iterdir())), 6)
            self.assertIn("Recommendation: none; synthetic fixture", result.stdout)
            self.assertIn("Performance recording: unavailable", result.stdout)
            self.assertNotIn("Performance package ID:", result.stdout)
            self.assertIn("Publishing status: DISABLED", result.stdout)
            self.assertNotIn("Recommended candidate for human review:", result.stdout)
        finally:
            if package_path.is_dir() and not package_path.is_symlink():
                shutil.rmtree(package_path)
            try:
                package_path.parent.rmdir()
            except OSError:
                pass

    def test_goal_and_format_route_independently_in_fixture_mode(self) -> None:
        cases = (
            ("reach", "artifact-demo"),
            ("opportunity", "text"),
        )
        for goal, output_format in cases:
            with self.subTest(goal=goal, output_format=output_format):
                result = run_cli(
                    "draft",
                    "--dry-run",
                    "--goal",
                    goal,
                    "--format",
                    output_format,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    f"Strategy brief: goal={goal}; format={output_format}", result.stdout
                )
                self.assertIn("No LinkedIn action was taken", result.stdout)

    def test_fixture_drafting_scores_three_candidates_for_each_goal(self) -> None:
        for goal in cli.workflow.STRATEGIC_GOALS:
            with self.subTest(goal=goal):
                result = run_cli("draft", "--dry-run", "--goal", goal)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.count("Candidate "), 3)
                self.assertEqual(result.stdout.count("Critic score: id="), 3)
                self.assertEqual(result.stdout.count("Gate result: id="), 3)
                self.assertIn("Three draft candidates scored", result.stdout)
                self.assertIn("Critic ranking:", result.stdout)
                expected_revisions = 1 if goal == "authority" else 0
                self.assertIn(
                    f"revision_count={expected_revisions}", result.stdout
                )
                lowered = result.stdout.casefold()
                for deferred in (
                    "score=",
                    "ready for human approval",
                    "package path",
                    "recommended winner",
                ):
                    self.assertNotIn(deferred, lowered)
                self.assertIn("manual_fact_verification_required=yes", result.stdout)
                self.assertIn("No winner was selected", result.stdout)

    def test_fixture_drafting_never_invokes_any_model(self) -> None:
        args = SimpleNamespace(
            dry_run=True,
            topic=None,
            goal="reach",
            output_format=None,
            week_slot=None,
            strong_current_signal=False,
            strategy_input=None,
            allow_model_egress=False,
        )
        with (
            patch.object(
                cli.workflow,
                "invoke_writer",
                side_effect=AssertionError("fixture mode crossed the model boundary"),
            ) as writer,
            patch.object(
                cli.workflow,
                "invoke_critic",
                side_effect=AssertionError("fixture mode crossed the model boundary"),
            ) as critic,
            patch.object(
                cli.workflow,
                "invoke_writer_revision",
                side_effect=AssertionError("fixture mode crossed the model boundary"),
            ) as revision,
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(cli.command_draft(args), 0)
        writer.assert_not_called()
        critic.assert_not_called()
        revision.assert_not_called()

    def test_fixture_mode_rejects_private_input_and_egress_flags(self) -> None:
        egress = run_cli("draft", "--dry-run", "--allow-model-egress")
        self.assertEqual(egress.returncode, 2)
        self.assertIn("does not accept strategy files, proof files", egress.stderr)
        proof = run_cli(
            "draft", "--dry-run", "--proof-manifest", "data/private/proof.json"
        )
        self.assertEqual(proof.returncode, 2)
        self.assertIn("does not accept strategy files, proof files", proof.stderr)

    def test_draft_analysis_receives_only_unique_fixture_rows(self) -> None:
        fixture = cli.workflow.load_fixture()
        fixture["research_items"].append(dict(fixture["research_items"][0]))
        args = SimpleNamespace(
            dry_run=True,
            topic=None,
            goal=None,
            output_format=None,
            week_slot=None,
            strong_current_signal=False,
        )
        with (
            patch.object(cli.workflow, "load_fixture", return_value=fixture),
            patch.object(
                cli.workflow,
                "analyse_research",
                wraps=cli.workflow.analyse_research,
            ) as analyse,
            redirect_stdout(io.StringIO()),
        ):
            result = cli.command_draft(args)
        self.assertEqual(result, 0)
        self.assertEqual(len(analyse.call_args.args[0]), 2)

    def test_cli_enforces_the_default_weekly_mix_and_guarded_fifth_slot(self) -> None:
        expected = ("reach", "authority", "authority", "opportunity")
        for slot, goal in enumerate(expected, start=1):
            with self.subTest(slot=slot):
                result = run_cli("draft", "--dry-run", "--week-slot", str(slot))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(
                    f"Strategy brief: goal={goal}; format=not-selected; weekly_slot={slot}",
                    result.stdout,
                )
        rejected = run_cli(
            "draft", "--dry-run", "--week-slot", "5", "--goal", "opportunity"
        )
        accepted = run_cli(
            "draft",
            "--dry-run",
            "--week-slot",
            "5",
            "--goal",
            "opportunity",
            "--strong-current-signal",
        )
        self.assertEqual(rejected.returncode, 2)
        self.assertIn("strong current incident or launch", rejected.stderr)
        self.assertEqual(accepted.returncode, 0, accepted.stderr)
        self.assertIn("weekly_slot=5", accepted.stdout)
        self.assertIn("validated local proof manifest", accepted.stdout)
        self.assertIn("proof=PASS", accepted.stdout)

    def test_opportunity_fixture_has_one_proof_pass_and_two_proof_failures(self) -> None:
        result = run_cli("draft", "--dry-run", "--goal", "opportunity")
        self.assertEqual(result.returncode, 0, result.stderr)
        gate_lines = [
            line for line in result.stdout.splitlines() if line.startswith("Gate result:")
        ]
        self.assertEqual(len(gate_lines), 3)
        self.assertIn("id=opportunity-1", gate_lines[0])
        self.assertIn("proof=PASS", gate_lines[0])
        self.assertIn("passes_required_gates=yes", gate_lines[0])
        self.assertEqual(sum("proof=FAIL" in line for line in gate_lines), 2)
        self.assertNotIn("synthetic-proof.md", result.stdout + result.stderr)

    def test_live_drafting_requires_explicit_strategy_input(self) -> None:
        result = run_cli("draft")
        self.assertEqual(result.returncode, 2)
        self.assertIn("requires --strategy-input", result.stderr)

    def test_live_opportunity_requires_proof_before_writer_invocation(self) -> None:
        fixture = cli.workflow.load_fixture()
        items = cli.workflow.prepare_research_items(fixture["research_items"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "authority.sqlite"
            database.touch()
            strategy = root / "strategy.json"
            strategy.write_text(json.dumps(fixture["strategy_inputs"]), encoding="utf-8")
            args = SimpleNamespace(
                dry_run=False,
                topic="agent reliability budgets",
                goal="opportunity",
                output_format=None,
                week_slot=None,
                strong_current_signal=False,
                strategy_input=strategy,
                allow_model_egress=True,
                proof_manifest=None,
                db=database,
            )
            with (
                patch.object(cli.storage, "list_research_items", return_value=items),
                patch.object(
                    cli.workflow,
                    "invoke_writer",
                    side_effect=AssertionError("Writer must not run without proof"),
                ) as writer,
            ):
                with self.assertRaisesRegex(
                    cli.workflow.WorkflowError, "requires --proof-manifest"
                ):
                    cli.command_draft(args)
            writer.assert_not_called()

    def test_model_egress_help_names_the_remote_provider_boundary(self) -> None:
        result = run_cli("draft", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = " ".join(result.stdout.split())
        self.assertIn("leave this machine", rendered)
        self.assertIn("configured Claude service", rendered)
        self.assertIn("public proof claim or attestation text", rendered)
        self.assertNotIn("local Writer model", rendered)

    def test_live_reach_may_use_optional_proof_for_exact_attestations(self) -> None:
        fixture = cli.workflow.load_fixture()
        items = cli.workflow.prepare_research_items(fixture["research_items"])
        cli.workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with (
            tempfile.TemporaryDirectory() as temporary,
            tempfile.TemporaryDirectory(
                dir=cli.workflow.DEFAULT_PRIVATE_DATA
            ) as private_temporary,
        ):
            root = Path(temporary)
            database = root / "authority.sqlite"
            database.touch()
            strategy = root / "strategy.json"
            strategy.write_text(
                json.dumps(fixture["strategy_inputs"]), encoding="utf-8"
            )
            artifact = Path(private_temporary) / "proof.txt"
            artifact.write_text("private proof", encoding="utf-8")
            proof = cli.workflow.LoadedProof(
                proof_id="proof-reach-attestation",
                proof_type="artifact",
                artifact_path=artifact,
                fixture_mode=False,
                public_claim="A local workflow artifact exists.",
                attested_personal_sentences=("I built the workflow.",),
            )
            args = SimpleNamespace(
                dry_run=False,
                topic="agent reliability budgets",
                goal="reach",
                output_format=None,
                week_slot=None,
                strong_current_signal=False,
                strategy_input=strategy,
                allow_model_egress=True,
                proof_manifest=Path(private_temporary) / "proof.json",
                db=database,
            )
            candidates = fixture["draft_candidates"]["reach"]
            critic_scores = [
                {
                    "candidate_id": draft["id"],
                    **{axis: 5 for axis in cli.workflow.CRITIC_AXES},
                }
                for draft in candidates
            ]
            with (
                patch.object(cli.storage, "list_research_items", return_value=items),
                patch.object(
                    cli.workflow, "load_proof_manifest", return_value=proof
                ) as load_proof,
                patch.object(
                    cli.workflow, "invoke_writer", return_value=candidates
                ) as writer,
                patch.object(
                    cli.workflow, "invoke_critic", return_value=critic_scores
                ),
                redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(cli.command_draft(args), 0)
            load_proof.assert_called_once_with(args.proof_manifest)
            self.assertIs(writer.call_args.kwargs["proof"], proof)

    def test_live_drafting_requires_egress_consent_before_ledger_access(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            strategy = root / "strategy.json"
            database = root / "missing.sqlite"
            strategy.write_text(
                json.dumps(cli.workflow.load_fixture()["strategy_inputs"]),
                encoding="utf-8",
            )
            missing_consent = run_cli(
                "draft",
                "--strategy-input",
                str(strategy),
                "--db",
                str(database),
            )
            consented_without_ledger = run_cli(
                "draft",
                "--strategy-input",
                str(strategy),
                "--allow-model-egress",
                "--db",
                str(database),
            )
            self.assertEqual(missing_consent.returncode, 2)
            self.assertIn("requires --allow-model-egress", missing_consent.stderr)
            self.assertEqual(consented_without_ledger.returncode, 2)
            self.assertIn("existing private research ledger", consented_without_ledger.stderr)
            self.assertFalse(database.exists())

    def test_consented_live_draft_projects_only_safe_selected_evidence(self) -> None:
        fixture = cli.workflow.load_fixture()
        items = cli.workflow.prepare_research_items(fixture["research_items"])
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "authority.sqlite"
            strategy = root / "strategy.json"
            database.touch()
            strategy.write_text(
                json.dumps(fixture["strategy_inputs"]),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                dry_run=False,
                topic="agent reliability budgets",
                goal="authority",
                output_format="carousel",
                week_slot=None,
                strong_current_signal=False,
                strategy_input=strategy,
                allow_model_egress=True,
                db=database,
            )
            candidates = fixture["draft_candidates"]["authority"]
            critic_scores = [
                {
                    "candidate_id": candidate["id"],
                    **{
                        axis: 5 if index == 0 else 4
                        for axis in cli.workflow.CRITIC_AXES
                    },
                }
                for index, candidate in enumerate(candidates)
            ]
            with (
                patch.object(
                    cli.storage, "list_research_items", return_value=items
                ) as listed,
                patch.object(
                    cli.workflow, "invoke_writer", return_value=candidates
                ) as writer,
                patch.object(
                    cli.workflow, "invoke_critic", return_value=critic_scores
                ) as critic,
                redirect_stdout(io.StringIO()) as output,
            ):
                self.assertEqual(cli.command_draft(args), 0)
            brief = writer.call_args.kwargs["brief"]
            evidence = writer.call_args.kwargs["evidence"]
            self.assertIs(writer.call_args.kwargs["allow_model_egress"], True)
            self.assertIs(critic.call_args.kwargs["allow_model_egress"], True)
            self.assertEqual(critic.call_args.args[1], brief)
            self.assertEqual(critic.call_args.args[2], evidence)
            self.assertEqual(brief["strategy_input_origin"], "explicit-input")
            self.assertEqual(brief["output_format"], "carousel")
            self.assertEqual(len(evidence), 2)
            self.assertEqual(
                set(evidence[0]),
                {"id", "title", "claim", "source", "source_quality", "body_read"},
            )
            rendered = json.dumps(evidence)
            for private_field in ("content_hash", "author", "fetched_at", '"id": 1'):
                self.assertNotIn(private_field, rendered)
            listed.assert_called_once_with(
                database,
                topic_terms=(
                    "agent",
                    "budgets",
                    "failure",
                    "reliab*",
                    "reliability",
                    "workflow",
                ),
                evidence_origins=("private-import",),
            )
            self.assertIn("No LinkedIn action was taken", output.getvalue())

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

    def test_fixture_analysis_is_isolated_from_newer_stored_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            initialised = run_cli("init", "--db", str(database))
            self.assertEqual(initialised.returncode, 0, initialised.stderr)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute(
                    """
                    INSERT INTO research_items (
                        canonical_url, title, body, source, author, published_at,
                        source_quality, content_hash, fetched_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "https://example.net/newer-live-row",
                        "Newer live evidence",
                        "A valid stored body that is newer than the fixture snapshot.",
                        "Live source",
                        "",
                        "2030-01-01T00:00:00+00:00",
                        "primary",
                        "a" * 64,
                        "2030-01-01T00:00:00+00:00",
                    ),
                )
            result = run_cli("research", "--dry-run", "--db", str(database))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn("implausibly in the future", result.stderr)
            self.assertIn("Selected cluster: agent-reliability", result.stdout)

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

    def test_private_import_analysis_cannot_borrow_fixture_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "authority.sqlite"
            source = root / "quantum.json"
            source.write_text(
                json.dumps(
                    [
                        {
                            "url": "https://example.com/quantum",
                            "title": "Quantum networking methods",
                            "body": "A private import about an unrelated system.",
                            "source": "Private import source",
                            "published_at": "2026-07-16T00:00:00Z",
                            "source_quality": "primary",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            fixture_import = run_cli(
                "research", "--dry-run", "--db", str(database)
            )
            private_import = run_cli(
                "research",
                "--input",
                str(source),
                "--topic",
                "agent reliability",
                "--db",
                str(database),
            )
            with closing(sqlite3.connect(database)) as connection:
                origins = {
                    row[0]
                    for row in connection.execute(
                        "SELECT DISTINCT evidence_origin FROM research_items"
                    )
                }
        self.assertEqual(fixture_import.returncode, 0, fixture_import.stderr)
        self.assertEqual(private_import.returncode, 2)
        self.assertIn("No research cluster matches requested topic", private_import.stderr)
        self.assertNotIn("Selected cluster: agent-reliability", private_import.stdout)
        self.assertEqual(origins, {"synthetic-fixture"})

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

    def test_record_performance_links_a_manual_checkpoint_without_publishing(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        published_at = (now - timedelta(hours=30)).isoformat()
        observed_at = (now - timedelta(hours=1)).isoformat()
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            output = io.StringIO()
            with (
                patch.object(
                    cli.performance,
                    "load_package_context",
                    return_value=performance_context(
                        package_created_at=(now - timedelta(hours=31)).isoformat()
                    ),
                ) as loaded,
                redirect_stdout(output),
            ):
                result = cli.main(
                    [
                        "record-performance",
                        "--package-id",
                        "2026-07-16-agent-reliability",
                        "--candidate",
                        "candidate-1",
                        "--manually-published-at",
                        published_at,
                        "--checkpoint",
                        "24h",
                        "--channel",
                        "organic",
                        "--observed-at",
                        observed_at,
                        "--impressions",
                        "1000",
                        "--profile-visits",
                        "30",
                        "--saves",
                        "12",
                        "--sends",
                        "5",
                        "--confirm-manual-publication",
                        "--db",
                        str(database),
                    ]
                )
            rows = cli.storage.list_performance(database)
        self.assertEqual(result, 0)
        loaded.assert_called_once_with(
            "2026-07-16-agent-reliability", "candidate-1"
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["impressions"], 1_000)
        self.assertEqual(rows[0]["profile_visits"], 30)
        self.assertEqual(rows[0]["recruiter_inbound"], 0)
        self.assertIn("inserted=1", output.getvalue())
        self.assertIn("Publishing remains disabled", output.getvalue())
        self.assertIn("No LinkedIn action was taken", output.getvalue())

    def test_record_performance_requires_explicit_manual_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "authority.sqlite"
            result = run_cli(
                "record-performance",
                "--package-id",
                "2026-07-16-agent-reliability",
                "--db",
                str(database),
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("--confirm-manual-publication", result.stderr)
            self.assertFalse(database.exists())

    def test_record_performance_rejects_partial_replace_and_mixed_csv(self) -> None:
        now = datetime.now(timezone.utc).replace(microsecond=0)
        common = (
            "--package-id",
            "2026-07-16-agent-reliability",
            "--candidate",
            "candidate-1",
            "--manually-published-at",
            (now - timedelta(hours=30)).isoformat(),
            "--checkpoint",
            "24h",
            "--channel",
            "organic",
            "--observed-at",
            (now - timedelta(hours=1)).isoformat(),
            "--confirm-manual-publication",
        )
        partial = run_cli("record-performance", *common, "--replace")
        self.assertEqual(partial.returncode, 2)
        self.assertIn("every performance metric", partial.stderr)
        mixed = run_cli(
            "record-performance",
            "--csv",
            "data/private/performance.csv",
            "--package-id",
            "2026-07-16-agent-reliability",
            "--confirm-manual-publication",
        )
        self.assertEqual(mixed.returncode, 2)
        self.assertIn("either --csv or direct", mixed.stderr)

    def test_record_performance_help_exposes_all_checkpoints_and_channels(self) -> None:
        result = run_cli("record-performance", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        rendered = " ".join(result.stdout.split())
        self.assertIn("{2h,24h,72h,7d}", rendered)
        self.assertIn("{organic,paid}", rendered)
        self.assertIn("--profile-visits", rendered)
        self.assertIn("--relevant-followers", rendered)
        self.assertIn("--recruiter-inbound", rendered)

    def test_oversized_direct_metric_fails_without_echoing_private_input(self) -> None:
        private_value = "9" * 5_000
        result = run_cli(
            "record-performance",
            "--impressions",
            private_value,
            "--confirm-manual-publication",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("outside the supported range", result.stderr)
        self.assertNotIn(private_value, result.stderr)

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
