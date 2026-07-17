"""Tests for package-linked manual performance recording."""

from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from authority_os import package as approval_package
from authority_os import performance, storage, workflow


def scorecard(candidate_id: str, scores: tuple[int, int, int, int, int]) -> dict[str, object]:
    card: dict[str, object] = {
        "candidate_id": candidate_id,
        **dict(zip(workflow.CRITIC_AXES, scores, strict=True)),
    }
    raw_total = sum(scores)
    hook_cap = scores[0] <= 3 and raw_total > 18
    effective_total = 18 if hook_cap else raw_total
    card.update(
        {
            "raw_total": raw_total,
            "effective_total": effective_total,
            "hook_cap_applied": hook_cap,
            "band": (
                "advance-to-gates"
                if effective_total >= 24
                else "one-light-revision"
                if effective_total >= 22
                else "below-critic-bar"
            ),
        }
    )
    return card


def gate_result(candidate_id: str, *, passes: bool) -> dict[str, object]:
    gates = {
        gate_name: {
            "status": (
                "NOT_REQUIRED"
                if gate_name == "proof"
                else "PASS"
                if passes or gate_name != "authority_conversion"
                else "FAIL"
            ),
            "reason_codes": [f"test-{gate_name}"],
        }
        for gate_name in workflow.GATE_ORDER
    }
    return {
        "candidate_id": candidate_id,
        "gates": gates,
        "passes_required_gates": passes,
        "manual_fact_verification_required": True,
    }


def package_documents() -> tuple[dict[str, object], dict[str, object]]:
    cards = [
        scorecard("candidate-1", (5, 5, 5, 5, 5)),
        scorecard("candidate-2", (5, 5, 5, 5, 4)),
        scorecard("candidate-3", (4, 4, 4, 4, 4)),
    ]
    ranking = ["candidate-1", "candidate-2", "candidate-3"]
    eligible = ["candidate-1", "candidate-2"]
    manifest: dict[str, object] = {
        "schema_version": 1,
        "package_id": "2026-07-16-agent-reliability",
        "created_at": "2026-07-16T00:00:00Z",
        "mode": "live",
        "topic_slug": "agent-reliability",
        "goal": "authority",
        "output_format": None,
        "weekly_slot": 2,
        "revision_count": 1,
        "review_status": "READY_FOR_HUMAN_REVIEW",
        "human_approval_status": "NOT_APPROVED",
        "publishing_status": "DISABLED",
        "eligible_candidate_ids": eligible,
        "recommended_candidate_id": "candidate-1",
        "manual_fact_verification_required": True,
        "files": dict(approval_package.PACKAGE_FILES),
    }
    evaluation: dict[str, object] = {
        "schema_version": 1,
        "scorecards": cards,
        "ranking": ranking,
        "score_leader_id": "candidate-1",
        "revision_count": 1,
        "revision_candidate_id": "candidate-2",
        "gate_results": [
            gate_result(candidate_id, passes=candidate_id in eligible)
            for candidate_id in ranking
        ],
        "eligible_candidate_ids": eligible,
        "recommended_candidate_id": "candidate-1",
        "review_status": "READY_FOR_HUMAN_REVIEW",
        "manual_fact_verification_required": True,
    }
    return manifest, evaluation


def write_package(
    output_root: Path,
    *,
    manifest: dict[str, object] | None = None,
    evaluation: dict[str, object] | None = None,
) -> Path:
    default_manifest, default_evaluation = package_documents()
    package_dir = output_root / "2026-07-16" / "agent-reliability"
    package_dir.mkdir(parents=True, exist_ok=True)
    output_root.chmod(0o700)
    package_dir.parent.chmod(0o700)
    package_dir.chmod(0o700)
    documents = {
        "manifest.json": json.dumps(manifest or default_manifest, sort_keys=True),
        "evaluation.json": json.dumps(evaluation or default_evaluation, sort_keys=True),
        "brief.md": "brief\n",
        "candidates.md": "candidates\n",
        "sources.md": "sources\n",
        "final-package.md": "final\n",
    }
    for filename, contents in documents.items():
        destination = package_dir / filename
        destination.write_text(contents, encoding="utf-8")
        destination.chmod(0o600)
    return package_dir


def zero_metrics() -> dict[str, int]:
    return {metric: 0 for metric in storage.PERFORMANCE_METRICS}


class PerformancePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "outputs"
        write_package(self.root)

    def load(self, candidate_id: str = "candidate-1") -> dict[str, object]:
        return performance.load_package_context(
            "2026-07-16-agent-reliability",
            candidate_id,
            output_root=self.root,
            _allow_test_output_root=True,
        )

    def test_live_package_snapshots_recommended_and_human_override_candidates(self) -> None:
        recommended = self.load("candidate-1")
        override = self.load("candidate-2")
        self.assertIs(recommended["is_recommended"], True)
        self.assertEqual(recommended["critic_rank"], 1)
        self.assertIs(recommended["was_revised"], False)
        self.assertIs(override["is_recommended"], False)
        self.assertEqual(override["critic_rank"], 2)
        self.assertIs(override["was_revised"], True)
        self.assertEqual(override["critic_effective_total"], 24)

    def test_fixture_blocked_unknown_and_ineligible_packages_fail_closed(self) -> None:
        manifest, evaluation = package_documents()
        cases = (
            ("fixture", "candidate-1"),
            ("blocked", "candidate-1"),
            ("live", "candidate-3"),
            ("live", "missing-candidate"),
        )
        for mode, candidate_id in cases:
            with self.subTest(mode=mode, candidate_id=candidate_id):
                current_manifest = deepcopy(manifest)
                current_evaluation = deepcopy(evaluation)
                if mode == "fixture":
                    current_manifest["mode"] = "fixture"
                    current_manifest["review_status"] = "FIXTURE_REVIEW_ONLY"
                    current_evaluation["review_status"] = "FIXTURE_REVIEW_ONLY"
                elif mode == "blocked":
                    current_manifest["review_status"] = "BLOCKED"
                    current_evaluation["review_status"] = "BLOCKED"
                write_package(
                    self.root,
                    manifest=current_manifest,
                    evaluation=current_evaluation,
                )
                with self.assertRaises(workflow.WorkflowError):
                    self.load(candidate_id)

    def test_package_id_inventory_and_symlinks_are_checked(self) -> None:
        package_dir = self.root / "2026-07-16" / "agent-reliability"
        manifest = json.loads((package_dir / "manifest.json").read_text())
        manifest["package_id"] = "2026-07-16-other"
        (package_dir / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(workflow.WorkflowError, "does not match"):
            self.load()

        write_package(self.root)
        (package_dir / "brief.md").unlink()
        with self.assertRaisesRegex(workflow.WorkflowError, "inventory"):
            self.load()

        write_package(self.root)
        outside = Path(self.temporary.name) / "outside.json"
        outside.write_text("{}")
        (package_dir / "evaluation.json").unlink()
        os.symlink(outside, package_dir / "evaluation.json")
        with self.assertRaisesRegex(workflow.WorkflowError, "unsafe"):
            self.load()

        shutil.rmtree(package_dir)
        outside_dir = Path(self.temporary.name) / "outside-package"
        write_package(outside_dir.parent / "unused")
        outside_dir.mkdir()
        os.symlink(outside_dir, package_dir)
        with self.assertRaises(workflow.WorkflowError):
            self.load()

    def test_package_permissions_must_preserve_private_writer_invariants(self) -> None:
        package_dir = self.root / "2026-07-16" / "agent-reliability"
        candidates_path = package_dir / "candidates.md"
        candidates_path.chmod(0o644)
        with self.assertRaisesRegex(workflow.WorkflowError, "owner-only"):
            self.load()
        candidates_path.chmod(0o600)
        manifest_path = package_dir / "manifest.json"
        manifest_path.chmod(0o644)
        with self.assertRaisesRegex(workflow.WorkflowError, "owner-only"):
            self.load()
        manifest_path.chmod(0o600)
        package_dir.chmod(0o750)
        with self.assertRaisesRegex(workflow.WorkflowError, "owner-only"):
            self.load()

    def test_deep_package_json_fails_as_a_safe_validation_error(self) -> None:
        manifest_path = (
            self.root / "2026-07-16" / "agent-reliability" / "manifest.json"
        )
        manifest_path.write_text(
            "[" * 200_000 + "0" + "]" * 200_000,
            encoding="utf-8",
        )
        manifest_path.chmod(0o600)
        with self.assertRaisesRegex(workflow.WorkflowError, "invalid JSON"):
            self.load()

    def test_tampered_ranking_and_computed_scores_are_rejected(self) -> None:
        manifest, evaluation = package_documents()
        tampered_score = deepcopy(evaluation)
        tampered_score["scorecards"][0]["effective_total"] = 1  # type: ignore[index]
        write_package(self.root, manifest=manifest, evaluation=tampered_score)
        with self.assertRaises(workflow.WorkflowError):
            self.load()

        tampered_ranking = deepcopy(evaluation)
        tampered_ranking["ranking"] = list(reversed(tampered_ranking["ranking"]))  # type: ignore[arg-type]
        write_package(self.root, manifest=manifest, evaluation=tampered_ranking)
        with self.assertRaisesRegex(workflow.WorkflowError, "ranking"):
            self.load()

    def test_gate_schema_and_exact_ranked_eligibility_are_recomputed(self) -> None:
        manifest, evaluation = package_documents()
        partial_manifest = deepcopy(manifest)
        partial_evaluation = deepcopy(evaluation)
        partial_manifest["eligible_candidate_ids"] = ["candidate-2"]
        partial_manifest["recommended_candidate_id"] = "candidate-2"
        partial_evaluation["eligible_candidate_ids"] = ["candidate-2"]
        partial_evaluation["recommended_candidate_id"] = "candidate-2"
        write_package(
            self.root,
            manifest=partial_manifest,
            evaluation=partial_evaluation,
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "eligibility"):
            self.load("candidate-2")

        malformed_evaluation = deepcopy(evaluation)
        malformed_evaluation["gate_results"][0]["gates"]["citation"]["status"] = "FAIL"  # type: ignore[index]
        write_package(
            self.root,
            manifest=manifest,
            evaluation=malformed_evaluation,
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "gate results"):
            self.load()

        malformed_type = deepcopy(evaluation)
        malformed_type["gate_results"][0]["gates"]["citation"]["status"] = []  # type: ignore[index]
        write_package(self.root, manifest=manifest, evaluation=malformed_type)
        with self.assertRaisesRegex(workflow.WorkflowError, "gate results"):
            self.load()

        opportunity_manifest = deepcopy(manifest)
        opportunity_manifest["goal"] = "opportunity"
        write_package(
            self.root,
            manifest=opportunity_manifest,
            evaluation=evaluation,
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "gate results"):
            self.load()


class PerformanceRecordValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output_root = Path(self.temporary.name) / "outputs"
        write_package(self.output_root)
        self.context = performance.load_package_context(
            "2026-07-16-agent-reliability",
            "candidate-1",
            output_root=self.output_root,
            _allow_test_output_root=True,
        )

    def prepare(self, **overrides: object) -> dict[str, object]:
        values: dict[str, object] = {
            "published_at": "2026-07-16T05:30:00+05:30",
            "checkpoint": "24h",
            "channel": "organic",
            "observed_at": "2026-07-17T05:30:00+05:30",
            "metrics": zero_metrics(),
            "recorded_at": "2026-07-25T00:00:00Z",
        }
        values.update(overrides)
        return performance.prepare_record(self.context, **values)  # type: ignore[arg-type]

    def test_all_checkpoint_boundaries_and_timezone_normalisation(self) -> None:
        cases = (
            ("2h", "2026-07-16T02:00:00Z"),
            ("24h", "2026-07-17T00:00:00Z"),
            ("72h", "2026-07-19T00:00:00Z"),
            ("7d", "2026-07-23T00:00:00Z"),
        )
        for checkpoint, observed_at in cases:
            with self.subTest(checkpoint=checkpoint):
                record = self.prepare(checkpoint=checkpoint, observed_at=observed_at)
                self.assertEqual(record["published_at"], "2026-07-16T00:00:00Z")
                self.assertEqual(record["observed_at"], observed_at)

    def test_bad_timestamps_and_checkpoint_windows_fail(self) -> None:
        cases = (
            {"published_at": "2026-07-01T00:00:00"},
            {"published_at": "2026-07-15T23:59:59Z"},
            {"observed_at": "not-a-time"},
            {"observed_at": "9999-12-31T23:59:59-23:59"},
            {"observed_at": "2026-07-17T00:00:00.100000Z"},
            {"observed_at": "2026-07-17T05:30:00+05:30:00.5"},
            {"recorded_at": ""},
            {"checkpoint": "24h", "observed_at": "2026-07-16T23:59:59Z"},
            {"checkpoint": "2h", "observed_at": "2026-07-17T00:00:00Z"},
            {"observed_at": "2026-07-26T00:00:01Z", "recorded_at": "2026-07-26T00:00:00Z"},
        )
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(
                workflow.WorkflowError
            ):
                self.prepare(**overrides)

    def test_metrics_reject_negative_bool_fraction_sign_and_overflow(self) -> None:
        invalid_values: tuple[object, ...] = (
            -1,
            True,
            1.5,
            "+1",
            "1.0",
            "1e3",
            "",
            9_223_372_036_854_775_808,
            "9" * 5_000,
        )
        for value in invalid_values:
            metrics: dict[str, object] = dict(zero_metrics())
            metrics["impressions"] = value
            with self.subTest(value=value), self.assertRaises(
                workflow.WorkflowError
            ):
                self.prepare(metrics=metrics)

    def test_candidate_id_accepts_the_existing_case_preserving_writer_contract(self) -> None:
        context = dict(self.context, candidate_id="Authority-1")
        record = performance.prepare_record(
            context,
            published_at="2026-07-16T00:00:00Z",
            checkpoint="24h",
            channel="organic",
            observed_at="2026-07-17T00:00:00Z",
            metrics=zero_metrics(),
            recorded_at="2026-07-18T00:00:00Z",
        )
        self.assertEqual(record["candidate_id"], "Authority-1")

    def test_exact_csv_batch_loads_and_duplicate_key_is_rejected(self) -> None:
        input_root = Path(self.temporary.name) / "private"
        input_root.mkdir()
        input_root.chmod(0o700)
        csv_path = input_root / "performance.csv"
        row = {
            "package_id": "2026-07-16-agent-reliability",
            "candidate_id": "candidate-1",
            "published_at": "2026-07-16T00:00:00Z",
            "checkpoint": "24h",
            "channel": "organic",
            "observed_at": "2026-07-17T00:00:00Z",
            **{metric: "0" for metric in storage.PERFORMANCE_METRICS},
        }

        def write_rows(rows: list[dict[str, str]], fields: tuple[str, ...] = performance.CSV_FIELDS) -> None:
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.DictWriter(
                    handle, fieldnames=fields, extrasaction="ignore"
                )
                writer.writeheader()
                writer.writerows(rows)
            csv_path.chmod(0o600)

        write_rows([row])
        records = performance.load_csv_records(
            csv_path,
            recorded_at="2026-07-18T00:00:00Z",
            output_root=self.output_root,
            input_root=input_root,
            _allow_test_roots=True,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["channel"], "organic")

        write_rows([row, row])
        with self.assertRaisesRegex(workflow.WorkflowError, "duplicate"):
            performance.load_csv_records(
                csv_path,
                recorded_at="2026-07-18T00:00:00Z",
                output_root=self.output_root,
                input_root=input_root,
                _allow_test_roots=True,
            )

        write_rows([row], fields=performance.CSV_FIELDS[:-1])
        with self.assertRaisesRegex(workflow.WorkflowError, "headers"):
            performance.load_csv_records(
                csv_path,
                recorded_at="2026-07-18T00:00:00Z",
                output_root=self.output_root,
                input_root=input_root,
                _allow_test_roots=True,
            )

    def test_private_csv_rejects_unsafe_modes_special_files_and_parser_limits(self) -> None:
        input_root = Path(self.temporary.name) / "private-security"
        input_root.mkdir(mode=0o700)
        csv_path = input_root / "performance.csv"
        csv_path.write_text(
            ",".join(performance.CSV_FIELDS)
            + "\n"
            + "x" * 150_000
            + "\n",
            encoding="utf-8",
        )
        csv_path.chmod(0o600)
        with self.assertRaisesRegex(workflow.WorkflowError, "parsed safely"):
            performance.load_csv_records(
                csv_path,
                recorded_at="2026-07-18T00:00:00Z",
                output_root=self.output_root,
                input_root=input_root,
                _allow_test_roots=True,
            )

        csv_path.write_text("package_id\nvalue\n", encoding="utf-8")
        csv_path.chmod(0o644)
        with self.assertRaisesRegex(workflow.WorkflowError, "owner-only"):
            performance.load_csv_records(
                csv_path,
                recorded_at="2026-07-18T00:00:00Z",
                output_root=self.output_root,
                input_root=input_root,
                _allow_test_roots=True,
            )

        if hasattr(os, "mkfifo"):
            csv_path.unlink()
            os.mkfifo(csv_path, mode=0o600)
            with self.assertRaisesRegex(workflow.WorkflowError, "unsafe"):
                performance.load_csv_records(
                    csv_path,
                    output_root=self.output_root,
                    input_root=input_root,
                    _allow_test_roots=True,
                )

if __name__ == "__main__":
    unittest.main()
