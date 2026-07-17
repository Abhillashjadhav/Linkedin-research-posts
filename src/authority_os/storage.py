"""Direct SQLite persistence for research and manual performance checkpoints."""

from __future__ import annotations

import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence, TypeVar

from . import workflow


SCHEMA_VERSION = 4
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
    "learning_context_fingerprint",
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
RESEARCH_ITEM_COLUMNS = (
    "id",
    "canonical_url",
    "title",
    "body",
    "source",
    "author",
    "published_at",
    "source_quality",
    "content_hash",
    "fetched_at",
    "evidence_origin",
)
RESEARCH_ITEMS_SQL = """
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
PUBLISHED_POSTS_SQL = """
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
_PUBLISHED_POSTS_V3_SQL = PUBLISHED_POSTS_SQL
PUBLISHED_POSTS_SQL = PUBLISHED_POSTS_SQL.replace(
    "first_recorded_at TEXT NOT NULL",
    """first_recorded_at TEXT NOT NULL,
        learning_context_fingerprint TEXT CHECK (
            learning_context_fingerprint IS NULL OR (
                length(learning_context_fingerprint) = 64
                AND learning_context_fingerprint NOT GLOB '*[^0-9a-f]*'
            )
        )""",
)
_PERFORMANCE_METRIC_COLUMNS_SQL = ",\n".join(
    f"{metric} INTEGER NOT NULL CHECK ({metric} >= 0)"
    for metric in PERFORMANCE_METRICS
)
PERFORMANCE_OBSERVATIONS_SQL = f"""
    CREATE TABLE IF NOT EXISTS performance_observations (
        id INTEGER PRIMARY KEY,
        package_id TEXT NOT NULL,
        checkpoint TEXT NOT NULL
            CHECK (checkpoint IN ('2h', '24h', '72h', '7d')),
        channel TEXT NOT NULL CHECK (channel IN ('organic', 'paid')),
        observed_at TEXT NOT NULL,
        {_PERFORMANCE_METRIC_COLUMNS_SQL},
        recorded_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (package_id) REFERENCES published_posts (package_id),
        UNIQUE (package_id, checkpoint, channel)
    )
"""
CURRENT_TABLE_SQL = {
    "published_posts": PUBLISHED_POSTS_SQL,
    "performance_observations": PERFORMANCE_OBSERVATIONS_SQL,
}
_EXPECTED_SQLITE_INTERNAL_OBJECTS = {
    "sqlite_autoindex_research_items_1": (
        "index",
        "research_items",
        None,
    ),
    "sqlite_autoindex_research_items_2": (
        "index",
        "research_items",
        None,
    ),
    "sqlite_autoindex_published_posts_1": (
        "index",
        "published_posts",
        None,
    ),
    "sqlite_autoindex_performance_observations_1": (
        "index",
        "performance_observations",
        None,
    ),
}
_DATABASE_INSPECTION_UNAVAILABLE = (
    "Read-only private database inspection is unavailable."
)
_DATABASE_PATH_UNSAFE = "Private database is unavailable or unsafe."
_DATABASE_SCHEMA_UNHEALTHY = "Private database schema is not current."
_DATABASE_INTEGRITY_UNHEALTHY = "Private database integrity check failed."
_ReadResult = TypeVar("_ReadResult")


def _normalise_schema_sql(value: object) -> str:
    if not isinstance(value, str):
        return ""
    normalised = re.sub(r"\s+", " ", value.strip()).replace(
        "CREATE TABLE IF NOT EXISTS", "CREATE TABLE"
    )
    # SQLite's ALTER TABLE formatter may place the new-column comma after
    # preserved indentation. This is whitespace-only, not a schema difference.
    normalised = normalised.replace(" ,", ",")
    normalised = re.sub(r"\(\s+", "(", normalised)
    return re.sub(r"\s+\)", ")", normalised)


