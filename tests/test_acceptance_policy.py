"""Contract tests for the single five-axis draft acceptance decision."""

from __future__ import annotations

import unittest
from pathlib import Path

from authority_os import acceptance_policy


def scorecard(
    hook: int,
    middle: int,
    closer: int,
    specificity: int,
    voice: int,
) -> dict[str, int]:
    axes = {
        "hook_strength": hook,
        "middle_escalation": middle,
        "earned_closer": closer,
        "specificity_and_source_quality": specificity,
        "voice_fidelity": voice,
    }
    return {**axes, "effective_total": sum(axes.values())}


class AcceptancePolicyTests(unittest.TestCase):
    def test_named_owner_boundaries(self) -> None:
        cases = (
            ((5, 4, 4, 4, 4), True),
            ((5, 3, 3, 3, 4), True),
            ((4, 1, 4, 5, 4), True),
            ((5, 4, 4, 4, 2), False),
            ((4, 4, 4, 4, 2), False),
        )
        for scores, expected in cases:
            with self.subTest(scores=scores):
                self.assertIs(
                    acceptance_policy.scorecard_is_acceptable(
                        scorecard(*scores), hard_gates_pass=True
                    ),
                    expected,
                )

    def test_perfect_score_never_offsets_a_failed_hard_gate(self) -> None:
        self.assertFalse(
            acceptance_policy.scorecard_is_acceptable(
                scorecard(5, 5, 5, 5, 5), hard_gates_pass=False
            )
        )

    def test_unsupported_factual_wording_is_advisory_only_after_rewrite(self) -> None:
        gates = {
            "authority_conversion": "PASS",
            "proof": "NOT_REQUIRED",
            "honesty": "FAIL",
            "citation": "FAIL",
            "relevance": "PASS",
        }
        reasons = ("unsupported-factual-marker",)
        self.assertFalse(
            acceptance_policy.hard_candidate_gates_pass(
                gates,
                passes_required_gates=False,
                reason_codes=reasons,
            )
        )
        self.assertTrue(
            acceptance_policy.hard_candidate_gates_pass(
                gates,
                passes_required_gates=False,
                reason_codes=reasons,
                allow_factual_wording_advisory=True,
            )
        )

    def test_mixed_factual_failure_never_becomes_advisory(self) -> None:
        gates = {
            "authority_conversion": "PASS",
            "proof": "NOT_REQUIRED",
            "honesty": "FAIL",
            "citation": "FAIL",
            "relevance": "PASS",
        }
        self.assertFalse(
            acceptance_policy.hard_candidate_gates_pass(
                gates,
                passes_required_gates=False,
                reason_codes=("unsupported-factual-marker", "untraceable-incident"),
                allow_factual_wording_advisory=True,
            )
        )

    def test_record_names_every_axis_shortfall_and_total_deficit(self) -> None:
        decision = acceptance_policy.acceptance_decision(
            scorecard(3, 2, 2, 3, 3), hard_gates_pass=True
        )
        self.assertEqual(decision["status"], "FAIL")
        self.assertEqual(decision["total_shortfall"], 5)
        self.assertEqual(
            set(decision["axis_shortfalls"]),
            {"hook_strength", "voice_fidelity"},
        )
        self.assertEqual(
            decision["axis_shortfalls"]["voice_fidelity"]["shortfall"], 1
        )

    def test_eighteen_is_the_only_total_boundary(self) -> None:
        self.assertFalse(hasattr(acceptance_policy, "QUALITY_TARGET"))
        decision = acceptance_policy.acceptance_decision(
            scorecard(5, 3, 3, 3, 4), hard_gates_pass=True
        )
        self.assertEqual(decision["effective_total"], 18)
        self.assertEqual(decision["status"], "PASS")

    def test_downstream_consumers_do_not_restore_legacy_band_eligibility(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "authority_os"
        for name in ("package.py", "performance.py", "learning.py", "campaign.py"):
            with self.subTest(module=name):
                source = (root / name).read_text(encoding="utf-8")
                self.assertNotIn('["band"] == "advance-to-gates"', source)
                self.assertNotIn("MIN_SCORE = 24", source)
                self.assertNotIn("MIN_COMMENT_SCORE = 24", source)

    def test_monitoring_uses_live_v2_rubric(self) -> None:
        root = Path(__file__).resolve().parents[1] / "src" / "authority_os"
        source = (root / "monitoring_export.py").read_text(encoding="utf-8")
        self.assertIn("critic-rubric-v2.json", source)
        self.assertNotIn("critic-rubric-v1.json", source)


if __name__ == "__main__":
    unittest.main()
