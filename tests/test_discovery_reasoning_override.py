"""Requested discovery reasoning reaches provider arguments, workers, child and identity."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli, model_runtime
from authority_os.workflow import WorkflowError


class DiscoveryReasoningTests(unittest.TestCase):
    def _probe(self, script: str) -> dict:
        """Composition-root imports install global routes; inspect them in a fresh process."""
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        env.pop(model_runtime.DISCOVERY_CHILD_REASONING_ENV, None)
        completed = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                                   capture_output=True, text=True, check=True)
        return json.loads(completed.stdout.splitlines()[-1])

    def test_parser_and_effective_provider_argument_and_worker_trace(self):
        root = Path(__file__).resolve().parents[1]
        help_result = subprocess.run([str(root / "bin" / "linkedin-os"), "discover", "--help"],
                                     cwd=root, capture_output=True, text=True, check=True)
        self.assertIn("--reasoning", help_result.stdout)
        invalid = subprocess.run([str(root / "bin" / "linkedin-os"), "discover", "--profile", "missing.json",
                                  "--reasoning", "unavailable"], cwd=root, capture_output=True, text=True)
        self.assertEqual(invalid.returncode, 2)
        self.assertIn("invalid choice", invalid.stderr)
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "medium")
        observed = []
        def fake_run(command, **_):
            observed.append(command)
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok":true}')
            return subprocess.CompletedProcess(command, 0, "", "")
        with patch.object(model_runtime.shutil, "which", return_value="/fake/codex"), patch.object(
            model_runtime.subprocess, "run", side_effect=fake_run
        ):
            with model_runtime.discovery_reasoning_override("ultra"):
                self.assertEqual(config.trace()["reasoning"], "ultra")
                with ThreadPoolExecutor(max_workers=1) as pool:
                    worker_trace = pool.submit(copy_context().run, config.trace).result()
                self.assertEqual(worker_trace["reasoning"], "ultra")
                self.assertEqual(daily_spine_cli.evaluator_versions()["models"]["surface_scout"]["reasoning"], "ultra")
                self.assertEqual(daily_spine_cli.evaluator_versions()["models"]["writer"]["reasoning"], "ultra")
                result = model_runtime.invoke_structured(config=config, role_prompt="Role", task_prompt="Task",
                                                         schema={"type": "object"}, stage_label="Reasoning test")
                self.assertEqual(result, {"ok": True})
        self.assertIn('model_reasoning_effort="ultra"', observed[0])
        self.assertEqual(observed[0][observed[0].index("--model") + 1], "gpt-5.6-sol")
        self.assertEqual(config.trace()["reasoning"], "medium")

    def test_child_transport_is_explicit_and_does_not_leak(self):
        key = model_runtime.DISCOVERY_CHILD_REASONING_ENV
        env = {key: "ultra"}
        daily_spine_cli.set_drafting_child_reasoning(env, None)
        self.assertNotIn(key, env)
        daily_spine_cli.set_drafting_child_reasoning(env, "ultra")
        self.assertEqual(env[key], "ultra")
        with self.assertRaises(WorkflowError):
            daily_spine_cli.set_drafting_child_reasoning(env, "not-supported")
        with patch.dict(os.environ, {key: "ultra"}):
            config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "max")
            self.assertEqual(config.validate().reasoning, "ultra")
            with model_runtime.discovery_reasoning_override(None):
                self.assertEqual(config.trace()["reasoning"], "max")
        self.assertEqual(config.trace()["reasoning"], "max")
        script = (
            "import json; from authority_os import campaign, v1_runtime_tuning, topic_value; "
            "v1_runtime_tuning.install(); models=campaign.StageModels.preferred(); "
            "selector=topic_value.ModelConfig('codex','gpt-5.6-sol','ultra'); "
            "print(json.dumps({'writer':models.writer.trace(), 'critic':models.critic.trace(), "
            "'selector':selector.trace()}))"
        )
        root = Path(__file__).resolve().parents[1]
        child_env = os.environ.copy()
        child_env["PYTHONPATH"] = str(root / "src")
        daily_spine_cli.set_drafting_child_reasoning(child_env, "ultra")
        child = subprocess.run([sys.executable, "-c", script], cwd=root, env=child_env,
                               capture_output=True, text=True, check=True)
        result = json.loads(child.stdout)
        self.assertEqual({item["reasoning"] for item in result.values()}, {"ultra"})
        self.assertEqual({item["model"] for item in result.values()}, {"gpt-5.6-sol"})

    def test_dashboard_profiles_match_the_actual_tuned_draft_child(self):
        script = """
