from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import time

from .core import _db, capture


def main(argv=None):
    parser = argparse.ArgumentParser(description="Nonblocking local workflow recorder")
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run", help="Run an unchanged command with optional recording")
    run.add_argument("--workflow", required=True)
    run.add_argument("--project-root")
    run.add_argument("--run-id")
    run.add_argument("args", nargs=argparse.REMAINDER)
    flush = commands.add_parser("flush", help="Deliver queued events outside the workflow")
    flush.add_argument("--watch", action="store_true")
    flush.add_argument("--quiet", action="store_true")
    status = commands.add_parser("status", help="Show local delivery counts, not workflow results")
    status.add_argument("--run-id")
    observe = commands.add_parser("readback", help="Verify accepted event markers in Beacon JSONL")
    observe.add_argument("--log-path", required=True)
    options = parser.parse_args(argv)
    if options.command == "run":
        args = options.args[1:] if options.args[:1] == ["--"] else options.args
        if not args:
            parser.error("run requires a command after --")
        with capture(options.workflow, options.project_root, options.run_id) as recording:
            try:
                child = subprocess.Popen(args, process_group=0)
            except FileNotFoundError:
                recording.set_result(127)
                recording.event("command.failed", status="failed", metadata={"exit_code": 127})
                return 127
            terminal = None
            parent_group = os.getpgrp()
            try:
                if os.isatty(0) and os.tcgetpgrp(0) == parent_group:
                    previous_ttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
                    try:
                        os.tcsetpgrp(0, child.pid)
                        terminal = 0
                    finally:
                        signal.signal(signal.SIGTTOU, previous_ttou)
            except OSError:
                pass
            original = {}
            def forward(value, frame):
                try:
                    os.killpg(child.pid, value)
                except ProcessLookupError:
                    pass
            for signum in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
                original[signum] = signal.getsignal(signum)
                signal.signal(signum, forward)
            try:
                code = child.wait()
            finally:
                for signum, handler in original.items():
                    signal.signal(signum, handler)
                if terminal is not None:
                    previous_ttou = signal.signal(signal.SIGTTOU, signal.SIG_IGN)
                    try:
                        os.tcsetpgrp(terminal, parent_group)
                    finally:
                        signal.signal(signal.SIGTTOU, previous_ttou)
            recording.set_result(code)
            recording.event("command.executed", status="completed" if code == 0 else "failed", metadata={"exit_code": code})
        if code < 0:
            signal.signal(-code, signal.SIG_DFL)
            os.kill(os.getpid(), -code)
        return code
    if options.command == "flush":
        from .transport import flush_once
        while True:
            try:
                result = flush_once()
            except Exception as error:
                result = {"delivery": "unavailable", "error": type(error).__name__}
            if not options.quiet:
                print(json.dumps(result))
            if not options.watch:
                return 0
            time.sleep(1)
    if options.command == "readback":
        from .transport import readback
        try:
            print(json.dumps({"observed": readback(options.log_path)}))
            return 0
        except Exception as error:
            print(json.dumps({"observed": 0, "error": type(error).__name__}))
            return 1
    if options.command == "status":
        try:
            connection = _db()
            try:
                clause = " WHERE run_id=?" if options.run_id else ""
                rows = connection.execute("SELECT state,count(*) FROM events" + clause + " GROUP BY state", (options.run_id,) if options.run_id else ()).fetchall()
                dropped = dict(connection.execute("SELECT name,value FROM counters"))
                from .transport import endpoint, delivery_allowed
                try:
                    url, _ = endpoint()
                    allowed, reason = delivery_allowed(url)
                except Exception as error:
                    url, allowed, reason = "invalid", False, type(error).__name__
                print(json.dumps({"states": dict(rows), "counters": dropped, "endpoint": url,
                                  "delivery": "enabled" if allowed else "queue_only", "reason": reason}))
            finally:
                connection.close()
            return 0
        except Exception as error:
            print(json.dumps({"recording": "unavailable", "error": type(error).__name__}))
            return 1
    return 0
