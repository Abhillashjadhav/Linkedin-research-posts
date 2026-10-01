"""Capability-bounded structured Codex calls with explicit configuration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from .workflow import WorkflowError


class ModelTimeoutError(WorkflowError):
    """A model deadline expired; callers may recover without hiding other failures."""


ALLOWED_REASONING = {"low", "medium", "high", "xhigh", "max", "ultra"}
NON_WEB_TOOL_FEATURES = frozenset(
    {
        "apps",
        "browser_use",
        "browser_use_external",
        "browser_use_full_cdp_access",
        "computer_use",
        "goals",
        "hooks",
        "image_generation",
        "in_app_browser",
        "multi_agent",
        "plugins",
        "remote_plugin",
        "shell_tool",
        "skill_mcp_dependency_install",
        "skill_search",
        "tool_call_mcp_elicitation",
        "tool_suggest",
        "unified_exec",
        "view_image",
        "workspace_dependencies",
    }
)


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """One auditable model assignment for one LLM stage."""

    runtime: str
    model: str
    reasoning: str

    def validate(self) -> "ModelConfig":
        if self.runtime != "codex":
            raise WorkflowError("Campaign model runtime must be codex.")
        if not self.model.strip():
            raise WorkflowError("Campaign model name must not be blank.")
        if self.reasoning not in ALLOWED_REASONING:
            raise WorkflowError("Campaign reasoning setting is unsupported.")
        return self

    def trace(self) -> dict[str, str]:
        return asdict(self)


def invoke_structured(
    *,
    config: ModelConfig,
    role_prompt: str,
    task_prompt: str,
    schema: Mapping[str, object],
    timeout: int = 180,
    web_search: bool = False,
    stage_label: str = "Campaign model stage",
) -> dict[str, object]:
    """Invoke Codex with either live web search or no external model tools.

    The CLI receives prompts over stdin, has no persisted conversation, ignores user
    configuration and exec-policy rules, and runs in an empty, read-only workspace.
    Shell variants and non-web integrations are explicitly disabled. Web search is
    explicitly configured as live or disabled for the exec invocation. Provider stderr
    is deliberately not reflected in failures because it may contain account or path
    details.
    """

    safe_config = config.validate()
    if not role_prompt.strip() or not task_prompt.strip():
        raise WorkflowError("Campaign model prompts must not be blank.")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise WorkflowError("Campaign model timeout must be a positive integer.")
    if type(web_search) is not bool:
        raise WorkflowError("Model web-search capability must be explicit.")
    if not isinstance(stage_label, str) or not stage_label.strip():
        raise WorkflowError("Model stage label must not be blank.")
    label = stage_label.strip()
    from . import runtime_budget
    from . import model_call_checkpoint

    effective_timeout, global_limit = runtime_budget.bounded_timeout(timeout)
    envelope = (
        "ROLE INSTRUCTIONS\n"
        f"{role_prompt.strip()}\n"
        "END ROLE INSTRUCTIONS\n\n"
        "TASK DATA AND INSTRUCTIONS\n"
        f"{task_prompt.strip()}\n"
        "END TASK DATA AND INSTRUCTIONS\n\n"
        "Return only the JSON object required by the supplied output schema."
    )
    call_token = model_call_checkpoint.begin_call({
        "stage_label": label, "config": safe_config.trace(),
        "envelope": envelope, "schema": dict(schema),
        "requested_timeout": timeout, "web_search": web_search,
        "disabled_features": sorted(NON_WEB_TOOL_FEATURES),
    })
    if call_token is not None and call_token[2] is not None:
        runtime_budget.remaining_seconds()
        return call_token[2]
    if call_token is not None and call_token[3] is not None:
        kind, message = call_token[3]
        if kind == "ModelTimeoutError":
            raise ModelTimeoutError(message)
        raise WorkflowError(message)
    try:
        executable = shutil.which("codex")
        if not executable:
            raise WorkflowError("Codex CLI is unavailable; install and authenticate it first.")
        with tempfile.TemporaryDirectory(prefix="authority-os-model-") as temporary:
            root = Path(temporary)
            schema_path = root / "schema.json"
            output_path = root / "result.json"
            schema_path.write_text(
                json.dumps(schema, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            command = [
                executable,
                "exec",
                "--ephemeral",
                "--ignore-user-config",
                "--ignore-rules",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--model",
                safe_config.model,
                "--config",
                f'model_reasoning_effort="{safe_config.reasoning}"',
                "--config",
                f'web_search="{"live" if web_search else "disabled"}"',
            ]
            for feature in sorted(NON_WEB_TOOL_FEATURES):
                command.extend(["--disable", feature])
            command.extend([
                "--output-schema",
                str(schema_path),
                "--output-last-message",
                str(output_path),
                "-",
            ])
            try:
                completed = subprocess.run(
                    command,
                    input=envelope,
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=effective_timeout,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                if global_limit:
                    raise runtime_budget.GlobalDeadlineExceeded(
                        "TIME_BUDGET_EXCEEDED: shared daily deadline expired."
                    ) from exc
                raise ModelTimeoutError(f"{label} timed out.") from exc
            except OSError as exc:
                raise WorkflowError(f"{label} could not start.") from exc
            if completed.returncode:
                raise WorkflowError(f"{label} failed; provider output was redacted.")
            try:
                parsed = json.loads(output_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise WorkflowError(f"{label} returned invalid JSON.") from exc
        if not isinstance(parsed, dict):
            raise WorkflowError(f"{label} must return one JSON object.")
    except WorkflowError as exc:
        if not isinstance(exc, runtime_budget.GlobalDeadlineExceeded):
            model_call_checkpoint.fail_call(call_token, exc)
        raise
    model_call_checkpoint.finish_call(call_token, parsed)
    runtime_budget.remaining_seconds()
    return parsed
