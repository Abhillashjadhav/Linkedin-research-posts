from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from authority_os import eval_dashboard_html


class EvalDashboardHtmlTests(unittest.TestCase):
    def test_empty_scorecard_says_drafting_stopped_before_critic(self) -> None:
        rendered = eval_dashboard_html.render_dashboard(
            {
                "outcome": "FAIL",
                "checks": [
                    {
                        "stage": "drafting",
                        "label": "High-bar drafting",
                        "status": "FAIL",
                        "reason": "ERROR: writer failed",
                    }
                ],
            },
            {"checks": [], "critic_scorecards": []},
        )
        self.assertIn(
            "Drafting stopped before the Critic ran. See FIRST BLOCKER.",
            rendered,
        )
        self.assertNotIn("The Critic ran but", rendered)

    def test_empty_scorecard_says_critic_returned_no_valid_scorecard(self) -> None:
        rendered = eval_dashboard_html.render_dashboard(
            {
                "outcome": "FAIL",
                "checks": [
                    {
                        "stage": "drafting",
                        "label": "High-bar drafting",
                        "status": "PASS",
                        "reason": "draft candidates reached evaluation",
                    }
                ],
            },
            {"checks": [], "critic_scorecards": []},
        )
        self.assertIn(
            "The Critic ran but returned no valid 1–5 scorecard.",
            rendered,
        )

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

    def test_render_shows_execution_identity_and_complete_decision_trace(self) -> None:
        rendered = eval_dashboard_html.render_dashboard(
            {
                "run_id": "linkedin-observed-run",
                "outcome": "FAIL",
                "execution": {
                    "commit": "f6d5fce397ce108d482132edb6c15acc9195dba3",
                    "branch": "main",
                    "dirty": False,
                    "observability_contract": "decision-trace-v1",
                },
                "decisions": [
                    {
                        "stage": "topic_value",
                        "decision": "candidate clears Topic Value",
                        "status": "REJECTED",
                        "expected": "reader relevance >= 4",
                        "observed": "reader relevance = 3",
                        "reason": "reader relevance missed the floor",
                        "subject_id": "topic-2",
                        "artifact": "data/private/run/topic-value-evaluations.json",
                    }
                ],
                "checks": [],
            },
            {"checks": [], "decisions": []},
        )

        for expected in (
            "Exact code that ran",
            "f6d5fce397ce108d482132edb6c15acc9195dba3",
            "decision-trace-v1",
            "Expected rule, observed value, and exact reason",
            "reader relevance &gt;= 4",
            "reader relevance = 3",
            "topic-2",
            "REJECTED",
        ):
            self.assertIn(expected, rendered)

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

    def test_render_surfaces_scout_reasons_baseline_versions_and_post_quality(self) -> None:
        rendered = eval_dashboard_html.render_dashboard(
            {
                "run_id": "linkedin-current",
                "outcome": "FAIL",
                "surface_scouts": [
                    {"label": "Reddit", "status": "OBSERVED", "reason_code": "evidence-returned", "reason": "Public evidence only.", "signal_count": 5},
                    {"label": "YouTube", "status": "UNAVAILABLE", "reason_code": "timeout", "reason": "Timed out.", "signal_count": 0},
                ],
                "baseline": [
                    {"run_id": "linkedin-prior", "outcome": "PASS", "stopped_at": None, "passed_stages": 7}
                ],
                "evaluator_versions": {
                    "linkedin_os": "6.0.0",
                    "models": {"critic": {"model": "gpt-test", "reasoning": "high"}},
                    "rubrics": {"critic-rubric-v1.json": "abc123"},
                },
                "checks": [],
            },
            {
                "checks": [
                    {"contract": "hook_strength", "category": "post_quality", "label": "hook strength", "status": "PASS", "reason": "hook-strength-5-of-5"}
                ],
                "critic_scorecards": [
                    {
                        "cycle": 2,
                        "candidate_id": "candidate-3",
                        "status": "PASS",
                        "total": 24,
                        "band": "advance-to-gates",
                        "hook_cap_applied": False,
                        "axes": {
                            "hook_strength": 5,
                            "middle_escalation": 5,
                            "earned_closer": 5,
                            "specificity_and_source_quality": 5,
                            "voice_fidelity": 4,
                        },
                        "failure_codes": ["package-recommendation-mismatch"],
                    }
                ],
            },
        )
        for expected in (
            "Reddit",
            "YouTube",
            "timeout",
            "5 usable signal",
            "linkedin-prior",
            "gpt-test",
            "abc123",
            "Diagnostics and enforced post checks",
            "hook-strength-5-of-5",
            "Diagnostic scores for every candidate",
            "candidate-3",
            "24/25",
            "advance-to-gates",
            "DIAGNOSTIC",
            "package-recommendation-mismatch",
        ):
            self.assertIn(expected, rendered)


if __name__ == "__main__":
    unittest.main()
