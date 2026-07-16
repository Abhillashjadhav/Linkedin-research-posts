"""Small, direct SQLite persistence for research deduplication and performance."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Mapping

SCHEMA_VERSION = 1
CHECKPOINTS = {"2h", "24h", "72h", "7d"}
CHANNELS = {"organic", "paid"}
METRICS = (
    "impressions",
    "non_follower_reach",
    "external_comments",
    "reactions",
    "reposts",
    "saves",
    "sends",
    "profile_visits",
    "relevant_followers",
    "github_clicks",
    "recruiter_inbound",
    "founder_advisor_inbound",
    "speaking_podcast_inbound",
)


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialise(db_path: Path | str) -> Path:
    """Create the idempotent two-table schema without deleting existing data."""

    path = Path(db_path)
    with connect(path) as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, SCHEMA_VERSION):
            raise RuntimeError(
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

            CREATE TABLE IF NOT EXISTS performance (
                id INTEGER PRIMARY KEY,
                post_id TEXT NOT NULL,
                checkpoint TEXT NOT NULL
                    CHECK (checkpoint IN ('2h', '24h', '72h', '7d')),
                channel TEXT NOT NULL
                    CHECK (channel IN ('organic', 'paid')),
                observed_at TEXT NOT NULL,
                impressions INTEGER NOT NULL DEFAULT 0 CHECK (impressions >= 0),
                non_follower_reach INTEGER NOT NULL DEFAULT 0
                    CHECK (non_follower_reach >= 0),
                external_comments INTEGER NOT NULL DEFAULT 0
                    CHECK (external_comments >= 0),
                reactions INTEGER NOT NULL DEFAULT 0 CHECK (reactions >= 0),
                reposts INTEGER NOT NULL DEFAULT 0 CHECK (reposts >= 0),
                saves INTEGER NOT NULL DEFAULT 0 CHECK (saves >= 0),
                sends INTEGER NOT NULL DEFAULT 0 CHECK (sends >= 0),
                profile_visits INTEGER NOT NULL DEFAULT 0
                    CHECK (profile_visits >= 0),
                relevant_followers INTEGER NOT NULL DEFAULT 0
                    CHECK (relevant_followers >= 0),
                github_clicks INTEGER NOT NULL DEFAULT 0 CHECK (github_clicks >= 0),
                recruiter_inbound INTEGER NOT NULL DEFAULT 0
                    CHECK (recruiter_inbound >= 0),
                founder_advisor_inbound INTEGER NOT NULL DEFAULT 0
                    CHECK (founder_advisor_inbound >= 0),
                speaking_podcast_inbound INTEGER NOT NULL DEFAULT 0
                    CHECK (speaking_podcast_inbound >= 0),
                UNIQUE (post_id, checkpoint, channel)
            );
            """
        )
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return path


def insert_research_items(
    db_path: Path | str, items: Iterable[Mapping[str, object]]
) -> tuple[int, int]:
    """Insert validated items, deduplicating by URL and normalised content hash."""

    rows = list(items)
    inserted = 0
    with connect(db_path) as connection:
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
    with connect(db_path) as connection:
        return [dict(row) for row in connection.execute(query, parameters)]


def record_performance(db_path: Path | str, record: Mapping[str, object]) -> None:
    """Insert or update one explicit post/checkpoint/channel observation."""

    post_id = str(record.get("post_id", "")).strip()
    checkpoint = str(record.get("checkpoint", ""))
    channel = str(record.get("channel", ""))
    observed_at = str(record.get("observed_at", "")).strip()
    if not post_id:
        raise ValueError("post_id is required")
    if checkpoint not in CHECKPOINTS:
        raise ValueError(f"checkpoint must be one of {sorted(CHECKPOINTS)}")
    if channel not in CHANNELS:
        raise ValueError(f"channel must be one of {sorted(CHANNELS)}")
    if not observed_at:
        raise ValueError("observed_at is required")

    values: list[int] = []
    for metric in METRICS:
        value = int(record.get(metric, 0))
        if value < 0:
            raise ValueError(f"{metric} cannot be negative")
        values.append(value)

    columns = ", ".join(METRICS)
    placeholders = ", ".join("?" for _ in METRICS)
    updates = ", ".join(f"{metric}=excluded.{metric}" for metric in METRICS)
    with connect(db_path) as connection:
        connection.execute(
            f"""
            INSERT INTO performance (
                post_id, checkpoint, channel, observed_at, {columns}
            ) VALUES (?, ?, ?, ?, {placeholders})
            ON CONFLICT(post_id, checkpoint, channel) DO UPDATE SET
                observed_at=excluded.observed_at, {updates}
            """,
            [post_id, checkpoint, channel, observed_at, *values],
        )


def list_performance(db_path: Path | str) -> list[dict[str, object]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT * FROM performance
            ORDER BY observed_at DESC, post_id, checkpoint, channel
            """
        )
        return [dict(row) for row in rows]
