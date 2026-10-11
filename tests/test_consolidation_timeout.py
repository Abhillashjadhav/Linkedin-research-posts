"""The installed consolidator's effective effort determines its provider timeout."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

from authority_os import model_call_checkpoint, model_runtime, runtime_budget


ROOT = Path(__file__).resolve().parents[1]
PROBE = """
import json
import os
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from authority_os import model_runtime, momentum_surface_parallel as surface, runtime_budget

installed = sys.argv[1] == 'installed'
if installed:
    from authority_os import daily_discovery_cli, v1_consumability  # noqa: F401

signals = [{'id': f's-{index}'} for index in range(1, 4)]
clusters = [
    {'id': f'topic-{index}', 'topic': f'Distinct decision {index}',
     'why_now': 'A current product decision.', 'signal_ids': [f's-{index}']}
    for index in range(1, 4)
]

def exercise(case):
    observed = []
    clock = [100.0]
    def provider(command, **kwargs):
        observed.append({
            'timeout': kwargs['timeout'],
            'model': command[command.index('--model') + 1],
            'effort': next(item for item in command if item.startswith('model_reasoning_effort=')),
            'web': next(item for item in command if item.startswith('web_search=')),
        })
        clock[0] += case.get('simulated_duration', 0)
        if case.get('expires') or case.get('simulated_duration', 0) > kwargs['timeout']:
            raise subprocess.TimeoutExpired(command, kwargs['timeout'])
        Path(command[command.index('--output-last-message') + 1]).write_text(
            json.dumps({'clusters': clusters}), encoding='utf-8')
        return subprocess.CompletedProcess(command, 0, stdout='', stderr='')

    with ExitStack() as stack:
        stack.enter_context(patch.object(model_runtime.shutil, 'which', return_value='/fake/codex'))
        stack.enter_context(patch.object(model_runtime.subprocess, 'run', side_effect=provider))
        if 'remaining' in case:
            stack.enter_context(patch.dict(os.environ, {
                runtime_budget.DEADLINE_ENV: str(100 + case['remaining'])}))
            stack.enter_context(patch.object(runtime_budget.time, 'time', side_effect=lambda: clock[0]))
        if case.get('child_ultra'):
            stack.enter_context(patch.dict(os.environ, {
                model_runtime.DISCOVERY_CHILD_REASONING_ENV: 'ultra'}))
        if 'reasoning' in case:
            stack.enter_context(model_runtime.discovery_reasoning_override(case['reasoning']))
        if 'model' in case:
            stack.enter_context(model_runtime.discovery_model_override(case['model']))
        try:
            result = surface._consolidate(signals, as_of='2026-10-11T00:00:00Z')
            outcome = f'{len(result)} clusters'
        except model_runtime.ModelTimeoutError as exc:
            outcome = type(exc).__name__
    return {'calls': observed, 'outcome': outcome}

if installed:
    cases = {
        'ordinary': {},
        'astra_ultra': {'reasoning': 'ultra', 'model': 'gpt-6-astra',
                        'remaining': 1800, 'simulated_duration': 151},
        'restored': {'reasoning': 'max'},
        'child_ultra': {'child_ultra': True},
        'masked_child': {'child_ultra': True, 'reasoning': None},
        'shared_deadline': {'reasoning': 'ultra', 'model': 'gpt-6-astra',
                            'remaining': 75, 'expires': True},
        'stage_deadline': {'reasoning': 'ultra', 'model': 'gpt-6-astra',
                           'remaining': 1800, 'expires': True},
    }
else:
    cases = {'ordinary': {}, 'ultra': {'reasoning': 'ultra'}}

print(json.dumps({
    'installed_adapter': surface._consolidate is v1_consumability._consolidate if installed else False,
    'configured_reasoning': surface.MODEL.reasoning,
    'results': {name: exercise(case) for name, case in cases.items()},
}))
"""


class ConsolidationTimeoutTests(unittest.TestCase):
    def _probe(self, adapter: str) -> dict[str, object]:
        # The CLI composition root installs process-global adapters.
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(ROOT / "src")
        for key in (
            model_runtime.DISCOVERY_CHILD_MODEL_ENV,
            model_runtime.DISCOVERY_CHILD_REASONING_ENV,
            runtime_budget.DEADLINE_ENV,
            model_call_checkpoint.SOURCE_ENV,
            model_call_checkpoint.OUTPUT_ENV,
            model_call_checkpoint.INPUT_ENV,
        ):
            environment.pop(key, None)
        process = subprocess.run(
            [sys.executable, "-c", PROBE, adapter], cwd=ROOT, env=environment,
            capture_output=True, text=True, check=True,
        )
        return json.loads(process.stdout.splitlines()[-1])

    def test_base_adapter_keeps_ordinary_cap_and_honors_effective_ultra(self) -> None:
        report = self._probe("base")
        self.assertFalse(report["installed_adapter"])
        self.assertEqual(report["configured_reasoning"], "high")
        results = report["results"]
        self.assertEqual(results["ordinary"]["calls"][0]["timeout"], 60)
        self.assertEqual(results["ultra"]["calls"][0]["timeout"], 600)
        self.assertEqual({row["outcome"] for row in results.values()}, {"3 clusters"})

    def test_installed_adapter_reaches_provider_with_a_scoped_ultra_cap(self) -> None:
        report = self._probe("installed")
        self.assertTrue(report["installed_adapter"])
        self.assertEqual(report["configured_reasoning"], "medium")
        results = report["results"]
        for name, cap in (
            ("ordinary", 150), ("astra_ultra", 600), ("restored", 150),
            ("child_ultra", 600), ("masked_child", 150),
        ):
            with self.subTest(name=name):
                self.assertEqual(results[name]["outcome"], "3 clusters")
                self.assertEqual(len(results[name]["calls"]), 1)
                self.assertEqual(results[name]["calls"][0]["timeout"], cap)
                self.assertEqual(results[name]["calls"][0]["web"], 'web_search="disabled"')
        self.assertEqual(results["ordinary"]["calls"][0]["model"], "gpt-5.6-sol")
        self.assertEqual(results["ordinary"]["calls"][0]["effort"], 'model_reasoning_effort="medium"')
        self.assertEqual(results["astra_ultra"]["calls"][0]["model"], "gpt-6-astra")
        self.assertEqual(results["astra_ultra"]["calls"][0]["effort"], 'model_reasoning_effort="ultra"')
        self.assertEqual(results["restored"]["calls"][0]["effort"], 'model_reasoning_effort="max"')

    def test_installed_ultra_still_obeys_shared_deadline_and_error_classification(self) -> None:
        results = self._probe("installed")["results"]
        clipped = results["shared_deadline"]
        self.assertEqual(clipped["outcome"], "GlobalDeadlineExceeded")
        self.assertEqual(len(clipped["calls"]), 1)
        self.assertEqual(clipped["calls"][0]["timeout"], 75)
        self.assertEqual(clipped["calls"][0]["model"], "gpt-6-astra")
        self.assertEqual(clipped["calls"][0]["effort"], 'model_reasoning_effort="ultra"')
        local = results["stage_deadline"]
        self.assertEqual(local["outcome"], "ModelTimeoutError")
        self.assertEqual(len(local["calls"]), 1)
        self.assertEqual(local["calls"][0]["timeout"], 600)


if __name__ == "__main__":
    unittest.main()
