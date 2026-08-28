from __future__ import annotations

import unittest

from authority_os import campaign, quality_cli, v1_runtime_tuning, workflow


class V1RuntimeTuningTests(unittest.TestCase):
    def test_human_review_gates_are_not_repair_failures(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-1",
            angle="mechanism",
            text="Hook with XX% placeholder.",
            axes={axis: 4 for axis in workflow.CRITIC_AXES},
            raw_total=20,
            effective_total=20,
            band="below-critic-bar",
            gates={
                "authority_conversion": "PASS",
                "proof": "NOT_REQUIRED",
                "honesty": "HUMAN_REVIEW",
                "citation": "HUMAN_REVIEW",
                "relevance": "PASS",
            },
            passes_required_gates=True,
            gate_reasons=("unsupported-factual-marker",),
        )
        self.assertEqual(v1_runtime_tuning._failed_gates_only(candidate), {})

    def test_literal_hard_failure_remains_repair_work(self) -> None:
        candidate = quality_cli.CandidateResult(
            candidate_id="candidate-1",
            angle="mechanism",
            text="Off-strategy draft.",
            axes={axis: 5 for axis in workflow.CRITIC_AXES},
            raw_total=25,
            effective_total=25,
            band="advance-to-gates",
            gates={
                "authority_conversion": "PASS",
                "proof": "NOT_REQUIRED",
                "honesty": "HUMAN_REVIEW",
                "citation": "HUMAN_REVIEW",
                "relevance": "FAIL",
            },
            passes_required_gates=False,
            gate_reasons=("target-reader-not-reflected",),
        )
        self.assertEqual(v1_runtime_tuning._failed_gates_only(candidate), {"relevance": "FAIL"})

    def test_generation_stays_high_while_critic_uses_max(self) -> None:
        models = v1_runtime_tuning._preferred_fast_single_topic(campaign.StageModels)
        self.assertEqual(models.writer.reasoning, "high")
        self.assertEqual(models.narrative_editor.reasoning, "high")
        self.assertEqual(models.critic.reasoning, "max")

    def test_selector_and_resonance_use_max_not_ultra(self) -> None:
        topic_config = v1_runtime_tuning._selection_model_config("codex", "gpt-5.6-sol", "ultra")
        resonance_config = v1_runtime_tuning._selection_model_config("codex", "gpt-5.6-sol", "max")
        already_high = v1_runtime_tuning._selection_model_config("codex", "gpt-5.6-sol", "high")
        self.assertEqual(topic_config.reasoning, "max")
        self.assertEqual(resonance_config.reasoning, "max")
        self.assertEqual(already_high.reasoning, "high")


if __name__ == "__main__":
    unittest.main()
