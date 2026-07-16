"""Direct SQLite persistence for the canonical research ledger."""

from __future__ import annotations

import re
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = 2
EVIDENCE_ORIGINS = frozenset(
    {"legacy-unverified", "private-import", "synthetic-fixture"}
)
INGEST_EVIDENCE_ORIGINS = EVIDENCE_ORIGINS - {"legacy-unverified"}


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
    except Exception:
        connection.close()
        raise
    return connection


def initialise(db_path: Path | str) -> Path:
    """Create or migrate the research schema without trusting legacy provenance."""

    path = Path(db_path)
    with closing(connect(path)) as connection, connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported database schema {version}; expected {SCHEMA_VERSION}."
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS research_items (
                id INTEGER PRIMARY KEY,
                canonical_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                source TEXT NOT NULL,
                author TEXT NOT NULL DEFAULT '',
                published_at TEXT NOT NULL,
                source_quality TEXT NOT NULL
                    CHECK (source_quality IN ('primary', 'secondary', 'mixed')),
                content_hash TEXT NOT NULL UNIQUE,
                fetched_at TEXT NOT NULL,
                evidence_origin TEXT NOT NULL DEFAULT 'legacy-unverified'
                    CHECK (evidence_origin IN (
                        'legacy-unverified', 'private-import', 'synthetic-fixture'
                    ))
            )
            """
        )
        columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(research_items)")
        }
        if "evidence_origin" not in columns:
            connection.execute(
                """
                ALTER TABLE research_items
                ADD COLUMN evidence_origin TEXT NOT NULL DEFAULT 'legacy-unverified'
                    CHECK (evidence_origin IN (
                        'legacy-unverified', 'private-import', 'synthetic-fixture'
                    ))
                """
            )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return path


def insert_research_items(
    db_path: Path | str,
    items: Iterable[Mapping[str, object]],
    *,
    evidence_origin: str,
) -> tuple[int, int]:
    """Insert validated items without allowing fixtures to gain live provenance."""

    if evidence_origin not in INGEST_EVIDENCE_ORIGINS:
        raise ValueError(
            f"evidence_origin must be one of {sorted(INGEST_EVIDENCE_ORIGINS)}"
        )
    rows = list(items)
    inserted = 0
    with closing(connect(db_path)) as connection, connection:
        for item in rows:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO research_items (
                    canonical_url, title, body, source, author, published_at,
                    source_quality, content_hash, fetched_at, evidence_origin
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["canonical_url"],
                    item["title"],
                    item["body"],
                    item["source"],
                    item.get("author", ""),
                    item["published_at"],
                    item["source_quality"],
                    item["content_hash"],
                    item["fetched_at"],
                    evidence_origin,
                ),
            )
            inserted += cursor.rowcount
            if cursor.rowcount == 0 and evidence_origin == "private-import":
                # An explicit private re-import may promote only the exact stored
                # URL/body pair. A one-key collision cannot lend private provenance
                # to a different body or source, and fixtures can never demote it.
                connection.execute(
                    """
                    UPDATE research_items
                    SET title = ?, body = ?, source = ?, author = ?,
                        published_at = ?, source_quality = ?, fetched_at = ?,
                        evidence_origin = 'private-import'
                    WHERE canonical_url = ? AND content_hash = ?
                    """,
                    (
                        item["title"],
                        item["body"],
                        item["source"],
                        item.get("author", ""),
                        item["published_at"],
                        item["source_quality"],
                        item["fetched_at"],
                        item["canonical_url"],
                        item["content_hash"],
                    ),
                )
    return inserted, len(rows) - inserted


def list_research_items(
    db_path: Path | str,
    *,
    limit: int = 200,
    topic: str | None = None,
    topic_terms: Sequence[str] | None = None,
    evidence_origins: Sequence[str] | None = None,
) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    if topic and topic_terms:
        raise ValueError("use topic or topic_terms, not both")
    origins = tuple(dict.fromkeys(evidence_origins or ()))
    if evidence_origins is not None and not origins:
        raise ValueError("evidence_origins must not be empty")
    if any(origin not in EVIDENCE_ORIGINS for origin in origins):
        raise ValueError(
            f"invalid evidence origin; expected one of {sorted(EVIDENCE_ORIGINS)}"
        )
    query = "SELECT * FROM research_items"
    parameters: list[object] = []
    required_terms = {
        term.casefold()
        for term in (topic_terms or ())
        if isinstance(term, str) and term.strip()
    }
    if topic_terms is not None and not required_terms:
        raise ValueError("topic_terms must contain at least one non-blank term")
    if len(required_terms) > 24 or any(
        not re.fullmatch(r"[a-z0-9]+\*?", term) for term in required_terms
    ):
        raise ValueError("topic_terms must contain at most 24 lexical terms")
    filters: list[str] = []
    if origins:
        filters.append(f"evidence_origin IN ({', '.join('?' for _ in origins)})")
        parameters.extend(origins)
    if topic:
        filters.append("lower(title || ' ' || body) LIKE ?")
        parameters.append(f"%{topic.lower()}%")
    if filters:
        query += " WHERE " + " AND ".join(filters)
    query += " ORDER BY published_at DESC, id DESC LIMIT ?"
    parameters.append(limit)
    with closing(connect(db_path)) as connection:
        if required_terms:
            connection.create_function(
                "title_has_topic_term",
                2,
                lambda value, term: int(
                    any(
                        token.startswith(str(term)[:-1])
                        if str(term).endswith("*")
                        else token == str(term)
                        for token in re.findall(
                            r"[a-z0-9]+", str(value).casefold()
                        )
                    )
                ),
                deterministic=True,
            )
            # Query each term independently so a rare term cannot be crowded out
            # by the limit on a common term. This matches the Analyst's title-only
            # metadata pass and bounds materialized full bodies to terms * limit.
            rows_by_id: dict[int, dict[str, object]] = {}
            for term in sorted(required_terms):
                origin_filter = ""
                origin_parameters: tuple[object, ...] = ()
                if origins:
                    placeholders = ", ".join("?" for _ in origins)
                    origin_filter = f"evidence_origin IN ({placeholders}) AND "
                    origin_parameters = tuple(origins)
                rows = connection.execute(
                    f"""
                    SELECT * FROM research_items
                    WHERE {origin_filter}title_has_topic_term(title, ?) = 1
                    ORDER BY published_at DESC, id DESC LIMIT ?
                    """,
                    (*origin_parameters, term, limit),
                )
                for row in rows:
                    converted = dict(row)
                    rows_by_id[int(converted["id"])] = converted
            return sorted(
                rows_by_id.values(),
                key=lambda row: (str(row["published_at"]), int(row["id"])),
                reverse=True,
            )
        return [dict(row) for row in connection.execute(query, parameters)]
