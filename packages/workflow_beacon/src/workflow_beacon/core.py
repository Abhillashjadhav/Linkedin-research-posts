"""Small, failure-isolated recorder. Network access lives only in a child worker.

The private ledger is authoritative for delivery/reporting. OTLP acceptance does
not assert that Beacon durably retained an event, and Beacon may retain duplicates.
"""
from __future__ import annotations

import contextvars
import configparser
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from urllib.parse import urlsplit, urlunsplit

MAX_BYTES = 100 * 1024 * 1024
MAX_AGE_SECONDS = 7 * 86400
MAX_EVENT_BYTES = 16 * 1024
DEFAULT_ENDPOINT = "http://127.0.0.1:4318/v1/logs"
_CURRENT = contextvars.ContextVar("workflow_beacon_run", default=None)
_TOKEN = re.compile(r"^[A-Za-z0-9_.:@+\-]{1,160}$")
_BAD_KEY = re.compile(r"secret|password|token|credential|authorization|prompt|prose|text|body|content|command|environment", re.I)
_SAFE_KEYS = {"attempt", "exit_code", "return_code", "error_type", "signal", "success", "model", "provider", "role", "operation", "revision", "schema_version", "correction_status", "correction_registry_fallback", "delivery_status", "checks", "loaded", "passed", "failed", "source", "duration_ms", "workflow", "quality_status", "root_process", "dry_run", "resume", "web_search", "reasoning"}


def state_dir() -> Path:
    raw = os.environ.get("WORKFLOW_BEACON_STATE_DIR") or os.environ.get("WORKFLOW_BEACON_DIR")
    return Path(raw).expanduser() if raw else Path.home() / ".local/share/workflow-beacon"


def disabled() -> bool:
    try:
        return os.environ.get("WORKFLOW_BEACON_DISABLED") == "1" or (state_dir() / "disabled").exists()
    except Exception:
        return True


def _label(value, fallback="unknown") -> str:
    value = str(value)
    return value if _TOKEN.fullmatch(value) else fallback


def _stage(value) -> str:
    return re.sub(r"[^A-Za-z0-9_.:@+\-]+", "_", str(value)).strip("_")[:80]


def _repository_url(root: Path) -> str:
    """Read local git metadata only. Never run git or retain remote credentials."""
    try:
        for parent in (root, *root.parents):
            entry = parent / ".git"
            if not entry.exists():
                continue
            gitdir = entry
            if entry.is_file():
                pointer = entry.read_text().strip()
                if not pointer.startswith("gitdir:"):
                    return ""
                gitdir = (parent / pointer.removeprefix("gitdir:").strip()).resolve()
            common = gitdir / "commondir"
            if common.is_file():
                gitdir = (gitdir / common.read_text().strip()).resolve()
            configuration = gitdir / "config"
            if configuration.stat().st_size > 1024 * 1024:
                return ""
            parser = configparser.ConfigParser(interpolation=None, strict=False)
            parser.read(configuration)
            raw = parser.get('remote "origin"', "url", fallback="").strip()
            scp = re.fullmatch(r"[^/@:]+@([^/:]+):(.+)", raw)
            if scp:
                raw = "https://" + scp.group(1) + "/" + scp.group(2)
            parsed = urlsplit(raw)
            if parsed.scheme not in {"https", "http", "ssh"} or not parsed.hostname:
                return ""
            hostname = parsed.hostname.lower()
            # Strip username/password, query and fragment; normalize harmless git suffix.
            return urlunsplit(("https", hostname, parsed.path.removesuffix(".git"), "", ""))
    except Exception:
        return ""
    return ""


def safe_metadata(value) -> dict:
    """Allow identifiers, numeric measures and booleans; never arbitrary prose."""
    if not isinstance(value, dict):
        return {}
    clean = {}
    for key, item in list(value.items())[:64]:
        if not isinstance(key, str) or _BAD_KEY.search(key):
            continue
        if key not in _SAFE_KEYS and not re.fullmatch(r"[a-z0-9_]+_(?:id|ids|digest|hash|count|ms|bytes|version)", key):
            continue
        if isinstance(item, (bool, int)) or item is None:
            clean[key] = item
        elif isinstance(item, float) and abs(item) < 1e30:
            clean[key] = item
        elif isinstance(item, str) and _TOKEN.fullmatch(item):
            clean[key] = item
        elif isinstance(item, (tuple, list)):
            clean[key] = [x for x in item[:32] if isinstance(x, str) and _TOKEN.fullmatch(x)]
    return clean


