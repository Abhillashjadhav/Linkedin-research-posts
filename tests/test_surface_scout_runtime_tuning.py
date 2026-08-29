from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import momentum_surface_parallel as surface
from authority_os import surface_scout_runtime_tuning as tuning
from authority_os import workflow


class SurfaceScoutRuntimeTuningTests(unittest.TestCase):
    def test_timeout_is_increased_and_model_reasoning_is_lowered_for_retrieval(self) -> None:
        tuning.install()
        self.assertEqual(surface.SURFACE_TIMEOUT, 180)
        self.assertEqual(tuning.SURFACE_TIMEOUT, 180)
        self.assertEqual(surface.CONSOLIDATION_TIMEOUT, 150)
        self.assertEqual(tuning.CONSOLIDATION_TIMEOUT, 150)
        self.assertEqual(surface.MODEL.reasoning, "medium")
        self.assertIs(surface._run_surface, tuning._run_surface)

    def test_shallow_schema_does_not_request_acceleration(self) -> None:
        schema = tuning._shallow_schema(("Reddit",))
        signal = schema["properties"]["signals"]["items"]
        self.assertNotIn("acceleration_percent", signal["properties"])
        self.assertIn("engagement_units", signal["properties"])
        self.assertIn("freshness_hours", signal["properties"])

    def test_timeout_failure_is_not_collapsed_into_unavailable(self) -> None:
        self.assertEqual(
            tuning._failure_status(workflow.WorkflowError("Surface Scout Reddit timed out.")),
            "TIMEOUT",
        )
        self.assertEqual(
            tuning._failure_status(workflow.WorkflowError("invalid schema")),
            "BAD_SCHEMA",
        )

    def test_shallow_result_projects_acceleration_as_unknown_for_existing_momentum_contract(self) -> None:
        lane = {
            "key": "reddit",
            "label": "Reddit",
            "allowed_platforms": ("Reddit",),
            "instruction": "Search only public Reddit.",
        }
        response = {
            "status": "OBSERVED",
            "signals": [
                {
                    "topic": "Agent evals",
                    "why_now": "Active discussion.",
                    "platform": "Reddit",
                    "url": "https://www.reddit.com/r/example/comments/123/example/",
                    "source": "r/example",
                    "published_at": "2026-08-29T00:00:00Z",
                    "freshness_hours": 3,
                    "engagement_units": 42,
                }
            ],
            "caveat": "Public evidence only.",
        }
        with patch.object(surface, "invoke_structured", return_value=response), patch.object(
            surface, "_write_surface_file"
        ), patch.object(surface, "_trace_event"):
            result = tuning._run_surface(
                lane,
                topic=None,
                days=7,
                as_of="2026-08-29T03:00:00Z",
            )
        self.assertEqual(result["status"], "OBSERVED")
        self.assertIsNone(result["signals"][0]["acceleration_percent"])


if __name__ == "__main__":
    unittest.main()