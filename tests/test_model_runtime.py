"""Regression tests for the shared, capability-bounded Codex runtime."""

from __future__ import annotations

import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import model_runtime, workflow


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": False,
}
CONFIG = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")


def successful_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
    output = Path(command[command.index("--output-last-message") + 1])
    output.write_text(json.dumps({"answer": "ok"}), encoding="utf-8")
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class ModelRuntimeTests(unittest.TestCase):
    @patch("authority_os.model_runtime.subprocess.run", side_effect=successful_run)
    @patch("authority_os.model_runtime.shutil.which", return_value="/opt/codex")
    def test_live_web_call_uses_explicit_live_mode_in_isolated_read_only_exec(
        self, which: object, run: object
    ) -> None:
        result = model_runtime.invoke_structured(
            config=CONFIG,
            role_prompt="Research only public sources.",
            task_prompt="Find current evidence.",
            schema=SCHEMA,
            web_search=True,
            stage_label="Scout",
        )

        self.assertEqual(result, {"answer": "ok"})
        which.assert_called_once_with("codex")  # type: ignore[attr-defined]
        command = run.call_args.args[0]  # type: ignore[attr-defined]
        self.assertEqual(command[:2], ["/opt/codex", "exec"])
        for option in (
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--skip-git-repo-check",
            "--output-schema",
            "--output-last-message",
        ):
            self.assertIn(option, command)
        self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
        self.assertIn('web_search="live"', command)
        self.assertNotIn('web_search="disabled"', command)
        disabled = {
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--disable"
        }
        self.assertTrue(model_runtime.NON_WEB_TOOL_FEATURES <= disabled)
        self.assertTrue(
            {"shell_tool", "unified_exec", "multi_agent", "apps", "plugins"}
            <= disabled
        )
        kwargs = run.call_args.kwargs  # type: ignore[attr-defined]
        self.assertNotEqual(Path(kwargs["cwd"]), model_runtime.Path.cwd())
        self.assertIn("Research only public sources.", kwargs["input"])
        self.assertIn("Find current evidence.", kwargs["input"])
        self.assertNotIn("Research only public sources.", " ".join(command))

    @patch("authority_os.model_runtime.subprocess.run", side_effect=successful_run)
    @patch("authority_os.model_runtime.shutil.which", return_value="/opt/codex")
    def test_zero_tool_call_explicitly_disables_web_and_non_web_tools(
        self, _which: object, run: object
    ) -> None:
        model_runtime.invoke_structured(
            config=CONFIG,
            role_prompt="Score only.",
            task_prompt="Score these cards.",
            schema=SCHEMA,
            web_search=False,
            stage_label="Thesis critic",
        )

        command = run.call_args.args[0]  # type: ignore[attr-defined]
        self.assertNotIn("--search", command)
        self.assertIn('web_search="disabled"', command)
        self.assertNotIn('web_search="live"', command)
        self.assertIn("--ignore-rules", command)
        disabled = {
            command[index + 1]
            for index, value in enumerate(command[:-1])
            if value == "--disable"
        }
        self.assertTrue(model_runtime.NON_WEB_TOOL_FEATURES <= disabled)
        self.assertTrue({"shell_tool", "unified_exec"} <= disabled)

    @patch("authority_os.model_runtime.shutil.which", return_value="/opt/codex")
    def test_invalid_or_failed_model_output_fails_closed_without_provider_leaks(
        self, _which: object
    ) -> None:
        secret = "OPENAI_API_KEY=private-runtime-sentinel"
        failed = subprocess.CompletedProcess(
            ["/opt/codex"], 1, stdout="", stderr=secret
        )
        with patch("authority_os.model_runtime.subprocess.run", return_value=failed):
            with self.assertRaisesRegex(workflow.WorkflowError, "provider output was redacted") as raised:
                model_runtime.invoke_structured(
                    config=CONFIG,
                    role_prompt="Role.",
                    task_prompt="Task.",
                    schema=SCHEMA,
                    stage_label="Scout",
                )
        self.assertNotIn(secret, str(raised.exception))

        def malformed(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            output = Path(command[command.index("--output-last-message") + 1])
            output.write_text("not-json", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout="", stderr=secret)

        with patch("authority_os.model_runtime.subprocess.run", side_effect=malformed):
            with self.assertRaisesRegex(workflow.WorkflowError, "invalid JSON") as raised:
                model_runtime.invoke_structured(
                    config=CONFIG,
                    role_prompt="Role.",
                    task_prompt="Task.",
                    schema=SCHEMA,
                    stage_label="Thesis generator",
                )
        self.assertNotIn(secret, str(raised.exception))


if __name__ == "__main__":
    unittest.main()
