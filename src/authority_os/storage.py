"""Direct SQLite persistence for research and manual performance checkpoints."""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCHEMA_VERSION = 3
EVIDENCE_ORIGINS = frozenset(
    {"legacy-unverified", "private-import", "synthetic-fixture"}
)
INGEST_EVIDENCE_ORIGINS = EVIDENCE_ORIGINS - {"legacy-unverified"}
PERFORMANCE_CHECKPOINTS = ("2h", "24h", "72h", "7d")
PERFORMANCE_CHANNELS = ("organic", "paid")
PERFORMANCE_OUTPUT_FORMATS = (
    "text",
    "carousel",
    "vertical-video",
    "article",
    "artifact-demo",
)
PERFORMANCE_METRICS = (
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
CRITIC_SNAPSHOT_FIELDS = (
    "hook_strength",
    "middle_escalation",
    "earned_closer",
    "specificity_and_source_quality",
    "voice_fidelity",
    "critic_raw_total",
    "critic_effective_total",
    "critic_hook_cap_applied",
    "critic_band",
    "critic_rank",
)
PUBLISHED_POST_FIELDS = (
    "package_id",
    "candidate_id",
    "package_created_at",
    "published_at",
    "goal",
    "output_format",
    "weekly_slot",
    "revision_count",
    "was_revised",
    *CRITIC_SNAPSHOT_FIELDS,
    "is_recommended",
)
PERFORMANCE_OBSERVATION_FIELDS = (
    "checkpoint",
    "channel",
    "observed_at",
    *PERFORMANCE_METRICS,
)
PERFORMANCE_RECORD_FIELDS = frozenset(
    (*PUBLISHED_POST_FIELDS, *PERFORMANCE_OBSERVATION_FIELDS, "recorded_at")
)
LEGACY_PERFORMANCE_COLUMNS = (
    "id",
    "post_id",
    "checkpoint",
    "channel",
    "observed_at",
    *PERFORMANCE_METRICS,
)


def _normalise_schema_sql(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value.strip()).replace(
        "CREATE TABLE IF NOT EXISTS", "CREATE TABLE"
    )


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    if path.name in {"", ".", ".."}:
        raise ValueError("Private database path is invalid.")
    try:
        parent_metadata = os.lstat(path.parent)
        if not stat.S_ISDIR(parent_metadata.st_mode):
            raise ValueError("Private database parent must be a real directory.")
    except FileNotFoundError:
        try:
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=False)
        except OSError as exc:
            raise ValueError("Private database parent could not be created safely.") from exc
    required_flags = (
        getattr(os, "O_DIRECTORY", 0),
        getattr(os, "O_NOFOLLOW", 0),
        getattr(os, "O_NONBLOCK", 0),
    )
    if (
        not all(required_flags)
        or not hasattr(os, "fchmod")
        or not hasattr(os, "geteuid")
    ):
        raise ValueError("Secure private database operations are unavailable.")
    parent_descriptor = descriptor = -1
    connection: sqlite3.Connection | None = None
    try:
        parent_descriptor = os.open(
            path.parent,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        parent_metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) & 0o022
        ):
            raise ValueError(
                "Private database parent must be owned and not group/world-writable."
            )
        descriptor = os.open(
            path.name,
            os.O_RDWR
            | os.O_CREAT
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0),
            0o600,
            dir_fd=parent_descriptor,
        )
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise ValueError("Private database path must be an owned regular file.")
        os.fchmod(descriptor, 0o600)
        uri = path.absolute().as_uri() + "?mode=rwc&nofollow=1"
        connection = sqlite3.connect(uri, uri=True)
        current = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("Private database path changed during secure open.")
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except OSError as exc:
        if connection is not None:
            connection.close()
        raise ValueError("Private database path is unavailable or unsafe.") from exc
    except Exception:
        if connection is not None:
            connection.close()
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if parent_descriptor >= 0:
            os.close(parent_descriptor)