class _VerifiedCursor(sqlite3.Cursor):
    """Cursor that cannot bypass the connection's held-path validation."""

    @property
    def _verified_connection(self) -> "_VerifiedConnection":
        connection = self.connection
        if not isinstance(connection, _VerifiedConnection):
            raise ValueError(_DATABASE_PATH_UNSAFE)
        return connection

    def execute(self, sql: str, parameters: Sequence[object] = ()) -> sqlite3.Cursor:
        connection = self._verified_connection
        connection._verify_path()
        try:
            return super().execute(sql, parameters)
        finally:
            connection._verify_path()

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Sequence[object]]
    ) -> sqlite3.Cursor:
        connection = self._verified_connection
        connection._verify_path()
        try:
            return super().executemany(sql, seq_of_parameters)
        finally:
            connection._verify_path()

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        connection = self._verified_connection
        connection._verify_path()
        try:
            return super().executescript(sql_script)
        finally:
            connection._verify_path()


class _VerifiedConnection(sqlite3.Connection):
    """SQLite connection retaining and revalidating its exact opened path."""

    def _attach_path_guard(
        self,
        *,
        database_descriptor: int,
        directory_descriptors: list[int],
        directory_anchor: Path,
        directory_identities: list[tuple[int, ...]],
        directory_edges: list[tuple[int, str, tuple[int, ...]]],
        filename: str,
        database_identity: tuple[int, int],
    ) -> None:
        self._database_descriptor = database_descriptor
        self._directory_descriptors = directory_descriptors
        self._directory_anchor = directory_anchor
        self._directory_identities = directory_identities
        self._directory_edges = directory_edges
        self._database_filename = filename
        self._database_identity = database_identity

    def _guard_is_attached(self) -> bool:
        return getattr(self, "_database_descriptor", -1) >= 0

    def _verify_path(self) -> None:
        if not self._guard_is_attached():
            raise ValueError(_DATABASE_PATH_UNSAFE)
        try:
            descriptor_metadata = os.fstat(self._database_descriptor)
            current = os.stat(
                self._database_filename,
                dir_fd=self._directory_descriptors[-1],
                follow_symlinks=False,
            )
            descriptor_identity = (
                descriptor_metadata.st_dev,
                descriptor_metadata.st_ino,
            )
            current_identity = (current.st_dev, current.st_ino)
            if (
                descriptor_identity != self._database_identity
                or current_identity != self._database_identity
                or not stat.S_ISREG(descriptor_metadata.st_mode)
                or not stat.S_ISREG(current.st_mode)
                or descriptor_metadata.st_uid != os.geteuid()
                or current.st_uid != os.geteuid()
                or stat.S_IMODE(descriptor_metadata.st_mode) != 0o600
                or stat.S_IMODE(current.st_mode) != 0o600
                or not _inspection_parent_is_current(
                    self._directory_descriptors,
                    self._directory_anchor,
                    self._directory_identities,
                    self._directory_edges,
                )
            ):
                raise ValueError(_DATABASE_PATH_UNSAFE)
        except OSError:
            raise ValueError(_DATABASE_PATH_UNSAFE) from None

    def _release_path_guard(self) -> None:
        descriptor = getattr(self, "_database_descriptor", -1)
        if descriptor >= 0:
            os.close(descriptor)
            self._database_descriptor = -1
        for directory_descriptor in reversed(
            getattr(self, "_directory_descriptors", [])
        ):
            os.close(directory_descriptor)
        self._directory_descriptors = []

    def _close_unchecked(self) -> None:
        try:
            if self.in_transaction:
                sqlite3.Connection.rollback(self)
            sqlite3.Connection.close(self)
        finally:
            self._release_path_guard()

    def execute(
        self, sql: str, parameters: Sequence[object] = ()
    ) -> sqlite3.Cursor:
        return self.cursor().execute(sql, parameters)

    def executemany(
        self, sql: str, seq_of_parameters: Iterable[Sequence[object]]
    ) -> sqlite3.Cursor:
        return self.cursor().executemany(sql, seq_of_parameters)

    def executescript(self, sql_script: str) -> sqlite3.Cursor:
        return self.cursor().executescript(sql_script)

    def cursor(self, factory: type[sqlite3.Cursor] | None = None) -> sqlite3.Cursor:
        if factory not in {None, _VerifiedCursor}:
            raise ValueError("Custom database cursor factories are unavailable.")
        self._verify_path()
        cursor = sqlite3.Connection.cursor(self, factory=_VerifiedCursor)
        self._verify_path()
        return cursor

    def create_function(self, *args: object, **kwargs: object) -> None:
        self._verify_path()
        try:
            sqlite3.Connection.create_function(self, *args, **kwargs)
        finally:
            self._verify_path()

    def commit(self) -> None:
        self._verify_path()
        try:
            sqlite3.Connection.commit(self)
        finally:
            self._verify_path()

    def rollback(self) -> None:
        unsafe: ValueError | None = None
        try:
            self._verify_path()
        except ValueError as exc:
            unsafe = exc
        try:
            sqlite3.Connection.rollback(self)
        finally:
            try:
                self._verify_path()
            except ValueError as exc:
                unsafe = unsafe or exc
        if unsafe is not None:
            raise unsafe

    def __enter__(self) -> "_VerifiedConnection":
        self._verify_path()
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: object,
    ) -> bool:
        if exception_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def close(self) -> None:
        if not self._guard_is_attached():
            sqlite3.Connection.close(self)
            return
        unsafe: ValueError | None = None
        try:
            self._verify_path()
        except ValueError as exc:
            unsafe = exc
        try:
            if self.in_transaction:
                sqlite3.Connection.rollback(self)
            sqlite3.Connection.close(self)
            try:
                self._verify_path()
            except ValueError as exc:
                unsafe = unsafe or exc
        finally:
            self._release_path_guard()
        if unsafe is not None:
            raise unsafe


