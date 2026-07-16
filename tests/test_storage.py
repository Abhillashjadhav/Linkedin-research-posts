"""Tests for research normalization and the persistent dedup ledger."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from authority_os import storage, workflow


def item(url: str, *, title: str = "Reliability note", body: str = "Stable body") -> dict[str, object]:
    return {
        "url": url,
        "title": title,
        "body": body,
        "source": "Synthetic source",
        "published_at": "2026-07-16T00:00:00Z",
        "source_quality": "primary",
    }


class ResearchStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "private" / "authority.sqlite"
        storage.initialise(self.database)

    def test_schema_contains_only_the_current_research_table(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
        self.assertEqual(tables, {"research_items"})

    def test_research_deduplicates_url_and_normalized_content(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item("HTTPS://EXAMPLE.COM/path/?utm_source=test&b=2&a=1"),
                item("https://example.com/path?a=1&b=2"),
                item("https://example.org/other", title="Different title"),
            ],
            fetched_at="2026-07-16T01:00:00Z",
        )
        inserted, duplicates = storage.insert_research_items(self.database, prepared)
        self.assertEqual((inserted, duplicates), (1, 2))
        rows = storage.list_research_items(self.database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonical_url"], "https://example.com/path?a=1&b=2")

    def test_initialise_is_idempotent_and_preserves_rows(self) -> None:
        prepared = workflow.prepare_research_items([item("https://example.com/one")])
        storage.insert_research_items(self.database, prepared)
        storage.initialise(self.database)
        self.assertEqual(len(storage.list_research_items(self.database)), 1)

    def test_private_or_local_source_url_is_rejected(self) -> None:
        for url in (
            "http://localhost/item",
            "http://foo.localhost/item",
            "http://127.0.0.1/item",
            "http://127.1/item",
            "http://2130706433/item",
            "http://0177.0.0.1/item",
            "http://0x7f000001/item",
            "file:///tmp/item",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                workflow.prepare_research_items([item(url)])

    def test_public_ipv6_url_remains_bracketed(self) -> None:
        self.assertEqual(
            workflow.canonicalise_url("HTTPS://[2606:4700:4700::1111]:443/path/"),
            "https://[2606:4700:4700::1111]/path",
        )

    def test_legacy_public_ipv4_is_normalized_before_storage(self) -> None:
        self.assertEqual(
            workflow.canonicalise_url("https://134744072/dns"),
            "https://8.8.8.8/dns",
        )

    def test_invalid_source_quality_is_rejected(self) -> None:
        raw = item("https://example.com/item")
        raw["source_quality"] = "social"
        with self.assertRaises(ValueError):
            workflow.prepare_research_items([raw])

    def test_non_object_research_item_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a JSON object"):
            workflow.prepare_research_items(["bad"])

    def test_topic_filter_and_positive_limit(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item("https://example.com/one", title="Agent reliability", body="First body"),
                item("https://example.com/two", title="RAG evaluation", body="Second body"),
            ]
        )
        storage.insert_research_items(self.database, prepared)
        self.assertEqual(len(storage.list_research_items(self.database, topic="RAG")), 1)
        with self.assertRaises(ValueError):
            storage.list_research_items(self.database, limit=0)


if __name__ == "__main__":
    unittest.main()
