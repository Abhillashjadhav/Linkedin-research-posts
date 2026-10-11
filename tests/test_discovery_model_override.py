"""A requested discovery model reaches every stage without changing defaults."""

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


ROOT = Path(__file__).resolve().parents[1]
ASTRA = "gpt-6-astra"


class DiscoveryModelOverrideTests(unittest.TestCase):
    def _probe(self, script: str, *, model: str | None = None) -> dict:
        """Keep composition-root patching isolated from the other tests."""
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        daily_spine_cli.set_drafting_child_model(env, model)
        env.pop(model_runtime.DISCOVERY_CHILD_REASONING_ENV, None)
        completed = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=env,
                                   capture_output=True, text=True, check=True)
        return json.loads(completed.stdout.splitlines()[-1])

    def test_cli_rejects_unsafe_or_blank_slugs(self):
        help_result = subprocess.run([str(ROOT / "bin" / "linkedin-os"), "discover", "--help"],
                                     cwd=ROOT, capture_output=True, text=True, check=True)
        self.assertIn("--model MODEL", help_result.stdout)
        for slug in ("", " ", "gpt-6-astra --config unsafe", "other/model", "-unsafe", "astra\nother"):
            with self.subTest(slug=slug):
                result = subprocess.run([str(ROOT / "bin" / "linkedin-os"), "discover",
                                         f"--model={slug}"], cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("nonblank Codex model slug", result.stderr)

    def test_effective_provider_argv_and_copied_worker_context(self):
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")
        commands = []

        def fake_run(command, **_):
            commands.append(command)
            Path(command[command.index("--output-last-message") + 1]).write_text('{"ok":true}')
            return subprocess.CompletedProcess(command, 0, "", "")

        with patch.object(model_runtime.shutil, "which", return_value="/fake/codex"), patch.object(
            model_runtime.subprocess, "run", side_effect=fake_run
        ):
            with model_runtime.discovery_model_override(ASTRA), model_runtime.discovery_reasoning_override("ultra"):
                self.assertEqual(config.trace(), {"runtime": "codex", "model": ASTRA, "reasoning": "ultra"})
                with ThreadPoolExecutor(max_workers=1) as pool:
                    self.assertEqual(pool.submit(copy_context().run, config.trace).result()["model"], ASTRA)
                self.assertEqual(model_runtime.invoke_structured(
                    config=config, role_prompt="Role", task_prompt="Task", schema={"type": "object"},
                    stage_label="Astra provider test",
                ), {"ok": True})
        self.assertEqual(commands[0][commands[0].index("--model") + 1], ASTRA)
        self.assertIn('model_reasoning_effort="ultra"', commands[0])
        self.assertEqual(config.trace(), {"runtime": "codex", "model": "gpt-5.6-sol", "reasoning": "high"})

    def test_child_transport_defaults_and_tuned_composition(self):
        key = model_runtime.DISCOVERY_CHILD_MODEL_ENV
        child_env = {key: ASTRA}
        daily_spine_cli.set_drafting_child_model(child_env, None)
        self.assertNotIn(key, child_env)
        daily_spine_cli.set_drafting_child_model(child_env, ASTRA)
        self.assertEqual(child_env[key], ASTRA)
        with self.assertRaises(WorkflowError):
            daily_spine_cli.set_drafting_child_model(child_env, "astra with spaces")
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")
        with patch.dict(os.environ, {key: ASTRA}):
            self.assertEqual(config.trace()["model"], ASTRA)
            with model_runtime.discovery_model_override(None):
                self.assertEqual(config.trace()["model"], "gpt-5.6-sol")
        self.assertEqual(config.trace()["model"], "gpt-5.6-sol")
        with patch.dict(os.environ, {key: "invalid model"}):
            with self.assertRaisesRegex(WorkflowError, "nonblank Codex model slug"):
                config.trace()

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
        requested_child = self._probe(script, model=ASTRA)
        dashboard = daily_spine_cli.evaluator_versions()["models"]
        for role, default in default_child.items():
            self.assertEqual(dashboard[role], default, role)
            self.assertEqual(default["model"], "gpt-5.6-sol", role)
        with model_runtime.discovery_model_override(ASTRA):
            selected = daily_spine_cli.evaluator_versions()["models"]
            self.assertEqual({row["model"] for row in selected.values()}, {ASTRA})
        for role, requested in requested_child.items():
            self.assertEqual(selected[role], requested, role)

    def test_discover_command_scopes_model_even_on_failure(self):
        result = self._probe("""
import argparse, json
from pathlib import Path
from unittest.mock import patch
from authority_os import daily_discovery_cli, model_runtime
config = model_runtime.ModelConfig('codex', 'gpt-5.6-sol', 'medium')
args = argparse.Namespace(as_of='2026-10-11T00:00:00Z', resume_from=None,
                          output_dir=Path('data/private/discovery-test'), model='gpt-6-astra')
seen = []
def fail(_):
    seen.append(config.trace()['model'])
    raise ValueError('test failure')
with patch.object(daily_discovery_cli.momentum_surface_parallel, 'configure_trace_dir'), patch.object(
    daily_discovery_cli.base.base.legacy_cli, '_ensure_owner_only_directory'
), patch.object(daily_discovery_cli, '_ORIGINAL_COMMAND', side_effect=fail):
    try:
        daily_discovery_cli.command(args)
    except ValueError:
        pass
print(json.dumps({'seen': seen, 'after': config.trace()['model']}))
""")
        self.assertEqual(result, {"seen": [ASTRA], "after": "gpt-5.6-sol"})

    def test_direct_daily_spine_entry_respects_advertised_flags(self):
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "medium")
        observed = []
        with patch.object(daily_spine_cli, "_command", side_effect=lambda _: observed.append(config.trace()) or 0):
            status = daily_spine_cli.main([
                "--profile", "unused-private-profile.json", "--model", ASTRA,
                "--reasoning", "ultra",
            ])
        self.assertEqual(status, 0)
        self.assertEqual(observed, [{"runtime": "codex", "model": ASTRA, "reasoning": "ultra"}])
        self.assertEqual(config.trace(), {"runtime": "codex", "model": "gpt-5.6-sol", "reasoning": "medium"})

    def test_provider_failure_does_not_downgrade_or_retry(self):
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")
        commands = []

        def failing_run(command, **_):
            commands.append(command)
            return subprocess.CompletedProcess(command, 1, "", "unsupported model")

        with patch.object(model_runtime.shutil, "which", return_value="/fake/codex"), patch.object(
            model_runtime.subprocess, "run", side_effect=failing_run
        ):
            with self.assertRaisesRegex(WorkflowError, "provider output was redacted"):
                with model_runtime.discovery_model_override(ASTRA):
                    model_runtime.invoke_structured(config=config, role_prompt="Role", task_prompt="Task",
                                                    schema={"type": "object"}, stage_label="No model fallback")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][commands[0].index("--model") + 1], ASTRA)
        self.assertEqual(config.trace()["model"], "gpt-5.6-sol")

    def test_model_changes_fingerprint_and_legacy_resume_rejects_explicit_model(self):
        def args(model):
            return argparse.Namespace(topic=None, days=7, db=Path("data/private/research.sqlite"),
                                      generate_post=True, week_slot=None, reasoning="ultra", model=model)
        default = daily_spine_cli._run_input_fingerprint(args(None), {}, "2026-10-11T00:00:00Z")
        astra = daily_spine_cli._run_input_fingerprint(args(ASTRA), {}, "2026-10-11T00:00:00Z")
        self.assertNotEqual(default, astra)
        with patch.object(daily_spine_cli.base, "_under_private", side_effect=lambda path: path), patch.object(
            daily_spine_cli.base, "_private_json", return_value={"schema_version": 2}
        ):
            with self.assertRaisesRegex(WorkflowError, "original model"):
                daily_spine_cli.load_discovery_resume(Path("/tmp/legacy-run"), days=7,
                                                      requested_topic=None, profile={}, model=ASTRA)

    def test_deadline_resume_command_preserves_exact_model_and_effort(self):
        result = self._probe("""
import argparse, json, tempfile
from pathlib import Path
from unittest.mock import patch
from authority_os import daily_discovery_cli
args = argparse.Namespace(profile=Path('data/private/profile.json'), days=7,
    db=Path('data/private/research.sqlite'), topic=None, week_slot=None,
    generate_post=True, model='gpt-6-astra', reasoning='ultra')
written = {}
with tempfile.TemporaryDirectory() as root, patch.object(daily_discovery_cli.base.base, '_private_json',
    return_value={'as_of':'2026-10-11T00:00:00Z'}), patch.object(daily_discovery_cli.base.base,
    'write_private_json', side_effect=lambda path, value: written.update(value)):
    daily_discovery_cli._record_deadline(Path(root) / 'failed', args, 480)
print(json.dumps(written))
""")
        self.assertIn("--model gpt-6-astra", result["resume_command"])
        self.assertIn("--reasoning ultra", result["resume_command"])


if __name__ == "__main__":
    unittest.main()
