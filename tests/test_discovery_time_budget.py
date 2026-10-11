"""Offline tests for the discovery invocation allowance and deadline reporting."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli, momentum_surface_parallel, runtime_budget, workflow
from tests.test_discovery_resume import AS_OF, candidate, profile_payload


class DiscoveryTimeBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA)
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        prior_trace = momentum_surface_parallel._TRACE_DIR
        self.addCleanup(setattr, momentum_surface_parallel, "_TRACE_DIR", prior_trace)

    def _installed(self):
        # The installed composition root swaps discovery adapters at import time.
        from authority_os import daily_discovery_cli
        return daily_discovery_cli

    def _args(self, *, seconds=None, output=None):
        return argparse.Namespace(
            profile=self.folder / "profile.json", days=7, as_of=AS_OF,
            db=self.folder / "research.sqlite", output_dir=output or self.folder / "run",
            resume_from=None, topic=None, week_slot=None, generate_post=False,
            model=None, reasoning=None, time_budget_seconds=seconds,
            allow_web_research=True, allow_model_egress=True,
        )

    def test_installed_cli_accepts_override_and_rejects_invalid_values(self) -> None:
        binary = workflow.REPO_ROOT / "bin" / "linkedin-os"
        help_result = subprocess.run([str(binary), "discover", "--help"], capture_output=True, text=True)
        self.assertEqual(help_result.returncode, 0)
        self.assertIn("--time-budget-seconds", help_result.stdout)
        for value in ("0", "-1", "3601", "2.5", "nonsense"):
            rejected = subprocess.run(
                [str(binary), "discover", "--profile", "unused.json", "--time-budget-seconds", value],
                capture_output=True, text=True,
            )
            self.assertEqual(rejected.returncode, 2, value)
            self.assertIn("1 to 3600", rejected.stderr)
        self.assertEqual(self._installed().parser().parse_args([
            "--profile", "unused.json", "--time-budget-seconds", "3600",
        ]).time_budget_seconds, 3600)

    def test_programmatic_validation_precedes_side_effects(self) -> None:
        entry = self._installed()
        for invalid in (0, -1, 3601, True, "1800", 2.5):
            with self.subTest(invalid=invalid), patch.object(entry, "_ORIGINAL_COMMAND") as run:
                with self.assertRaisesRegex(workflow.WorkflowError, "integer from 1 to 3600"):
                    entry.command(self._args(seconds=invalid))
                run.assert_not_called()
        expected = {"requested_seconds": None, "effective_seconds": 480,
                    "default_seconds": 480, "runtime_slo_seconds": 480}
        policy = daily_spine_cli.discovery_time_budget(self._args())
        self.assertEqual({key: policy[key] for key in expected}, expected)

    def test_root_default_override_and_prior_deadline_restoration(self) -> None:
        entry = self._installed()
        for requested, selected in ((None, 480), (1800, 1800)):
            seen = []
            def command(_):
                seen.append(runtime_budget.deadline_epoch())
                return 0
            with self.subTest(requested=requested), patch.dict(os.environ, {runtime_budget.DEADLINE_ENV: "42"}), \
                 patch.object(entry.base.base.legacy_cli, "_ensure_owner_only_directory"), \
                 patch.object(entry.momentum_surface_parallel, "configure_trace_dir"), \
                 patch.object(entry, "_ORIGINAL_COMMAND", side_effect=command), \
                 patch.object(entry, "_delivered", return_value=True):
                start = time.time()
                self.assertEqual(entry.command(self._args(seconds=requested)), 0)
                self.assertAlmostEqual(seen[0] - start, selected, delta=2)
                self.assertEqual(os.environ[runtime_budget.DEADLINE_ENV], "42")
        with patch.dict(os.environ, {runtime_budget.DEADLINE_ENV: "42"}), \
             patch.object(entry.base.base.legacy_cli, "_ensure_owner_only_directory"), \
             patch.object(entry.momentum_surface_parallel, "configure_trace_dir"), \
             patch.object(entry, "_ORIGINAL_COMMAND", side_effect=ValueError("offline failure")):
            with self.assertRaisesRegex(ValueError, "offline failure"):
                entry.command(self._args(seconds=1800))
            self.assertEqual(os.environ[runtime_budget.DEADLINE_ENV], "42")

    def test_nested_spine_uses_the_root_clock(self) -> None:
        entry = self._installed()
        original = entry._ORIGINAL_COMMAND
        seen = []
        def entered(args):
            seen.append(runtime_budget.deadline_epoch())
            return original(args)
        with patch.object(entry.base.base.legacy_cli, "_ensure_owner_only_directory"), \
             patch.object(entry.momentum_surface_parallel, "configure_trace_dir"), \
             patch.object(entry, "_ORIGINAL_COMMAND", side_effect=entered), \
             patch.object(entry.base, "_command", side_effect=lambda _: seen.append(runtime_budget.deadline_epoch()) or 0), \
             patch.object(entry, "_delivered", return_value=True):
            self.assertEqual(entry.command(self._args(seconds=1800)), 0)
        self.assertEqual(len(seen), 2)
        self.assertEqual(seen[0], seen[1])

    def test_direct_python_entry_honors_override_and_restores_environment(self) -> None:
        args = self._args(seconds=1800)
        seen = []
        with patch.dict(os.environ, {runtime_budget.DEADLINE_ENV: "42"}):
            with patch.object(daily_spine_cli, "_command", side_effect=lambda _: seen.append(runtime_budget.deadline_epoch()) or 0):
                start = time.time()
                self.assertEqual(self._installed()._ORIGINAL_COMMAND(args), 0)
            self.assertAlmostEqual(seen[0] - start, 1800, delta=2)
            self.assertEqual(os.environ[runtime_budget.DEADLINE_ENV], "42")

    def test_budget_is_outside_resume_identity_and_provenance_records_distinction(self) -> None:
        default = self._args()
        changed = self._args(seconds=1800, output=self.folder / "resumed")
        identity = daily_spine_cli._run_input_fingerprint(default, profile_payload(), AS_OF)
        self.assertEqual(identity, daily_spine_cli._run_input_fingerprint(changed, profile_payload(), AS_OF))
        source = self.folder / "source"
        source.mkdir()
        daily_spine_cli.base.write_private_json(source / "run-input.json", {
            "schema_version": 1, "run_id": "source-id", "as_of": AS_OF,
            "input_fingerprint": identity, "contract_sha256": daily_spine_cli._contract_sha256(),
            "implementation_sha256": daily_spine_cli._implementation_sha256(),
            "time_budget": daily_spine_cli.discovery_time_budget(default),
        })
        daily_spine_cli.base.write_private_json(source / "momentum.json", {
            "schema_version": 1, "created_at": AS_OF, "topic": None,
            "days": 7, "candidates": [candidate()],
        })
        daily_spine_cli._write_stage_checkpoint(source, "conversation_discovery", identity)
        resumed = daily_spine_cli.load_stage_resume(source, args=changed, profile=profile_payload())
        self.assertEqual(resumed.completed_stages, ("conversation_discovery",))

        policy = daily_spine_cli.discovery_time_budget(changed)
        self.assertEqual(policy["requested_seconds"], 1800)
        self.assertEqual(policy["effective_seconds"], 1800)
        self.assertEqual(policy["default_seconds"], 480)
        self.assertEqual(policy["runtime_slo_seconds"], 480)
        self.assertIn("does not change", policy["slo_interpretation"])

    def test_actual_run_writes_budget_to_input_and_dashboard(self) -> None:
        entry = self._installed()
        args = self._args(seconds=1800)
        daily_spine_cli.base.write_private_json(args.profile, profile_payload())
        with patch.object(entry.base.momentum, "invoke_scout", side_effect=workflow.WorkflowError("offline scout failure")), \
             patch.object(entry.base.v1_completion, "begin_run", return_value="budget-case"), \
             patch.object(entry.base.v1_completion, "_read_jsonl", return_value=[]):
            with self.assertRaisesRegex(workflow.WorkflowError, "offline scout failure"):
                entry.command(args)
        identity = json.loads((args.output_dir / "run-input.json").read_text())
        run = json.loads((args.output_dir / "run-dashboard.json").read_text())
        self.assertEqual(identity["time_budget"], run["time_budget"])
        self.assertEqual(identity["time_budget"]["requested_seconds"], 1800)
        self.assertEqual(identity["time_budget"]["effective_seconds"], 1800)
        self.assertEqual(identity["time_budget"]["default_seconds"], 480)
        self.assertEqual(identity["time_budget"]["runtime_slo_seconds"], 480)
        html = (args.output_dir / "eval-dashboard.html").read_text()
        self.assertIn("Effective time allowance</td><td>1800 seconds", html)
        self.assertIn("Full-run SLO</td><td>480 seconds", html)

    def test_deadline_reaches_child_and_html_matches_json_after_record(self) -> None:
        entry = self._installed()
        args = self._args(seconds=2)
        folder = args.output_dir
        folder.mkdir(mode=0o700)
        daily_spine_cli.base.write_private_json(folder / "run-input.json", {
            "as_of": AS_OF, "run_id": "budget-run",
            "time_budget": daily_spine_cli.discovery_time_budget(args),
        })
        dashboard = daily_spine_cli.new_run_dashboard("budget-run")
        dashboard["time_budget"] = daily_spine_cli.discovery_time_budget(args)
        dashboard["outcome"] = "FAIL"
        dashboard["checks"][0]["status"] = "FAIL"
        evaluation = {"run_id": "budget-run", "checks": [], "results": []}
        daily_spine_cli.base.write_private_json(folder / "run-dashboard.json", dashboard)
        daily_spine_cli.base.write_private_json(folder / "eval-dashboard.json", evaluation)
        entry.base.eval_dashboard_html.write_dashboard(folder, dashboard, evaluation)
        self.assertIn("FAIL", (folder / "eval-dashboard.html").read_text())
        child = []
        def run(_):
            result = daily_spine_cli.run_drafting_child(
                [sys.executable, "-c", "import os, time; print(os.environ['LINKEDIN_OS_GLOBAL_DEADLINE_EPOCH'], flush=True); time.sleep(5)"],
                cwd=workflow.REPO_ROOT, folder=folder, env=os.environ.copy(),
            )
            child.append(result)
            return result.returncode
        with patch.object(entry.momentum_surface_parallel, "configure_trace_dir"), \
             patch.object(entry, "_ORIGINAL_COMMAND", side_effect=run):
            self.assertEqual(entry.command(args), 124)
        self.assertEqual(child[0].returncode, 124)
        log = (folder / "drafting.log").read_text()
        self.assertIn("TIME_BUDGET_EXCEEDED", log)
        self.assertAlmostEqual(float(log.splitlines()[0]) - time.time(), 0, delta=2)
        saved = json.loads((folder / "run-dashboard.json").read_text())
        self.assertEqual(saved["outcome"], "TIME_BUDGET_EXCEEDED")
        self.assertEqual(saved["checks"][0]["status"], "TIME_BUDGET_EXCEEDED")
        report = folder / "eval-dashboard.html"
        html = report.read_text()
        self.assertIn('class="verdict fail">TIME_BUDGET_EXCEEDED', html)
        self.assertIn('class="status time-budget-exceeded">TIME_BUDGET_EXCEEDED', html)
        self.assertIn("1800", daily_spine_cli.eval_dashboard_html.render_dashboard({**saved, "time_budget": daily_spine_cli.discovery_time_budget(self._args(seconds=1800))}, evaluation))
        self.assertEqual(stat.S_IMODE(report.stat().st_mode), 0o600)
        checkpoint = json.loads((folder / "deadline-checkpoint.json").read_text())
        words = shlex.split(checkpoint["resume_command"])
        self.assertEqual(words[words.index("--time-budget-seconds") + 1], "2")
        parsed = entry.parser().parse_args(words[2:])
        self.assertEqual(parsed.time_budget_seconds, 2)
        self.assertEqual(parsed.resume_from, folder)

    def test_report_refresh_rejects_symlink_without_touching_target(self) -> None:
        folder = self.folder / "run"
        folder.mkdir()
        external = self.folder / "outside.html"
        external.write_text("untouched", encoding="utf-8")
        (folder / "eval-dashboard.html").symlink_to(external)
        with self.assertRaisesRegex(workflow.WorkflowError, "must not be a symlink"):
            daily_spine_cli.eval_dashboard_html.refresh_dashboard(folder, {}, {})
        self.assertEqual(external.read_text(encoding="utf-8"), "untouched")


if __name__ == "__main__":
    unittest.main()
