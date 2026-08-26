"""Tests for free public-web conversation momentum ranking."""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from authority_os import daily_spine_cli, momentum, workflow


def profile() -> dict[str, object]:
    return {
        "target_audience": "Senior product leaders and AI founders",
        "authority_goal": "Practical judgment for reliable enterprise AI products",
        "proof_inventory": [
            {
                "id": "proof-repository",
                "label": "Public repository",
                "public_safe_claim": "A public repository demonstrates the implementation.",
                "evidence_type": "repository",
            }
        ],
        "avoid_topics": [],
        "recent_theses": [],
    }


def observation(value: float | None, evidence: str = "Observed public signal") -> dict[str, object]:
    return {
        "status": "OBSERVED" if value is not None else "UNKNOWN",
        "basis_value": value,
        "evidence": evidence,
    }


def momentum_candidates() -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index in range(1, 11):
        result.append(
            {
                "id": f"topic-{index}",
                "topic": f"Current GenAI conversation {index}",
                "why_now": f"Independent public discussion is active for topic {index}.",
                "platforms": ["Hacker News", "Reddit", "X public search"],
                "representative_urls": [
                    f"https://example.com/{index}/a",
                    f"https://example.com/{index}/b",
                    f"https://example.com/{index}/c",
                ],
                "caveats": "Public-web proxy; exact X volume is unavailable.",
                "conversation_breadth": observation(max(1, 11 - index)),
                "engagement_strength": observation(max(1, 1200 - index * 100)),
                "acceleration": observation(max(1, 120 - index * 10)),
                "cross_platform_confirmation": observation(3),
                "freshness": observation(index * 12),
            }
        )
    return result


def authority_scores(candidates: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "topic_id": str(candidate["id"]),
            **{axis: 5 for axis in momentum.AUTHORITY_TOPIC_AXES},
        }
        for candidate in candidates
    ]


class MomentumValidationTests(unittest.TestCase):
    def test_scores_are_derived_locally_from_observed_basis(self) -> None:
        validated = momentum.validate_candidates(momentum_candidates())
        first = validated[0]
        self.assertEqual(first["scores"]["conversation_breadth"], 5)
        self.assertEqual(first["scores"]["engagement_strength"], 5)
        self.assertEqual(first["scores"]["acceleration"], 5)
        self.assertEqual(first["scores"]["cross_platform_confirmation"], 3)
        self.assertEqual(first["scores"]["freshness"], 5)
        self.assertEqual(first["total"], 23)

    def test_missing_engagement_is_unknown_not_zero(self) -> None:
        candidates = momentum_candidates()
        candidates[0]["engagement_strength"] = observation(
            None, "Public engagement counts were not exposed."
        )
        validated = momentum.validate_candidates(candidates)
        first = validated[0]

        self.assertIsNone(first["engagement_strength"]["score"])
        self.assertEqual(first["engagement_strength"]["status"], "UNKNOWN")
        self.assertEqual(first["observed_axes"], 4)
        self.assertEqual(first["confidence"], "MEDIUM")
        self.assertIsInstance(first["total"], int)

        invalid = momentum_candidates()
        invalid[0]["engagement_strength"] = {
            "status": "UNKNOWN",
            "basis_value": 0,
            "evidence": "Missing was incorrectly encoded as zero.",
        }
        with self.assertRaisesRegex(workflow.WorkflowError, "basis_value=null"):
            momentum.validate_candidates(invalid)

    def test_cross_platform_basis_is_derived_from_distinct_platforms(self) -> None:
        candidates = momentum_candidates()
        candidates[0]["cross_platform_confirmation"] = observation(5)
        validated = momentum.validate_candidates(candidates)
        cross_platform = validated[0]["cross_platform_confirmation"]

        self.assertEqual(cross_platform["basis_value"], 3)
        self.assertEqual(cross_platform["score"], 3)
        self.assertIn("Local reconciliation", cross_platform["evidence"])
        self.assertIn("reported 5", cross_platform["evidence"])

    def test_momentum_rank_cannot_be_changed_by_authority_fit(self) -> None:
        validated = momentum.validate_candidates(momentum_candidates())
        ranked = momentum.rank_candidates(validated)
        top_five = ranked[: momentum.MOMENTUM_TOP_K]

        reversed_authority = []
        for index, candidate in enumerate(top_five, start=1):
            value = 1 if index == 1 else 5
            reversed_authority.append(
                {
                    "topic_id": candidate["id"],
                    **{axis: value for axis in momentum.AUTHORITY_TOPIC_AXES},
                    "total": value * len(momentum.AUTHORITY_TOPIC_AXES),
                }
            )
        attached = momentum.attach_authority_fit(top_five, reversed_authority)

        self.assertEqual(
            [item["id"] for item in attached],
            [item["id"] for item in top_five],
        )
        self.assertEqual(attached[0]["momentum_rank"], 1)
        self.assertLess(
            attached[0]["authority_fit"]["total"],
            attached[-1]["authority_fit"]["total"],
        )

    def test_authority_floor_is_applied_locally(self) -> None:
        candidates = momentum_candidates()
        candidates[0].update(
            {
                "conversation_breadth": observation(2),
                "engagement_strength": observation(10),
                "acceleration": observation(10),
                "cross_platform_confirmation": observation(3),
                "freshness": observation(100),
            }
        )
        candidates[1].update(
            {
                "conversation_breadth": observation(8),
                "engagement_strength": observation(1000),
                "acceleration": observation(100),
                "cross_platform_confirmation": observation(3),
                "freshness": observation(12),
            }
        )
        validated = momentum.validate_candidates(candidates)
        ranked = momentum.rank_candidates(
            validated, minimum=momentum.MIN_AUTHORITY_MOMENTUM
        )
        by_id = {item["id"]: item for item in ranked}
        self.assertFalse(by_id["topic-1"]["momentum_eligible"])
        self.assertTrue(by_id["topic-2"]["momentum_eligible"])

    def test_printed_label_does_not_claim_exact_x_ranking(self) -> None:
        validated = momentum.validate_candidates(momentum_candidates())
        top_five = momentum.rank_candidates(validated)[:5]
        scores = momentum.validate_authority_scores(
            authority_scores(top_five), top_five
        )
        attached = momentum.attach_authority_fit(top_five, scores)
        output = io.StringIO()
        with redirect_stdout(output):
            momentum.print_top(attached)
        rendered = output.getvalue().casefold()
        self.assertIn("observed cross-platform conversation momentum", rendered)
        self.assertIn("not an exact x/twitter ranking", rendered)


