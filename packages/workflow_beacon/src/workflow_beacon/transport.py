"""Separate-process delivery. Native collector acknowledgement is not durability."""
from __future__ import annotations

from datetime import datetime, timezone
import fcntl
import hashlib
import http.client
import json
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urlsplit

from .core import DEFAULT_ENDPOINT, _db, _prune, disabled, state_dir


def endpoint():
    value = os.environ.get("WORKFLOW_BEACON_ENDPOINT", DEFAULT_ENDPOINT)
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "::1"} or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"/v1/logs", "/v1/traces"}:
        raise ValueError("endpoint_must_be_numeric_loopback_otlp")
    if parsed.path != "/v1/logs":
        raise ValueError("adapter_requires_v1_logs")
    return value, parsed


def delivery_allowed(value):
    if disabled():
        return False, "disabled"
    if os.environ.get("WORKFLOW_BEACON_ALLOW_UNVERIFIED_LOCAL") == "1":
        return True, "probe_override"
    try:
        receipt = json.loads((state_dir() / "beacon-local-ready.json").read_text())
        if receipt.get("schema_version") != 1 or receipt.get("local_only") is not True or receipt.get("endpoint") != value:
            return False, "local_verification_missing"
        verified = datetime.fromisoformat(receipt["verified_at"].replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - verified).total_seconds()
        if age < 0:
            return False, "local_verification_invalid_date"
        for prefix in ("", "collector_"):
            source = Path(receipt[prefix + "config_path"])
            if not source.is_absolute() or source.stat().st_size > 1024 * 1024:
                return False, "local_configuration_invalid"
            if hashlib.sha256(source.read_bytes()).hexdigest() != receipt[prefix + "config_sha256"]:
                return False, "local_configuration_changed"
        configuration = json.loads(Path(receipt["config_path"]).read_text())
        if (configuration.get("managed_ingest") or {}).get("enabled") is True:
            return False, "managed_forwarding_enabled"
        for destination in ("splunk_hec", "falcon_hec"):
            if configuration.get(destination):
                return False, "external_destination_configured"
        if any((configuration.get("destinations") or {}).values()):
            return False, "external_destination_configured"
        return True, "verified"
    except Exception:
        return False, "local_verification_missing"


def _attribute(key, value):
    if isinstance(value, bool):
        typed = {"boolValue": value}
    elif isinstance(value, int):
        typed = {"intValue": str(value)}
    else:
        typed = {"stringValue": str(value)}
    return {"key": key, "value": typed}


def otlp_event(event):
    action = event["action"]
    if action.startswith(("run.", "workflow.")):
        action = {"started": "session.started", "completed": "session.ended", "failed": "session.error"}.get(action.rsplit(".", 1)[-1], "session.activity")
    elif action.startswith(("model.", "stage.")):
        suffix = action.rsplit(".", 1)[-1]
        if suffix == "finished":
            action = "tool.failed" if event.get("status", "").lower() in {"error", "failed", "failure"} else "tool.completed"
        else:
            action = {"started": "tool.invoked", "completed": "tool.completed", "failed": "tool.failed"}.get(suffix, "tool.invoked")
    category = action.split(".", 1)[0]
    if category not in {"session", "tool", "command", "file", "mcp", "prompt", "approval"}:
        action, category = "session.activity", "session"
    attributes = {"beacon.harness.name": "workflow_bridge", "beacon.origin": "local",
                  "beacon.event.action": action, "beacon.event.category": category,
                  "beacon.session.id": event["run_id"],
                  "beacon.session.working_directory": event["project_root"],
                  "repository": event["project_root"],
                  "workflow_beacon.event_id": event["event_id"],
                  "workflow_beacon.sequence": event["sequence"],
                  "workflow_beacon.instance_id": event["instance_id"],
                  "workflow_beacon.parent_instance_id": event.get("parent_instance_id", ""),
                  "workflow_beacon.status": event["status"],
                  "workflow_beacon.project_id": event["project_id"],
                  "workflow_beacon.action": event["action"],
                  "gen_ai.workflow.name": event["workflow"]}
    if event.get("repository_url"):
        attributes["vcs.repository.url"] = event["repository_url"]
    if event["stage"]:
        attributes["beacon.tool.name"] = event["stage"]
    if category in {"tool", "mcp"}:
        attributes["gen_ai.tool.call.id"] = event["metadata"].get("call_id", event["event_id"])
    for key, value in event["metadata"].items():
        attributes["workflow_beacon." + key] = json.dumps(value, separators=(",", ":")) if isinstance(value, list) else value
    trace_id = hashlib.sha256(event["run_id"].encode()).hexdigest()[:32]
    record = {"timeUnixNano": event["time_unix_nano"], "severityNumber": 9,
              "severityText": "INFO", "traceId": trace_id,
              "spanId": hashlib.sha256(str(event["metadata"].get("call_id", event["event_id"])).encode()).hexdigest()[:16],
              # Deliberate fixed token body helps exact readback without recording prose.
              "body": {"stringValue": "workflow_beacon:" + event["event_id"]},
              "attributes": [_attribute(k, v) for k, v in attributes.items()]}
    return {"resourceLogs": [{"resource": {"attributes": [_attribute("service.name", "workflow_beacon")]},
                              "scopeLogs": [{"scope": {"name": "workflow_beacon", "version": "0.1.0"}, "logRecords": [record]}]}]}