def connect(db_path: Path | str) -> sqlite3.Connection:
    path = Path(db_path)
    if path.name in {"", ".", ".."}:
        raise ValueError("Private database path is invalid.")
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
    directory_descriptors: list[int] = []
    directory_anchor = Path(".")
    directory_identities: list[tuple[int, ...]] = []
    directory_edges: list[tuple[int, str, tuple[int, ...]]] = []
    parent_descriptor = descriptor = -1
    connection: _VerifiedConnection | None = None
    try:
        (
            directory_descriptors,
            directory_anchor,
            directory_identities,
            directory_edges,
        ) = _open_mutating_parent(path)
        parent_descriptor = directory_descriptors[-1]
        parent_metadata = os.fstat(parent_descriptor)
        if (
            not stat.S_ISDIR(parent_metadata.st_mode)
            or parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise ValueError(
                "Private database parent must be owned and mode 0700."
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
        if stat.S_IMODE(metadata.st_mode) != 0o600:
            os.fchmod(descriptor, 0o600)
            metadata = os.fstat(descriptor)
        uri = path.absolute().as_uri() + "?mode=rw&nofollow=1"
        opened = sqlite3.connect(uri, uri=True, factory=_VerifiedConnection)
        if not isinstance(opened, _VerifiedConnection):
            opened.close()
            raise ValueError("Secure private database operations are unavailable.")
        connection = opened
        connection._attach_path_guard(
            database_descriptor=descriptor,
            directory_descriptors=directory_descriptors,
            directory_anchor=directory_anchor,
            directory_identities=directory_identities,
            directory_edges=directory_edges,
            filename=path.name,
            database_identity=(metadata.st_dev, metadata.st_ino),
        )
        descriptor = -1
        directory_descriptors = []
        current = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (current.st_dev, current.st_ino) != (metadata.st_dev, metadata.st_ino):
            raise ValueError("Private database path changed during secure open.")
        connection._verify_path()
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
    except (OSError, sqlite3.Error) as exc:
        if connection is not None:
            connection._close_unchecked()
        raise ValueError("Private database path is unavailable or unsafe.") from exc
    except Exception:
        if connection is not None:
            connection._close_unchecked()
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)


def _research_schema_is_current(connection: sqlite3.Connection) -> bool:
    columns = connection.execute("PRAGMA table_info(research_items)").fetchall()
    if tuple(str(row[1]) for row in columns) != RESEARCH_ITEM_COLUMNS:
        return False
    expected_metadata = {
        "id": ("INTEGER", 0, {None}, 1),
        "canonical_url": ("TEXT", 1, {None}, 0),
        "title": ("TEXT", 1, {None}, 0),
        "body": ("TEXT", 1, {None}, 0),
        "source": ("TEXT", 1, {None}, 0),
        "author": ("TEXT", 1, {"''", '\"\"'}, 0),
        "published_at": ("TEXT", 1, {None}, 0),
        "source_quality": ("TEXT", 1, {None}, 0),
        "content_hash": ("TEXT", 1, {None}, 0),
        "fetched_at": ("TEXT", 1, {None}, 0),
        "evidence_origin": (
            "TEXT",
            1,
            {None, "'legacy-unverified'", '\"legacy-unverified\"'},
            0,
        ),
    }
    for row in columns:
        name = str(row[1])
        expected_type, expected_not_null, expected_defaults, expected_primary_key = (
            expected_metadata[name]
        )
        if (
            str(row[2]).upper() != expected_type
            or int(row[3]) != expected_not_null
            or row[4] not in expected_defaults
            or int(row[5]) != expected_primary_key
        ):
            return False

    unique_columns: set[tuple[str, ...]] = set()
    for index in connection.execute("PRAGMA index_list(research_items)"):
        if int(index[2]) != 1:
            continue
        index_name = str(index[1]).replace('"', '""')
        index_columns = tuple(
            str(row[2])
            for row in connection.execute(f'PRAGMA index_info("{index_name}")')
        )
        unique_columns.add(index_columns)
    if not {
        ("canonical_url",),
        ("content_hash",),
    }.issubset(unique_columns):
        return False

    stored = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'research_items'"
    ).fetchone()
    compact_sql = re.sub(
        r"\s+", "", _normalise_schema_sql(stored[0] if stored else None)
    ).casefold()
    if columns[-1][4] is None:
        # The supported v2 schema already had the provenance column but did
        # not yet carry its default/check constraint. Initialisation preserves
        # those quarantined rows instead of rebuilding the private ledger.
        return True
    return (
        "check(evidence_originin("
        "'legacy-unverified','private-import','synthetic-fixture'))"
        in compact_sql
    )


