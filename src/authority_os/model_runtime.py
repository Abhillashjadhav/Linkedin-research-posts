"""Zero-tool structured model calls with explicit, persisted configuration."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping

from .workflow import WorkflowError


ALLOWED_REASONING = {"low", "medium", "high", "xhigh", "max", "ultra"}


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
) -> dict[str, object]:
    """Invoke Codex in an empty, read-only workspace and return validated JSON.

    The CLI receives prompts over stdin, has no persisted conversation, ignores user
    configuration, and cannot mutate the repository. Provider stderr is deliberately
    not reflected in failures because it may contain account or path details.
    """

    safe_config = config.validate()
    if not role_prompt.strip() or not task_prompt.strip():
        raise WorkflowError("Campaign model prompts must not be blank.")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout < 1:
        raise WorkflowError("Campaign model timeout must be a positive integer.")
    executable = shutil.which("codex")
    if not executable:
        raise WorkflowError("Codex CLI is unavailable; install and authenticate it first.")

    envelope = (
        "ROLE INSTRUCTIONS\n"
        f"{role_prompt.strip()}\n"
        "END ROLE INSTRUCTIONS\n\n"
        "TASK DATA AND INSTRUCTIONS\n"
        f"{task_prompt.strip()}\n"
        "END TASK DATA AND INSTRUCTIONS\n\n"
        "Return only the JSON object required by the supplied output schema."
    )
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
            "--skip-git-repo-check",
            "--sandbox",
            "read-only",
            "--model",
            safe_config.model,
            "--config",
            f'model_reasoning_effort="{safe_config.reasoning}"',
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "-",
        ]
        try:
            completed = subprocess.run(
                command,
                input=envelope,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise WorkflowError("Campaign model stage timed out.") from exc
        except OSError as exc:
            raise WorkflowError("Campaign model stage could not start.") from exc
        if completed.returncode:
            raise WorkflowError(
                "Campaign model stage failed; provider output was redacted."
            )
        try:
            parsed = json.loads(output_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError("Campaign model stage returned invalid JSON.") from exc
    if not isinstance(parsed, dict):
        raise WorkflowError("Campaign model stage must return one JSON object.")
    return parsed
