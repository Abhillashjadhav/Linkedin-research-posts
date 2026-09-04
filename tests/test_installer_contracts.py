from __future__ import annotations

import inspect
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import unittest

from authority_os import v1_completion, v1_gates


PROBE = Path(__file__).with_name("runtime_overlay_probe.py")
REPO_ROOT = Path(__file__).resolve().parents[1]

EXPECTED_DISCOVERY_LAYERS = {
    "v1_gates": 11,
    "v1_completion": 9,
    "topic_value_id_contract": 2,
    "daily_discovery_cli": 10,
}

EXPECTED_DRAFT_LAYERS = {
    "v1_gates": 11,
    "v1_completion": 9,
    "topic_value_id_contract": 2,
    "v1_length_policy": 0,
    "single_topic_codex": 3,
    "human_readability": 1,
    "critic_anchor_retry": 2,
    "actionable_diagnostics": 1,
    "social_media_gate_policy": 2,
    "v1_consumability": 2,
    "v1_runtime_tuning": 4,
    "quality_optimizer": 6,
    "integrated_cli": 4,
}


def _assert_signature_compatible(
    test: unittest.TestCase,
    original,
    replacement,
    dotted_name: str,
) -> None:
    original_parameters = inspect.signature(original).parameters
    replacement_parameters = inspect.signature(replacement).parameters
    replacement_var_positional = any(
        parameter.kind == inspect.Parameter.VAR_POSITIONAL
        for parameter in replacement_parameters.values()
    )
    replacement_var_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in replacement_parameters.values()
    )

    for name, original_parameter in original_parameters.items():
        replacement_parameter = replacement_parameters.get(name)
        message = f"{dotted_name}: replacement lost parameter {name!r}"
        if original_parameter.kind == inspect.Parameter.VAR_POSITIONAL:
            test.assertTrue(replacement_var_positional, message)
            continue
        if original_parameter.kind == inspect.Parameter.VAR_KEYWORD:
            test.assertTrue(replacement_var_keyword, message)
            continue
        if original_parameter.kind == inspect.Parameter.POSITIONAL_ONLY:
            test.assertTrue(
                replacement_parameter is not None
                and replacement_parameter.kind == inspect.Parameter.POSITIONAL_ONLY
                or replacement_var_positional,
                message,
            )
        elif original_parameter.kind == inspect.Parameter.KEYWORD_ONLY:
            test.assertIsNotNone(replacement_parameter, message)
            test.assertEqual(
                replacement_parameter.kind,
                inspect.Parameter.KEYWORD_ONLY,
                f"{dotted_name}: keyword-only parameter {name!r} changed kind",
            )
        else:
            explicit_match = (
                replacement_parameter is not None
                and replacement_parameter.kind
                == inspect.Parameter.POSITIONAL_OR_KEYWORD
            )
            test.assertTrue(
                explicit_match
                or (replacement_var_positional and replacement_var_keyword),
                message,
            )

        if (
            original_parameter.default is not inspect.Parameter.empty
            and replacement_parameter is not None
        ):
            test.assertIsNot(
                replacement_parameter.default,
                inspect.Parameter.empty,
                f"{dotted_name}: optional parameter {name!r} became required",
            )

    for name, replacement_parameter in replacement_parameters.items():
        if name in original_parameters or replacement_parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        test.assertIsNot(
            replacement_parameter.default,
            inspect.Parameter.empty,
            f"{dotted_name}: replacement added required parameter {name!r}",
        )


class InstallerContractTests(unittest.TestCase):
    def test_every_installed_callable_preserves_its_original_signature(self) -> None:
        pairs = (*v1_gates.INSTALLED_PAIRS, *v1_completion.INSTALLED_PAIRS)
        for original, replacement, dotted_name in pairs:
            with self.subTest(target=dotted_name):
                _assert_signature_compatible(
                    self,
                    original,
                    replacement,
                    dotted_name,
                )

    def _run_overlay_probe(self, mode: str) -> dict[str, object]:
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(
            Path(__file__).resolve().parents[1] / "src"
        )
        completed = subprocess.run(
            [sys.executable, str(PROBE), mode],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout.splitlines()[-1])

    def test_probe_tracks_exact_launcher_installer_inventory(self) -> None:
        launcher = (REPO_ROOT / "bin" / "linkedin-os").read_text(encoding="utf-8")
        installed = re.findall(
            r"from authority_os import ([a-z0-9_]+)\n[ \t]*\1\.install\(\)",
            launcher,
        )
        self.assertEqual(
            installed,
            [
                "v1_gates",
                "v1_completion",
                "topic_value_id_contract",
                "v1_gates",
                "v1_completion",
                "topic_value_id_contract",
                "v1_length_policy",
                "single_topic_codex",
                "human_readability",
                "critic_anchor_retry",
                "actionable_diagnostics",
                "social_media_gate_policy",
                "v1_consumability",
                "v1_runtime_tuning",
                "quality_optimizer",
            ],
        )
        discovery_composition = (
            REPO_ROOT / "src" / "authority_os" / "daily_discovery_cli.py"
        ).read_text(encoding="utf-8")
        self.assertEqual(
            re.findall(
                r"^([a-z0-9_]+)\.install\(\)$",
                discovery_composition,
                re.MULTILINE,
            ),
            [
                "discovery_runtime_tuning",
                "surface_scout_runtime_tuning",
                "individual_launch_runtime_tuning",
                "v1_consumability",
            ],
        )

    def test_discovery_runtime_stack_preserves_every_callable_boundary(self) -> None:
        report = self._run_overlay_probe("discovery")
        self.assertTrue(report["dispatch_ok"])
        self.assertEqual(report["failures"], [])
        self.assertEqual(
            {
                name: len(targets)
                for name, targets in report["layers"].items()
            },
            EXPECTED_DISCOVERY_LAYERS,
        )

    def test_draft_runtime_stack_preserves_every_callable_boundary(self) -> None:
        report = self._run_overlay_probe("draft")
        self.assertTrue(report["dispatch_ok"])
        self.assertEqual(report["failures"], [])
        self.assertEqual(
            {
                name: len(targets)
                for name, targets in report["layers"].items()
            },
            EXPECTED_DRAFT_LAYERS,
        )


if __name__ == "__main__":
    unittest.main()