def _db() -> sqlite3.Connection:
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(directory, 0o700)
    path = directory / "outbox.sqlite3"
    connection = sqlite3.connect(path, timeout=0.05)
    os.chmod(path, 0o600)
    connection.execute("PRAGMA busy_timeout=50")
    connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
    connection.execute("PRAGMA journal_mode=DELETE")
    page_size = connection.execute("PRAGMA page_size").fetchone()[0]
    connection.execute(f"PRAGMA max_page_count={MAX_BYTES // page_size}")
    connection.executescript("""
      CREATE TABLE IF NOT EXISTS events (
        event_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, created REAL NOT NULL,
        payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
        attempts INTEGER NOT NULL DEFAULT 0, next_try REAL NOT NULL DEFAULT 0,
        accepted_at REAL, observed_at REAL, error TEXT);
      CREATE INDEX IF NOT EXISTS events_pending ON events(state,next_try,created);
      CREATE INDEX IF NOT EXISTS events_run ON events(run_id,created);
      CREATE TABLE IF NOT EXISTS counters (name TEXT PRIMARY KEY, value INTEGER NOT NULL);
    """)
    return connection


def _prune(connection, incoming=0):
    cutoff = time.time() - MAX_AGE_SECONDS
    dropped = connection.execute("SELECT COUNT(*) FROM events WHERE created < ? AND state != 'observed'", (cutoff,)).fetchone()[0]
    connection.execute("DELETE FROM events WHERE created < ?", (cutoff,))
    # Leave ample room for indices/page overhead within the fixed database cap.
    budget = MAX_BYTES * 3 // 4 - incoming
    total = connection.execute("SELECT COALESCE(SUM(length(payload)+512),0) FROM events").fetchone()[0]
    while total > budget:
        rows = connection.execute("SELECT event_id,length(payload)+512,state FROM events ORDER BY created LIMIT 256").fetchall()
        if not rows:
            break
        connection.executemany("DELETE FROM events WHERE event_id=?", [(r[0],) for r in rows])
        total -= sum(r[1] for r in rows)
        dropped += sum(r[2] != "observed" for r in rows)
    if dropped:
        connection.execute("INSERT INTO counters VALUES('expired_or_evicted',?) ON CONFLICT(name) DO UPDATE SET value=value+excluded.value", (dropped,))


