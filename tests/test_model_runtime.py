"""Regression tests for the shared, capability-bounded Codex runtime."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import compare_capture_runtime
from authority_os import campaign, model_call_checkpoint, model_runtime, resonance, runtime_budget, topic_value, workflow


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
    def test_optional_editor_failure_is_replayed_before_completed_critic(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            source, resumed = root / "source", root / "resumed"
            for folder, run_id in ((source, "source-run"), (resumed, "resumed-run")):
                folder.mkdir()
                (folder / "run-input.json").write_text(json.dumps({
                    "schema_version": 1, "run_id": run_id,
                    "input_fingerprint": "c" * 64,
                }), encoding="utf-8")
            stages = ("Writer", "Optional Editor", "Critic", "Advisory")
            def invoke(label: str) -> dict[str, object]:
                return model_runtime.invoke_structured(
                    config=CONFIG, role_prompt=label, task_prompt="Exact same selected evidence.",
                    schema=SCHEMA, stage_label=label,
                )

            def first_provider(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
                prompt = str(kwargs.get("input", ""))
                if "Optional Editor" in prompt or "Advisory" in prompt:
                    raise subprocess.TimeoutExpired("codex", 180)
                return successful_run(command, **kwargs)

            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, {
                model_call_checkpoint.OUTPUT_ENV: str(source / "model-calls"),
                model_call_checkpoint.INPUT_ENV: "c" * 64,
            }), patch.object(model_runtime.shutil, "which", return_value="/opt/codex"), patch.object(
                model_runtime.subprocess, "run", side_effect=first_provider,
            ):
                self.assertEqual(invoke(stages[0]), {"answer": "ok"})
                with self.assertRaises(model_runtime.ModelTimeoutError):
                    invoke(stages[1])  # Existing optional-editor caller continues.
                self.assertEqual(invoke(stages[2]), {"answer": "ok"})
                with self.assertRaises(model_runtime.ModelTimeoutError):
                    invoke(stages[3])
            self.assertEqual(len(list((source / "model-calls").glob("call-*.json"))), 4)

            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, {
                model_call_checkpoint.SOURCE_ENV: str(source / "model-calls"),
                model_call_checkpoint.OUTPUT_ENV: str(resumed / "model-calls"),
                model_call_checkpoint.INPUT_ENV: "c" * 64,
            }), patch.object(model_runtime.shutil, "which", return_value="/opt/codex"), patch.object(
                model_runtime.subprocess, "run", side_effect=successful_run,
            ) as provider:
                self.assertEqual(invoke(stages[0]), {"answer": "ok"})
                with self.assertRaises(model_runtime.ModelTimeoutError):
                    invoke(stages[1])
                self.assertEqual(invoke(stages[2]), {"answer": "ok"})
                self.assertEqual(invoke(stages[3]), {"answer": "ok"})
                provider.assert_called_once()  # Only interrupted advisory reruns.

    def test_writer_checkpoint_survives_critic_interruption_and_rejects_tampering(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            source, resumed = root / "source", root / "resumed"
            for folder, run_id in ((source, "source-run"), (resumed, "resumed-run")):
                folder.mkdir()
                (folder / "run-input.json").write_text(json.dumps({
                    "schema_version": 1, "run_id": run_id,
                    "input_fingerprint": "b" * 64,
                }), encoding="utf-8")
            writer = dict(config=CONFIG, role_prompt="Writer", task_prompt="Use selected evidence.", schema=SCHEMA)
            critic = dict(config=CONFIG, role_prompt="Critic", task_prompt="Score the exact post.", schema=SCHEMA)
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, {
                model_call_checkpoint.OUTPUT_ENV: str(source / "model-calls"),
                model_call_checkpoint.INPUT_ENV: "b" * 64,
            }), patch.object(model_runtime.shutil, "which", return_value="/opt/codex"), patch.object(
                model_runtime.subprocess, "run",
                side_effect=lambda command, **kwargs: (
                    (_ for _ in ()).throw(subprocess.TimeoutExpired("codex", 180))
                    if "Critic" in kwargs.get("input", "") else successful_run(command, **kwargs)
                ),
            ):
                self.assertEqual(model_runtime.invoke_structured(**writer), {"answer": "ok"})
                with self.assertRaises(model_runtime.ModelTimeoutError):
                    model_runtime.invoke_structured(**critic)
            cached = source / "model-calls" / "call-000001.json"
            original = cached.read_text(encoding="utf-8")
            altered = json.loads(original)
            altered["response"]["answer"] = "tampered"
            cached.write_text(json.dumps(altered), encoding="utf-8")
            resumed_env = {
                model_call_checkpoint.SOURCE_ENV: str(source / "model-calls"),
                model_call_checkpoint.OUTPUT_ENV: str(resumed / "model-calls"),
                model_call_checkpoint.INPUT_ENV: "b" * 64,
            }
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, resumed_env), self.assertRaisesRegex(
                workflow.WorkflowError, "no longer matches"
            ):
                model_runtime.invoke_structured(**writer)
            cached.write_text(original, encoding="utf-8")
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, resumed_env), self.assertRaisesRegex(
                workflow.WorkflowError, "no longer matches"
            ):
                model_runtime.invoke_structured(**{**writer, "task_prompt": "Changed prompt."})
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, resumed_env), patch.object(
                model_runtime.shutil, "which", return_value="/opt/codex"
            ), patch.object(model_runtime.subprocess, "run", side_effect=successful_run) as provider:
                self.assertEqual(model_runtime.invoke_structured(**writer), {"answer": "ok"})
                self.assertEqual(model_runtime.invoke_structured(**critic), {"answer": "ok"})
                self.assertEqual(provider.call_count, 1)

    def test_resume_replays_writer_and_critic_without_duplicate_provider_calls(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            source, resumed = root / "source", root / "resumed"
            source.mkdir()
            resumed.mkdir()
            fingerprint = "a" * 64
            for folder, run_id in ((source, "run-one"), (resumed, "run-two")):
                (folder / "run-input.json").write_text(json.dumps({
                    "schema_version": 1, "run_id": run_id,
                    "input_fingerprint": fingerprint,
                }), encoding="utf-8")
            source_env = {
                model_call_checkpoint.OUTPUT_ENV: str(source / "model-calls"),
                model_call_checkpoint.INPUT_ENV: fingerprint,
            }
            calls = ["Writer", "Critic", "Advisory"]
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, source_env), patch.object(
                model_runtime.shutil, "which", return_value="/opt/codex"
            ), patch.object(model_runtime.subprocess, "run", side_effect=[
                successful_run, successful_run, subprocess.TimeoutExpired("codex", 20)
            ]) as run:
                # A callable side effect gives each successful call a structured result.
                run.side_effect = lambda command, **kwargs: (
                    (_ for _ in ()).throw(subprocess.TimeoutExpired("codex", 20))
                    if "Advisory" in kwargs.get("input", "") else successful_run(command, **kwargs)
                )
                for label in calls[:2]:
                    model_runtime.invoke_structured(
                        config=CONFIG, role_prompt=label, task_prompt="Return scores.",
                        schema=SCHEMA, stage_label=label,
                    )
                with self.assertRaises(model_runtime.ModelTimeoutError):
                    model_runtime.invoke_structured(
                        config=CONFIG, role_prompt="Advisory", task_prompt="Return scores.",
                        schema=SCHEMA, stage_label="Advisory", timeout=20,
                    )
                self.assertEqual(run.call_count, 3)

            model_call_checkpoint.reset_sequence_for_tests()
            resumed_env = {
                model_call_checkpoint.SOURCE_ENV: str(source / "model-calls"),
                model_call_checkpoint.OUTPUT_ENV: str(resumed / "model-calls"),
                model_call_checkpoint.INPUT_ENV: fingerprint,
            }
            with patch.dict(os.environ, resumed_env), patch.object(
                model_runtime.shutil, "which", return_value="/opt/codex"
            ), patch.object(model_runtime.subprocess, "run", side_effect=successful_run) as run:
                for label in calls:
                    result = model_runtime.invoke_structured(
                        config=CONFIG, role_prompt=label, task_prompt="Return scores.",
                        schema=SCHEMA, stage_label=label, timeout=20 if label == "Advisory" else 180,
                    )
                    self.assertEqual(result, {"answer": "ok"})
                self.assertEqual(run.call_count, 1)
            self.assertEqual(len(list((resumed / "model-calls").glob("call-*.json"))), 3)
            third = root / "third"
            third.mkdir()
            (third / "run-input.json").write_text(json.dumps({
                "schema_version": 1, "run_id": "run-three",
                "input_fingerprint": fingerprint,
            }), encoding="utf-8")
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, {
                model_call_checkpoint.SOURCE_ENV: str(resumed / "model-calls"),
                model_call_checkpoint.OUTPUT_ENV: str(third / "model-calls"),
                model_call_checkpoint.INPUT_ENV: fingerprint,
            }), patch.object(model_runtime.subprocess, "run", side_effect=AssertionError("completed call repeated")):
                for label in calls:
                    self.assertEqual(model_runtime.invoke_structured(
                        config=CONFIG, role_prompt=label, task_prompt="Return scores.",
                        schema=SCHEMA, stage_label=label, timeout=20 if label == "Advisory" else 180,
                    ), {"answer": "ok"})
            (resumed / "model-calls" / "call-000001.json").unlink()
            (resumed / "model-calls" / "call-000002.json").unlink()
            fourth = root / "fourth"
            fourth.mkdir()
            (fourth / "run-input.json").write_text(json.dumps({
                "schema_version": 1, "run_id": "run-four",
                "input_fingerprint": fingerprint,
            }), encoding="utf-8")
            model_call_checkpoint.reset_sequence_for_tests()
            with patch.dict(os.environ, {
                model_call_checkpoint.SOURCE_ENV: str(resumed / "model-calls"),
                model_call_checkpoint.OUTPUT_ENV: str(fourth / "model-calls"),
                model_call_checkpoint.INPUT_ENV: fingerprint,
            }), patch.object(model_runtime.subprocess, "run") as provider, self.assertRaisesRegex(
                workflow.WorkflowError, "missing earlier call checkpoint"
            ):
                model_runtime.invoke_structured(
                    config=CONFIG, role_prompt="Writer", task_prompt="Return scores.",
                    schema=SCHEMA, stage_label="Writer",
                )
            provider.assert_not_called()

    def test_shared_deadline_bounds_each_provider_call_without_paid_request(self) -> None:
        with (
            patch.dict("os.environ", {runtime_budget.DEADLINE_ENV: "120"}),
            patch.object(runtime_budget.time, "time", return_value=110),
            patch.object(model_runtime.shutil, "which", return_value="/opt/codex"),
            patch.object(model_runtime.subprocess, "run", side_effect=subprocess.TimeoutExpired("codex", 10)) as run,
            self.assertRaises(runtime_budget.GlobalDeadlineExceeded),
        ):
            model_runtime.invoke_structured(
                config=CONFIG, role_prompt="Score topics.", task_prompt="Return scores.",
                schema=SCHEMA, timeout=120,
            )
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_deadline_has_a_distinct_recoverable_error_type(self) -> None:
        with (
            patch.object(model_runtime.shutil, "which", return_value="/opt/codex"),
            patch.object(model_runtime.subprocess, "run", side_effect=subprocess.TimeoutExpired("codex", 120)),
            self.assertRaisesRegex(model_runtime.ModelTimeoutError, "Authority topic critic timed out"),
        ):
            model_runtime.invoke_structured(config=CONFIG, role_prompt="Score topics.",
                task_prompt="Return scores.", schema=SCHEMA, timeout=120,
                stage_label="Authority topic critic")

    @patch("authority_os.model_runtime.subprocess.run", side_effect=successful_run)
    @patch("authority_os.model_runtime.shutil.which", return_value="/opt/codex")
    def test_both_comparison_versions_use_sol_high_without_fast_mode(
        self, _which: object, run: object
    ) -> None:
        original_preferred = campaign.StageModels.__dict__["preferred"]
        original_features = model_runtime.NON_WEB_TOOL_FEATURES
        original_topic_value_config = topic_value.ModelConfig
        original_resonance_config = resonance.ModelConfig
        try:
            for label, include_v1_selection in (("v0", False), ("v1", True)):
                with self.subTest(label=label):
                    compare_capture_runtime._lock_comparison_codex_runtime(  # type: ignore[attr-defined]
                        include_v1_selection=include_v1_selection
                    )
                    config = campaign.StageModels.preferred().writer
                    model_runtime.invoke_structured(
                        config=config,
                        role_prompt="Write from frozen evidence.",
                        task_prompt="Return one structured candidate set.",
                        schema=SCHEMA,
                        web_search=False,
                        stage_label=f"{label} comparison writer",
                    )
                    command = run.call_args.args[0]  # type: ignore[attr-defined]
                    self.assertEqual(
                        command[command.index("--model") + 1], "gpt-5.6-sol"
                    )
                    self.assertIn('model_reasoning_effort="high"', command)
                    self.assertIn("--ignore-user-config", command)
                    disabled = {
                        command[index + 1]
                        for index, value in enumerate(command[:-1])
                        if value == "--disable"
                    }
                    self.assertIn("fast_mode", disabled)
        finally:
            campaign.StageModels.preferred = original_preferred  # type: ignore[method-assign]
            model_runtime.NON_WEB_TOOL_FEATURES = original_features
            topic_value.ModelConfig = original_topic_value_config  # type: ignore[assignment]
            resonance.ModelConfig = original_resonance_config  # type: ignore[assignment]

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
