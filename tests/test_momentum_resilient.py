"""Regression tests for adaptive momentum enrichment."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from authority_os import momentum_resilient, workflow


def seeds() -> list[dict[str, str]]:
    return [
        {
            "id": f"topic-{index}",
            "topic": f"Conversation {index}",
            "why_now": "Active now.",
        }
        for index in range(1, 11)
    ]


def enriched(seed: dict[str, str]) -> dict[str, object]:
    return {**seed, "enriched": True}


class AdaptiveMomentumTests(unittest.TestCase):
    def test_invoke_scout_starts_with_two_topic_batches_and_prints_progress(self) -> None:
        topic_seeds = seeds()
        batches = [
            [enriched(seed) for seed in topic_seeds[offset : offset + 2]]
            for offset in range(0, 10, 2)
        ]
        output = io.StringIO()
        with patch.object(
            momentum_resilient.base,
            "discover_topics",
            return_value=topic_seeds,
        ), patch.object(
            momentum_resilient.base,
            "research_batch",
            side_effect=batches,
        ) as research, patch.object(
            momentum_resilient.base.base,
            "validate_candidates",
            side_effect=lambda value: value,
        ), redirect_stdout(output):
            result = momentum_resilient.invoke_scout(
                None, 7, "2026-08-18T00:00:00Z"
            )

        self.assertEqual(research.call_count, 5)
        self.assertEqual([item["id"] for item in result], [f"topic-{i}" for i in range(1, 11)])
        rendered = output.getvalue()
        self.assertIn("discovering 10 candidate conversations", rendered)
        self.assertIn("researching topic-1, topic-2", rendered)
        self.assertIn("all 10 topics enriched", rendered)

    def test_timeout_splits_a_multi_topic_batch_and_continues(self) -> None:
        pair = seeds()[:2]
        with patch.object(
            momentum_resilient.base,
            "research_batch",
            side_effect=[
                workflow.WorkflowError("Momentum research batch 1 timed out."),
                [enriched(pair[0])],
                [enriched(pair[1])],
            ],
        ) as research:
            result = momentum_resilient._research_adaptive(
                pair,
                days=7,
                as_of="2026-08-18T00:00:00Z",
                label="1/5",
            )

        self.assertEqual(research.call_count, 3)
        self.assertEqual([item["id"] for item in result], ["topic-1", "topic-2"])

    def test_single_topic_timeout_is_left_unranked_without_fabricating_zero(self) -> None:
        output = io.StringIO()
        with patch.object(
            momentum_resilient.base,
            "research_batch",
            side_effect=workflow.WorkflowError("Momentum research batch 1a timed out."),
        ), redirect_stdout(output):
            result = momentum_resilient._research_adaptive(
                seeds()[:1],
                days=7,
                as_of="2026-08-18T00:00:00Z",
                label="1/5a",
            )

        self.assertEqual(result, [])
        rendered = output.getvalue()
        self.assertIn("topic-1 timed out", rendered)
        self.assertIn("unranked", rendered)
        self.assertIn("no fabricated score", rendered)

    def test_finalize_partial_coverage_requires_five_completed_topics(self) -> None:
        with self.assertRaisesRegex(workflow.WorkflowError, "at least 5 completed topics"):
            momentum_resilient.finalize_enrichment(
                seeds(),
                [enriched(seed) for seed in seeds()[:4]],
            )

    def test_finalize_partial_coverage_uses_partial_validator_and_labels_coverage(self) -> None:
        completed = [enriched(seed) for seed in seeds()[1:]]
        output = io.StringIO()
        with patch.object(
            momentum_resilient,
            "validate_partial_candidates",
            side_effect=lambda value, expected_ids: list(value),
        ) as validate_partial, redirect_stdout(output):
            result = momentum_resilient.finalize_enrichment(seeds(), completed)

        self.assertEqual(len(result), 9)
        validate_partial.assert_called_once()
        rendered = output.getvalue()
        self.assertIn("9/10 topics enriched", rendered)
        self.assertIn("topic-1", rendered)
        self.assertIn("partial coverage", rendered)
        self.assertIn("no timeout was converted to zero", rendered)

    def test_non_timeout_error_is_not_split_or_retried(self) -> None:
        with patch.object(
            momentum_resilient.base,
            "research_batch",
            side_effect=workflow.WorkflowError("Momentum batch IDs are invalid."),
        ) as research:
            with self.assertRaisesRegex(workflow.WorkflowError, "batch IDs"):
                momentum_resilient._research_adaptive(
                    seeds()[:2],
                    days=7,
                    as_of="2026-08-18T00:00:00Z",
                    label="1/5",
                )
        self.assertEqual(research.call_count, 1)


if __name__ == "__main__":
    unittest.main()