def _database_schema_is_current_unchecked(connection: sqlite3.Connection) -> bool:
    version = connection.execute("PRAGMA user_version").fetchone()
    if version is None or int(version[0]) != SCHEMA_VERSION:
        return False
    object_rows: list[tuple[str, str]] = []
    internal_objects: dict[str, tuple[str, str, object]] = {}
    seen_names: set[str] = set()
    for row in connection.execute(
        "SELECT name, type, tbl_name, sql FROM sqlite_master"
    ):
        name = str(row[0])
        object_type = str(row[1])
        folded_name = name.casefold()
        if folded_name in seen_names:
            return False
        seen_names.add(folded_name)
        if folded_name.startswith("sqlite_"):
            internal = (object_type, str(row[2]), row[3])
            if _EXPECTED_SQLITE_INTERNAL_OBJECTS.get(name) != internal:
                return False
            internal_objects[name] = internal
            continue
        if object_type != "table":
            return False
        object_rows.append((name, object_type))
    if set(internal_objects) != set(_EXPECTED_SQLITE_INTERNAL_OBJECTS):
        return False
    objects = dict(object_rows)
    required = {"research_items", *CURRENT_TABLE_SQL}
    allowed = {*required, "legacy_performance_unverified"}
    if not required.issubset(objects) or not set(objects).issubset(allowed):
        return False
    if any(object_type != "table" for object_type in objects.values()):
        return False
    if not _research_schema_is_current(connection):
        return False
    for table_name, expected_sql in CURRENT_TABLE_SQL.items():
        stored = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        if stored is None or _normalise_schema_sql(stored[0]) != _normalise_schema_sql(
            expected_sql
        ):
            return False
    if "legacy_performance_unverified" in objects:
        legacy_columns = tuple(
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(legacy_performance_unverified)"
            )
        )
        if legacy_columns != LEGACY_PERFORMANCE_COLUMNS:
            return False
    return True


def _database_schema_is_current(connection: sqlite3.Connection) -> bool:
    try:
        return _database_schema_is_current_unchecked(connection)
    except (
        IndexError,
        KeyError,
        OverflowError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ):
        return False


