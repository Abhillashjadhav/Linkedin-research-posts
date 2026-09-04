"""Regression tests for the integrated anti-slop draft gate."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import anti_slop, integrated_cli, quality_cli


class AntiSlopAuditTests(unittest.TestCase):
    def test_clean_human_copy_passes(self) -> None:
        text = (
            "OpenAI found that most health questions appeared outside its Health area.\n\n"
            "That changes the product architecture. Sensitive context can appear in any flow, "
            "so permission checks and scoped access need to work across the product."
        )
        self.assertEqual(anti_slop.audit(text), ())

    def test_named_patterns_fail_with_checkable_excerpts(self) -> None:
        cases = {
            "binary": "This is not a model problem. It is an evaluation problem.",
            "throat": "Here's the thing: teams keep missing the evidence.",
            "faux": "What most people miss is the permission boundary.",
            "puffery": "This marks a pivotal moment for AI products.",
            "fragments": "Detect.\nAsk.\nLimit.\nEscalate.",
        }
        for name, text in cases.items():
            with self.subTest(name=name):
                findings = anti_slop.audit(text)
                self.assertTrue(findings)
                self.assertTrue(all(finding.code and isinstance(finding.excerpt, str) for finding in findings))

    def test_harness_is_allowed_as_a_technical_noun_but_not_as_hype(self) -> None:
        self.assertEqual(
            anti_slop.audit("A harness controls what the model can remember and do."),
            (),
        )
        findings = anti_slop.audit("Harness the power of AI for your business.")
        self.assertEqual([finding.code for finding in findings], ["hype-harness"])


class IntegratedGateTests(unittest.TestCase):
    def candidate(self, text: str) -> SimpleNamespace:
        return SimpleNamespace(candidate_id="candidate-1", text=text)

    def test_sloppy_candidate_cannot_clear_existing_quality_gate(self) -> None:
        sloppy = self.candidate("Here's the thing: this changes everything.")
        clean = self.candidate("The permission boundary belongs underneath every product flow.")
        with patch.object(quality_cli, "_qualifying_candidates", return_value=(sloppy, clean)):
            # Re-importing is unnecessary; call the integrated wrapper directly with its saved original patched.
            original = integrated_cli._original_qualifying
            try:
                integrated_cli._original_qualifying = quality_cli._qualifying_candidates
                accepted = integrated_cli._qualifying_candidates(
                    object(),
                    rejected_openings=set(),
                    package_requested=False,
                    fixture_mode=True,
                )
            finally:
                integrated_cli._original_qualifying = original
        self.assertEqual(accepted, (clean,))
        self.assertTrue(
            all(
                reason.startswith("anti-slop:")
                for reason in integrated_cli._active_acceptance_diagnostics["candidate-1"]
            )
        )

    def test_retry_feedback_contains_named_slop_findings(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-1",
            angle="decision",
            text="What most people miss is the safety layer.",
            axes={"hook_strength": 5},
            raw_total=24,
            effective_total=24,
            band="advance-to-gates",
            gates={},
            passes_required_gates=True,
            gate_reasons=(),
        )
        attempt = quality_cli.AttemptResult(
            candidates=(candidate,),
            context_lines=(),
            review_status=None,
            recommendation=None,
            package_lines=(),
        )
        with patch.object(
            integrated_cli,
            "_original_feedback",
            return_value={"rejected_candidates": [{"candidate_id": "candidate-1"}]},
        ):
            feedback = integrated_cli._quality_feedback(attempt, 1)
        findings = feedback["rejected_candidates"][0]["anti_slop_findings"]
        self.assertEqual(findings[0]["code"], "faux-insight")
        self.assertIs(feedback["anti_slop_required"], True)

    def test_package_mismatch_diagnostic_names_both_exact_conditions(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-3",
            angle="decision",
            text="A grounded candidate.",
            axes={
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 5,
            },
            raw_total=25,
            effective_total=25,
            band="advance-to-gates",
            gates={"honesty": "HUMAN_REVIEW", "citation": "HUMAN_REVIEW"},
            passes_required_gates=True,
            gate_reasons=(),
        )
        attempt = quality_cli.AttemptResult(
            candidates=(candidate,),
            context_lines=(),
            review_status="BLOCKED",
            recommendation=None,
            package_lines=(),
        )
        reasons = integrated_cli._pre_acceptance_failures(  # type: ignore[attr-defined]
            candidate,
            attempt,
            {"package_requested": True, "fixture_mode": False},
        )
        self.assertEqual(
            reasons,
            [
                "package-review-status:BLOCKED",
                "package-recommendation:none!=candidate:candidate-3",
            ],
        )

    def test_post_quality_records_every_axis_and_anti_slop(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-3",
            angle="decision",
            text="A grounded candidate with a clear reader decision.",
            axes={
                "hook_strength": 5,
                "middle_escalation": 5,
                "earned_closer": 5,
                "specificity_and_source_quality": 5,
                "voice_fidelity": 4,
            },
            raw_total=24,
            effective_total=24,
            band="advance-to-gates",
            gates={},
            passes_required_gates=True,
            gate_reasons=(),
        )
        with patch.object(integrated_cli.v1_completion, "record_decision") as record:
            integrated_cli._record_post_quality(candidate)  # type: ignore[attr-defined]
        contracts = [call.args[0]["contract"] for call in record.call_args_list]
        self.assertEqual(
            contracts,
            [
                "hook_strength",
                "middle_escalation",
                "earned_closer",
                "specificity_and_source_quality",
                "voice_fidelity",
                "anti_slop",
            ],
        )


if __name__ == "__main__":
    unittest.main()
