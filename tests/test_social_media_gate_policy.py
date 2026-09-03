from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import quality_cli, social_media_gate_policy, workflow


class SocialMediaGatePolicyTests(unittest.TestCase):
    def test_package_gate_result_uses_the_same_advisory_policy(self) -> None:
        softened = social_media_gate_policy.soften_gate_result(
            {
                "candidate_id": "candidate-1",
                "gates": {
                    "authority_conversion": "PASS",
                    "honesty": "FAIL",
                    "citation": "FAIL",
                    "relevance": "PASS",
                },
                "passes_required_gates": False,
            }
        )
        self.assertEqual(softened["gates"]["honesty"], "HUMAN_REVIEW")  # type: ignore[index]
        self.assertEqual(softened["gates"]["citation"], "HUMAN_REVIEW")  # type: ignore[index]
        self.assertIs(softened["passes_required_gates"], True)

    def test_package_gate_result_preserves_a_real_hard_failure(self) -> None:
        softened = social_media_gate_policy.soften_gate_result(
            {
                "gates": {"authority_conversion": "FAIL", "honesty": "FAIL"},
                "passes_required_gates": False,
            }
        )
        self.assertEqual(softened["gates"]["honesty"], "HUMAN_REVIEW")  # type: ignore[index]
        self.assertIs(softened["passes_required_gates"], False)

    def test_honesty_and_citation_failures_become_human_review(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-1",
            angle="mechanism",
            text="A strongly worded but human-reviewed social post.",
            axes={
                "hook_strength": 5,
                "middle_escalation": 4,
                "earned_closer": 4,
                "specificity_and_source_quality": 4,
                "voice_fidelity": 5,
            },
            raw_total=22,
            effective_total=22,
            band="one-light-revision",
            gates={
                "authority_conversion": "PASS",
                "proof": "NOT_REQUIRED",
                "honesty": "FAIL",
                "citation": "FAIL",
                "relevance": "PASS",
            },
            passes_required_gates=False,
            gate_reasons=("unsupported-factual-marker",),
        )
        softened = social_media_gate_policy._soften_candidate(candidate)  # type: ignore[attr-defined]
        self.assertEqual(softened.gates["honesty"], "HUMAN_REVIEW")
        self.assertEqual(softened.gates["citation"], "HUMAN_REVIEW")
        self.assertTrue(softened.passes_required_gates)
        self.assertEqual(softened.gate_reasons, candidate.gate_reasons)

    def test_other_hard_gate_failures_still_block(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-1",
            angle="mechanism",
            text="Off-strategy post.",
            axes={axis: 5 for axis in workflow.CRITIC_AXES},
            raw_total=25,
            effective_total=25,
            band="advance-to-gates",
            gates={
                "authority_conversion": "FAIL",
                "proof": "NOT_REQUIRED",
                "honesty": "FAIL",
                "citation": "FAIL",
                "relevance": "PASS",
            },
            passes_required_gates=False,
            gate_reasons=("product-decision-not-reflected", "unsupported-factual-marker"),
        )
        softened = social_media_gate_policy._soften_candidate(candidate)  # type: ignore[attr-defined]
        self.assertEqual(softened.gates["authority_conversion"], "FAIL")
        self.assertEqual(softened.gates["honesty"], "HUMAN_REVIEW")
        self.assertEqual(softened.gates["citation"], "HUMAN_REVIEW")
        self.assertFalse(softened.passes_required_gates)

    def test_writer_policy_allows_explicit_xx_placeholders_without_inventing_numbers(self) -> None:
        with patch.object(
            social_media_gate_policy,
            "_ORIGINAL_BUILD_WRITER_PROMPT",
            return_value="BASE WRITER PROMPT",
        ):
            prompt = social_media_gate_policy._build_writer_prompt_social()  # type: ignore[attr-defined]
        self.assertIn("XX%", prompt)
        self.assertIn("XXx", prompt)
        self.assertIn("human reviewer", prompt.casefold())
        self.assertIn("never silently substitute a fabricated number", prompt.casefold())


if __name__ == "__main__":
    unittest.main()
