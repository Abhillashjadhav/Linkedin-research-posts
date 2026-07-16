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

    def test_schema_contains_research_table_and_provenance_column(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            }
            columns = {
                row[1] for row in connection.execute("PRAGMA table_info(research_items)")
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(tables, {"research_items"})
        self.assertIn("evidence_origin", columns)
        self.assertEqual(version, 2)

    def test_v1_rows_are_quarantined_until_exact_private_reimport(self) -> None:
        legacy = Path(self.temporary.name) / "legacy.sqlite"
        prepared = workflow.prepare_research_items(
            [item("https://example.com/legacy")],
            fetched_at="2026-07-16T01:00:00Z",
        )[0]
        with closing(sqlite3.connect(legacy)) as connection, connection:
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
                (
                    prepared["canonical_url"],
                    prepared["title"],
                    prepared["body"],
                    prepared["source"],
                    prepared["author"],
                    prepared["published_at"],
                    prepared["source_quality"],
                    prepared["content_hash"],
                    prepared["fetched_at"],
                ),
            )

        storage.initialise(legacy)
        self.assertEqual(
            storage.list_research_items(legacy)[0]["evidence_origin"],
            "legacy-unverified",
        )
        self.assertEqual(
            storage.list_research_items(
                legacy, evidence_origins=("private-import",)
            ),
            [],
        )

        inserted, duplicates = storage.insert_research_items(
            legacy, [prepared], evidence_origin="private-import"
        )
        self.assertEqual((inserted, duplicates), (0, 1))
        promoted = storage.list_research_items(
            legacy, evidence_origins=("private-import",)
        )
        self.assertEqual(len(promoted), 1)

    def test_fixture_rows_are_isolated_and_cannot_demote_private_rows(self) -> None:
        fixture_raw = item(
            "https://example.com/provenance",
            title="Synthetic title",
            body="Shared body",
        )
        private_raw = item(
            "https://example.com/provenance",
            title="Private title",
            body="  shared   BODY  ",
        )
        private_raw.update(
            {
                "source": "Explicit private source",
                "author": "Private author",
                "published_at": "2025-01-02T00:00:00Z",
                "source_quality": "secondary",
            }
        )
        fixture = workflow.prepare_research_items(
            [fixture_raw], fetched_at="2026-07-16T01:00:00Z"
        )
        private = workflow.prepare_research_items(
            [private_raw], fetched_at="2026-07-16T02:00:00Z"
        )
        storage.insert_research_items(
            self.database, fixture, evidence_origin="synthetic-fixture"
        )
        self.assertEqual(
            storage.list_research_items(
                self.database, evidence_origins=("private-import",)
            ),
            [],
        )
        storage.insert_research_items(
            self.database, private, evidence_origin="private-import"
        )
        promoted = storage.list_research_items(self.database)[0]
        for field in (
            "title",
            "body",
            "source",
            "author",
            "published_at",
            "source_quality",
            "fetched_at",
        ):
            self.assertEqual(promoted[field], private[0][field])
        self.assertEqual(promoted["evidence_origin"], "private-import")
        storage.insert_research_items(
            self.database, fixture, evidence_origin="synthetic-fixture"
        )
        preserved = storage.list_research_items(self.database)[0]
        self.assertEqual(preserved["evidence_origin"], "private-import")
        self.assertEqual(preserved["source"], "Explicit private source")
        self.assertEqual(preserved["source_quality"], "secondary")

    def test_one_key_collision_does_not_promote_fixture_body(self) -> None:
        cases = (
            (
                item("https://example.com/collision", body="Fixture body"),
                item("https://example.com/collision", body="Different private body"),
            ),
            (
                item("https://example.com/fixture-url", body="Shared body"),
                item("https://example.com/private-url", body="Shared body"),
            ),
        )
        for index, (fixture_raw, private_raw) in enumerate(cases):
            with self.subTest(index=index):
                database = Path(self.temporary.name) / f"collision-{index}.sqlite"
                storage.initialise(database)
                fixture_item = workflow.prepare_research_items([fixture_raw])
                private_item = workflow.prepare_research_items([private_raw])
                storage.insert_research_items(
                    database,
                    fixture_item,
                    evidence_origin="synthetic-fixture",
                )
                storage.insert_research_items(
                    database,
                    private_item,
                    evidence_origin="private-import",
                )
                rows = storage.list_research_items(database)
                self.assertEqual(rows[0]["evidence_origin"], "synthetic-fixture")
                self.assertEqual(
                    storage.list_research_items(
                        database, evidence_origins=("private-import",)
                    ),
                    [],
                )

    def test_research_deduplicates_url_and_normalized_content(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item("HTTPS://EXAMPLE.COM/path/?utm_source=test&b=2&a=1"),
                item("https://example.com/path?a=1&b=2"),
                item("https://example.org/other", title="Different title"),
            ],
            fetched_at="2026-07-16T01:00:00Z",
        )
        inserted, duplicates = storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        self.assertEqual((inserted, duplicates), (1, 2))
        rows = storage.list_research_items(self.database)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["canonical_url"], "https://example.com/path?a=1&b=2")

    def test_initialise_is_idempotent_and_preserves_rows(self) -> None:
        prepared = workflow.prepare_research_items([item("https://example.com/one")])
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
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

    def test_invalid_source_timestamp_is_rejected_before_storage(self) -> None:
        raw = item("https://example.com/item")
        raw["published_at"] = "not-a-date"
        with self.assertRaisesRegex(ValueError, "invalid source timestamp"):
            workflow.prepare_research_items([raw])

    def test_null_required_fields_are_rejected(self) -> None:
        for field in ("title", "source", "published_at", "url"):
            raw = item("https://example.com/item")
            raw[field] = None
            with self.subTest(field=field), self.assertRaises(ValueError):
                workflow.prepare_research_items([raw])

    def test_json_object_without_items_list_is_rejected(self) -> None:
        source = Path(self.temporary.name) / "malformed.json"
        source.write_text('{"research_items": []}', encoding="utf-8")
        with self.assertRaisesRegex(workflow.WorkflowError, "must contain an items"):
            workflow.load_research_file(source)

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
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        self.assertEqual(len(storage.list_research_items(self.database, topic="RAG")), 1)
        with self.assertRaises(ValueError):
            storage.list_research_items(self.database, limit=0)

    def test_topic_terms_are_boundary_safe_and_filter_before_the_limit(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item(
                    f"https://example.com/item-{index}",
                    title=(
                        "Go reliability target"
                        if index == 204
                        else f"Governance research item {index}"
                    ),
                    body=f"Distinct body {index}",
                )
                for index in range(205)
            ]
        )
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        self.assertEqual(len(storage.list_research_items(self.database)), 200)
        matches = storage.list_research_items(
            self.database, topic_terms=("go", "reliability")
        )
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["title"], "Go reliability target")
        with self.assertRaises(ValueError):
            storage.list_research_items(self.database, topic_terms=())

    def test_topic_terms_can_be_distributed_across_one_cluster(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item(
                    "https://example.com/agent",
                    title="Agent workflows",
                    body="An agent-focused body without the other requested term.",
                ),
                item(
                    "https://example.com/reliability",
                    title="Reliability methods",
                    body="A reliability-focused body without the other requested term.",
                ),
            ]
        )
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        rows = storage.list_research_items(
            self.database, topic_terms=("agent", "reliability")
        )
        self.assertEqual(len(rows), 2)
        analysis = workflow.analyse_research(rows, topic="agent reliability")
        self.assertEqual(analysis["pass_2"]["selected"]["slug"], "agent-reliability")

    def test_body_only_matches_cannot_crowd_out_an_older_title_match(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item(
                    f"https://example.com/body-{index}",
                    title=f"Unrelated title {index}",
                    body="Agent reliability appears only in this full body.",
                )
                for index in range(205)
            ]
            + [
                item(
                    "https://example.com/title-match",
                    title="Agent reliability evidence",
                    body="A bounded full body.",
                )
            ]
        )
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        rows = storage.list_research_items(
            self.database, topic_terms=("agent", "reliability")
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "Agent reliability evidence")

    def test_prefilter_preserves_a_match_expressed_only_by_the_cluster_slug(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item(
                    "https://example.com/failure",
                    title="Workflow failure methods",
                    body="A distinct body about the mechanism.",
                )
            ]
        )
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        rows = storage.list_research_items(
            self.database,
            topic_terms=workflow.topic_prefilter_terms("agent reliability"),
        )
        self.assertEqual(len(rows), 1)
        analysis = workflow.analyse_research(rows, topic="agent reliability")
        self.assertEqual(analysis["pass_2"]["selected"]["slug"], "agent-reliability")

    def test_prefilter_preserves_prefix_based_theme_matches(self) -> None:
        prepared = workflow.prepare_research_items(
            [
                item(
                    "https://example.com/reliability-prefix",
                    title="Reliability methods",
                    body="A distinct body about the mechanism.",
                ),
                item(
                    "https://example.com/evaluation-prefix",
                    title="Evaluation design",
                    body="A distinct body about measurement.",
                ),
            ]
        )
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        cases = (
            ("agent", "agent-reliability"),
            ("evaluations", "evaluations"),
        )
        for topic, expected_slug in cases:
            with self.subTest(topic=topic):
                rows = storage.list_research_items(
                    self.database,
                    topic_terms=workflow.topic_prefilter_terms(topic),
                )
                analysis = workflow.analyse_research(rows, topic=topic)
                self.assertEqual(
                    analysis["pass_2"]["selected"]["slug"], expected_slug
                )


if __name__ == "__main__":
    unittest.main()
