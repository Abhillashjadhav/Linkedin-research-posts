"""Tests for private observation-only narrative-spine performance feedback."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from authority_os import spine_feedback, workflow

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "linkedin-os"


def record(
    index: int,
    *,
    spine: str = "counterposition",
    impressions: int = 1_000,
    engagements: int = 10,
    breakout: bool = False,
    observed_at: str = "2026-08-20T04:00:00Z",
) -> dict[str, object]:
    return spine_feedback.prepare_record(
        post_url=f"https://www.linkedin.com/posts/abhillash-test-{index}",
        post_id=f"activity-{index}",
        published_at="2026-08-17T09:00:00+05:30",
        topic=f"Test topic {index}",
        attention_source="x_and_web",
        selected_spine=spine,
        impressions=impressions,
        engagements=engagements,
        is_breakout_outlier=breakout,
        observed_at=observed_at,
        recorded_at="2026-08-21T00:00:00Z",
    )


class RecordValidationTests(unittest.TestCase):
    def test_record_derives_local_weekday_and_allows_missing_optional_metrics(self) -> None:
        prepared = record(1)
        self.assertEqual(prepared["weekday"], "Monday")
        self.assertIsNone(prepared["saves"])
        self.assertIsNone(prepared["qualified_comments"])

    def test_invalid_spine_url_and_attention_source_fail_closed(self) -> None:
        raw = record(1)
        raw["selected_spine"] = "viral"
        with self.assertRaisesRegex(workflow.WorkflowError, "selected_spine"):
            spine_feedback.validate_record(raw)

        raw = record(1)
        raw["post_url"] = "https://example.com/posts/1"
        with self.assertRaisesRegex(workflow.WorkflowError, "LinkedIn"):
            spine_feedback.validate_record(raw)

        raw = record(1)
        raw["attention_source"] = "linkedin_scrape"
        with self.assertRaisesRegex(workflow.WorkflowError, "attention_source"):
            spine_feedback.validate_record(raw)

    def test_timestamp_order_and_weekday_are_validated(self) -> None:
        raw = record(1)
        raw["observed_at"] = "2026-08-16T00:00:00Z"
        with self.assertRaisesRegex(workflow.WorkflowError, "cannot precede"):
            spine_feedback.validate_record(raw)

        raw = record(1)
        raw["weekday"] = "Tuesday"
        with self.assertRaisesRegex(workflow.WorkflowError, "weekday"):
            spine_feedback.validate_record(raw)


class PrivateFileTests(unittest.TestCase):
    def test_append_and_load_stay_owner_only_under_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "private"
            private.mkdir(mode=0o700)
            path = private / "spine-performance.jsonl"
            spine_feedback.append_record(
                record(1),
                path=path,
                private_root=private,
                _allow_test_root=True,
            )
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            loaded = spine_feedback.load_records(
                path=path,
                private_root=private,
                _allow_test_root=True,
            )
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["selected_spine"], "counterposition")

    def test_existing_unsafe_feedback_file_is_rejected_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "private"
            private.mkdir(mode=0o700)
            path = private / "spine-performance.jsonl"
            path.write_bytes(b"do-not-repair\n")
            path.chmod(0o644)
            before = path.read_bytes()

            with self.assertRaisesRegex(workflow.WorkflowError, "unavailable or unsafe"):
                spine_feedback.append_record(
                    record(1),
                    path=path,
                    private_root=private,
                    _allow_test_root=True,
                )

            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mode & 0o777, 0o644)

    def test_feedback_path_cannot_escape_private_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "private"
            private.mkdir(mode=0o700)
            outside = Path(temporary) / "outside.jsonl"
            with self.assertRaisesRegex(workflow.WorkflowError, "data/private"):
                spine_feedback.append_record(
                    record(1),
                    path=outside,
                    private_root=private,
                    _allow_test_root=True,
                )


class SummaryTests(unittest.TestCase):
    def test_baseline_uses_medians_and_excludes_breakout_outlier(self) -> None:
        rows = [
            record(index, impressions=800 + 100 * index, engagements=8 + index)
            for index in range(5)
        ]
        rows.append(
            record(99, impressions=227_249, engagements=684, breakout=True)
        )
        summary = spine_feedback.summarise(rows)
        counter = summary["by_spine"]["counterposition"]
        self.assertEqual(summary["excluded_breakout_outliers"], 1)
        self.assertEqual(summary["baseline_records"], 5)
        self.assertEqual(counter["observation_count"], 5)
        self.assertEqual(counter["median_impressions"], 1_000)
        self.assertEqual(counter["median_engagements"], 10)
        self.assertEqual(counter["median_engagement_rate_pct"], 1.0)
        self.assertEqual(counter["sample_status"], "READY_TO_COMPARE")
        self.assertFalse(summary["strategy_mutated"])

    def test_latest_snapshot_per_post_wins_without_inflating_sample_size(self) -> None:
        first = record(
            1,
            impressions=500,
            engagements=5,
            observed_at="2026-08-19T04:00:00Z",
        )
        latest = dict(record(1, impressions=1_000, engagements=10))
        latest["recorded_at"] = "2026-08-22T00:00:00Z"
        summary = spine_feedback.summarise([first, latest])
        counter = summary["by_spine"]["counterposition"]
        self.assertEqual(counter["observation_count"], 1)
        self.assertEqual(counter["median_impressions"], 1_000)
        self.assertEqual(counter["sample_status"], "INSUFFICIENT_SAMPLE")

    def test_later_snapshot_cannot_reclassify_immutable_post_context(self) -> None:
        first = record(1)
        changed = dict(record(1, observed_at="2026-08-21T04:00:00Z"))
        changed["recorded_at"] = "2026-08-22T00:00:00Z"
        changed["selected_spine"] = "failure_reversal"
        with self.assertRaisesRegex(workflow.WorkflowError, "immutable post context"):
            spine_feedback.summarise([first, changed])

    def test_outliers_can_be_included_explicitly_for_breakout_inspection(self) -> None:
        rows = [
            record(1),
            record(99, impressions=227_249, engagements=684, breakout=True),
        ]
        summary = spine_feedback.summarise(rows, include_outliers=True)
        self.assertEqual(summary["baseline_records"], 2)
        self.assertEqual(summary["excluded_breakout_outliers"], 0)
        self.assertEqual(len(summary["breakout_cases"]), 1)


class CliRoutingTests(unittest.TestCase):
    def test_spine_feedback_commands_are_exposed_by_single_entrypoint(self) -> None:
        record_help = subprocess.run(
            [str(CLI), "record-spine-performance", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(record_help.returncode, 0, record_help.stderr)
        self.assertIn("--spine", record_help.stdout)
        self.assertIn("--breakout-outlier", record_help.stdout)

        review_help = subprocess.run(
            [str(CLI), "spine-review", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(review_help.returncode, 0, review_help.stderr)
        self.assertIn("--include-outliers", review_help.stdout)


if __name__ == "__main__":
    unittest.main()
