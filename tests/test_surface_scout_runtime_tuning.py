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
                surface=lane,
                topic=None,
                days=7,
                as_of="2026-08-29T03:00:00Z",
            )
        self.assertEqual(result["status"], "OBSERVED")
        self.assertIsNone(result["signals"][0]["acceleration_percent"])

    def test_active_runtime_does_not_retry_timeout_or_unavailable(self) -> None:
        lane = {
            "key": "reddit",
            "label": "Reddit",
            "allowed_platforms": ("Reddit",),
            "instruction": "Search only public Reddit.",
        }
        for response, expected in (
            (workflow.WorkflowError("timed out"), "TIMEOUT"),
            ({"status": "UNAVAILABLE", "signals": [], "caveat": "Search unavailable."}, "UNAVAILABLE"),
        ):
            with self.subTest(expected=expected), patch.object(
                surface, "invoke_structured", side_effect=response if isinstance(response, Exception) else None,
                return_value=response if isinstance(response, dict) else None,
            ) as invoke, patch.object(
                surface.daily_cli, "_role", return_value="Scout"
            ), patch.object(
                surface, "_write_surface_file"
            ), patch.object(
                surface, "_trace_event"
            ) as trace:
                result = tuning._run_surface(
                    lane, topic=None, days=7, as_of="2026-09-02T00:00:00Z"
                )
            self.assertEqual(invoke.call_count, 1)
            self.assertEqual(result["status"], expected)
            self.assertNotIn("surface_retry", [call.args[0]["event"] for call in trace.call_args_list])

    def test_active_adapter_excludes_out_of_window_date(self) -> None:
        lane = surface.SURFACES[1]
        response = {
            "status": "OBSERVED", "caveat": "Public evidence only.",
            "signals": [{
                "topic": "Old discussion", "why_now": "Old release.",
                "platform": "Reddit", "url": "https://example.com/old",
                "source": "Public thread", "published_at": "2026-08-01",
                "freshness_hours": 1, "engagement_units": 4,
            }],
        }
        with patch.object(surface, "invoke_structured", return_value=response), patch.object(
            surface.daily_cli, "_role", return_value="Scout"
        ), patch.object(surface, "_write_surface_file"), patch.object(surface, "_trace_event"):
            result = tuning._run_surface(lane, topic=None, days=7, as_of="2026-09-04T12:00:00Z")
        self.assertEqual(result["status"], "NO_SIGNAL")
        self.assertEqual(result["signals"], [])
        self.assertIn("Excluded 1 signal", result["caveat"])


if __name__ == "__main__":
    unittest.main()