import json
from authority_os import campaign, resonance, topic_value, v1_runtime_tuning
v1_runtime_tuning.install()
models = campaign.StageModels.preferred()
rows = {name: getattr(models, name).trace() for name in models.__dataclass_fields__}
rows['draft_topic_value'] = topic_value.ModelConfig('codex', 'gpt-5.6-sol', 'ultra').trace()
rows['resonance'] = resonance.ModelConfig('codex', 'gpt-5.6-sol', 'ultra').trace()
print(json.dumps(rows))
"""
        default_child = self._probe(script)
        dashboard = daily_spine_cli.evaluator_versions()["models"]
        for role, actual in default_child.items():
            self.assertEqual(dashboard[role], actual, role)
        self.assertEqual(dashboard["writer"]["reasoning"], "high")
        self.assertEqual(dashboard["narrative_editor"]["reasoning"], "high")
        self.assertEqual(dashboard["critic"]["reasoning"], "max")
        self.assertEqual(dashboard["topic_value"]["reasoning"], "ultra")
        self.assertEqual(dashboard["draft_topic_value"]["reasoning"], "max")
        self.assertEqual(dashboard["resonance"]["reasoning"], "max")
        with model_runtime.discovery_reasoning_override("ultra"):
            selected = daily_spine_cli.evaluator_versions()["models"]
            self.assertEqual({selected[role]["reasoning"] for role in (*default_child, "topic_value")}, {"ultra"})
        root = Path(__file__).resolve().parents[1]
        env = os.environ.copy()
        env["PYTHONPATH"] = str(root / "src")
        daily_spine_cli.set_drafting_child_reasoning(env, "ultra")
        child = subprocess.run([sys.executable, "-c", script], cwd=root, env=env,
                               capture_output=True, text=True, check=True)
        ultra_child = json.loads(child.stdout)
        for role, actual in ultra_child.items():
            self.assertEqual(selected[role], actual, role)

    def test_provider_failure_has_no_downgrade_retry_and_scope_restores(self):
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")
        commands = []
        def failing_run(command, **_):
            commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "redacted")
        with patch.object(model_runtime.shutil, "which", return_value="/fake/codex"), patch.object(
            model_runtime.subprocess, "run", side_effect=failing_run
        ):
            with self.assertRaisesRegex(WorkflowError, "provider output was redacted"):
                with model_runtime.discovery_reasoning_override("ultra"):
                    model_runtime.invoke_structured(config=config, role_prompt="Role", task_prompt="Task",
                                                    schema={"type": "object"}, stage_label="No fallback")
        self.assertEqual(len(commands), 1)
        self.assertIn('model_reasoning_effort="ultra"', commands[0])
        self.assertEqual(config.trace()["reasoning"], "high")

    def test_discover_command_scopes_requested_effort(self):
        result = self._probe("""
import argparse, json
from pathlib import Path
from unittest.mock import patch
from authority_os import daily_discovery_cli, model_runtime
config = model_runtime.ModelConfig('codex', 'gpt-5.6-sol', 'medium')
args = argparse.Namespace(as_of='2026-10-11T00:00:00Z', resume_from=None,
                          output_dir=Path('data/private/discovery-test'), reasoning='ultra')
seen = []
with patch.object(daily_discovery_cli.momentum_surface_parallel, 'configure_trace_dir'), patch.object(
    daily_discovery_cli.base.base.legacy_cli, '_ensure_owner_only_directory'
), patch.object(daily_discovery_cli, '_ORIGINAL_COMMAND', side_effect=lambda _: seen.append(config.trace()['reasoning']) or 0), patch.object(
    daily_discovery_cli, '_delivered', return_value=True
):
    status = daily_discovery_cli.command(args)
print(json.dumps({'status': status, 'seen': seen, 'after': config.trace()['reasoning']}))
""")
        self.assertEqual(result, {"status": 0, "seen": ["ultra"], "after": "medium"})

    def test_requested_reasoning_changes_resume_fingerprint_and_legacy_is_rejected(self):
        def args(reasoning):
            return argparse.Namespace(topic=None, days=7, db=Path("data/private/research.sqlite"),
                                      generate_post=True, week_slot=None, reasoning=reasoning)
        default = daily_spine_cli._run_input_fingerprint(args(None), {}, "2026-10-11T00:00:00Z")
        ultra = daily_spine_cli._run_input_fingerprint(args("ultra"), {}, "2026-10-11T00:00:00Z")
        self.assertNotEqual(default, ultra)
        with patch.object(daily_spine_cli.base, "_under_private", side_effect=lambda path: path), patch.object(
            daily_spine_cli.base, "_private_json", return_value={"schema_version": 2}
        ):
            with self.assertRaisesRegex(WorkflowError, "Legacy discovery resume cannot establish"):
                daily_spine_cli.load_discovery_resume(Path("/tmp/legacy-run"), days=7,
                                                       requested_topic=None, profile={}, reasoning="ultra")

    def test_deadline_resume_command_keeps_reasoning(self):
        result = self._probe("""
import argparse, json, tempfile
from pathlib import Path
from unittest.mock import patch
from authority_os import daily_discovery_cli
args = argparse.Namespace(profile=Path('data/private/profile.json'), days=7,
    db=Path('data/private/research.sqlite'), topic=None, week_slot=None,
    generate_post=True, reasoning='ultra')
written = {}
with tempfile.TemporaryDirectory() as root, patch.object(daily_discovery_cli.base.base, '_private_json',
    return_value={'as_of':'2026-10-11T00:00:00Z'}), patch.object(daily_discovery_cli.base.base,
    'write_private_json', side_effect=lambda path, value: written.update(value)):
    daily_discovery_cli._record_deadline(Path(root) / 'failed', args, 480)
print(json.dumps(written))
""")
        self.assertIn("--reasoning ultra", result["resume_command"])


if __name__ == "__main__":
    unittest.main()
