from __future__ import annotations

import unittest

from authority_os import quality_cli, social_media_gate_policy


class SocialMediaGatePolicyTests(unittest.TestCase):
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
            axes={axis: 5 for axis in (
                "hook_strength",
                "middle_escalation",
                "earned_closer",
                "specificity_and_source_quality",
                "voice_fidelity",
            )},
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


if __name__ == "__main__":
    unittest.main()
