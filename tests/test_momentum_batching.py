"""Regression tests for bounded momentum Scout execution."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import momentum_batched, workflow


def topic_seeds() -> list[dict[str, str]]:
    return [
        {
            "id": f"topic-{index}",
            "topic": f"Current GenAI conversation {index}",
            "why_now": f"Conversation {index} is active now.",
        }
        for index in range(1, 11)
    ]


def observation(value: float | None) -> dict[str, object]:
    return {
        "status": "OBSERVED" if value is not None else "UNKNOWN",
        "basis_value": value,
        "evidence": "Observed public signal" if value is not None else "Not publicly observable",
    }


def enriched(seed: dict[str, str]) -> dict[str, object]:
    index = int(seed["id"].split("-")[1])
    return {
        **seed,
        "platforms": ["Hacker News", "Reddit", "X public search"],
        "representative_urls": [
            f"https://example.com/{index}/a",
            f"https://example.com/{index}/b",
            f"https://example.com/{index}/c",
        ],
        "caveats": "Public-web proxy; exact X volume is unavailable.",
        "conversation_breadth": observation(8),
        "engagement_strength": observation(1000),
        "acceleration": observation(50),
        "cross_platform_confirmation": observation(3),
        "freshness": observation(12),
    }


class BatchedMomentumTests(unittest.TestCase):
    @patch("authority_os.momentum_batched.invoke_structured")
    def test_discovery_uses_one_seed_call_then_two_five_topic_batches(self, invoke: object) -> None:
        seeds = topic_seeds()
        invoke.side_effect = [  # type: ignore[attr-defined]
            {"topics": seeds},
            {"candidates": [enriched(seed) for seed in seeds[:5]]},
            {"candidates": [enriched(seed) for seed in seeds[5:]]},
        ]
        with patch.object(momentum_batched.base, "_role", return_value="Scout role"):
            result = momentum_batched.invoke_scout(None, 7, "2026-08-18T00:00:00Z")

        self.assertEqual([item["id"] for item in result], [f"topic-{i}" for i in range(1, 11)])
        self.assertEqual(invoke.call_count, 3)  # type: ignore[attr-defined]
        calls = invoke.call_args_list  # type: ignore[attr-defined]
        self.assertEqual(calls[0].kwargs["stage_label"], "Momentum topic discovery")
        self.assertEqual(calls[1].kwargs["stage_label"], "Momentum research batch 1")
        self.assertEqual(calls[2].kwargs["stage_label"], "Momentum research batch 2")
        self.assertTrue(all(call.kwargs["web_search"] for call in calls))
        self.assertNotIn("proof_inventory", calls[0].kwargs["task_prompt"])
        self.assertIn("topic-1", calls[1].kwargs["task_prompt"])
        self.assertNotIn("topic-6", calls[1].kwargs["task_prompt"])
        self.assertIn("topic-6", calls[2].kwargs["task_prompt"])

    @patch("authority_os.momentum_batched.invoke_structured")
    def test_duplicate_or_missing_ids_across_batches_fail_closed(self, invoke: object) -> None:
        seeds = topic_seeds()
        second = [enriched(seed) for seed in seeds[5:]]
        second[-1] = enriched(seeds[4])
        invoke.side_effect = [  # type: ignore[attr-defined]
            {"topics": seeds},
            {"candidates": [enriched(seed) for seed in seeds[:5]]},
            {"candidates": second},
        ]
        with patch.object(momentum_batched.base, "_role", return_value="Scout role"):
            with self.assertRaisesRegex(workflow.WorkflowError, "batch IDs"):
                momentum_batched.invoke_scout(None, 7, "2026-08-18T00:00:00Z")

    @patch("authority_os.momentum_batched.invoke_structured")
    def test_batch_cannot_rename_a_discovered_topic(self, invoke: object) -> None:
        seeds = topic_seeds()
        first = [enriched(seed) for seed in seeds[:5]]
        first[0]["topic"] = "Different topic invented during enrichment"
        invoke.side_effect = [  # type: ignore[attr-defined]
            {"topics": seeds},
            {"candidates": first},
        ]
        with patch.object(momentum_batched.base, "_role", return_value="Scout role"):
            with self.assertRaisesRegex(workflow.WorkflowError, "changed a discovered topic"):
                momentum_batched.invoke_scout(None, 7, "2026-08-18T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
