"""Regression tests for surface-first parallel momentum discovery."""

from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from authority_os import momentum_surface_parallel as surface


class SurfaceParallelTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
