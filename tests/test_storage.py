from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from authority_os import storage, workflow


def performance_record(channel: str, impressions: int) -> dict[str, object]:
    return {
        "post_id": "post-one",
        "checkpoint": "24h",
        "channel": channel,
        "observed_at": "2026-07-16T12:00:00+00:00",
        "impressions": impressions,
        "profile_visits": 10 if channel == "organic" else 2,
        "saves": 4 if channel == "organic" else 1,
    }


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.db = Path(self.temporary.name) / "missing" / "authority_os.sqlite"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_missing_private_data_does_not_break_initialise(self) -> None:
        self.assertFalse(self.db.parent.exists())
        result = storage.initialise(self.db)
        self.assertEqual(result, self.db)
        self.assertTrue(self.db.exists())

    def test_schema_has_exactly_two_tables(self) -> None:
        storage.initialise(self.db)
        with closing(sqlite3.connect(self.db)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(tables, {"research_items", "performance"})
        self.assertEqual(version, 1)

    def test_research_deduplicates_url_and_normalised_content(self) -> None:
        storage.initialise(self.db)
        raw = [
            {
                "canonical_url": "https://EXAMPLE.org/post/?utm_source=test",
                "title": "Agent reliability",
                "body": "Same body with   spacing.",
                "source": "A",
                "author": "Author",
                "published_at": "2026-07-16T00:00:00Z",
                "source_quality": "primary",
            },
            {
                "canonical_url": "https://example.org/post",
                "title": "A different title",
                "body": "Different body",
                "source": "B",
                "author": "Author",
                "published_at": "2026-07-16T01:00:00Z",
                "source_quality": "secondary",
            },
            {
                "canonical_url": "https://example.org/elsewhere",
                "title": "Syndicated reliability analysis",
                "body": "same body with spacing.",
                "source": "C",
                "author": "Author",
                "published_at": "2026-07-16T02:00:00Z",
                "source_quality": "mixed",
            },
        ]
        items = workflow.prepare_research_items(raw)
        inserted, duplicates = storage.insert_research_items(self.db, items)
        self.assertEqual((inserted, duplicates), (1, 2))
        self.assertEqual(len(storage.list_research_items(self.db)), 1)

    def test_initialise_is_idempotent_and_preserves_rows(self) -> None:
        storage.initialise(self.db)
        item = workflow.prepare_research_items(
            [
                {
                    "canonical_url": "https://example.org/a",
                    "title": "A",
                    "body": "Body",
                    "source": "A",
                    "author": "A",
                    "published_at": "2026-07-16T00:00:00Z",
                    "source_quality": "primary",
                }
            ]
        )
        storage.insert_research_items(self.db, item)
        storage.initialise(self.db)
        self.assertEqual(len(storage.list_research_items(self.db)), 1)

    def test_paid_and_organic_metrics_remain_separate(self) -> None:
        storage.initialise(self.db)
        storage.record_performance(self.db, performance_record("organic", 1000))
        storage.record_performance(self.db, performance_record("paid", 250))
        rows = storage.list_performance(self.db)
        by_channel = {row["channel"]: row for row in rows}
        self.assertEqual(set(by_channel), {"organic", "paid"})
        self.assertEqual(by_channel["organic"]["impressions"], 1000)
        self.assertEqual(by_channel["paid"]["impressions"], 250)

        updated = performance_record("organic", 1200)
        storage.record_performance(self.db, updated)
        by_channel = {row["channel"]: row for row in storage.list_performance(self.db)}
        self.assertEqual(by_channel["organic"]["impressions"], 1200)
        self.assertEqual(by_channel["paid"]["impressions"], 250)

    def test_negative_performance_is_rejected_without_writing(self) -> None:
        storage.initialise(self.db)
        record = performance_record("organic", -1)
        with self.assertRaises(ValueError):
            storage.record_performance(self.db, record)
        self.assertEqual(storage.list_performance(self.db), [])

    def test_invalid_csv_sized_batch_is_rejected_transactionally(self) -> None:
        storage.initialise(self.db)
        valid = performance_record("organic", 100)
        invalid = performance_record("paid", -1)
        with self.assertRaises(ValueError):
            storage.record_performance_many(self.db, [valid, invalid])
        self.assertEqual(storage.list_performance(self.db), [])

    def test_private_or_local_source_url_is_rejected(self) -> None:
        for url in ("http://localhost/post", "http://127.0.0.1/post", "file:///tmp/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                workflow.canonicalise_url(url)

    def test_invalid_source_quality_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            workflow.prepare_research_items(
                [
                    {
                        "canonical_url": "https://example.org/a",
                        "title": "A",
                        "body": "Body",
                        "source": "A",
                        "author": "A",
                        "published_at": "2026-07-16T00:00:00Z",
                        "source_quality": "discovery",
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
