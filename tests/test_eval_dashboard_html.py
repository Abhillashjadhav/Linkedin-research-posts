from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from authority_os import eval_dashboard_html


class EvalDashboardHtmlTests(unittest.TestCase):
    def test_render_names_first_blocker_and_keeps_missing_checks_visible(self) -> None:
        rendered = eval_dashboard_html.render_dashboard(
            {
                "run_id": "linkedin-test-run",
                "outcome": "FAIL",
                "checks": [
                    {"stage": "drafting", "label": "Drafting", "status": "PASS", "reason": "generated"},
                    {"stage": "final_evals", "label": "Final evals", "status": "FAIL", "reason": "anti-slop failed"},
                ],
            },
            {
                "run_id": "linkedin-test-run",
                "checks": [
                    {"contract": "reader_attention", "label": "reader attention", "status": "NOT_EVALUATED", "reason": "stage was not reached"}
                ],
            },
        )
        self.assertIn("Final evals", rendered)
        self.assertIn("anti-slop failed", rendered)
        self.assertIn("NOT_EVALUATED", rendered)
        self.assertIn("linkedin-test-run", rendered)

    def test_render_escapes_run_content(self) -> None:
        rendered = eval_dashboard_html.render_dashboard(
            {"run_id": "<script>alert(1)</script>", "outcome": "FAIL", "checks": []},
            {"checks": []},
        )
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)

    def test_open_is_disabled_outside_macos(self) -> None:
        with patch.object(eval_dashboard_html.sys, "platform", "linux"):
            self.assertFalse(eval_dashboard_html.open_dashboard(Path("dashboard.html")))


if __name__ == "__main__":
    unittest.main()
