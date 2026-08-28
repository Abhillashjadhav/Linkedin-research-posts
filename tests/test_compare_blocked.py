from __future__ import annotations

import unittest
from pathlib import Path

from authority_os import compare_versions_blocked


class CompareBlockedTests(unittest.TestCase):
    def _payload(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "label": "v0",
            "exit_code": 2,
            "cycles": [
                {
                    "cycle": 1,
                    "limit": 4,
                    "outcome": "REJECTED",
                    "accepted_candidate_ids": [],
                    "candidates": [
                        {
                            "candidate_id": "candidate-3",
                            "angle": "state handoff",
                            "text": "The model looked right. The handoff was wrong.",
                            "axes": {
                                "hook_strength": 5,
                                "middle_escalation": 5,
                                "earned_closer": 5,
                                "specificity_and_source_quality": 5,
                                "voice_fidelity": 5,
                            },
                            "raw_total": 25,
                            "effective_total": 25,
                            "band": "advance-to-gates",
                            "gates": {
                                "factual_grounding": "FAIL",
                                "voice": "PASS",
                            },
                            "passes_required_gates": False,
                            "gate_reasons": ["claim-not-supported"],
                        }
                    ],
                    "feedback": {
                        "rejected_cycle": 1,
                        "required_next_action": "preserve evidence boundaries",
                    },
                }
            ],
        }

    def test_nonzero_with_captured_quality_cycles_is_a_block_not_infrastructure_error(self) -> None:
        status = compare_versions_blocked.classify_draft_result(
            2,
            "ERROR: No candidate cleared the locked quality bar",
            self._payload(),
        )
        self.assertEqual(status, "BLOCKED")

    def test_unknown_nonzero_without_product_evidence_is_an_error(self) -> None:
        status = compare_versions_blocked.classify_draft_result(
            2,
            "ERROR: provider executable failed unexpectedly",
            {"schema_version": 1, "cycles": []},
        )
        self.assertEqual(status, "ERROR")

    def test_attempt_markdown_preserves_rejected_text_and_gate_attribution(self) -> None:
        markdown = compare_versions_blocked.render_attempts_markdown(
            self._payload(), label="v0"
        )
        self.assertIn("Cycle 1", markdown)
        self.assertIn("candidate-3", markdown)
        self.assertIn("effective=25", markdown)
        self.assertIn("factual_grounding=FAIL", markdown)
        self.assertIn("claim-not-supported", markdown)
        self.assertIn("The model looked right. The handoff was wrong.", markdown)
        self.assertIn("A rejected candidate remains rejected", markdown)

    def test_manifest_represents_blocked_and_passed_versions_without_declaring_winner(self) -> None:
        runs = (
            compare_versions_blocked.CapturedVersionRun(
                label="v0",
                ref="baseline/v0-pre-eval-v1",
                commit_sha="a" * 40,
                status="BLOCKED",
                exit_code=2,
                package_source=None,
                recommendation=None,
                score_lines=(
                    "cycle 1 best=candidate-3; effective=25/25; required_gates=fail",
                ),
                attempts_path="attempts.md",
                output_dir=Path("v0"),
            ),
            compare_versions_blocked.CapturedVersionRun(
                label="v1",
                ref="main",
                commit_sha="b" * 40,
                status="PASS",
                exit_code=0,
                package_source="outputs/v1",
                recommendation="candidate-1",
                score_lines=(
                    "cycle 1 best=candidate-1; effective=25/25; required_gates=pass",
                ),
                attempts_path="attempts.md",
                output_dir=Path("v1"),
            ),
        )
        manifest = compare_versions_blocked.build_manifest(
            run_id="20260828T000000Z",
            topic="Production Engineering OS",
            goal="authority",
            output_format="text",
            research_sha256="c" * 64,
            strategy_sha256="d" * 64,
            proof_sha256=None,
            versions=runs,
        )
        self.assertEqual(manifest["schema_version"], 2)
        self.assertIsNone(manifest["winner"])
        versions = manifest["versions"]
        self.assertEqual(versions[0]["status"], "BLOCKED")  # type: ignore[index]
        self.assertIsNone(versions[0]["package_source"])  # type: ignore[index]
        markdown = compare_versions_blocked.render_comparison_markdown(manifest)
        self.assertIn("V0", markdown)
        self.assertIn("BLOCKED", markdown)
        self.assertIn("v0/attempts.md", markdown)
        self.assertNotIn("v0/package/candidates.md", markdown)
        self.assertIn("v1/package/candidates.md", markdown)
        self.assertIn("No automatic quality winner", markdown)


if __name__ == "__main__":
    unittest.main()
