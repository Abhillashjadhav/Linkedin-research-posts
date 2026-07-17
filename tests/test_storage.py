"""Tests for research normalization and the persistent dedup ledger."""

from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from authority_os import learning, storage, workflow


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
        "learning_context_fingerprint": "a" * 64,
        "checkpoint": checkpoint,
        "channel": channel,
        "observed_at": observed_at,
        **{
            metric: impressions if metric == "impressions" else index
            for index, metric in enumerate(storage.PERFORMANCE_METRICS)
        },
        "recorded_at": "2026-07-25T00:00:00Z",
    }


class DatabaseHealthInspectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.database = Path(self.temporary.name) / "private" / "authority.sqlite"
        storage.initialise(self.database)

    def test_current_database_is_inspected_without_any_filesystem_change(self) -> None:
        prepared = workflow.prepare_research_items(
            [item("https://example.com/health-check")]
        )
        storage.insert_research_items(
            self.database, prepared, evidence_origin="private-import"
        )
        before_bytes = self.database.read_bytes()
        before_metadata = self.database.stat()
        before_entries = {
            entry.name for entry in self.database.parent.iterdir()
        }
        with closing(sqlite3.connect(self.database)) as connection:
            before_version = connection.execute("PRAGMA user_version").fetchone()[0]

        result = storage.inspect_database_health(self.database)

        after_metadata = self.database.stat()
        with closing(sqlite3.connect(self.database)) as connection:
            after_version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(
            result,
            {
                "status": "ready",
                "schema_version": storage.SCHEMA_VERSION,
                "permissions": "owner-only",
                "access": "read-only",
            },
        )
        self.assertEqual(self.database.read_bytes(), before_bytes)
        self.assertEqual(before_version, after_version)
        self.assertEqual(before_metadata.st_mode, after_metadata.st_mode)
        self.assertEqual(before_metadata.st_mtime_ns, after_metadata.st_mtime_ns)
        self.assertEqual(before_metadata.st_ctime_ns, after_metadata.st_ctime_ns)
        self.assertEqual(
            {entry.name for entry in self.database.parent.iterdir()},
            before_entries,
        )

    def test_learning_query_is_read_only_and_preserves_database_metadata(self) -> None:
        storage.record_performance(self.database, performance_record())
        before_bytes = self.database.read_bytes()
        before_metadata = self.database.stat()
        before_entries = {entry.name for entry in self.database.parent.iterdir()}

        rows = storage.list_performance_readonly(self.database)

        after_metadata = self.database.stat()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["package_id"], "2026-07-16-agent-reliability")
        self.assertEqual(self.database.read_bytes(), before_bytes)
        self.assertEqual(after_metadata.st_mode, before_metadata.st_mode)
        self.assertEqual(after_metadata.st_mtime_ns, before_metadata.st_mtime_ns)
        self.assertEqual(after_metadata.st_ctime_ns, before_metadata.st_ctime_ns)
        self.assertEqual(
            {entry.name for entry in self.database.parent.iterdir()}, before_entries
        )

    def test_path_swap_during_read_only_open_fails_closed(self) -> None:
        storage.record_performance(self.database, performance_record())
        attacker_dir = Path(self.temporary.name) / "attacker"
        attacker = attacker_dir / "authority.sqlite"
        storage.initialise(attacker)
        attacker_record = performance_record()
        attacker_record["package_id"] = "2026-07-16-attacker"
        storage.record_performance(attacker, attacker_record)
        parked = self.database.with_name("parked.sqlite")
        real_connect = sqlite3.connect
        swapped = False

        def swap_before_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
            nonlocal swapped
            if not swapped and str(args[0]).startswith("file:///dev/fd/"):
                os.replace(self.database, parked)
                os.replace(attacker, self.database)
                swapped = True
            return real_connect(*args, **kwargs)

        try:
            with patch(
                "authority_os.storage.sqlite3.connect",
                side_effect=swap_before_connect,
            ):
                with self.assertRaisesRegex(
                    ValueError, r"^Private database is unavailable or unsafe\.$"
                ):
                    storage.list_performance_readonly(self.database)
        finally:
            if parked.exists():
                if self.database.exists():
                    os.replace(self.database, attacker)
                os.replace(parked, self.database)
        self.assertTrue(swapped)
        rows = storage.list_performance_readonly(self.database)
        self.assertEqual(rows[0]["package_id"], "2026-07-16-agent-reliability")

    def test_missing_database_and_parent_are_never_created(self) -> None:
        missing = Path(self.temporary.name) / "missing" / "authority.sqlite"
        with self.assertRaisesRegex(
            ValueError, r"^Private database is unavailable or unsafe\.$"
        ):
            storage.inspect_database_health(missing)
        self.assertFalse(missing.parent.exists())
        self.assertFalse(missing.exists())

    def test_unsafe_permissions_are_rejected_without_being_repaired(self) -> None:
        original = self.database.read_bytes()
        self.database.chmod(0o644)
        with self.assertRaisesRegex(
            ValueError, r"^Private database is unavailable or unsafe\.$"
        ):
            storage.inspect_database_health(self.database)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o644)
        self.assertEqual(self.database.read_bytes(), original)

        self.database.chmod(0o600)
        self.database.parent.chmod(0o750)
        with self.assertRaisesRegex(
            ValueError, r"^Private database is unavailable or unsafe\.$"
        ):
            storage.inspect_database_health(self.database)
        self.assertEqual(self.database.parent.stat().st_mode & 0o777, 0o750)
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.database.read_bytes(), original)

    def test_database_sidecars_are_rejected_without_ignoring_pending_state(self) -> None:
        original = self.database.read_bytes()
        for suffix in ("-wal", "-shm", "-journal"):
            with self.subTest(suffix=suffix):
                sidecar = self.database.with_name(self.database.name + suffix)
                sidecar.write_bytes(b"pending-state")
                sidecar.chmod(0o600)
                try:
                    with self.assertRaisesRegex(
                        ValueError, r"^Private database is unavailable or unsafe\.$"
                    ):
                        storage.inspect_database_health(self.database)
                finally:
                    sidecar.unlink()
                self.assertEqual(self.database.read_bytes(), original)

    def test_symlink_is_rejected_without_reading_or_changing_its_target(self) -> None:
        target = self.database
        before = target.read_bytes()
        linked = target.parent / "linked.sqlite"
        linked.symlink_to(target)
        with self.assertRaisesRegex(
            ValueError, r"^Private database is unavailable or unsafe\.$"
        ):
            storage.inspect_database_health(linked)
        self.assertTrue(linked.is_symlink())
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

        linked_parent = Path(self.temporary.name) / "linked-private"
        linked_parent.symlink_to(target.parent, target_is_directory=True)
        with self.assertRaisesRegex(
            ValueError, r"^Private database is unavailable or unsafe\.$"
        ):
            storage.inspect_database_health(linked_parent / target.name)
        self.assertTrue(linked_parent.is_symlink())
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_old_schema_is_rejected_without_migration_or_version_change(self) -> None:
        legacy = Path(self.temporary.name) / "legacy"
        legacy.mkdir(mode=0o700)
        database = legacy / "authority.sqlite"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute("CREATE TABLE performance (id INTEGER PRIMARY KEY)")
            connection.execute("PRAGMA user_version = 2")
        database.chmod(0o600)
        before = database.read_bytes()

        with self.assertRaisesRegex(
            ValueError, r"^Private database schema is not current\.$"
        ):
            storage.inspect_database_health(database)

        self.assertEqual(database.read_bytes(), before)
        with closing(sqlite3.connect(database)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
        self.assertEqual(version, 2)
        self.assertEqual(tables, {"performance"})

    def test_supported_migrated_schema_is_current_and_remains_unchanged(self) -> None:
        migrated = Path(self.temporary.name) / "migrated.sqlite"
        with closing(sqlite3.connect(migrated)) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE research_items (
                    id INTEGER PRIMARY KEY,
                    canonical_url TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    source TEXT NOT NULL,
                    author TEXT NOT NULL DEFAULT "",
                    published_at TEXT NOT NULL,
                    source_quality TEXT NOT NULL,
                    content_hash TEXT NOT NULL UNIQUE,
                    fetched_at TEXT NOT NULL
                );
                PRAGMA user_version = 1;
                """
            )
        storage.initialise(migrated)
        before = migrated.read_bytes()

        result = storage.inspect_database_health(migrated)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(migrated.read_bytes(), before)
        with closing(sqlite3.connect(migrated)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA user_version").fetchone()[0],
                storage.SCHEMA_VERSION,
            )

    def test_current_version_with_an_unknown_object_is_rejected_unchanged(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute("CREATE TABLE unexpected (value TEXT)")
        before = self.database.read_bytes()
        with self.assertRaisesRegex(ValueError, "explicit recovery"):
            storage.initialise(self.database)
        self.assertEqual(self.database.read_bytes(), before)
        with self.assertRaisesRegex(
            ValueError, r"^Private database schema is not current\.$"
        ):
            storage.inspect_database_health(self.database)
        self.assertEqual(self.database.read_bytes(), before)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertIsNotNone(
                connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE name = 'unexpected'"
                ).fetchone()
            )

    def test_duplicate_table_trigger_name_fails_schema_attestation_unchanged(self) -> None:
        malicious = self.database.parent / "duplicate-object.sqlite"
        with closing(sqlite3.connect(malicious)) as connection, connection:
            connection.execute(storage.PUBLISHED_POSTS_SQL)
            connection.execute(storage.PERFORMANCE_OBSERVATIONS_SQL)
            connection.executescript(
                """
                CREATE TRIGGER research_items
                AFTER INSERT ON performance_observations
                BEGIN
                    UPDATE performance_observations
                    SET impressions = 999999
                    WHERE id = NEW.id;
                END;
                """
            )
            connection.execute(storage.RESEARCH_ITEMS_SQL)
            connection.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION}")
        malicious.chmod(0o600)
        before = malicious.read_bytes()
        before_metadata = malicious.stat()
        with self.assertRaisesRegex(
            ValueError, r"^Private database schema is not current\.$"
        ):
            storage.record_performance(malicious, performance_record())
        with closing(sqlite3.connect(malicious)) as connection:
            self.assertEqual(
                [
                    row[0]
                    for row in connection.execute(
                        "SELECT type FROM sqlite_master WHERE name = 'research_items'"
                    )
                ],
                ["trigger", "table"],
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM performance_observations"
                ).fetchone()[0],
                0,
            )

        for reader in (
            storage.inspect_database_health,
            storage.list_performance_readonly,
        ):
            with self.subTest(reader=reader.__name__), self.assertRaisesRegex(
                ValueError, r"^Private database schema is not current\.$"
            ):
                reader(malicious)

        after_metadata = malicious.stat()
        self.assertEqual(malicious.read_bytes(), before)
        self.assertEqual(after_metadata.st_mtime_ns, before_metadata.st_mtime_ns)
        self.assertEqual(after_metadata.st_ctime_ns, before_metadata.st_ctime_ns)

    def test_writable_schema_sqlite_trigger_fails_attestation_unchanged(self) -> None:
        with closing(sqlite3.connect(self.database)) as connection, connection:
            schema_version = connection.execute(
                "PRAGMA schema_version"
            ).fetchone()[0]
            connection.execute("PRAGMA writable_schema = ON")
            connection.execute(
                """
                INSERT INTO sqlite_master (type, name, tbl_name, rootpage, sql)
                VALUES ('trigger', 'sqlite_shadow', 'performance_observations', 0, ?)
                """,
                (
                    "CREATE TRIGGER sqlite_shadow AFTER INSERT ON "
                    "performance_observations BEGIN UPDATE performance_observations "
                    "SET impressions = 999999 WHERE id = NEW.id; END",
                ),
            )
            connection.execute(f"PRAGMA schema_version = {schema_version + 1}")
            connection.execute("PRAGMA writable_schema = OFF")
        before = self.database.read_bytes()
        before_metadata = self.database.stat()
        with self.assertRaisesRegex(
            ValueError, r"^Private database schema is not current\.$"
        ):
            storage.record_performance(self.database, performance_record())
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM performance_observations"
                ).fetchone()[0],
                0,
            )

        for reader in (
            storage.inspect_database_health,
            storage.list_performance_readonly,
        ):
            with self.subTest(reader=reader.__name__), self.assertRaisesRegex(
                ValueError, r"^Private database schema is not current\.$"
            ):
                reader(self.database)

        after_metadata = self.database.stat()
        self.assertEqual(self.database.read_bytes(), before)
        self.assertEqual(after_metadata.st_mtime_ns, before_metadata.st_mtime_ns)
        self.assertEqual(after_metadata.st_ctime_ns, before_metadata.st_ctime_ns)

    def test_current_schema_has_only_the_exact_allowed_internal_objects(self) -> None:
        expected = {
            (
                "sqlite_autoindex_research_items_1",
                "index",
                "research_items",
                None,
            ),
            (
                "sqlite_autoindex_research_items_2",
                "index",
                "research_items",
                None,
            ),
            (
                "sqlite_autoindex_published_posts_1",
                "index",
                "published_posts",
                None,
            ),
            (
                "sqlite_autoindex_performance_observations_1",
                "index",
                "performance_observations",
                None,
            ),
        }
        with closing(sqlite3.connect(self.database)) as connection:
            actual = {
                tuple(row)
                for row in connection.execute(
                    """
                    SELECT name, type, tbl_name, sql
                    FROM sqlite_master
                    WHERE name GLOB 'sqlite_*'
                    """
                )
            }

        self.assertEqual(actual, expected)
        self.assertEqual(
            storage.inspect_database_health(self.database)["status"],
            "ready",
        )

    def test_sidecars_created_during_immutable_open_fail_closed(self) -> None:
        real_connect = sqlite3.connect
        for index, reader in enumerate(
            (
                storage.inspect_database_health,
                storage.list_performance_readonly,
            ),
            start=1,
        ):
            with self.subTest(reader=reader.__name__):
                database = self.database.parent / f"sidecar-race-{index}.sqlite"
                storage.initialise(database)
                with closing(real_connect(database)) as connection, connection:
                    self.assertEqual(
                        connection.execute("PRAGMA journal_mode = WAL").fetchone()[0],
                        "wal",
                    )
                self.assertFalse(database.with_name(database.name + "-wal").exists())
                writers: list[sqlite3.Connection] = []

                def connect_with_pending_wal(
                    target: object, *args: object, **kwargs: object
                ) -> sqlite3.Connection:
                    if isinstance(target, str) and target.startswith("file:///dev/fd/"):
                        writer = real_connect(database)
                        writer.execute("CREATE TABLE pending_schema (value TEXT)")
                        writer.commit()
                        writers.append(writer)
                    return real_connect(target, *args, **kwargs)  # type: ignore[arg-type]

                try:
                    with (
                        patch.object(
                            storage.sqlite3,
                            "connect",
                            side_effect=connect_with_pending_wal,
                        ),
                        patch.object(
                            storage,
                            "_database_sidecars_absent",
                            wraps=storage._database_sidecars_absent,
                        ) as sidecar_check,
                        self.assertRaisesRegex(
                            ValueError,
                            r"^Private database is unavailable or unsafe\.$",
                        ),
                    ):
                        reader(database)
                    self.assertGreaterEqual(sidecar_check.call_count, 2)
                    self.assertTrue(
                        database.with_name(database.name + "-wal").exists()
                    )
                finally:
                    for writer in writers:
                        writer.close()

    def test_intermediate_symlink_cannot_redirect_readonly_database(self) -> None:
        outside = Path(self.temporary.name) / "outside"
        target = outside / "private" / "authority.sqlite"
        storage.initialise(target)
        storage.record_performance(target, performance_record())
        redirected = Path(self.temporary.name) / "redirected"
        redirected.mkdir(mode=0o700)
        (redirected / "data").symlink_to(outside, target_is_directory=True)
        escaped = redirected / "data" / "private" / "authority.sqlite"
        before = target.read_bytes()

        for reader in (
            storage.inspect_database_health,
            storage.list_performance_readonly,
        ):
            with self.subTest(reader=reader.__name__), self.assertRaisesRegex(
                ValueError, r"^Private database is unavailable or unsafe\.$"
            ):
                reader(escaped)

        self.assertTrue((redirected / "data").is_symlink())
        self.assertEqual(target.read_bytes(), before)

    def test_foreign_key_damage_fails_integrity_without_repair(self) -> None:
        columns = (
            "package_id",
            "checkpoint",
            "channel",
            "observed_at",
            *storage.PERFORMANCE_METRICS,
            "recorded_at",
            "updated_at",
        )
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                f"INSERT INTO performance_observations ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _ in columns)})",
                (
                    "missing-package",
                    "2h",
                    "organic",
                    "2026-07-16T02:00:00Z",
                    *([0] * len(storage.PERFORMANCE_METRICS)),
                    "2026-07-16T02:00:00Z",
                    "2026-07-16T02:00:00Z",
                ),
            )
        before = self.database.read_bytes()

        with self.assertRaisesRegex(
            ValueError, r"^Private database integrity check failed\.$"
        ):
            storage.inspect_database_health(self.database)

        self.assertEqual(self.database.read_bytes(), before)
        with closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(
                connection.execute("PRAGMA foreign_key_check").fetchall(),
                [("performance_observations", 1, "published_posts", 0)],
            )

    def test_corrupt_regular_file_fails_with_static_error_and_is_unchanged(self) -> None:
        corrupt = self.database.parent / "corrupt.sqlite"
        corrupt.write_bytes(b"private-corrupt-sentinel")
        corrupt.chmod(0o600)
        with self.assertRaises(ValueError) as raised:
            storage.inspect_database_health(corrupt)
        self.assertEqual(
            str(raised.exception), "Private database is unavailable or unsafe."
        )
        self.assertNotIn(str(corrupt), str(raised.exception))
        self.assertNotIn("private-corrupt-sentinel", str(raised.exception))
        self.assertEqual(corrupt.read_bytes(), b"private-corrupt-sentinel")
        self.assertEqual(corrupt.stat().st_mode & 0o777, 0o600)


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
        self.assertEqual(version, storage.SCHEMA_VERSION)

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

    def test_unknown_schema_object_blocks_research_writes(self) -> None:
        prepared = workflow.prepare_research_items(
            [item("https://example.com/untrusted-schema")]
        )
        with closing(sqlite3.connect(self.database)) as connection, connection:
            connection.execute(
                "CREATE VIEW unexpected_research AS SELECT 1 AS value"
            )
        before = self.database.read_bytes()

        with self.assertRaisesRegex(
            ValueError, r"^Private database schema is not current\.$"
        ):
            storage.insert_research_items(
                self.database,
                prepared,
                evidence_origin="private-import",
            )

        self.assertEqual(self.database.read_bytes(), before)
        with closing(sqlite3.connect(self.database)) as connection:
            count = connection.execute(
                "SELECT COUNT(*) FROM research_items"
            ).fetchone()[0]
        self.assertEqual(count, 0)

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

    def test_backdated_correction_rolls_back_the_whole_batch(self) -> None:
        organic = performance_record(channel="organic", impressions=1_000)
        paid = performance_record(channel="paid", impressions=250)
        storage.record_performance_many(self.database, [organic, paid])
        valid_correction = dict(
            organic,
            impressions=1_500,
            recorded_at="2026-07-26T00:00:00Z",
        )
        backdated_correction = dict(
            paid,
            impressions=500,
            recorded_at="2026-07-24T00:00:00Z",
        )

        with self.assertRaisesRegex(ValueError, "older correction"):
            storage.record_performance_many(
                self.database,
                [valid_correction, backdated_correction],
                replace=True,
            )

        rows = storage.list_performance(self.database)
        by_channel = {str(row["channel"]): row for row in rows}
        self.assertEqual(by_channel["organic"]["impressions"], 1_000)
        self.assertEqual(by_channel["paid"]["impressions"], 250)
        self.assertEqual(by_channel["organic"]["updated_at"], organic["recorded_at"])
        self.assertEqual(by_channel["paid"]["updated_at"], paid["recorded_at"])

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

    def test_learning_context_fingerprint_is_required_and_immutable(self) -> None:
        missing = performance_record()
        missing["learning_context_fingerprint"] = None
        with self.assertRaisesRegex(ValueError, "fingerprint is required"):
            storage.record_performance(self.database, missing)

        malformed = performance_record()
        malformed["learning_context_fingerprint"] = "A" * 64
        with self.assertRaisesRegex(ValueError, "fingerprint is invalid"):
            storage.record_performance(self.database, malformed)

        original = performance_record()
        storage.record_performance(self.database, original)
        changed = performance_record(channel="paid")
        changed["learning_context_fingerprint"] = "b" * 64
        with self.assertRaisesRegex(ValueError, "immutable publication context"):
            storage.record_performance(self.database, changed)

    def test_v3_rows_migrate_as_unanchored_and_remain_metric_eligible(self) -> None:
        database = Path(self.temporary.name) / "schema-v3.sqlite"
        original = performance_record(
            checkpoint="72h",
            observed_at="2026-07-19T01:00:00Z",
        )
        v3_fields = tuple(
            field
            for field in storage.PUBLISHED_POST_FIELDS
            if field != "learning_context_fingerprint"
        )
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(storage.RESEARCH_ITEMS_SQL)
            connection.execute(storage._PUBLISHED_POSTS_V3_SQL)
            connection.execute(storage.PERFORMANCE_OBSERVATIONS_SQL)
            connection.execute(
                f"INSERT INTO published_posts ({', '.join(v3_fields)}, "
                f"first_recorded_at) VALUES "
                f"({', '.join('?' for _ in (*v3_fields, 'first_recorded_at'))})",
                (
                    *(
                        storage._database_value(field, original[field])
                        for field in v3_fields
                    ),
                    original["recorded_at"],
                ),
            )
            observation_fields = storage.PERFORMANCE_OBSERVATION_FIELDS
            connection.execute(
                f"INSERT INTO performance_observations (package_id, "
                f"{', '.join(observation_fields)}, recorded_at, updated_at) "
                f"VALUES ({', '.join('?' for _ in range(len(observation_fields) + 3))})",
                (
                    original["package_id"],
                    *(original[field] for field in observation_fields),
                    original["recorded_at"],
                    original["recorded_at"],
                ),
            )
            connection.execute("PRAGMA user_version = 3")

        storage.initialise(database)
        migrated = storage.list_performance_readonly(database)

        self.assertEqual(len(migrated), 1)
        self.assertIsNone(migrated[0]["learning_context_fingerprint"])
        report = learning.build_weekly_review(
            migrated, as_of="2026-08-15T00:00:00Z"
        )
        self.assertEqual(report["basis"]["canonical_posts"], 1)
        self.assertEqual(
            report["strongest_hook_by_goal"]["authority"]["status"],
            "OBSERVED_REFERENCE_CONTEXT_GAP",
        )

        followup = performance_record(
            checkpoint="7d",
            observed_at="2026-07-23T00:00:00Z",
        )
        storage.record_performance(database, followup)
        self.assertTrue(
            all(
                row["learning_context_fingerprint"] is None
                for row in storage.list_performance_readonly(database)
            )
        )
        with closing(sqlite3.connect(database)) as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, storage.SCHEMA_VERSION)

    def test_v3_current_shape_cannot_preserve_a_forged_fingerprint(self) -> None:
        database = Path(self.temporary.name) / "forged-v3-anchor.sqlite"
        forged = performance_record()
        published_fields = storage.PUBLISHED_POST_FIELDS
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(storage.RESEARCH_ITEMS_SQL)
            connection.execute(storage.PUBLISHED_POSTS_SQL)
            connection.execute(storage.PERFORMANCE_OBSERVATIONS_SQL)
            connection.execute(
                f"INSERT INTO published_posts ({', '.join(published_fields)}, "
                f"first_recorded_at) VALUES "
                f"({', '.join('?' for _ in (*published_fields, 'first_recorded_at'))})",
                (
                    *(
                        storage._database_value(field, forged[field])
                        for field in published_fields
                    ),
                    forged["recorded_at"],
                ),
            )
            connection.execute("PRAGMA user_version = 3")

        storage.initialise(database)

        with closing(sqlite3.connect(database)) as connection:
            fingerprint = connection.execute(
                "SELECT learning_context_fingerprint FROM published_posts"
            ).fetchone()[0]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertIsNone(fingerprint)
        self.assertEqual(version, storage.SCHEMA_VERSION)

    def test_current_version_missing_fingerprint_column_is_not_self_repaired(self) -> None:
        database = Path(self.temporary.name) / "broken-current-schema.sqlite"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(storage.RESEARCH_ITEMS_SQL)
            connection.execute(storage._PUBLISHED_POSTS_V3_SQL)
            connection.execute(storage.PERFORMANCE_OBSERVATIONS_SQL)
            connection.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION}")
        before = database.read_bytes()

        with self.assertRaisesRegex(ValueError, "explicit recovery"):
            storage.initialise(database)

        self.assertEqual(database.read_bytes(), before)
        with closing(sqlite3.connect(database)) as connection:
            columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(published_posts)")
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertNotIn("learning_context_fingerprint", columns)
        self.assertEqual(version, storage.SCHEMA_VERSION)

    def test_current_version_missing_research_table_is_not_self_repaired(self) -> None:
        database = Path(self.temporary.name) / "broken-current-research.sqlite"
        with closing(sqlite3.connect(database)) as connection, connection:
            connection.execute(storage.PUBLISHED_POSTS_SQL)
            connection.execute(storage.PERFORMANCE_OBSERVATIONS_SQL)
            connection.execute(f"PRAGMA user_version = {storage.SCHEMA_VERSION}")
        before = database.read_bytes()

        with self.assertRaisesRegex(ValueError, "explicit recovery"):
            storage.initialise(database)

        self.assertEqual(database.read_bytes(), before)
        with closing(sqlite3.connect(database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertNotIn("research_items", tables)
        self.assertEqual(version, storage.SCHEMA_VERSION)

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
        self.assertEqual(version, storage.SCHEMA_VERSION)
        after_migration = database.read_bytes()
        self.assertEqual(storage.inspect_database_health(database)["status"], "ready")
        self.assertEqual(database.read_bytes(), after_migration)

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

    def test_late_schema_collision_rolls_back_legacy_table_rename(self) -> None:
        database = Path(self.temporary.name) / "late-migration-collision.sqlite"
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
                CREATE TABLE published_posts (surprise TEXT);
                PRAGMA user_version = 2;
                """
            )
        before = database.read_bytes()

        with self.assertRaisesRegex(ValueError, "Reserved performance table"):
            storage.initialise(database)

        self.assertEqual(database.read_bytes(), before)
        with closing(sqlite3.connect(database)) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            columns = [
                row[1]
                for row in connection.execute(
                    "PRAGMA table_info(published_posts)"
                )
            ]
            version = connection.execute("PRAGMA user_version").fetchone()[0]
        self.assertIn("performance", tables)
        self.assertNotIn("legacy_performance_unverified", tables)
        self.assertEqual(columns, ["surprise"])
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

    def test_intermediate_symlink_cannot_redirect_initialise_or_record(self) -> None:
        base = Path(self.temporary.name) / "mutating-root"
        base.mkdir(mode=0o700)
        outside = Path(self.temporary.name) / "mutating-outside"
        outside.mkdir(mode=0o700)
        (base / "data").symlink_to(outside, target_is_directory=True)
        escaped = base / "data" / "private" / "authority.sqlite"

        with self.assertRaisesRegex(ValueError, "unavailable or unsafe"):
            storage.initialise(escaped)
        self.assertFalse((outside / "private").exists())

        target = outside / "private" / "authority.sqlite"
        storage.initialise(target)
        before = target.read_bytes()
        with self.assertRaisesRegex(ValueError, "unavailable or unsafe"):
            storage.record_performance(escaped, performance_record())

        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(storage.list_performance(target), [])
        self.assertTrue((base / "data").is_symlink())

    def test_connect_time_parent_swap_cannot_create_an_outside_database(self) -> None:
        base = Path(self.temporary.name) / "connect-race"
        data = base / "data"
        data.mkdir(mode=0o700, parents=True)
        outside = Path(self.temporary.name) / "connect-race-outside"
        outside.mkdir(mode=0o700)
        database = data / "authority.sqlite"
        parked = base / "parked"
        real_connect = sqlite3.connect
        swapped = False

        def swap_parent(*args: object, **kwargs: object) -> sqlite3.Connection:
            nonlocal swapped
            if not swapped and isinstance(args[0], str):
                os.replace(data, parked)
                data.symlink_to(outside, target_is_directory=True)
                swapped = True
            return real_connect(*args, **kwargs)  # type: ignore[arg-type]

        try:
            with patch(
                "authority_os.storage.sqlite3.connect",
                side_effect=swap_parent,
            ):
                with self.assertRaisesRegex(ValueError, "unavailable or unsafe"):
                    storage.initialise(database)
            self.assertTrue(swapped)
            self.assertFalse((outside / database.name).exists())
            self.assertTrue((parked / database.name).exists())
        finally:
            if data.is_symlink():
                data.unlink()
            if parked.exists():
                os.replace(parked, data)

    def test_connection_revalidates_held_directories_before_execute(self) -> None:
        base = Path(self.temporary.name) / "lifecycle-race"
        data = base / "data"
        data.mkdir(mode=0o700, parents=True)
        outside = Path(self.temporary.name) / "lifecycle-outside"
        outside.mkdir(mode=0o700)
        database = data / "authority.sqlite"
        parked = base / "parked"
        storage.initialise(database)
        connection = storage.connect(database)
        cursor = connection.cursor()
        try:
            os.replace(data, parked)
            data.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "unavailable or unsafe"):
                connection.execute("SELECT 1")
            with self.assertRaisesRegex(ValueError, "unavailable or unsafe"):
                cursor.execute("SELECT 1")
            self.assertFalse((outside / database.name).exists())
        finally:
            if data.is_symlink():
                data.unlink()
            if parked.exists():
                os.replace(parked, data)
            connection.close()

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

    def test_owned_database_parent_is_normalised_for_readonly_health(self) -> None:
        shared = Path(self.temporary.name) / "shared"
        shared.mkdir(mode=0o777)
        shared.chmod(0o777)
        database = shared / "ledger.sqlite"
        storage.initialise(database)

        self.assertEqual(shared.stat().st_mode & 0o777, 0o700)
        self.assertEqual(database.stat().st_mode & 0o777, 0o600)
        self.assertEqual(
            storage.inspect_database_health(database)["status"], "ready"
        )


if __name__ == "__main__":
    unittest.main()
