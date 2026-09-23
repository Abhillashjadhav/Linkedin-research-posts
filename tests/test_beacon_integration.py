from __future__ import annotations

from contextlib import nullcontext
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, patch

from authority_os import beacon_integration, eval_dashboard_html, v1_completion


class BeaconIntegrationTests(unittest.TestCase):
    def test_bootstrap_preserves_arguments_exit_and_root_identity(self) -> None:
        recorder = MagicMock()
        with patch.dict(os.environ, {}, clear=True), patch.object(v1_completion, "_PROCESS_RUN_ID", ""), patch.object(
            beacon_integration, "_capture", return_value=nullcontext(recorder)
        ), patch.object(beacon_integration, "_install_model_observer"):
            with self.assertRaises(SystemExit) as stopped:
                beacon_integration.main([
                    "test", "code",
                    "import sys; assert sys.argv == ['-c', 'two words', '--flag']; raise SystemExit(7)",
                    "two words", "--flag",
                ])
            self.assertEqual(stopped.exception.code, 7)
            self.assertEqual(v1_completion.begin_run(), os.environ["LINKEDIN_OS_RUN_ID"])
            self.assertEqual(os.environ["LINKEDIN_OS_BEACON_ROOT_PID"], str(os.getpid()))
        self.assertTrue(recorder.event.called)

    def test_recorder_failure_never_reruns_or_changes_business_result(self) -> None:
        recorder = MagicMock()
        recorder.event.side_effect = RuntimeError("recorder down")
        with patch.dict(os.environ, {}, clear=True), patch.object(
            beacon_integration, "_capture", return_value=nullcontext(recorder)
        ), patch.object(beacon_integration, "_install_model_observer"):
            with self.assertRaises(SystemExit) as stopped:
                beacon_integration.main(["test", "code", "raise SystemExit(23)"])
            self.assertEqual(stopped.exception.code, 23)

    def test_dashboard_open_is_explicit_even_on_mac(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch.object(
            eval_dashboard_html.sys, "platform", "darwin"
        ), patch.object(eval_dashboard_html.subprocess, "run") as launch:
            self.assertFalse(eval_dashboard_html.open_dashboard(Path("report.html")))
            launch.assert_not_called()
            os.environ["LINKEDIN_OS_OPEN_REPORT"] = "1"
            launch.return_value.returncode = 0
            self.assertTrue(eval_dashboard_html.open_dashboard(Path("report.html")))
            launch.assert_called_once()


if __name__ == "__main__":
    unittest.main()