def _require_current_schema(connection: sqlite3.Connection) -> None:
    if not _database_schema_is_current(connection):
        raise ValueError(_DATABASE_SCHEMA_UNHEALTHY)


def _metadata_token(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _safe_directory_component(metadata: os.stat_result) -> bool:
    permissions = stat.S_IMODE(metadata.st_mode)
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid in {0, os.geteuid()}
        and (
            permissions & 0o022 == 0
            or permissions & stat.S_ISVTX != 0
        )
    )


def _inspection_parent_plan(path: Path) -> tuple[Path, tuple[str, ...]]:
    if path == workflow.DEFAULT_DB:
        try:
            components = path.parent.relative_to(workflow.REPO_ROOT).parts
        except ValueError:
            raise ValueError(_DATABASE_PATH_UNSAFE) from None
        anchor = workflow.REPO_ROOT
    elif path.is_absolute():
        anchor = Path(path.anchor)
        components = path.parent.parts[1:]
        if components and components[0] in {"tmp", "var"}:
            alias = Path(path.anchor) / components[0]
            try:
                alias_metadata = os.lstat(alias)
                alias_target = os.readlink(alias)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISLNK(alias_metadata.st_mode)
                    and alias_metadata.st_uid == 0
                    and alias_target == f"private/{components[0]}"
                ):
                    components = ("private", components[0], *components[1:])
    else:
        anchor = Path(".")
        components = path.parent.parts
    cleaned = tuple(part for part in components if part not in {"", "."})
    if any(part == ".." for part in cleaned):
        raise ValueError(_DATABASE_PATH_UNSAFE)
    return anchor, cleaned


def _open_inspection_parent(
    path: Path,
) -> tuple[
    list[int],
    Path,
    list[tuple[int, ...]],
    list[tuple[int, str, tuple[int, ...]]],
]:
    anchor, components = _inspection_parent_plan(path)
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    edges: list[tuple[int, str, tuple[int, ...]]] = []
    try:
        descriptor = os.open(anchor, flags)
        metadata = os.fstat(descriptor)
        if not _safe_directory_component(metadata):
            raise ValueError(_DATABASE_PATH_UNSAFE)
        descriptors.append(descriptor)
        identities.append(_directory_identity(metadata))
        for index, component in enumerate(components):
            parent_descriptor = descriptors[-1]
            descriptor = os.open(component, flags, dir_fd=parent_descriptor)
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            identity = _directory_identity(metadata)
            current = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not _safe_directory_component(metadata)
                or _directory_identity(current) != identity
            ):
                raise ValueError(_DATABASE_PATH_UNSAFE)
            identities.append(identity)
            edges.append((parent_descriptor, component, identity))
        parent_metadata = os.fstat(descriptors[-1])
        if (
            parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise ValueError(_DATABASE_PATH_UNSAFE)
        return descriptors, anchor, identities, edges
    except Exception:
        for opened in reversed(descriptors):
            os.close(opened)
        raise


def _open_mutating_parent(
    path: Path,
) -> tuple[
    list[int],
    Path,
    list[tuple[int, ...]],
    list[tuple[int, str, tuple[int, ...]]],
]:
    anchor, components = _inspection_parent_plan(path)
    flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    edges: list[tuple[int, str, tuple[int, ...]]] = []
    try:
        descriptor = os.open(anchor, flags)
        metadata = os.fstat(descriptor)
        if not _safe_directory_component(metadata):
            raise ValueError("Private database path is unavailable or unsafe.")
        descriptors.append(descriptor)
        identities.append(_directory_identity(metadata))
        for index, component in enumerate(components):
            parent_descriptor = descriptors[-1]
            created = False
            try:
                descriptor = os.open(component, flags, dir_fd=parent_descriptor)
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_descriptor)
                    created = True
                except FileExistsError:
                    pass
                descriptor = os.open(component, flags, dir_fd=parent_descriptor)
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            if created:
                if metadata.st_uid != os.geteuid():
                    raise ValueError("Private database path is unavailable or unsafe.")
                os.fchmod(descriptor, 0o700)
                metadata = os.fstat(descriptor)
            is_final_parent = index == len(components) - 1
            if is_final_parent:
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                ):
                    raise ValueError(
                        "Private database path is unavailable or unsafe."
                    )
                if stat.S_IMODE(metadata.st_mode) != 0o700:
                    os.fchmod(descriptor, 0o700)
                    metadata = os.fstat(descriptor)
            identity = _directory_identity(metadata)
            current = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            component_is_safe = (
                stat.S_ISDIR(metadata.st_mode)
                and metadata.st_uid == os.geteuid()
                and stat.S_IMODE(metadata.st_mode) == 0o700
                if is_final_parent
                else _safe_directory_component(metadata)
            )
            if not component_is_safe or _directory_identity(current) != identity:
                raise ValueError("Private database path is unavailable or unsafe.")
            identities.append(identity)
            edges.append((parent_descriptor, component, identity))
        parent_metadata = os.fstat(descriptors[-1])
        if (
            parent_metadata.st_uid != os.geteuid()
            or stat.S_IMODE(parent_metadata.st_mode) != 0o700
        ):
            raise ValueError(
                "Private database parent must be owned and mode 0700."
            )
        return descriptors, anchor, identities, edges
    except Exception:
        for opened in reversed(descriptors):
            os.close(opened)
        raise


