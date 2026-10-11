"""Regression tests for surface-first parallel momentum discovery."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from authority_os import momentum_surface_parallel as surface
from authority_os import workflow


class SurfaceParallelTests(unittest.TestCase):
    def test_month_only_signal_keeps_uncertainty_and_loses_exact_date_tie(self) -> None:
        lane = surface.SURFACES[0]
        common = {
            "topic": "Agent budgets",
            "why_now": "Adoption is accelerating.",
            "platform": "Google Search",
            "source": "Example",
            "freshness_hours": None,
            "engagement_units": 10,
            "acceleration_percent": 20,
        }
        raw = {
            "status": "OBSERVED",
            "signals": [
                {
                    **common,
                    "url": "https://example.com/month",
                    "published_at": "2026-09",
                },
                {
                    **common,
                    "url": "https://example.com/exact",
                    "published_at": "2026-09-03T00:00:00Z",
                    "freshness_hours": 36,
                },
            ],
            "caveat": "Public evidence only.",
        }

        result = surface._validate_surface_result(
            raw, surface=lane, days=7, as_of="2026-09-04T12:00:00Z"
        )

        exact, month = result["signals"]
        self.assertEqual(exact["url"], "https://example.com/exact")
        self.assertFalse(exact["publication_date_uncertain"])
        self.assertEqual(month["publication_date_precision"], "month")
        self.assertIsNone(month["freshness_hours"])

    def test_timeout_surface_has_one_attempt(self) -> None:
        lane = surface.SURFACES[0]
        with patch.object(surface.daily_cli, "_role", return_value="Scout"), patch.object(
            surface,
            "invoke_structured",
            side_effect=workflow.WorkflowError("timed out"),
        ) as invoke:
            result = surface._run_surface(
                lane,
                topic=None,
                days=7,
                as_of="2026-09-02T00:00:00Z",
            )
        self.assertEqual(invoke.call_count, 1)
        self.assertIn(result["status"], {"UNAVAILABLE", "TIMEOUT"})

    def test_supported_date_precisions_and_window_exclude_undated_signals(self) -> None:
        lane = surface.SURFACES[0]

        def signal(index: int, date: str | None) -> dict[str, object]:
            return {
                "topic": f"Topic {index}", "why_now": "Current product decision.",
                "platform": "Google Search", "url": f"https://example.com/{index}",
                "source": f"Source {index}", "published_at": date,
                "freshness_hours": 1, "engagement_units": None,
                "acceleration_percent": None,
            }

        raw = {
            "status": "OBSERVED",
            "signals": [
                signal(1, "2026-09"), signal(2, "2026-09-03"),
                signal(3, "2026-09-03T14:00:00+02:00"),
                signal(4, None), signal(5, "2026-08-01T00:00:00Z"),
            ],
            "caveat": "Public evidence only.",
        }
        validated = surface._validate_surface_result(
            raw, surface=lane, days=7, as_of="2026-09-04T12:00:00Z"
        )
        by_url = {item["url"]: item for item in validated["signals"]}
        self.assertEqual(set(by_url), {f"https://example.com/{index}" for index in (1, 2, 3)})
        self.assertEqual(by_url["https://example.com/2"]["publication_date_precision"], "day")
        self.assertIsNone(by_url["https://example.com/2"]["freshness_hours"])
        self.assertEqual(by_url["https://example.com/3"]["freshness_hours"], 1)
        self.assertIn("Excluded 2 signal(s)", validated["caveat"])
        projected = surface._project_candidates(
            [{"id": "topic-1", "topic": "Topic 2", "why_now": "Current product decision.",
              "signal_ids": [by_url["https://example.com/2"]["id"]]}],
            validated["signals"],
        )
        self.assertEqual(projected[0]["freshness"]["status"], "UNKNOWN")
        self.assertIn("Exact freshness", projected[0]["freshness"]["evidence"])

        raw["signals"] = [signal(4, "unknown"), signal(5, "2026-08-01")]
        empty = surface._validate_surface_result(
            raw, surface=lane, days=7, as_of="2026-09-04T12:00:00Z"
        )
        self.assertEqual(empty["status"], "NO_SIGNAL")
        self.assertEqual(empty["signals"], [])

    def test_three_distinct_clusters_are_supported_but_two_or_duplicates_fail(self) -> None:
        signals = [{"id": f"signal-{index}"} for index in range(1, 4)]
        clusters = [
            {"id": f"topic-{index}", "topic": f"Distinct topic {index}",
             "why_now": "Current public discussion.", "signal_ids": [f"signal-{index}"]}
            for index in range(1, 4)
        ]
        self.assertEqual(len(surface._validate_clusters(clusters, signals)), 3)
        with self.assertRaisesRegex(workflow.WorkflowError, "at least 3"):
            surface._validate_clusters(clusters[:2], signals)
        duplicates = [*clusters[:2], {**clusters[2], "topic": clusters[0]["topic"]}]
        with self.assertRaisesRegex(workflow.WorkflowError, "materially distinct"):
            surface._validate_clusters(duplicates, signals)
        reused = [*clusters[:2], {**clusters[2], "signal_ids": ["signal-1"]}]
        with self.assertRaisesRegex(workflow.WorkflowError, "cannot belong to multiple"):
            surface._validate_clusters(reused, signals)

    def test_exactly_seven_bounded_surface_lanes_are_defined(self) -> None:
        self.assertEqual(surface.MAX_WORKERS, 7)
        self.assertEqual(len(surface.SURFACES), 7)
        self.assertEqual(
            [item["key"] for item in surface.SURFACES],
            [
                "google",
                "reddit",
                "hacker-news",
                "public-social",
                "youtube",
                "substack",
                "primary-reporting",
            ],
        )
        joined = " ".join(str(item) for item in surface.SURFACES).casefold()
        for term in (
            "google trends",
            "reddit",
            "hacker news",
            "x/twitter",
            "linkedin",
            "youtube",
            "substack",
            "newsletter",
            "primary source",
            "reputable reporting",
        ):
            self.assertIn(term, joined)

    def test_all_seven_surface_scouts_run_concurrently(self) -> None:
        lock = threading.Lock()
        active = 0
        max_active = 0

        def fake_surface(item: object, **_kwargs: object) -> dict[str, object]:
            nonlocal active, max_active
            assert isinstance(item, dict)
            key = str(item["key"])
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.04)
            with lock:
                active -= 1
            return {
                "schema_version": 1,
                "surface": key,
                "label": str(item["label"]),
                "status": "OBSERVED",
                "caveat": "Public evidence only.",
                "signals": [
                    {
                        "id": f"{key}-1",
                        "surface": key,
                        "surface_label": str(item["label"]),
                        "topic": f"Conversation {key}",
                        "why_now": "Active now.",
                        "platform": str(item["allowed_platforms"][0]),
                        "url": f"https://example.com/{key}",
                        "source": f"Source {key}",
                        "published_at": "2026-08-28T00:00:00Z",
                        "freshness_hours": 1.0,
                        "engagement_units": 10,
                        "acceleration_percent": None,
                    },
                    {
                        "id": f"{key}-2",
                        "surface": key,
                        "surface_label": str(item["label"]),
                        "topic": f"Second {key}",
                        "why_now": "Also active now.",
                        "platform": str(item["allowed_platforms"][0]),
                        "url": f"https://example.com/{key}/2",
                        "source": f"Second source {key}",
                        "published_at": "2026-08-28T00:00:00Z",
                        "freshness_hours": 2.0,
                        "engagement_units": 5,
                        "acceleration_percent": None,
                    },
                ],
            }

        fake_clusters = [
            {"id": f"topic-{index}", "topic": f"Topic {index}", "why_now": "Now", "signal_ids": ["unused"]}
            for index in range(1, 11)
        ]
        expected = [{"id": f"topic-{index}"} for index in range(1, 11)]
        with patch.object(surface, "_run_surface", side_effect=fake_surface) as scout_mock, patch.object(
            surface, "_consolidate", return_value=fake_clusters
        ), patch.object(surface, "_project_candidates", return_value=expected):
            result = surface.invoke_scout(None, 7, "2026-08-28T00:00:00Z")

        self.assertEqual(scout_mock.call_count, 7)
        self.assertGreaterEqual(max_active, 6)
        self.assertEqual(result, expected)

    def test_one_surface_failure_does_not_destroy_other_surface_results(self) -> None:
        def fake_surface(item: object, **_kwargs: object) -> dict[str, object]:
            assert isinstance(item, dict)
            key = str(item["key"])
            if key == "youtube":
                return {
                    "schema_version": 1,
                    "surface": key,
                    "label": str(item["label"]),
                    "status": "UNAVAILABLE",
                    "caveat": "Timed out.",
                    "signals": [],
                }
            return {
                "schema_version": 1,
                "surface": key,
                "label": str(item["label"]),
                "status": "OBSERVED",
                "caveat": "Public evidence only.",
                "signals": [
                    {
                        "id": f"{key}-{index}",
                        "surface": key,
                        "surface_label": str(item["label"]),
                        "topic": f"{key} topic {index}",
                        "why_now": "Now.",
                        "platform": str(item["allowed_platforms"][0]),
                        "url": f"https://example.com/{key}/{index}",
                        "source": f"Source {key} {index}",
                        "published_at": "2026-08-28T00:00:00Z",
                        "freshness_hours": 1.0,
                        "engagement_units": 1,
                        "acceleration_percent": None,
                    }
                    for index in range(1, 3)
                ],
            }

        with patch.object(surface, "_run_surface", side_effect=fake_surface), patch.object(
            surface, "_consolidate", return_value=[]
        ), patch.object(surface, "_project_candidates", return_value=[]):
            result = surface.invoke_scout(None, 7, "2026-08-28T00:00:00Z")

        self.assertEqual(result, [])

    def test_three_surfaces_continue_when_signal_floor_is_met(self) -> None:
        def fake_surface(item: object, **_kwargs: object) -> dict[str, object]:
            assert isinstance(item, dict)
            key = str(item["key"])
            observed = key in {"google", "reddit", "substack"}
            count = 4 if observed else 0
            return {
                "schema_version": 1,
                "surface": key,
                "label": str(item["label"]),
                "status": "OBSERVED" if observed else "UNAVAILABLE",
                "caveat": "Public evidence only." if observed else "Timed out.",
                "signals": [
                    {
                        "id": f"{key}-{index}",
                        "surface": key,
                        "surface_label": str(item["label"]),
                        "topic": f"{key} topic {index}",
                        "why_now": "Now.",
                        "platform": str(item["allowed_platforms"][0]),
                        "url": f"https://example.com/{key}/{index}",
                        "source": f"Source {key} {index}",
                        "published_at": "2026-09-03T00:00:00Z",
                        "freshness_hours": 1.0,
                        "engagement_units": float(100 - index),
                        "acceleration_percent": None,
                    }
                    for index in range(1, count + 1)
                ],
            }

        clusters = [
            {
                "id": f"topic-{index}",
                "topic": f"Topic {index}",
                "why_now": "Now",
                "signal_ids": ["unused"],
            }
            for index in range(1, 11)
        ]
        expected = [{"id": f"topic-{index}"} for index in range(1, 11)]
        with patch.object(surface, "_run_surface", side_effect=fake_surface), patch.object(
            surface, "_consolidate", return_value=clusters
        ) as consolidate, patch.object(
            surface, "_project_candidates", return_value=expected
        ):
            result = surface.invoke_scout(None, 1, "2026-09-03T12:00:00Z")

        self.assertEqual(len(consolidate.call_args.args[0]), 12)
        self.assertEqual(result, expected)

    def test_three_signals_from_one_lane_clear_floor_with_coverage_warning(self) -> None:
        for count in (2, 3):
            def fake_surface(item: object, **_kwargs: object) -> dict[str, object]:
                assert isinstance(item, dict)
                key = str(item["key"])
                signals = [
                    {"id": f"google-{index}", "topic": f"Topic {index}",
                     "why_now": "Now", "platform": "Google Search",
                     "url": f"https://example.com/{index}", "source": f"Source {index}",
                     "published_at": "2026-09-03", "freshness_hours": None,
                     "engagement_units": None, "acceleration_percent": None}
                    for index in range(1, count + 1)
                ] if key == "google" else []
                return {"status": "OBSERVED" if signals else "UNAVAILABLE", "signals": signals}

            with self.subTest(count=count), patch.object(surface, "_run_surface", side_effect=fake_surface) as scout, patch.object(
                surface, "_consolidate", return_value=[]
            ) as consolidate, patch.object(surface, "_project_candidates", return_value=[]) as project, patch.object(
                surface, "_trace_event"
            ) as trace:
                if count == 2:
                    with self.assertRaisesRegex(workflow.WorkflowError, "Only 2 usable public signals"):
                        surface.invoke_scout(None, 7, "2026-09-04T12:00:00Z")
                    consolidate.assert_not_called()
                else:
                    self.assertEqual(surface.invoke_scout(None, 7, "2026-09-04T12:00:00Z"), [])
                    self.assertEqual(len(consolidate.call_args.args[0]), 3)
                    project.assert_called_once()
                    self.assertIn(
                        "surface_coverage_warning",
                        [call.args[0]["event"] for call in trace.call_args_list],
                    )
                self.assertEqual(scout.call_count, 7)


if __name__ == "__main__":
    unittest.main()
