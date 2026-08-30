from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import momentum_surface_parallel as surface
from authority_os import v1_consumability as tuning


class V1ConsumabilityTests(unittest.TestCase):
    def test_plain_consequence_hook_passes(self) -> None:
        result = tuning.hook_entry_check(
            "Your AI agent can hit its budget and stop a customer workflow.\nBefore production, prove you can stop spending safely."
        )
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["reason_codes"], [])

    def test_specialist_hook_without_plain_consequence_blocks(self) -> None:
        result = tuning.hook_entry_check(
            "MCP GPU orchestration and RAG benchmark contamination are converging.\nInference routing is changing fast."
        )
        self.assertEqual(result["status"], "BLOCKED")
        self.assertIn("hook-entry-specialist-load", result["reason_codes"])
        self.assertIn("hook-entry-no-plain-consequence", result["reason_codes"])

    def test_consolidation_prompt_prioritises_broad_consequence_and_one_argument(self) -> None:
        captured: dict[str, object] = {}

        def invoke_structured(**kwargs: object) -> dict[str, object]:
            captured.update(kwargs)
            clusters = [
                {
                    "id": f"topic-{index}",
                    "topic": f"Plain topic {index}",
                    "why_now": "A product decision changed for a broad reader.",
                    "signal_ids": [f"s-{index}"],
                }
                for index in range(1, surface.MOMENTUM_CANDIDATES + 1)
            ]
            return {"clusters": clusters}

        signals = [
            {
                "id": f"s-{index}",
                "topic": f"Signal {index}",
                "why_now": "Now",
                "platform": "Google Search",
                "url": f"https://example.com/{index}",
                "source": f"source-{index}",
                "published_at": "2026-08-30T00:00:00Z",
                "freshness_hours": 1.0,
                "engagement_units": None,
                "acceleration_percent": None,
            }
            for index in range(1, surface.MOMENTUM_CANDIDATES + 1)
        ]
        with patch.object(surface, "invoke_structured", side_effect=invoke_structured):
            result = tuning._consolidate(signals, as_of="2026-08-30T00:00:00Z")

        self.assertEqual(len(result), surface.MOMENTUM_CANDIDATES)
        task = str(captured["task_prompt"])
        self.assertIn("concrete consequence", task)
        self.assertIn("one central argument", task)
        self.assertIn("Do not reward technical sophistication", task)
        self.assertIn("Social/community popularity is momentum evidence only", task)


if __name__ == "__main__":
    unittest.main()