def _inspection_parent_is_current(
    descriptors: Sequence[int],
    anchor: Path,
    identities: Sequence[tuple[int, ...]],
    edges: Sequence[tuple[int, str, tuple[int, ...]]],
) -> bool:
    try:
        if _directory_identity(os.stat(anchor, follow_symlinks=False)) != identities[0]:
            return False
        if any(
            _directory_identity(os.fstat(descriptor)) != expected
            for descriptor, expected in zip(descriptors, identities, strict=True)
        ):
            return False
        return all(
            _directory_identity(
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            )
            == expected
            for parent, name, expected in edges
        )
    except OSError:
        return False


def _database_sidecars_absent(parent_descriptor: int, filename: str) -> bool:
    for suffix in ("-wal", "-shm", "-journal"):
        try:
            os.stat(
                filename + suffix,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileNotFoundError:
            continue
        else:
            return False
    return True


def _with_inspected_database(
    db_path: Path | str,
    reader: Callable[[sqlite3.Connection], _ReadResult],
) -> _ReadResult:
    """Run one read against the same descriptor-verified immutable database inode."""

    try:
        path = Path(db_path)
    except (OSError, TypeError, ValueError):
        raise ValueError(_DATABASE_PATH_UNSAFE) from None
    if path.name in {"", ".", ".."}:
        raise ValueError(_DATABASE_PATH_UNSAFE)
    required_flags = (
        getattr(os, "O_DIRECTORY", 0),
        getattr(os, "O_NOFOLLOW", 0),
        getattr(os, "O_NONBLOCK", 0),
    )
    if (
        not all(required_flags)
        or not hasattr(os, "geteuid")
        or os.open not in getattr(os, "supports_dir_fd", ())
        or os.stat not in getattr(os, "supports_dir_fd", ())
        or os.stat not in getattr(os, "supports_follow_symlinks", ())
    ):
        raise ValueError(_DATABASE_INSPECTION_UNAVAILABLE)

    directory_descriptors: list[int] = []
    directory_anchor = Path(".")
    directory_identities: list[tuple[int, ...]] = []
    directory_edges: list[tuple[int, str, tuple[int, ...]]] = []
    parent_descriptor = descriptor = -1
    connection: sqlite3.Connection | None = None
    try:
        (
            directory_descriptors,
            directory_anchor,
            directory_identities,
            directory_edges,
        ) = _open_inspection_parent(path)
        parent_descriptor = directory_descriptors[-1]
        if not _database_sidecars_absent(parent_descriptor, path.name):
            # Immutable read-only SQLite must not ignore uncheckpointed state.
            raise ValueError(_DATABASE_PATH_UNSAFE)
        descriptor = os.open(
            path.name,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | os.O_NONBLOCK
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=parent_descriptor,
        )
        metadata_before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata_before.st_mode)
            or metadata_before.st_uid != os.geteuid()
            or stat.S_IMODE(metadata_before.st_mode) != 0o600
        ):
            raise ValueError(_DATABASE_PATH_UNSAFE)
        current = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if _metadata_token(current) != _metadata_token(metadata_before):
            raise ValueError(_DATABASE_PATH_UNSAFE)

        try:
            uri = f"file:///dev/fd/{descriptor}?mode=ro&immutable=1"
            connection = sqlite3.connect(uri, uri=True)
        except (OSError, sqlite3.Error, ValueError):
            raise ValueError(_DATABASE_PATH_UNSAFE) from None
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")
        integrity = connection.execute("PRAGMA integrity_check(1)").fetchall()
        if len(integrity) != 1 or str(integrity[0][0]) != "ok":
            raise ValueError(_DATABASE_INTEGRITY_UNHEALTHY)
        if not _database_schema_is_current(connection):
            raise ValueError(_DATABASE_SCHEMA_UNHEALTHY)
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise ValueError(_DATABASE_INTEGRITY_UNHEALTHY)

        result = reader(connection)

        metadata_after = os.fstat(descriptor)
        current_after = os.stat(
            path.name,
            dir_fd=parent_descriptor,
            follow_symlinks=False,
        )
        if (
            not _inspection_parent_is_current(
                directory_descriptors,
                directory_anchor,
                directory_identities,
                directory_edges,
            )
            or not _database_sidecars_absent(parent_descriptor, path.name)
            or _metadata_token(metadata_after) != _metadata_token(metadata_before)
            or _metadata_token(current_after) != _metadata_token(metadata_before)
        ):
            raise ValueError(_DATABASE_PATH_UNSAFE)
    except ValueError:
        raise
    except (OSError, sqlite3.Error):
        raise ValueError(_DATABASE_PATH_UNSAFE) from None
    finally:
        if connection is not None:
            connection.close()
        if descriptor >= 0:
            os.close(descriptor)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
    return result


