#!/usr/bin/env python3
"""Local installer support. No third-party Python dependencies or model calls."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import time
import urllib.request
import uuid
from pathlib import Path


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def private_write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError(f"Refusing symlink: {path}")
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")
    os.replace(temporary, path)


def command(*args: str) -> str:
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=30).stdout


def paths() -> tuple[Path, Path]:
    base = Path.home() / ".beacon" / "endpoint"
    return base, base / "config.json"


def config() -> tuple[dict, Path]:
    _, path = paths()
    if path.is_symlink():
        raise ValueError("Beacon config.json must not be a symlink for this installer")
    return json.loads(path.read_text()), path


def yaml_checks(path: Path) -> list[str]:
    """Accept only the documented, generated local collector configuration shape."""
    if path.is_symlink() or not path.is_file():
        return ["collector configuration missing or symlinked"]
    content = path.read_text()
    block = re.search(r"^exporters:\s*\n(.*?)(?=^\S|\Z)", content, re.M | re.S)
    names = re.findall(r"^  ([\w/.-]+):\s*$", block.group(1), re.M) if block else []
    problems = []
    if names != ["beaconjson"]:
        problems.append("collector has external or unrecognized exporters")
    pipelines = re.findall(r"^\s+exporters:\s*(.+)$", content, re.M)
    if len(pipelines) != 3 or any(re.sub(r"\s", "", item) != "[beaconjson]" for item in pipelines):
        problems.append("collector pipeline exporters are not exclusively beaconjson")
    endpoints = re.findall(r"^\s+endpoint:\s*(.+)$", content, re.M)
    if len(endpoints) != 3 or any(not re.fullmatch(r"127\.0\.0\.1:\d+", value.strip("\"' ")) for value in endpoints):
        problems.append("collector does not have exactly three loopback listeners")
    if re.search(r"[&*][A-Za-z]|!<|!!|^include:", content, re.M):
        problems.append("custom YAML constructs require manual review")
    return problems


def inspect_config(strict: bool = False) -> dict:
    _, cfg_path = paths()
    if not cfg_path.exists():
        if strict:
            raise ValueError("Beacon user endpoint has not been installed")
        return {"exists": False, "managed": False, "problems": []}
    cfg, _ = config()
    managed = bool((cfg.get("managed_ingest") or {}).get("enabled"))
    problems = []
    if cfg.get("user_mode") is not True:
        problems.append("configuration is not a user-mode endpoint")
    if any(value for value in (cfg.get("destinations") or {}).values()):
        problems.append("preexisting external forwarding destination")
    if any(cfg.get(name) for name in ("splunk_hec", "falcon_hec")):
        problems.append("preexisting top-level external forwarding destination")
    collector = cfg.get("collector") or {}
    yaml_path = Path(collector.get("config_path") or paths()[0] / "otelcol.yaml").expanduser()
    problems.extend(yaml_checks(yaml_path))
    if int(collector.get("http_port") or 4318) != 4318:
        problems.append("custom HTTP port requires matching adapter configuration")
    if strict and managed:
        problems.append("Beacon Managed forwarding remains enabled")
    result = {"exists": True, "managed": managed, "problems": problems,
              "config_path": str(cfg_path), "collector_config_path": str(yaml_path)}
    if strict and problems:
        raise ValueError("; ".join(problems))
    return result


def snapshot(destination: Path) -> None:
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    home = Path.home()
    endpoint = home / ".beacon" / "endpoint"
    targets = [home / ".codex" / "config.toml", home / ".codex" / "hooks.json",
               endpoint / "config.json", endpoint / "otelcol.yaml", endpoint / "manifest.json",
               home / "Library/LaunchAgents/com.beacon.endpoint.collector.user.plist",
               home / "Library/LaunchAgents/com.beacon.endpoint.inventory.plist",
               home / "Library/LaunchAgents/com.beacon.endpoint.asymptote-forwarder.plist",
               home / "Library/LaunchAgents/com.abhillash.workflow-beacon.flush.plist"]
    # Managed credentials are kept only in the private backup, never printed or committed.
    managed = endpoint / "asymptote"
    for name in ("enrollment.json", "vector-secrets.json", "vector.toml", "install-id"):
        targets.append(managed / name)
    records = []
    for index, path in enumerate(targets):
        if path.is_symlink():
            raise ValueError(f"Refusing to back up symlinked configuration: {path}")
        record = {"path": str(path), "existed": path.exists()}
        if path.exists():
            if not path.is_file():
                raise ValueError(f"Expected configuration file: {path}")
            backup = destination / f"config-{index:02d}"
            shutil.copyfile(path, backup)
            backup.chmod(0o600)
            record.update(backup=str(backup), sha256=digest(path), mode=stat.S_IMODE(path.stat().st_mode))
        records.append(record)
    private_write(destination / "snapshot.json", {"created_at": now(), "files": records})


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Local Beacon endpoint attempted an HTTP redirect")


def probe(state: Path, diagnostics: Path, beacon: str) -> None:
    info = inspect_config(strict=True)
    cfg, cfg_path = config()
    collector = cfg["collector"]
    yaml_path = Path(info["collector_config_path"])
    original_digests = (digest(cfg_path), digest(yaml_path))
    launch_jobs = command("launchctl", "list")
    if re.search(r"com\.beacon\.endpoint\.[\w-]*forwarder", launch_jobs):
        raise ValueError("A Beacon forwarder is loaded; keeping delivery disabled")
    command("launchctl", "print", f"gui/{os.getuid()}/com.beacon.endpoint.collector.user")
    log = Path(cfg["log_path"]).expanduser()
    if not log.is_absolute() or log.is_symlink():
        raise ValueError("Runtime log must be an absolute regular local file")
    endpoint = "http://127.0.0.1:4318/v1/logs"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    health_port = int(collector.get("health_port") or 13133)
    with opener.open(f"http://127.0.0.1:{health_port}/", timeout=3) as response:
        if response.status != 200:
            raise ValueError("Collector health endpoint is not healthy")
    # Use the same serializer and project identity as real adapter events, without
    # enqueueing or enabling unverified delivery. This one explicit install probe
    # is sent only after the local-only configuration audit above.
    project_root = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project_root / "packages/workflow_beacon/src"))
    from workflow_beacon.core import Run
    from workflow_beacon.transport import otlp_event

    run = Run("beacon.install_probe", project_root=project_root, run_id=str(uuid.uuid4()))
    event_id = str(uuid.uuid4())
    marker = "workflow_beacon:" + event_id
    probe_event = {"schema_version": 1, "event_id": event_id, "run_id": run.run_id,
                   "instance_id": run.instance_id, "parent_instance_id": "", "sequence": 1,
                   "time_unix_nano": str(time.time_ns()), "workflow": run.workflow,
                   "project_id": run.project_id, "project_root": run.project_root,
                   "repository_url": run.repository_url, "action": "workflow.install_probe",
                   "stage": "install_probe", "status": "synthetic", "metadata": {"dry_run": True}}
    body = otlp_event(probe_event)
    expected_repository = run.repository_url or run.project_root
    expected_trace = hashlib.sha256(run.run_id.encode()).hexdigest()[:32]
    req = urllib.request.Request(endpoint, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=3) as response:
        result = json.loads(response.read() or b"{}")
    partial = result.get("partialSuccess") or result.get("partial_success") or {}
    if int(partial.get("rejectedLogRecords") or partial.get("rejected_log_records") or 0):
        raise ValueError("Collector rejected the synthetic OTLP event")
    found = False
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not found:
        for item in [log] + [log.with_name(log.name + f".{index}") for index in range(1, 6)]:
            if not item.exists():
                continue
            if item.is_symlink():
                raise ValueError("Runtime log archive is a symlink")
            with item.open("rb") as stream:
                stream.seek(max(0, item.stat().st_size - 2 * 1024 * 1024))
                for line in stream:
                    if marker.encode() in line:
                        try:
                            event = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        if (event.get("message") == marker
                                and (event.get("harness") or {}).get("name") == "workflow_bridge"
                                and (event.get("session") or {}).get("id") == run.run_id
                                and (event.get("session") or {}).get("working_directory") == run.project_root
                                and event.get("repository") == expected_repository
                                and (event.get("trace") or {}).get("id") == expected_trace):
                            found = True
                            break
            if found:
                break
        if not found:
            time.sleep(0.2)
    if not found:
        raise ValueError("OTLP accepted the request but exact adapter event, harness, session, trace and project were not verified in runtime history")
    # Recheck after the event: a concurrent configuration change cannot authorize delivery.
    inspect_config(strict=True)
    if original_digests != (digest(cfg_path), digest(yaml_path)):
        raise ValueError("Configuration changed during validation; rerun setup")
    receipt = {"schema_version": 1, "local_only": True, "managed_connected": False,
               "endpoint": endpoint, "verified_at": now(), "config_path": str(cfg_path),
               "config_sha256": digest(cfg_path), "collector_config_path": str(yaml_path),
               "collector_config_sha256": digest(yaml_path),
               "beacon_version": command(beacon, "version").strip()}
    private_write(diagnostics / "otlp-probe.json", {"marker": marker, "event_id": event_id,
                  "readback": True, "harness": "workflow_bridge", "run_id": run.run_id,
                  "project_id": run.project_id, "project_root": run.project_root,
                  "repository": expected_repository, "trace_id": expected_trace,
                  "serializer": "workflow_beacon.transport.otlp_event",
                  "observed_at": now(), "log_path": str(log)})
    private_write(state / "beacon-local-ready.json", receipt)
    print("PASS: adapter OTLP event, harness, session, trace and project read back; local delivery receipt written")


def write_launcher(state: Path, python: Path) -> None:
    import shlex
    bin_dir = Path.home() / ".local" / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    wrapper = bin_dir / "workflow-beacon"
    marker = "# Managed by Linkedin-research-posts/tools/beacon"
    if wrapper.exists() and (wrapper.is_symlink() or marker not in wrapper.read_text()):
        raise ValueError("~/.local/bin/workflow-beacon already exists and is not owned by this installer")
    wrapper.write_text("#!/bin/sh\n" + marker + "\nexport WORKFLOW_BEACON_STATE_DIR=" +
                       shlex.quote(str(state)) + "\nexec " + shlex.quote(str(python)) +
                       ' -m workflow_beacon "$@"\n')
    wrapper.chmod(0o755)
    plist = Path.home() / "Library/LaunchAgents/com.abhillash.workflow-beacon.flush.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    if plist.is_symlink():
        raise ValueError("Refusing symlinked LaunchAgent plist")
    if plist.exists():
        old = plistlib.loads(plist.read_bytes())
        if old.get("Comment") != marker:
            raise ValueError("Existing flush LaunchAgent is not owned by this installer")
    data = {"Label": "com.abhillash.workflow-beacon.flush", "Comment": marker,
            "ProgramArguments": [str(python), "-m", "workflow_beacon", "flush", "--watch", "--quiet"],
            "RunAtLoad": True, "KeepAlive": True, "ThrottleInterval": 10,
            "EnvironmentVariables": {"WORKFLOW_BEACON_STATE_DIR": str(state)}}
    plist.write_bytes(plistlib.dumps(data))
    plist.chmod(0o600)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("inspect")
    check = sub.add_parser("audit")
    check.add_argument("--strict", action="store_true")
    back = sub.add_parser("snapshot")
    back.add_argument("destination", type=Path)
    test = sub.add_parser("probe")
    test.add_argument("--state", required=True, type=Path)
    test.add_argument("--diagnostics", required=True, type=Path)
    test.add_argument("--beacon", required=True)
    launcher = sub.add_parser("launcher")
    launcher.add_argument("--state", required=True, type=Path)
    launcher.add_argument("--python", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "snapshot":
        snapshot(args.destination)
    elif args.action == "inspect":
        info = inspect_config()
        print("managed" if info["managed"] else "local")
    elif args.action == "audit":
        result = inspect_config(args.strict)
        for problem in result["problems"]:
            print(problem, file=sys.stderr)
        if result["problems"]:
            raise SystemExit(2)
    elif args.action == "probe":
        probe(args.state, args.diagnostics, args.beacon)
    elif args.action == "launcher":
        write_launcher(args.state, args.python)


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        print(f"Beacon setup: {exc}", file=sys.stderr)
        raise SystemExit(1)
