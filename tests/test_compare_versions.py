from __future__ import annotations

import unittest
from pathlib import Path

from authority_os import compare_versions


class CompareVersionsTests(unittest.TestCase):
    def test_draft_command_preserves_shared_inputs_and_never_publishes(self) -> None:
        command = compare_versions.build_draft_command(
            topic="agent reliability",
            goal="authority",
            private_strategy="data/private/comparison-input/strategy.json",
            output_format="text",
            week_slot=2,
            strong_current_signal=True,
        )
        self.assertEqual(command[0:2], ("./bin/linkedin-os", "draft"))
        self.assertIn("--allow-model-egress", command)
        self.assertIn("--package", command)
        self.assertIn("--strategy-input", command)
        self.assertIn("--strong-current-signal", command)
        self.assertNotIn("publish", " ".join(command).casefold())
        self.assertNotIn("record-performance", command)

    def test_research_command_uses_exact_same_topic_and_private_file(self) -> None:
        command = compare_versions.build_research_command(
            topic="agent reliability",
            private_research="data/private/comparison-input/research.json",
        )
        self.assertEqual(
            command,
            (
                "./bin/linkedin-os",
                "research",
                "--input",
                "data/private/comparison-input/research.json",
                "--topic",
                "agent reliability",
            ),
        )

    def test_package_path_must_be_single_relative_safe_path(self) -> None:
        stdout = "Content package: outputs/2026-08-28-example\n"
        self.assertEqual(
            compare_versions.extract_package_path(stdout),
            "outputs/2026-08-28-example",
        )
        with self.assertRaises(compare_versions.ComparisonError):
            compare_versions.extract_package_path("Content package: /tmp/escape\n")
        with self.assertRaises(compare_versions.ComparisonError):
            compare_versions.extract_package_path(
                "Content package: outputs/one\nContent package: outputs/two\n"
            )

    def test_draft_summary_parses_recommendation_and_critic_lines(self) -> None:
        stdout = (
            "Critic score: id=candidate-1; hook_strength=5,middle_escalation=4,"
            "earned_closer=4,specificity_and_source_quality=5,voice_fidelity=5; "
            "raw_total=23; effective_total=23; band=one-light-revision.\n"
            "Recommended candidate for human review: candidate-1\n"
        )
        recommendation, scores = compare_versions.summarize_draft_log(stdout)
        self.assertEqual(recommendation, "candidate-1")
        self.assertEqual(len(scores), 1)
        self.assertIn("candidate-1", scores[0])
        self.assertIn("raw=23", scores[0])

    def test_manifest_never_auto_declares_a_winner(self) -> None:
        runs = (
            compare_versions.VersionRun(
                label="v0",
                ref="baseline/v0-pre-eval-v1",
                commit_sha="a" * 40,
                package_source="outputs/v0",
                recommendation="candidate-1",
                score_lines=("candidate-1: raw=24",),
                output_dir=Path("v0"),
            ),
            compare_versions.VersionRun(
                label="v1",
                ref="main",
                commit_sha="b" * 40,
                package_source="outputs/v1",
                recommendation="candidate-2",
                score_lines=("candidate-2: raw=25",),
                output_dir=Path("v1"),
            ),
        )
        manifest = compare_versions.build_manifest(
            run_id="20260828T000000Z",
            topic="agent reliability",
            goal="authority",
            output_format="text",
            research_sha256="c" * 64,
            strategy_sha256="d" * 64,
            proof_sha256=None,
            versions=runs,
        )
        self.assertIsNone(manifest["winner"])
        self.assertEqual(
            manifest["winner_policy"], "human-product-review-required"
        )
        markdown = compare_versions.render_comparison_markdown(manifest)
        self.assertIn("v0/package/candidates.md", markdown)
        self.assertIn("v1/package/candidates.md", markdown)
        self.assertIn("No automatic winner", markdown)

    def test_parser_defaults_to_frozen_v0_and_current_main(self) -> None:
        args = compare_versions.build_parser().parse_args(
            [
                "--research",
                "research.json",
                "--strategy",
                "strategy.json",
                "--topic",
                "agent reliability",
            ]
        )
        self.assertEqual(args.v0_ref, "baseline/v0-pre-eval-v1")
        self.assertEqual(args.v1_ref, "main")
        self.assertEqual(args.goal, "authority")


if __name__ == "__main__":
    unittest.main()
