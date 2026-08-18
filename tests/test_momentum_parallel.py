"""Regression tests for bounded parallel momentum enrichment."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from authority_os import momentum_parallel


def seeds() -> list[dict[str, str]]:
    return [
        {
            "id": f"topic-{index}",
            "topic": f"Conversation {index}",
            "why_now": "Active now.",
        }
        for index in range(1, 11)
    ]


def enriched(batch: object) -> list[dict[str, object]]:
    assert isinstance(batch, list)
    return [{**seed, "enriched": True} for seed in batch]


class ParallelMomentumTests(unittest.TestCase):
    def test_top_level_batches_run_concurrently_and_reassemble_in_seed_order(self) -> None:
        topic_seeds = seeds()
        lock = threading.Lock()
        active = 0
        max_active = 0

        def research(batch: object, **_kwargs: object) -> list[dict[str, object]]:
            nonlocal active, max_active
            assert isinstance(batch, list)
            batch_number = int(str(batch[0]["id"]).split("-")[1])
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.01 * (12 - batch_number))
            result = enriched(batch)
            with lock:
                active -= 1
            return result

        with patch.object(
            momentum_parallel.base.base,
            "discover_topics",
            return_value=topic_seeds,
        ), patch.object(
            momentum_parallel.base,
            "_research_adaptive",
            side_effect=research,
        ) as research_mock, patch.object(
            momentum_parallel.base.base.base,
            "validate_candidates",
            side_effect=lambda value: value,
        ):
            result = momentum_parallel.invoke_scout(
                None, 7, "2026-08-18T00:00:00Z"
            )

        self.assertEqual(research_mock.call_count, 5)
        self.assertGreaterEqual(max_active, 2)
        self.assertLessEqual(max_active, momentum_parallel.MAX_WORKERS)
        self.assertEqual(
            [item["id"] for item in result],
            [f"topic-{index}" for index in range(1, 11)],
        )

    def test_worker_pool_is_bounded(self) -> None:
        self.assertEqual(momentum_parallel.BATCH_SIZE, 2)
        self.assertEqual(momentum_parallel.MAX_WORKERS, 3)


if __name__ == "__main__":
    unittest.main()
