"""Explicitly reviewed, repository-local corrections. No model or Beacon calls.

The registry is private local state, not a learned policy. Only explicit review
changes approval status. A run freezes its approved rules once, across processes.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile
from typing import Iterable

MAX_FILE_BYTES = 1024 * 1024
MAX_RULE_CHARS = 1200
MAX_CONTEXT_CHARS = 16000
MAX_CONTEXT_RULES = 32
_TOKEN = re.compile(r"(?:\*|[a-z][a-z0-9-]{0,63})\Z")
_ID = re.compile(r"correction-[0-9a-f]{24}\Z")


class CorrectionError(ValueError):
    """Safe, content-free validation error."""


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: object) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bounded(value: str, *, field: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise CorrectionError(f"Invalid {field}.")
    if any(ord(char) < 32 and char not in "\n\t" for char in value):
        raise CorrectionError(f"Invalid {field}.")
    return value.strip()


def _token(value: str) -> str:
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        raise CorrectionError("Invalid correction scope.")
    return value


def _rule_line(rule: dict) -> str:
    line = f"- [{rule['id']}] {rule['text']}"
    if rule.get("check"):
        line += f" (Exact case-sensitive check: {rule['check']['kind']} {_json(rule['check']['literal'])}.)"
    return line


@dataclass(frozen=True)
class CorrectionSnapshot:
    digest: str
    registry_version: int
    rule_ids: tuple[str, ...]
    context: str
    omitted_count: int = 0
    checks: tuple[tuple[str, str, str], ...] = ()
    registry_fallback: bool = False

    def metadata(self) -> dict[str, object]:
        """No correction text, provenance, or user identity in telemetry."""
        return {
            "correction_digest": self.digest,
            "correction_version": self.registry_version,
            "correction_ids": list(self.rule_ids),
            "correction_count": len(self.rule_ids),
            "correction_omitted_count": self.omitted_count,
            "correction_status": "bounded" if self.omitted_count else "loaded",
            "correction_registry_fallback": self.registry_fallback,
        }

    def evaluate(self, text: str) -> dict[str, object]:
        """Exact local substring checks only; subjective rules are not evaluated."""
        configured = {identifier: (kind, literal) for identifier, kind, literal in self.checks}
        records = []
        for identifier in self.rule_ids:
            check = configured.get(identifier)
            if check is None:
                status, reason = "not_evaluated", "subjective_rule"
            else:
                kind, literal = check
                violated = (literal in text) if kind == "forbidden_literal" else (literal not in text)
                status = "violated" if violated else "passed"
                reason = kind if violated else "literal_check_passed"
            records.append({"rule_id": identifier, "status": status, "reason": reason})
        violated = sum(item["status"] == "violated" for item in records)
        untested = sum(item["status"] == "not_evaluated" for item in records)
        passed = len(records) - violated - untested
        status = "violated" if violated else ("partially_evaluated" if untested and passed else ("passed" if passed else "not_evaluated"))
        return {"digest": self.digest, "status": status, "rules": records,
                "violation_count": violated, "passed_count": passed, "not_evaluated_count": untested,
                "text_digest": hashlib.sha256(text.encode("utf-8")).hexdigest()}


class CorrectionStore:
    def __init__(self, project_root: str | Path):
        self.project_root = Path(project_root).resolve()
        self.directory = self.project_root / "data" / "private" / "workflow-beacon"
        self.registry_path = self.directory / "corrections.json"
        self.backup_path = self.directory / "corrections.last-good.json"
        self.used_fallback = False

    def _prepare(self) -> None:
        current = self.project_root
        for part in ("data", "private", "workflow-beacon", "snapshots"):
            current = current / part
            if current.is_symlink():
                raise CorrectionError("Correction storage cannot use symbolic links.")
            current.mkdir(mode=0o700, exist_ok=True)
            if not current.is_dir():
                raise CorrectionError("Correction storage is unavailable.")

    @contextmanager
    def _locked(self):
        self._prepare()
        fd = os.open(self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise CorrectionError("Correction storage is busy; retry after the current update.") from exc
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _read(self, path: Path) -> dict | None:
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None
        with os.fdopen(fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_FILE_BYTES:
                raise CorrectionError("Correction storage is invalid or too large.")
            raw = handle.read(MAX_FILE_BYTES + 1)
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise CorrectionError("Correction storage is invalid.") from exc
        if len(raw) > MAX_FILE_BYTES or not isinstance(value, dict):
            raise CorrectionError("Correction storage is invalid or too large.")
        return value

    def _write(self, path: Path, value: dict) -> None:
        raw = (_json(value) + "\n").encode("utf-8")
        if len(raw) > MAX_FILE_BYTES:
            raise CorrectionError("Correction storage reached its size limit.")
        fd, filename = tempfile.mkstemp(prefix=".corrections-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            if path.is_symlink():
                raise CorrectionError("Correction storage cannot use symbolic links.")
            os.replace(filename, path)
        finally:
            if os.path.exists(filename):
                os.unlink(filename)

    def _registry(self) -> dict:
        try:
            registry = self._read(self.registry_path)
            if registry is not None:
                return self._validate_registry(registry)
        except (CorrectionError, OSError):
            # Supported mutations persist the new backup before publishing the
            # current registry, including every revocation. Never use an older
            # archived version or infer approved rules from traces.
            registry = self._read(self.backup_path)
            if registry is None:
                raise CorrectionError("Correction registry and its current backup are unavailable.")
            self.used_fallback = True
            return self._validate_registry(registry)
        if registry is None:
            backup = self._read(self.backup_path)
            if backup is not None:
                self.used_fallback = True
                return self._validate_registry(backup)
            return {"schema_version": 1, "version": 0, "rules": []}

    def _validate_registry(self, registry: dict) -> dict:
        if (registry.get("schema_version") != 1 or type(registry.get("version")) is not int
                or registry["version"] < 0 or not isinstance(registry.get("rules"), list)):
            raise CorrectionError("Correction registry is invalid.")
        ids = set()
        for rule in registry["rules"]:
            self._validate_rule(rule)
            if rule["id"] in ids:
                raise CorrectionError("Correction registry has duplicate IDs.")
            ids.add(rule["id"])
        return registry

    def _save_registry(self, registry: dict) -> None:
        # Backup-first ordering prevents a successfully saved revoke from later
        # falling back to the preceding approved version after corruption.
        self._write(self.backup_path, registry)
        self._write(self.registry_path, registry)

    @staticmethod
    def _validate_rule(rule: dict) -> None:
        if not isinstance(rule, dict) or not _ID.fullmatch(str(rule.get("id", ""))):
            raise CorrectionError("Correction record is invalid.")
        _bounded(rule.get("text"), field="correction text", maximum=MAX_RULE_CHARS)
        _token(rule.get("workflow"))
        _token(rule.get("key"))
        roles = rule.get("roles")
        if not isinstance(roles, list) or not roles:
            raise CorrectionError("Correction roles are invalid.")
        for role in roles:
            _token(role)
        body = {key: rule[key] for key in ("text", "workflow", "roles", "key")}
        if "check" in rule:
            body["check"] = rule["check"]
        check = rule.get("check")
        if check is not None:
            if not isinstance(check, dict) or check.get("kind") not in {"forbidden_literal", "required_literal"}:
                raise CorrectionError("Correction check is invalid.")
            _bounded(check.get("literal"), field="check literal", maximum=300)
        if rule["id"] != "correction-" + _digest(body)[:24]:
            raise CorrectionError("Correction content does not match its ID; import a new revision.")
        if rule.get("status") not in {"pending", "approved", "revoked", "superseded"}:
            raise CorrectionError("Correction status is invalid.")
        if rule.get("source_kind") not in {"user", "machine"}:
            raise CorrectionError("Correction source kind is invalid.")
        if not isinstance(rule.get("history"), list):
            raise CorrectionError("Correction history is invalid.")
        if rule["status"] == "approved" and not any(
            isinstance(event, dict) and event.get("action") == "approved"
            and isinstance(event.get("reviewed_by"), str) and event["reviewed_by"].strip()
            for event in rule["history"]
        ):
            raise CorrectionError("Approved correction is missing explicit review.")

    def add(self, text: str, *, source_ref: str, source_kind: str = "machine",
            workflow: str = "*", roles: Iterable[str] = ("*",), key: str = "*",
            forbidden_literal: str | None = None, required_literal: str | None = None) -> str:
        text = _bounded(text, field="correction text", maximum=MAX_RULE_CHARS)
        source_ref = _bounded(source_ref, field="source reference", maximum=300)
        if source_kind not in {"user", "machine"}:
            raise CorrectionError("Correction source must be user or machine.")
        if isinstance(roles, str):
            raise CorrectionError("Correction roles must be a sequence.")
        role_list = sorted(set(_token(role) for role in roles))
        if not role_list:
            raise CorrectionError("At least one correction role is required.")
        if forbidden_literal is not None and required_literal is not None:
            raise CorrectionError("Choose one required or forbidden literal per correction.")
        check = None
        if forbidden_literal is not None or required_literal is not None:
            check = {"kind": "forbidden_literal" if forbidden_literal is not None else "required_literal",
                     "literal": _bounded(forbidden_literal if forbidden_literal is not None else required_literal,
                                         field="check literal", maximum=300)}
        body = {"text": text, "workflow": _token(workflow), "roles": role_list, "key": _token(key), "check": check}
        identifier = "correction-" + _digest(body)[:24]
        with self._locked():
            registry = self._registry()
            if any(rule["id"] == identifier for rule in registry["rules"]):
                return identifier
            registry["rules"].append({
                "id": identifier, **body, "source_ref": source_ref, "source_kind": source_kind,
                "status": "pending", "history": [{"action": "added", "at": _now()}],
            })
            registry["version"] += 1
            self._save_registry(registry)
        return identifier

    def approve(self, identifier: str, *, reviewed_by: str, supersedes: str | None = None) -> None:
        self._transition(identifier, "approved", reviewed_by=reviewed_by, supersedes=supersedes)

    def revoke(self, identifier: str, *, reviewed_by: str) -> None:
        self._transition(identifier, "revoked", reviewed_by=reviewed_by)

    def _transition(self, identifier: str, action: str, *, reviewed_by: str,
                    supersedes: str | None = None) -> None:
        reviewed_by = _bounded(reviewed_by, field="reviewer", maximum=120)
        with self._locked():
            registry = self._registry()
            rules = {rule["id"]: rule for rule in registry["rules"]}
            if identifier not in rules:
                raise CorrectionError("Correction ID was not found.")
            rule = rules[identifier]
            if rule["status"] == action:
                return
            if action == "approved":
                conflicts = [other["id"] for other in rules.values()
                             if other["id"] != identifier and other["status"] == "approved"
                             and rule["key"] != "*" and other["key"] == rule["key"]
                             and (other["workflow"] == rule["workflow"] or "*" in (other["workflow"], rule["workflow"]))
                             and ("*" in other["roles"] or "*" in rule["roles"] or set(other["roles"]) & set(rule["roles"]))]
                if conflicts and conflicts != [supersedes]:
                    raise CorrectionError("An approved rule with this key overlaps; explicitly supersede it.")
                if supersedes:
                    if supersedes not in rules or supersedes == identifier or rules[supersedes]["status"] != "approved":
                        raise CorrectionError("Superseded correction must be an active approved rule.")
                    rules[supersedes]["status"] = "superseded"
                    rules[supersedes]["history"].append({"action": "superseded", "at": _now(), "reviewed_by": reviewed_by, "replacement_id": identifier})
            rule["status"] = action
            active = [entry for entry in registry["rules"] if entry["status"] == "approved"]
            size = sum(len(_rule_line(entry)) + 1 for entry in active)
            if action == "approved" and (len(active) > MAX_CONTEXT_RULES or size > MAX_CONTEXT_CHARS):
                raise CorrectionError("Approved correction context is full; revoke or supersede an existing rule before approval.")
            rule["history"].append({"action": action, "at": _now(), "reviewed_by": reviewed_by})
            registry["version"] += 1
            self._save_registry(registry)

    def list_rules(self) -> list[dict]:
        with self._locked():
            return self._registry()["rules"]

    def snapshot(self, workflow: str, role: str | None = None,
                 run_id: str | None = None) -> CorrectionSnapshot:
        workflow = _token(workflow)
        if role is not None:
            _token(role)
        if run_id is not None:
            run_id = _bounded(run_id, field="run ID", maximum=256)
        self._prepare()
        snapshot_path = self.directory / "snapshots" / (_digest([workflow, run_id]) + ".json") if run_id else None
        frozen = self._read(snapshot_path) if snapshot_path else None
        if frozen is None:
            with self._locked():
                # The snapshot may have been created by a sibling process.
                frozen = self._read(snapshot_path) if snapshot_path else None
                if frozen is None:
                    registry = self._registry()
                    rules = [rule for rule in registry["rules"]
                             if rule["status"] == "approved" and rule["workflow"] in (workflow, "*")]
                    payload = {"registry_version": registry["version"], "workflow": workflow,
                               "rules": [{**{key: rule[key] for key in ("id", "text", "roles")}, "check": rule.get("check")} for rule in rules]}
                    frozen = {**payload, "digest": _digest(payload), "registry_fallback": self.used_fallback}
                    if snapshot_path:
                        self._write(snapshot_path, frozen)
        payload = {key: frozen.get(key) for key in ("registry_version", "workflow", "rules")}
        if (frozen.get("digest") != _digest(payload) or payload["workflow"] != workflow
                or not isinstance(payload["rules"], list) or type(payload["registry_version"]) is not int):
            raise CorrectionError("Correction snapshot is invalid.")
        relevant = [rule for rule in frozen["rules"] if role is None or role in rule["roles"] or "*" in rule["roles"]]
        selected, pieces, checks, used = [], [], [], 0
        for rule in relevant:
            piece = _rule_line(rule)
            if len(selected) >= MAX_CONTEXT_RULES or used + len(piece) > MAX_CONTEXT_CHARS:
                raise CorrectionError("Approved correction snapshot exceeds the context budget; no rules were silently omitted.")
            selected.append(rule["id"])
            pieces.append(piece)
            used += len(piece) + 1
            if rule.get("check") is not None:
                checks.append((rule["id"], rule["check"]["kind"], rule["check"]["literal"]))
        return CorrectionSnapshot(frozen["digest"], frozen["registry_version"], tuple(selected), "\n".join(pieces),
                                  0, tuple(checks), bool(frozen.get("registry_fallback")))

    def write_checks(self, run_id: str, report: dict) -> None:
        """Keep a separate local check record; never modify workflow scores."""
        with self._locked():
            self._write(self.directory / ("checks-" + _digest(run_id) + ".json"), report)

    def read_checks(self, run_id: str) -> dict | None:
        self._prepare()
        return self._read(self.directory / ("checks-" + _digest(run_id) + ".json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manage explicit local correction review; no model calls.")
    parser.add_argument("--project-root", default=".")
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add")
    add.add_argument("--text-file", required=True, help="UTF-8 file containing only the correction text")
    add.add_argument("--source-ref", required=True, help="Short reference to the explicit correction or proposal")
    add.add_argument("--source-kind", choices=("user", "machine"), default="machine")
    add.add_argument("--workflow", default="*")
    add.add_argument("--role", action="append")
    add.add_argument("--key", default="*", help="Optional named rule key for explicit conflict/supersession checks")
    add.add_argument("--approve", action="store_true", help="Only for an explicit user correction you have reviewed")
    add.add_argument("--reviewed-by")
    checks = add.add_mutually_exclusive_group()
    checks.add_argument("--forbid-literal", help="Exact case-sensitive substring that must be absent")
    checks.add_argument("--require-literal", help="Exact case-sensitive substring that must be present")
    for name in ("approve", "revoke"):
        sub = commands.add_parser(name)
        sub.add_argument("id")
        sub.add_argument("--reviewed-by", required=True)
        if name == "approve":
            sub.add_argument("--supersedes")
    listing = commands.add_parser("list")
    listing.add_argument("--show-text", action="store_true", help="Display private correction text locally")
    check_report = commands.add_parser("checks")
    check_report.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    try:
        store = CorrectionStore(args.project_root)
        if args.command == "add":
            if args.approve and (args.source_kind != "user" or not args.reviewed_by):
                raise CorrectionError("Direct approval requires an explicit user source and a named reviewer; machine proposals need separate review.")
            with open(args.text_file, encoding="utf-8") as handle:
                text = handle.read(MAX_RULE_CHARS + 1)
            identifier = store.add(text, source_ref=args.source_ref, source_kind=args.source_kind,
                                   workflow=args.workflow, roles=args.role or ("*",), key=args.key,
                                   forbidden_literal=args.forbid_literal, required_literal=args.require_literal)
            if args.approve:
                store.approve(identifier, reviewed_by=args.reviewed_by)
            print(_json({"id": identifier, "status": "approved" if args.approve else "recorded"}))
        elif args.command == "approve":
            store.approve(args.id, reviewed_by=args.reviewed_by, supersedes=args.supersedes)
            print(_json({"id": args.id, "status": "approved"}))
        elif args.command == "revoke":
            store.revoke(args.id, reviewed_by=args.reviewed_by)
            print(_json({"id": args.id, "status": "revoked"}))
        elif args.command == "checks":
            print(_json(store.read_checks(args.run_id) or {"status": "not_evaluated", "latest": []}))
        else:
            rules = store.list_rules()
            fields = ("id", "status", "workflow", "roles", "key") + (("text",) if args.show_text else ())
            print(_json([{key: rule[key] for key in fields} for rule in rules]))
        return 0
    except CorrectionError as exc:
        parser.exit(2, str(exc) + "\n")
    except (OSError, UnicodeError):
        # Private inputs and OS errors can contain paths or source text.
        parser.exit(2, "Correction operation failed validation or local storage access; no private content was printed.\n")


if __name__ == "__main__":
    raise SystemExit(main())
