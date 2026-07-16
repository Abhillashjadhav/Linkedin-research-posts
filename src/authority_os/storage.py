"""Direct SQLite persistence for the canonical research ledger."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Iterable, Mapping


SCHEMA_VERSION = 1


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
    """Create the idempotent research schema without deleting existing data."""

    path = Path(db_path)
    with closing(connect(path)) as connection, connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported database schema {version}; expected {SCHEMA_VERSION}."
            )
        connection.executescript(
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
                fetched_at TEXT NOT NULL
            );
            """
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return path


def insert_research_items(
    db_path: Path | str, items: Iterable[Mapping[str, object]]
) -> tuple[int, int]:
    """Insert validated items, deduplicating by URL and normalized content hash."""

    rows = list(items)
    inserted = 0
    with closing(connect(db_path)) as connection, connection:
        for item in rows:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO research_items (
                    canonical_url, title, body, source, author, published_at,
                    source_quality, content_hash, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            inserted += cursor.rowcount
    return inserted, len(rows) - inserted


def list_research_items(
    db_path: Path | str, *, limit: int = 200, topic: str | None = None
) -> list[dict[str, object]]:
    if limit < 1:
        raise ValueError("limit must be positive")
    query = "SELECT * FROM research_items"
    parameters: list[object] = []
    if topic:
        query += " WHERE lower(title || ' ' || body) LIKE ?"
        parameters.append(f"%{topic.lower()}%")
    query += " ORDER BY published_at DESC, id DESC LIMIT ?"
    parameters.append(limit)
    with closing(connect(db_path)) as connection:
        return [dict(row) for row in connection.execute(query, parameters)]