def send_event(event, parsed):
    connection = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=0.5)
    # This is called by a separate worker; enforce one total wall-clock deadline,
    # including a receiver that drips response bytes slowly enough to reset sockets.
    previous_alarm = None
    if threading.current_thread() is threading.main_thread():
        def timed_out(signum, frame):
            raise TimeoutError("delivery_deadline")
        previous_alarm = signal.signal(signal.SIGALRM, timed_out)
        signal.setitimer(signal.ITIMER_REAL, 0.5)
    try:
        payload = json.dumps(otlp_event(event), separators=(",", ":")).encode()
        connection.request("POST", parsed.path, body=payload, headers={"Content-Type": "application/json", "Accept": "application/json"})
        response = connection.getresponse()
        body = response.read(65537)
        if len(body) > 65536:
            return "rejected", "oversized_response"
        if response.status == 200:
            data = json.loads(body or b"{}")
            partial = data.get("partialSuccess", data.get("partial_success"))
            if partial:
                rejected = int(partial.get("rejectedLogRecords", partial.get("rejected_log_records", 0)))
                return ("rejected", "partial_success") if rejected else ("accepted", "accepted_with_warning")
            return "accepted", None
        if response.status in {429, 502, 503, 504}:
            return "pending", "http_" + str(response.status)
        return "rejected", "http_" + str(response.status)
    except Exception as error:
        return "pending", type(error).__name__
    finally:
        if previous_alarm is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_alarm)
        connection.close()


def flush_once():
    value, parsed = endpoint()
    allowed, reason = delivery_allowed(value)
    if not allowed:
        return {"delivery": "queue_only", "reason": reason, "sent": 0}
    directory = state_dir()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_fd = os.open(directory / "flush.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {"delivery": "worker_active", "sent": 0}
        connection = _db()
        sent = 0
        try:
            with connection:
                _prune(connection)
            rows = connection.execute("SELECT event_id,payload,attempts FROM events WHERE state='pending' AND next_try <= ? ORDER BY created LIMIT 64", (time.time(),)).fetchall()
            for event_id, payload, attempts in rows:
                # Receipt changes during a batch must stop further delivery.
                if not delivery_allowed(value)[0]:
                    break
                state, error = send_event(json.loads(payload), parsed)
                delay = (1, 5, 30, 120, 300)[min(attempts, 4)]
                with connection:
                    connection.execute("UPDATE events SET state=?,attempts=attempts+1,next_try=?,accepted_at=?,error=? WHERE event_id=?",
                                       (state, time.time() + delay, time.time() if state == "accepted" else None, error, event_id))
                sent += state == "accepted"
            return {"delivery": "attempted", "sent": sent}
        finally:
            connection.close()
    finally:
        os.close(lock_fd)


def readback(log_path):
    """Mark observed only after the exact unique marker is read from Beacon JSONL."""
    connection = _db()
    observed = 0
    try:
        rows = connection.execute("SELECT event_id FROM events WHERE state='accepted' LIMIT 10000").fetchall()
        wanted = {row[0] for row in rows}
        if not wanted:
            return 0
        with Path(log_path).open("rb") as stream:
            # Current Beacon default retention is smaller; never scan unbounded files.
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - 64 * 1024 * 1024))
            if stream.tell():
                stream.readline()
            for line in stream:
                if len(line) > 1024 * 1024:
                    continue
                try:
                    event = json.loads(line)
                    marker = event.get("message", "")
                    if not marker.startswith("workflow_beacon:"):
                        continue
                    event_id = marker.removeprefix("workflow_beacon:")
                    if event_id in wanted and event.get("harness", {}).get("name") == "workflow_bridge":
                        with connection:
                            connection.execute("UPDATE events SET state='observed',observed_at=? WHERE event_id=? AND state='accepted'", (time.time(), event_id))
                        wanted.remove(event_id)
                        observed += 1
                except (ValueError, TypeError, AttributeError):
                    continue
        return observed
    finally:
        connection.close()