def inspect_database_health(db_path: Path | str) -> dict[str, object]:
    """Inspect the current private ledger without creating or changing it."""

    def health(_connection: sqlite3.Connection) -> dict[str, object]:
        return {
            "status": "ready",
            "schema_version": SCHEMA_VERSION,
            "permissions": "owner-only",
            "access": "read-only",
        }

    return _with_inspected_database(db_path, health)


def initialise(db_path: Path | str) -> Path:
    """Create or migrate the research schema without trusting legacy provenance."""

    path = Path(db_path)
    with closing(connect(path)) as connection, connection:
        # sqlite3 does not implicitly start a transaction for DDL.  Begin one
        # explicitly so a validation failure after an ALTER/rename cannot
        # leave a partially migrated private ledger behind.
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version not in (0, 1, 2, 3, SCHEMA_VERSION):
            raise ValueError(
                f"Unsupported database schema {version}; expected {SCHEMA_VERSION}."
            )
        if version == SCHEMA_VERSION and not _database_schema_is_current(connection):
            raise ValueError(
                "Current database schema is incomplete or untrusted; "
                "explicit recovery is required."
            )
        connection.execute(RESEARCH_ITEMS_SQL)
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
        if version == SCHEMA_VERSION and "published_posts" not in tables:
            raise ValueError(
                "Current performance schema is incomplete; explicit recovery is required."
            )
        connection.execute(PUBLISHED_POSTS_SQL)
        stored_published = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
            ("published_posts",),
        ).fetchone()
        stored_published_sql = _normalise_schema_sql(
            stored_published[0] if stored_published else None
        )
        v3_published = stored_published_sql == _normalise_schema_sql(
            _PUBLISHED_POSTS_V3_SQL
        )
        current_published = stored_published_sql == _normalise_schema_sql(
            PUBLISHED_POSTS_SQL
        )
        published_columns = {
            str(row[1])
            for row in connection.execute("PRAGMA table_info(published_posts)")
        }
        if version == SCHEMA_VERSION:
            if not current_published or "learning_context_fingerprint" not in published_columns:
                raise ValueError(
                    "Current performance schema is incomplete; explicit recovery is required."
                )
        elif v3_published:
            if "learning_context_fingerprint" in published_columns:
                raise ValueError(
                    "Reserved performance table 'published_posts' has an "
                    "unrecognized schema."
                )
            connection.execute(
                """
                ALTER TABLE published_posts
                ADD COLUMN learning_context_fingerprint TEXT CHECK (
                    learning_context_fingerprint IS NULL OR (
                        length(learning_context_fingerprint) = 64
                        AND learning_context_fingerprint NOT GLOB '*[^0-9a-f]*'
                    )
                )
                """
            )
        elif not current_published or "learning_context_fingerprint" not in published_columns:
            raise ValueError(
                "Reserved performance table 'published_posts' has an "
                "unrecognized schema."
            )
        if version < SCHEMA_VERSION:
            # Pre-v4 state cannot prove when or how an anchor was written.  Even
            # an interrupted migration with the new column remains unanchored.
            connection.execute(
                "UPDATE published_posts SET learning_context_fingerprint = NULL"
            )
        if version == SCHEMA_VERSION and "performance_observations" not in tables:
            raise ValueError(
                "Current performance schema is incomplete; explicit recovery is required."
            )
        connection.execute(PERFORMANCE_OBSERVATIONS_SQL)
        for table_name, expected_sql in CURRENT_TABLE_SQL.items():
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
        _require_current_schema(connection)
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
        connection.execute("BEGIN IMMEDIATE")
        _require_current_schema(connection)
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
    *,
    allow_unanchored_learning_context: bool = False,
) -> dict[str, object]:
    if type(allow_unanchored_learning_context) is not bool:
        raise ValueError("allow_unanchored_learning_context must be a boolean")
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
    fingerprint = validated["learning_context_fingerprint"]
    if fingerprint is None:
        if not allow_unanchored_learning_context:
            raise ValueError("performance learning context fingerprint is required")
    elif not isinstance(fingerprint, str) or re.fullmatch(
        r"[0-9a-f]{64}", fingerprint
    ) is None:
        raise ValueError("performance learning context fingerprint is invalid")
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
            _require_current_schema(connection)
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
                    existing_values = tuple(existing_post)
                    fingerprint_index = PUBLISHED_POST_FIELDS.index(
                        "learning_context_fingerprint"
                    )
                    comparable_values = list(published_values)
                    if existing_values[fingerprint_index] is None:
                        # Schema-v3 publications remain explicitly unanchored. A
                        # later checkpoint may add metrics, but it cannot backfill
                        # provenance that was absent at first recording.
                        comparable_values[fingerprint_index] = None
                    if existing_values != tuple(comparable_values):
                        raise ValueError(
                            "performance record changes immutable publication context"
                        )
                existing_observation = connection.execute(
                    f"""
                    SELECT {observation_columns}, updated_at
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
                elif tuple(existing_observation[:-1]) == observation_values:
                    counts["unchanged"] += 1
                elif not replace:
                    raise ValueError(
                        "performance observation already exists; use --replace for a correction"
                    )
                else:
                    existing_observed = normalise_performance_timestamp(
                        existing_observation[2], field="observed_at"
                    )
                    existing_updated = normalise_performance_timestamp(
                        existing_observation[-1], field="updated_at"
                    )
                    if str(row["observed_at"]) < existing_observed:
                        raise ValueError(
                            "an older observation cannot replace a newer checkpoint"
                        )
                    if str(row["recorded_at"]) < existing_updated:
                        raise ValueError(
                            "an older correction cannot replace a newer recorded snapshot"
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


def _list_performance_rows(
    connection: sqlite3.Connection,
    *,
    package_id: str | None,
    channel: str | None,
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


def list_performance(
    db_path: Path | str,
    *,
    package_id: str | None = None,
    channel: str | None = None,
) -> list[dict[str, object]]:
    with closing(connect(db_path)) as connection:
        return _list_performance_rows(
            connection,
            package_id=package_id,
            channel=channel,
        )


def list_performance_readonly(
    db_path: Path | str,
    *,
    package_id: str | None = None,
    channel: str | None = None,
) -> list[dict[str, object]]:
    """List learning inputs without creating, migrating, chmodding, or writing state."""

    return _with_inspected_database(
        db_path,
        lambda connection: _list_performance_rows(
            connection,
            package_id=package_id,
            channel=channel,
        ),
    )
