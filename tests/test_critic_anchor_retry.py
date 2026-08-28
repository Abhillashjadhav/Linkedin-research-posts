from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import critic_anchor_retry, workflow


class CriticAnchorRetryTests(unittest.TestCase):
    def test_exact_excerpt_failure_retries_once_on_same_candidates(self) -> None:
        candidates = [{"id": "candidate-1", "text": "Exact candidate text."}]
        seen: list[object] = []

        def provider(items):
            seen.append(items)
            if len(seen) == 1:
                raise workflow.WorkflowError(
                    "Critic anchor evidence must be an exact excerpt from the candidate."
                )
            return [{"candidate_id": "candidate-1"}]

        wrapped = critic_anchor_retry._retry_score_provider(provider)  # type: ignore[attr-defined]
        result = wrapped(candidates)

        self.assertEqual(result, [{"candidate_id": "candidate-1"}])
        self.assertEqual(len(seen), 2)
        self.assertIs(seen[0], candidates)
        self.assertIs(seen[1], candidates)

    def test_second_anchor_failure_still_fails_closed(self) -> None:
        calls = 0

        def provider(_items):
            nonlocal calls
            calls += 1
            raise workflow.WorkflowError(
                "Critic anchor evidence must be an exact excerpt from the candidate."
            )

        wrapped = critic_anchor_retry._retry_score_provider(provider)  # type: ignore[attr-defined]
        with self.assertRaisesRegex(workflow.WorkflowError, "exact excerpt"):
            wrapped([{"id": "candidate-1"}])
        self.assertEqual(calls, 2)

    def test_unrelated_workflow_error_is_not_retried(self) -> None:
        calls = 0

        def provider(_items):
            nonlocal calls
            calls += 1
            raise workflow.WorkflowError("Research evidence is unavailable.")

        wrapped = critic_anchor_retry._retry_score_provider(provider)  # type: ignore[attr-defined]
        with self.assertRaisesRegex(workflow.WorkflowError, "Research evidence"):
            wrapped([{"id": "candidate-1"}])
        self.assertEqual(calls, 1)

    def test_review_wrapper_retries_only_score_provider_not_writer_or_editor(self) -> None:
        candidates = [{"id": "candidate-1", "text": "Exact candidate text."}]
        provider_calls = 0
        review_calls = 0

        def provider(items):
            nonlocal provider_calls
            provider_calls += 1
            self.assertIs(items, candidates)
            if provider_calls == 1:
                raise workflow.WorkflowError(
                    "Critic anchor evidence must be an exact excerpt from the candidate."
                )
            return [{"candidate_id": "candidate-1"}]

        def fake_review(items, _brief, _evidence, score_provider, _revision_provider, *, proof=None):
            nonlocal review_calls
            review_calls += 1
            self.assertIs(items, candidates)
            self.assertIsNone(proof)
            return score_provider(items)

        with patch.object(
            critic_anchor_retry,
            "_ORIGINAL_RUN_CRITIC_REVIEW",
            side_effect=fake_review,
        ):
            result = critic_anchor_retry._run_critic_review(  # type: ignore[attr-defined]
                candidates,
                {},
                [],
                provider,
                lambda *_args: {},
            )

        self.assertEqual(result, [{"candidate_id": "candidate-1"}])
        self.assertEqual(review_calls, 1)
        self.assertEqual(provider_calls, 2)

    def test_prompt_requires_character_for_character_contiguous_copy(self) -> None:
        prompt = critic_anchor_retry._strict_critic_system_prompt()  # type: ignore[attr-defined]
        self.assertIn("character-for-character", prompt)
        self.assertIn("contiguous substring", prompt)
        self.assertIn("Do not paraphrase", prompt)
        self.assertIn("insert ellipses", prompt)


class CriticAnchorRetryWiringTests(unittest.TestCase):
    def test_live_launcher_installs_after_human_readability(self) -> None:
        root = Path(__file__).resolve().parents[1]
        launcher = (root / "bin" / "linkedin-os").read_text(encoding="utf-8")
        human = launcher.index("human_readability.install()")
        retry = launcher.index("critic_anchor_retry.install()")
        optimizer = launcher.index("quality_optimizer.install()")
        self.assertLess(human, retry)
        self.assertLess(retry, optimizer)
        self.assertEqual(launcher.count("critic_anchor_retry.install()"), 1)

    def test_comparison_installs_retry_only_inside_v1_path(self) -> None:
        root = Path(__file__).resolve().parents[1]
        capture = (root / "scripts" / "compare_capture_runtime.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('if args.label == "v1":', capture)
        self.assertEqual(capture.count("critic_anchor_retry.install()"), 1)
        self.assertLess(
            capture.index("human_readability.install()"),
            capture.index("critic_anchor_retry.install()"),
        )


if __name__ == "__main__":
    unittest.main()
