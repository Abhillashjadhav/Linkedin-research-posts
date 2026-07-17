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


def performance_record(
    *,
    channel: str = "organic",
    checkpoint: str = "24h",
    observed_at: str = "2026-07-17T12:00:00Z",
    impressions: int = 1_000,
) -> dict[str, object]:
    return {
        "package_id": "2026-07-16-agent-reliability",
        "candidate_id": "candidate-1",
        "package_created_at": "2026-07-16T00:00:00Z",
        "published_at": "2026-07-16T00:00:00Z",
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
        "checkpoint": checkpoint,
        "channel": channel,
        "observed_at": observed_at,
        **{
            metric: impressions if metric == "impressions" else index
            for index, metric in enumerate(storage.PERFORMANCE_METRICS)
        },
        "recorded_at": "2026-07-25T00:00:00Z",
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
        self.assertEqual(
            tables,
            {"research_items", "published_posts", "performance_observations"},
        )
        self.assertIn("evidence_origin", columns)
        self.assertEqual(version, 3)

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


class PerformanceStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "private" / "authority.sqlite"
        storage.initialise(self.database)

    def test_all_metrics_round_trip_and_channels_remain_separate(self) -> None:
        organic = performance_record(channel="organic", impressions=1_000)
        paid = performance_record(channel="paid", impressions=250)
        result = storage.record_performance_many(self.database, [organic, paid])
        self.assertEqual(result, {"inserted": 2, "replaced": 0, "unchanged": 0})
        rows = storage.list_performance(self.database)
        by_channel = {str(row["channel"]): row for row in rows}
        self.assertEqual(set(by_channel), {"organic", "paid"})
        self.assertEqual(by_channel["organic"]["impressions"], 1_000)
        self.assertEqual(by_channel["paid"]["impressions"], 250)
        for metric in storage.PERFORMANCE_METRICS:
            self.assertIn(metric, by_channel["organic"])

    def test_idempotence_explicit_replace_and_older_snapshot_guard(self) -> None:
        original = performance_record()
        first = storage.record_performance(self.database, original)
        repeated = storage.record_performance(self.database, original)
        self.assertEqual(first["inserted"], 1)
        self.assertEqual(repeated["unchanged"], 1)

        corrected = dict(original, impressions=1_200)
        with self.assertRaisesRegex(ValueError, "--replace"):
            storage.record_performance(self.database, corrected)
        replaced = storage.record_performance(
            self.database, corrected, replace=True
        )
        self.assertEqual(replaced["replaced"], 1)
        self.assertEqual(
            storage.list_performance(self.database)[0]["impressions"], 1_200
        )

        older = dict(
            corrected,
            observed_at="2026-07-17T10:00:00Z",
            impressions=1_300,
        )
        with self.assertRaisesRegex(ValueError, "older"):
            storage.record_performance(self.database, older, replace=True)
        self.assertEqual(
            storage.list_performance(self.database)[0]["impressions"], 1_200
        )

    def test_organic_replacement_never_changes_paid(self) -> None:
        organic = performance_record(channel="organic", impressions=1_000)
        paid = performance_record(channel="paid", impressions=250)
        storage.record_performance_many(self.database, [organic, paid])
        storage.record_performance(
            self.database,
            dict(organic, impressions=1_500),
            replace=True,
        )
        rows = storage.list_performance(self.database)
        by_channel = {str(row["channel"]): row for row in rows}
        self.assertEqual(by_channel["organic"]["impressions"], 1_500)
        self.assertEqual(by_channel["paid"]["impressions"], 250)

    def test_publication_context_is_immutable_and_batches_are_atomic(self) -> None:
        organic = performance_record(channel="organic")
        conflicting = performance_record(
            channel="paid",
            impressions=100,
        )
        conflicting["candidate_id"] = "candidate-2"
        with self.assertRaisesRegex(ValueError, "immutable publication context"):
            storage.record_performance_many(
                self.database,
                [organic, conflicting],
            )
        self.assertEqual(storage.list_performance(self.database), [])
        with closing(sqlite3.connect(self.database)) as connection:
            posts = connection.execute("SELECT count(*) FROM published_posts").fetchone()[0]
        self.assertEqual(posts, 0)

    def test_v2_legacy_performance_table_is_quarantined_without_data_loss(self) -> None:
        database = Path(self.temporary.name) / "legacy-performance.sqlite"
        metrics_sql = ",\n".join(
            f"{metric} INTEGER NOT NULL" for metric in storage.PERFORMANCE_METRICS
        )
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.executescript(
                f"""
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
                    fetched_at TEXT NOT NULL,
                    evidence_origin TEXT NOT NULL
                );
                CREATE TABLE performance (
                    id INTEGER PRIMARY KEY,
                    post_id TEXT NOT NULL,
                    checkpoint TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    {metrics_sql}
                );
                PRAGMA user_version = 2;
                """
            )
            columns = (
                "post_id",
                "checkpoint",
                "channel",
                "observed_at",
                *storage.PERFORMANCE_METRICS,
            )
            connection.execute(
                f"INSERT INTO performance ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                ("legacy-post", "24h", "organic", "2026-07-16T00:00:00Z", *range(13)),
            )

        storage.initialise(database)
        with closing(sqlite3.connect(database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            legacy_row = connection.execute(
                "SELECT * FROM legacy_performance_unverified"
            ).fetchone()
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertNotIn("performance", tables)
        self.assertIn("legacy_performance_unverified", tables)
        self.assertEqual(legacy_row[1], "legacy-post")
        self.assertEqual(tuple(legacy_row[5:]), tuple(range(13)))
        self.assertEqual(version, 3)

    def test_unrecognized_legacy_schema_rolls_back_migration(self) -> None:
        database = Path(self.temporary.name) / "bad-legacy.sqlite"
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
                    fetched_at TEXT NOT NULL,
                    evidence_origin TEXT NOT NULL
                );
                CREATE TABLE performance (id INTEGER PRIMARY KEY, surprise TEXT);
                PRAGMA user_version = 2;
                """
            )
        with self.assertRaisesRegex(ValueError, "unrecognized"):
            storage.initialise(database)
        with closing(sqlite3.connect(database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(tables, {"research_items", "performance"})
        self.assertEqual(version, 2)

    def test_reserved_performance_table_collisions_fail_closed(self) -> None:
        for table_name in ("published_posts", "performance_observations"):
            with self.subTest(table_name=table_name):
                database = Path(self.temporary.name) / f"bad-{table_name}.sqlite"
                with closing(sqlite3.connect(database)) as connection, connection:
                    connection.execute(
                        f"CREATE TABLE {table_name} (surprise TEXT)"
                    )
                    connection.execute("PRAGMA user_version = 2")
                with self.assertRaisesRegex(ValueError, "Reserved performance table"):
                    storage.initialise(database)
                with closing(sqlite3.connect(database)) as connection:
                    columns = [
                        row[1]
                        for row in connection.execute(
                            f"PRAGMA table_info({table_name})"
                        )
                    ]
                    version = connection.execute("PRAGMA user_version").fetchone()[0]
                self.assertEqual(columns, ["surprise"])
                self.assertEqual(version, 2)

    def test_new_private_ledger_uses_private_directory_and_file_modes(self) -> None:
        private_database = Path(self.temporary.name) / "new-private" / "ledger.sqlite"
        storage.initialise(private_database)
        self.assertEqual(private_database.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(private_database.stat().st_mode & 0o777, 0o600)

    def test_symlinked_database_is_rejected_without_touching_target(self) -> None:
        target = Path(self.temporary.name) / "outside.txt"
        target.write_bytes(b"do-not-touch")
        target.chmod(0o644)
        database = Path(self.temporary.name) / "linked.sqlite"
        database.symlink_to(target)
        with self.assertRaisesRegex(ValueError, "unsafe"):
            storage.initialise(database)
        self.assertEqual(target.read_bytes(), b"do-not-touch")
        self.assertEqual(target.stat().st_mode & 0o777, 0o644)

    def test_shared_writable_database_parent_is_rejected(self) -> None:
        shared = Path(self.temporary.name) / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        database = shared / "ledger.sqlite"
        with self.assertRaisesRegex(ValueError, "group/world-writable"):
            storage.initialise(database)
        self.assertFalse(database.exists())


if __name__ == "__main__":
    unittest.main()