class MomentumRuntimeTests(unittest.TestCase):
    @patch("authority_os.momentum.invoke_structured")
    def test_momentum_scout_is_live_web_and_receives_no_private_profile(self, invoke: object) -> None:
        invoke.return_value = {"candidates": momentum_candidates()}  # type: ignore[attr-defined]
        with patch.object(momentum, "_role", return_value="Scout role"):
            result = momentum.invoke_scout(None, 7, "2026-08-18T00:00:00Z")
        self.assertEqual(len(result), 10)
        kwargs = invoke.call_args.kwargs  # type: ignore[attr-defined]
        self.assertTrue(kwargs["web_search"])
        self.assertEqual(kwargs["config"].runtime, "codex")
        self.assertNotIn("proof_inventory", kwargs["task_prompt"])
        self.assertIn("do not assign 0-5 scores", kwargs["task_prompt"].casefold())
        self.assertIn("basis_value", kwargs["task_prompt"])

    @patch("authority_os.momentum.invoke_structured")
    def test_authority_fit_is_scored_separately_without_web(self, invoke: object) -> None:
        validated = momentum.validate_candidates(momentum_candidates())
        top_five = momentum.rank_candidates(validated)[:5]
        invoke.return_value = {"scorecards": authority_scores(top_five)}  # type: ignore[attr-defined]

        result = momentum.score_authority_fit(top_five, profile())

        self.assertEqual(len(result), 5)
        kwargs = invoke.call_args.kwargs  # type: ignore[attr-defined]
        self.assertFalse(kwargs["web_search"])
        self.assertIn("popularity and authority fit are separate", kwargs["role_prompt"].casefold())

    @patch("authority_os.daily_cli.invoke_structured")
    def test_source_scout_is_constrained_to_momentum_topics(self, invoke: object) -> None:
        invoke.return_value = {"items": []}  # type: ignore[attr-defined]
        prepared = [
            {
                "id": "research-1",
                "title": "Verified source",
                "body": "Body-read evidence",
                "source": "Research lab",
                "author": "Research lab",
                "published_at": "2026-08-18T00:00:00Z",
                "source_quality": "primary",
                "canonical_url": "https://example.com/source",
                "content_hash": "abc",
            }
        ] * 3
        with patch.object(daily_spine_cli.base, "_role", return_value="Scout role"), patch.object(
            workflow, "prepare_research_items", return_value=prepared
        ):
            daily_spine_cli._invoke_signal_scout(
                None,
                7,
                "2026-08-18T00:00:00Z",
                ["Agent coordination", "Model economics", "A2A"],
            )
        prompt = invoke.call_args.kwargs["task_prompt"]  # type: ignore[attr-defined]
        self.assertIn("momentum-qualified topic candidates", prompt)
        self.assertIn("Agent coordination", prompt)
        self.assertIn("[Capability Launch]", prompt)
        self.assertIn("same exact title", prompt)
        self.assertIn("runnable artifact", prompt)
        self.assertIn("original creator demo page", prompt)
        self.assertIn("never download", prompt)


if __name__ == "__main__":
    unittest.main()