def initialise(db_path: Path | str) -> Path:
    """Create or migrate the research schema without trusting legacy provenance."""

    path = Path(db_path)
    with closing(connect(path)) as connection, connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, SCHEMA_VERSION):
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
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        if "performance" in tables:
            if "legacy_performance_unverified" in tables:
                raise ValueError(
                    "Legacy performance tables are ambiguous; migration stopped safely."
                )
            legacy_columns = tuple(
                str(row[1])
                for row in connection.execute("PRAGMA table_info(performance)")
            )
            if legacy_columns != LEGACY_PERFORMANCE_COLUMNS:
                raise ValueError(
                    "Legacy performance schema is unrecognized; migration stopped safely."
                )
            connection.execute(
                "ALTER TABLE performance RENAME TO legacy_performance_unverified"
            )
        published_posts_sql = """
            CREATE TABLE IF NOT EXISTS published_posts (
                package_id TEXT PRIMARY KEY,
                candidate_id TEXT NOT NULL,
                package_created_at TEXT NOT NULL,
                published_at TEXT NOT NULL,
                goal TEXT NOT NULL
                    CHECK (goal IN ('reach', 'authority', 'opportunity')),
                output_format TEXT CHECK (output_format IS NULL OR output_format IN (
                    'text', 'carousel', 'vertical-video', 'article', 'artifact-demo'
                )),
                weekly_slot INTEGER CHECK (weekly_slot IS NULL OR weekly_slot BETWEEN 1 AND 5),
                revision_count INTEGER NOT NULL CHECK (revision_count IN (0, 1)),
                was_revised INTEGER NOT NULL CHECK (was_revised IN (0, 1)),
                hook_strength INTEGER NOT NULL CHECK (hook_strength BETWEEN 1 AND 5),
                middle_escalation INTEGER NOT NULL
                    CHECK (middle_escalation BETWEEN 1 AND 5),
                earned_closer INTEGER NOT NULL CHECK (earned_closer BETWEEN 1 AND 5),
                specificity_and_source_quality INTEGER NOT NULL
                    CHECK (specificity_and_source_quality BETWEEN 1 AND 5),
                voice_fidelity INTEGER NOT NULL CHECK (voice_fidelity BETWEEN 1 AND 5),
                critic_raw_total INTEGER NOT NULL
                    CHECK (critic_raw_total BETWEEN 5 AND 25),
                critic_effective_total INTEGER NOT NULL
                    CHECK (critic_effective_total BETWEEN 5 AND 25),
                critic_hook_cap_applied INTEGER NOT NULL
                    CHECK (critic_hook_cap_applied IN (0, 1)),
                critic_band TEXT NOT NULL CHECK (critic_band IN (
                    'advance-to-gates', 'one-light-revision', 'below-critic-bar'
                )),
                critic_rank INTEGER NOT NULL CHECK (critic_rank BETWEEN 1 AND 3),
                is_recommended INTEGER NOT NULL CHECK (is_recommended IN (0, 1)),
                first_recorded_at TEXT NOT NULL
            )
            """
        connection.execute(published_posts_sql)
        metric_columns = ",\n".join(
            f"{metric} INTEGER NOT NULL CHECK ({metric} >= 0)"
            for metric in PERFORMANCE_METRICS
        )
        performance_observations_sql = f"""
            CREATE TABLE IF NOT EXISTS performance_observations (
                id INTEGER PRIMARY KEY,
                package_id TEXT NOT NULL,
                checkpoint TEXT NOT NULL
                    CHECK (checkpoint IN ('2h', '24h', '72h', '7d')),
                channel TEXT NOT NULL CHECK (channel IN ('organic', 'paid')),
                observed_at TEXT NOT NULL,
                {metric_columns},
                recorded_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (package_id) REFERENCES published_posts (package_id),
                UNIQUE (package_id, checkpoint, channel)
            )
            """
        connection.execute(performance_observations_sql)
        for table_name, expected_sql in (
            ("published_posts", published_posts_sql),
            ("performance_observations", performance_observations_sql),
        ):
            stored = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
            if stored is None or _normalise_schema_sql(stored[0]) != _normalise_schema_sql(
                expected_sql
            ):
                raise ValueError(
                    f"Reserved performance table {table_name!r} has an unrecognized schema."
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


def normalise_performance_timestamp(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a timezone-aware timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError
        normalised = parsed.astimezone(timezone.utc)
    except (OverflowError, ValueError) as exc:
        raise ValueError(f"{field} must be a timezone-aware timestamp") from exc
    if parsed.microsecond != 0 or normalised.microsecond != 0:
        raise ValueError(f"{field} must use whole-second precision")
    return normalised.isoformat().replace("+00:00", "Z")


def validate_performance_record(
    record: Mapping[str, object],
) -> dict[str, object]:
    if not isinstance(record, Mapping) or set(record) != PERFORMANCE_RECORD_FIELDS:
        raise ValueError("performance record has an invalid schema")
    validated = dict(record)
    package_id = validated["package_id"]
    package_match = (
        re.fullmatch(
            r"(\d{4}-\d{2}-\d{2})-([a-z0-9](?:[a-z0-9-]{0,78}[a-z0-9])?)",
            package_id,
        )
        if isinstance(package_id, str)
        else None
    )
    if package_match is None:
        raise ValueError("package_id is invalid")
    try:
        datetime.strptime(package_match.group(1), "%Y-%m-%d")
    except ValueError as exc:
        raise ValueError("package_id is invalid") from exc
    candidate_id = validated["candidate_id"]
    if not isinstance(candidate_id, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", candidate_id
    ):
        raise ValueError("candidate_id is invalid")
    if validated["goal"] not in {"reach", "authority", "opportunity"}:
        raise ValueError("performance goal is invalid")
    output_format = validated["output_format"]
    if output_format is not None and output_format not in PERFORMANCE_OUTPUT_FORMATS:
        raise ValueError("performance output format is invalid")
    weekly_slot = validated["weekly_slot"]
    if weekly_slot is not None and (
        type(weekly_slot) is not int or not 1 <= weekly_slot <= 5
    ):
        raise ValueError("performance weekly slot is invalid")
    revision_count = validated["revision_count"]
    if type(revision_count) is not int or revision_count not in (0, 1):
        raise ValueError("performance revision count is invalid")
    for field in (
        "was_revised",
        "critic_hook_cap_applied",
        "is_recommended",
    ):
        if type(validated[field]) is not bool:
            raise ValueError(f"{field} must be a boolean")
    for field in (
        "hook_strength",
        "middle_escalation",
        "earned_closer",
        "specificity_and_source_quality",
        "voice_fidelity",
    ):
        if type(validated[field]) is not int or not 1 <= int(validated[field]) <= 5:
            raise ValueError(f"{field} must be an integer from 1 to 5")
    raw_total = sum(
        int(validated[field])
        for field in (
            "hook_strength",
            "middle_escalation",
            "earned_closer",
            "specificity_and_source_quality",
            "voice_fidelity",
        )
    )
    hook_cap = int(validated["hook_strength"]) <= 3 and raw_total > 18
    effective_total = 18 if hook_cap else raw_total
    band = (
        "advance-to-gates"
        if effective_total >= 24
        else "one-light-revision"
        if effective_total >= 22
        else "below-critic-bar"
    )
    if (
        validated["critic_raw_total"] != raw_total
        or validated["critic_effective_total"] != effective_total
        or validated["critic_hook_cap_applied"] is not hook_cap
        or validated["critic_band"] != band
    ):
        raise ValueError("performance Critic snapshot is inconsistent")
    critic_rank = validated["critic_rank"]
    if type(critic_rank) is not int or not 1 <= critic_rank <= 3:
        raise ValueError("performance Critic rank is invalid")
    checkpoint = validated["checkpoint"]
    channel = validated["channel"]
    if checkpoint not in PERFORMANCE_CHECKPOINTS:
        raise ValueError("performance checkpoint is invalid")
    if channel not in PERFORMANCE_CHANNELS:
        raise ValueError("performance channel is invalid")
    for metric in PERFORMANCE_METRICS:
        value = validated[metric]
        if type(value) is not int or not 0 <= value <= 9_223_372_036_854_775_807:
            raise ValueError(f"{metric} must be a non-negative SQLite integer")
    package_created_at = normalise_performance_timestamp(
        validated["package_created_at"], field="package_created_at"
    )
    published_at = normalise_performance_timestamp(
        validated["published_at"], field="published_at"
    )
    observed_at = normalise_performance_timestamp(
        validated["observed_at"], field="observed_at"
    )
    recorded_at = normalise_performance_timestamp(
        validated["recorded_at"], field="recorded_at"
    )
    package_created = datetime.fromisoformat(
        package_created_at.replace("Z", "+00:00")
    )
    published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
    recorded = datetime.fromisoformat(recorded_at.replace("Z", "+00:00"))
    if published < package_created:
        raise ValueError("published_at cannot precede package creation")
    age_seconds = (observed - published).total_seconds()
    checkpoint_windows = {
        "2h": (2 * 3600, 24 * 3600),
        "24h": (24 * 3600, 72 * 3600),
        "72h": (72 * 3600, 7 * 24 * 3600),
        "7d": (7 * 24 * 3600, None),
    }
    lower, upper = checkpoint_windows[str(checkpoint)]
    if age_seconds < lower or (upper is not None and age_seconds >= upper):
        raise ValueError("observed_at is outside the selected checkpoint window")
    if observed > recorded:
        raise ValueError("observed_at cannot be in the future")
    validated["package_created_at"] = package_created_at
    validated["published_at"] = published_at
    validated["observed_at"] = observed_at
    validated["recorded_at"] = recorded_at
    return validated


def _database_value(field: str, value: object) -> object:
    if field in {
        "was_revised",
        "critic_hook_cap_applied",
        "is_recommended",
    }:
        return int(bool(value))
    return value


def record_performance_many(
    db_path: Path | str,
    records: Iterable[Mapping[str, object]],
    *,
    replace: bool = False,
) -> dict[str, int]:
    """Atomically record package-linked observations without merging channels."""

    if type(replace) is not bool:
        raise ValueError("replace must be a boolean")
    rows = [validate_performance_record(record) for record in records]
    keys: set[tuple[str, str, str]] = set()
    contexts: dict[str, tuple[object, ...]] = {}
    for row in rows:
        key = (str(row["package_id"]), str(row["checkpoint"]), str(row["channel"]))
        if key in keys:
            raise ValueError("performance batch contains a duplicate observation key")
        keys.add(key)
        context = tuple(
            _database_value(field, row[field]) for field in PUBLISHED_POST_FIELDS
        )
        previous = contexts.setdefault(str(row["package_id"]), context)
        if previous != context:
            raise ValueError("performance batch changes immutable publication context")
    counts = {"inserted": 0, "replaced": 0, "unchanged": 0}
    if not rows:
        return counts
    published_columns = ", ".join(PUBLISHED_POST_FIELDS)
    published_placeholders = ", ".join("?" for _ in PUBLISHED_POST_FIELDS)
    observation_columns = ", ".join(PERFORMANCE_OBSERVATION_FIELDS)
    observation_placeholders = ", ".join(
        "?" for _ in PERFORMANCE_OBSERVATION_FIELDS
    )
    with closing(connect(db_path)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            for row in rows:
                package_id = str(row["package_id"])
                existing_post = connection.execute(
                    f"SELECT {published_columns} FROM published_posts WHERE package_id = ?",
                    (package_id,),
                ).fetchone()
                published_values = tuple(
                    _database_value(field, row[field])
                    for field in PUBLISHED_POST_FIELDS
                )
                if existing_post is None:
                    connection.execute(
                        f"""
                        INSERT INTO published_posts (
                            {published_columns}, first_recorded_at
                        ) VALUES ({published_placeholders}, ?)
                        """,
                        (*published_values, row["recorded_at"]),
                    )
                elif tuple(existing_post) != published_values:
                    raise ValueError(
                        "performance record changes immutable publication context"
                    )
                existing_observation = connection.execute(
                    f"""
                    SELECT {observation_columns}
                    FROM performance_observations
                    WHERE package_id = ? AND checkpoint = ? AND channel = ?
                    """,
                    (package_id, row["checkpoint"], row["channel"]),
                ).fetchone()
                observation_values = tuple(
                    row[field] for field in PERFORMANCE_OBSERVATION_FIELDS
                )
                if existing_observation is None:
                    connection.execute(
                        f"""
                        INSERT INTO performance_observations (
                            package_id, {observation_columns}, recorded_at, updated_at
                        ) VALUES (?, {observation_placeholders}, ?, ?)
                        """,
                        (
                            package_id,
                            *observation_values,
                            row["recorded_at"],
                            row["recorded_at"],
                        ),
                    )
                    counts["inserted"] += 1
                elif tuple(existing_observation) == observation_values:
                    counts["unchanged"] += 1
                elif not replace:
                    raise ValueError(
                        "performance observation already exists; use --replace for a correction"
                    )
                else:
                    existing_observed = normalise_performance_timestamp(
                        existing_observation[2], field="observed_at"
                    )
                    if str(row["observed_at"]) < existing_observed:
                        raise ValueError(
                            "an older observation cannot replace a newer checkpoint"
                        )
                    assignments = ", ".join(
                        f"{field} = ?" for field in PERFORMANCE_OBSERVATION_FIELDS
                    )
                    connection.execute(
                        f"""
                        UPDATE performance_observations
                        SET {assignments}, updated_at = ?
                        WHERE package_id = ? AND checkpoint = ? AND channel = ?
                        """,
                        (
                            *observation_values,
                            row["recorded_at"],
                            package_id,
                            row["checkpoint"],
                            row["channel"],
                        ),
                    )
                    counts["replaced"] += 1
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return counts


def record_performance(
    db_path: Path | str,
    record: Mapping[str, object],
    *,
    replace: bool = False,
) -> dict[str, int]:
    return record_performance_many(db_path, [record], replace=replace)


def list_performance(
    db_path: Path | str,
    *,
    package_id: str | None = None,
    channel: str | None = None,
) -> list[dict[str, object]]:
    if package_id is not None and not isinstance(package_id, str):
        raise ValueError("package_id filter is invalid")
    if channel is not None and channel not in PERFORMANCE_CHANNELS:
        raise ValueError("performance channel is invalid")
    filters: list[str] = []
    parameters: list[object] = []
    if package_id is not None:
        filters.append("p.package_id = ?")
        parameters.append(package_id)
    if channel is not None:
        filters.append("o.channel = ?")
        parameters.append(channel)
    where = " WHERE " + " AND ".join(filters) if filters else ""
    fields = ", ".join(
        [
            *(f"p.{field}" for field in PUBLISHED_POST_FIELDS),
            *(f"o.{field}" for field in PERFORMANCE_OBSERVATION_FIELDS),
            "o.recorded_at",
            "o.updated_at",
        ]
    )
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            f"""
            SELECT {fields}
            FROM performance_observations AS o
            JOIN published_posts AS p ON p.package_id = o.package_id
            {where}
            ORDER BY p.published_at DESC,
                CASE o.checkpoint
                    WHEN '2h' THEN 1 WHEN '24h' THEN 2
                    WHEN '72h' THEN 3 WHEN '7d' THEN 4
                END,
                o.channel
            """,
            parameters,
        )
        converted = [dict(row) for row in rows]
    for row in converted:
        for field in {
            "was_revised",
            "critic_hook_cap_applied",
            "is_recommended",
        }:
            row[field] = bool(row[field])
    return converted