def enqueue(event: dict) -> bool:
    payload = json.dumps(event, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    if len(payload.encode()) > MAX_EVENT_BYTES:
        return False
    connection = _db()
    try:
        with connection:
            _prune(connection, len(payload))
            connection.execute("INSERT OR IGNORE INTO events(event_id,run_id,created,payload) VALUES(?,?,?,?)", (event["event_id"], event["run_id"], time.time(), payload))
        connection.execute("PRAGMA incremental_vacuum(64)")
        return True
    finally:
        connection.close()


def nudge_worker():
    """Detached child never inherits the workflow's input/output streams."""
    environment = os.environ.copy()
    src = str(Path(__file__).resolve().parent.parent)
    environment["PYTHONPATH"] = src + os.pathsep + environment.get("PYTHONPATH", "")
    subprocess.Popen([sys.executable, "-m", "workflow_beacon", "flush", "--quiet"],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True, start_new_session=True,
                     env=environment)


class Run:
    def __init__(self, workflow, project_root=None, run_id=None):
        self.workflow = _label(workflow, "workflow")
        candidate = run_id or os.environ.get("WORKFLOW_BEACON_RUN_ID") or os.environ.get("LINKEDIN_OS_RUN_ID")
        self.run_id = _label(candidate, "") if candidate else ""
        self.run_id = self.run_id or str(uuid.uuid4())
        self.instance_id = uuid.uuid4().hex
        self.parent_instance_id = _label(os.environ.get("WORKFLOW_BEACON_INSTANCE_ID", ""), "")
        self.project_root = str(Path(project_root or os.getcwd()).absolute())
        self.repository_url = _repository_url(Path(self.project_root))
        self.project_id = hashlib.sha256((self.repository_url or self.project_root).encode()).hexdigest()
        self.sequence = 0
        self.recording = "ready"
        self._last_nudge = 0.0
        self._started = time.monotonic()
        self._token = None
        self._previous_id = None
        self._previous_instance = None
        self._result = None

    def set_result(self, exit_code):
        """Record a returned CLI result without replacing it or raising SystemExit."""
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            self._result = exit_code

    def event(self, action, stage=None, status=None, metadata=None):
        try:
            if disabled():
                self.recording = "disabled"
                return None
            self.sequence += 1
            event_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"{self.run_id}:{self.instance_id}:{self.sequence}"))
            event = {"schema_version": 1, "event_id": event_id, "run_id": self.run_id,
                     "instance_id": self.instance_id, "sequence": self.sequence,
                     "parent_instance_id": self.parent_instance_id,
                     "time_unix_nano": str(time.time_ns()), "workflow": self.workflow,
                     "project_id": self.project_id, "project_root": self.project_root,
                     "repository_url": self.repository_url,
                     "action": _label(action, "workflow.event"),
                     "stage": _stage(stage) if stage is not None else "",
                     "status": _label(status, "") if status is not None else "",
                     "metadata": safe_metadata(metadata)}
            if not enqueue(event):
                self.recording = "incomplete"
                return None
            self.recording = "queued"
            if time.monotonic() - self._last_nudge >= 2:
                self._last_nudge = time.monotonic()
                try:
                    nudge_worker()
                except Exception:
                    pass
            return event_id
        except Exception:
            self.recording = "incomplete"
            return None

    def __enter__(self):
        self._previous_id = os.environ.get("WORKFLOW_BEACON_RUN_ID")
        self._previous_instance = os.environ.get("WORKFLOW_BEACON_INSTANCE_ID")
        os.environ["WORKFLOW_BEACON_RUN_ID"] = self.run_id
        os.environ["WORKFLOW_BEACON_INSTANCE_ID"] = self.instance_id
        self._token = _CURRENT.set(self)
        self.event("session.started", status="started")
        return self

    def __exit__(self, error_type, error, traceback):
        success = (error_type is None and self._result in (None, 0)) or (isinstance(error, SystemExit) and error.code in (None, 0))
        metadata = {"duration_ms": round((time.monotonic() - self._started) * 1000)}
        if error_type and not success:
            metadata["error_type"] = error_type.__name__
        if isinstance(error, SystemExit) and isinstance(error.code, int):
            metadata["exit_code"] = error.code
        elif self._result is not None:
            metadata["exit_code"] = self._result
        self.event("session.ended" if success else "session.error", status="completed" if success else "failed", metadata=metadata)
        try:
            if not disabled():
                nudge_worker()
        except Exception:
            pass
        if self._token is not None:
            _CURRENT.reset(self._token)
        if self._previous_id is None:
            os.environ.pop("WORKFLOW_BEACON_RUN_ID", None)
        else:
            os.environ["WORKFLOW_BEACON_RUN_ID"] = self._previous_id
        if self._previous_instance is None:
            os.environ.pop("WORKFLOW_BEACON_INSTANCE_ID", None)
        else:
            os.environ["WORKFLOW_BEACON_INSTANCE_ID"] = self._previous_instance
        return False


class _NullRun(Run):
    def event(self, *args, **kwargs):
        return None


def capture(workflow, project_root=None, run_id=None):
    try:
        return Run(workflow, project_root, run_id)
    except Exception:
        # Even a vanished cwd must not turn telemetry into a workflow dependency.
        return _NullRun("workflow", project_root="/", run_id=str(uuid.uuid4()))


def current_run():
    return _CURRENT.get()
