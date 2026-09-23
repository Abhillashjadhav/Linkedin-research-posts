"""Fail-open Beacon capture around the existing local CLI composition roots.

The launcher executes the original module/code in this process. No new subprocess,
shell, model tools, stdout redirection or retry of business work is introduced.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path
import re
import runpy
import secrets
import sys
import time
from typing import Iterator


PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_ID_ENV = "LINKEDIN_OS_RUN_ID"
ACTIVE_ENV = "LINKEDIN_OS_BEACON_ACTIVE"
ROOT_PID_ENV = "LINKEDIN_OS_BEACON_ROOT_PID"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9._:@+-]{1,160}")
_RUN: object | None = None


def _warn(reason: str) -> None:
    # Fixed messages only: provider exceptions may contain credentials or paths.
    print(f"Beacon: {reason}; workflow continues.", file=sys.stderr)


def event(action: str, *, stage: str | None = None, status: str | None = None,
          metadata: dict[str, object] | None = None) -> None:
    """Emit optional telemetry without becoming a workflow failure boundary."""
    if _RUN is None:
        return
    try:
        _RUN.event(action, stage=stage, status=status, metadata=metadata)  # type: ignore[attr-defined]
    except Exception:
        pass


def record_correction_metadata(role: str, metadata: dict[str, object]) -> None:
    """Record prompt context identity, without asserting model compliance."""
    status = "unavailable" if metadata.get("correction_status") == "unavailable" else "completed"
    event("corrections.injected", stage=role, status=status, metadata=metadata)


@contextmanager
def _capture(run_id: str) -> Iterator[object | None]:
    manager = None
    run = None
    try:
        from workflow_beacon import capture
        manager = capture("linkedin-os", project_root=PROJECT_ROOT, run_id=run_id)
        run = manager.__enter__()
    except Exception:
        _warn("recording unavailable")
    try:
        yield run
    except BaseException:
        if manager is not None and run is not None:
            try:
                manager.__exit__(*sys.exc_info())
            except Exception:
                _warn("recording could not finish")
        raise
    else:
        if manager is not None and run is not None:
            try:
                manager.__exit__(None, None, None)
            except Exception:
                _warn("recording could not finish")


def _install_model_observer() -> None:
    # Do not import v1_completion here: its baseline callables must be captured
    # only after the launcher's existing v1_gates.install().
    from . import model_runtime

    original = model_runtime.invoke_structured
    if getattr(original, "_beacon_observer", False):
        return

    @wraps(original)
    def observed(*args, **kwargs):
        stage = re.sub(r"[^A-Za-z0-9_.:@+-]+", "-", str(
            kwargs.get("stage_label", "Model stage")
        )).strip("-")[:160] or "model"
        started = time.monotonic()
        call_id = secrets.token_hex(12)
        metadata: dict[str, object] = {"call_id": call_id}
        try:
            config = kwargs.get("config")
            if config is not None:
                metadata["model"] = config.model
                metadata["provider"] = config.runtime
                metadata["reasoning"] = config.reasoning
            metadata["input_digest"] = hashlib.sha256(
                (str(kwargs.get("role_prompt", "")) + "\0"
                 + str(kwargs.get("task_prompt", ""))).encode("utf-8")
            ).hexdigest()
            metadata["web_search"] = kwargs.get("web_search", False)
        except Exception:
            pass
        event("model.started", stage=stage, status="started", metadata=metadata)
        try:
            result = original(*args, **kwargs)
        except BaseException as exc:
            event("model.failed", stage=stage, status="failed", metadata={
                "call_id": call_id, "error_type": type(exc).__name__,
                "duration_ms": round((time.monotonic() - started) * 1000),
            })
            raise
        result_metadata: dict[str, object] = {
            "call_id": call_id, "duration_ms": round((time.monotonic() - started) * 1000),
        }
        try:
            result_metadata["output_digest"] = hashlib.sha256(
                json.dumps(result, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        except Exception:
            pass
        event("model.completed", stage=stage, status="completed", metadata=result_metadata)
        return result

    observed._beacon_observer = True
    model_runtime.invoke_structured = observed


def _run_identity() -> str:
    inherited = os.environ.get(RUN_ID_ENV, "")
    if inherited and RUN_ID_PATTERN.fullmatch(inherited):
        run_id = inherited
    else:
        run_id = ("linkedin-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
                  + "-" + secrets.token_hex(6))
    os.environ[RUN_ID_ENV] = run_id
    os.environ[ACTIVE_ENV] = "1"
    os.environ.setdefault(ROOT_PID_ENV, str(os.getpid()))
    return run_id


def main(argv: list[str] | None = None) -> int:
    """Usage: beacon_integration COMMAND (module NAME | code SOURCE) [ARGS...]."""
    global _RUN
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) < 3 or arguments[1] not in {"module", "code"}:
        print("Invalid LinkedIn OS launcher configuration.", file=sys.stderr)
        return 2
    command, mode, target, *forwarded = arguments
    run_id = _run_identity()
    # Alias this __main__ instance so imports from prompt builders share _RUN.
    sys.modules.setdefault("authority_os.beacon_integration", sys.modules[__name__])
    with _capture(run_id) as captured:
        _RUN = captured
        event("command.started", stage=command, status="started", metadata={
            "root_process": os.environ.get(ROOT_PID_ENV) == str(os.getpid()),
            "dry_run": "--dry-run" in forwarded,
            "resume": "--resume-from" in forwarded,
        })
        try:
            _install_model_observer()
        except Exception:
            _warn("model observation unavailable")
        if command in {"discover", "draft", "eval-package"} and "--dry-run" not in forwarded:
            try:
                from . import correction_context
                metadata = correction_context.freeze(project_root=PROJECT_ROOT, workflow="linkedin-os")
                status = "unavailable" if metadata.get("correction_status") == "unavailable" else "completed"
                event("corrections.loaded", stage=command, status=status, metadata=metadata)
            except Exception:
                event("corrections.loaded", stage=command, status="unavailable")
                _warn("correction context unavailable")
        previous_argv = sys.argv
        sys.argv = ["-c" if mode == "code" else target, *forwarded]
        try:
            if mode == "code":
                exec(compile(target, "<linkedin-os-launcher>", "exec"), {
                    "__name__": "__main__", "__builtins__": __builtins__,
                })
            else:
                runpy.run_module(target, run_name="__main__", alter_sys=True)
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
            event("command.executed", stage=command, status="completed" if code == 0 else "failed",
                  metadata={"return_code": code})
            raise
        except BaseException as exc:
            event("command.failed", stage=command, status="failed",
                  metadata={"error_type": type(exc).__name__})
            raise
        else:
            event("command.executed", stage=command, status="completed", metadata={"return_code": 0})
        finally:
            sys.argv = previous_argv
            _RUN = None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
