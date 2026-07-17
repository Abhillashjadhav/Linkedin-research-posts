"""Tests for deterministic, private weekly learning reviews."""

from __future__ import annotations

import copy
import json
import os
import stat
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

from authority_os import learning, storage, workflow


UTC = timezone.utc


def _text(moment: datetime) -> str:
    return moment.astimezone(UTC).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def performance_row(
    slug: str,
    *,
    published: datetime,
    goal: str = "reach",
    checkpoint: str = "72h",
    channel: str = "organic",
    lower_axis: str | None = None,
    rank: int = 1,
    recommended: bool | None = None,
    output_format: str | None = "text",
    learning_context_fingerprint: str | None = "a" * 64,
    updated_at: datetime | None = None,
    observed_age_hours: int | None = None,
    **metrics: int,
) -> dict[str, object]:
    scores = {axis: 5 for axis in workflow.CRITIC_AXES}
    if lower_axis is not None:
        scores[lower_axis] = 4
    raw_total = sum(scores.values())
    age = (
        observed_age_hours
        if observed_age_hours is not None
        else {"2h": 3, "24h": 25, "72h": 73, "7d": 169}[checkpoint]
    )
    observed = published + timedelta(hours=age)
    updated = updated_at or observed + timedelta(hours=1)
    values = {metric: 0 for metric in storage.PERFORMANCE_METRICS}
    values.update({"impressions": 100, **metrics})
    return {
        "package_id": f"{published.date().isoformat()}-{slug}",
        "candidate_id": "candidate-1" if rank == 1 else "candidate-2",
        "package_created_at": _text(published - timedelta(hours=1)),
        "published_at": _text(published),
        "goal": goal,
        "output_format": output_format,
        "weekly_slot": 2,
        "revision_count": 0,
        "was_revised": False,
        **scores,
        "critic_raw_total": raw_total,
        "critic_effective_total": raw_total,
        "critic_hook_cap_applied": False,
        "critic_band": "advance-to-gates",
        "critic_rank": rank,
        "is_recommended": (rank == 1) if recommended is None else recommended,
        "learning_context_fingerprint": learning_context_fingerprint,
        "checkpoint": checkpoint,
        "channel": channel,
        "observed_at": _text(observed),
        **values,
        "recorded_at": _text(observed + timedelta(minutes=30)),
        "updated_at": _text(updated),
    }


def candidate_context(
    row: Mapping[str, object],
    *,
    hook: str | None = None,
    angle: str = "A decision-led opening",
    paragraphs: int = 6,
) -> tuple[tuple[str, str], dict[str, object]]:
    package_id = str(row["package_id"])
    candidate_id = str(row["candidate_id"])
    routes = {
        "reach": ["incident", "mechanism", "implication"],
        "authority": ["incident-or-problem", "mechanism", "decision"],
        "opportunity": ["problem", "decision", "artifact", "evidence"],
    }
    return (
        (package_id, candidate_id),
        {
            "package_id": package_id,
            "candidate_id": candidate_id,
            "hook_excerpt": hook or f"Observed hook for {package_id}.",
            "hook_excerpt_truncated": False,
            "candidate_angle": angle,
            "structure": {
                "planned_route": routes[str(row["goal"])],
                "paragraph_count": paragraphs,
            },
        },
    )


class WeeklyLearningTests(unittest.TestCase):
    def setUp(self) -> None:
        self.as_of = "2026-08-15T00:00:00Z"

    def test_empty_review_is_honest_and_never_enables_actions(self) -> None:
        report = learning.build_weekly_review([], as_of=self.as_of)

        self.assertEqual(report["basis"]["canonical_posts"], 0)
        self.assertEqual(
            report["strongest_hook_by_goal"]["reach"]["status"],
            "INSUFFICIENT_EVIDENCE",
        )
        self.assertEqual(
            report["critic_alignment"]["within_package_ranking"]["status"],
            "NOT_TESTABLE",
        )
        self.assertIs(report["safety"]["rubric_mutated"], False)
        self.assertEqual(report["safety"]["publishing_status"], "DISABLED")
        self.assertIs(report["safety"]["automatic_linkedin_actions"], False)
        self.assertIs(report["safety"]["contains_full_candidate_body"], False)

    def test_only_organic_72h_is_canonical(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row("canonical", published=published),
            performance_row("early", published=published, checkpoint="24h"),
            performance_row("followup", published=published, checkpoint="7d"),
            performance_row(
                "paid", published=published, channel="paid", non_follower_reach=999_999
            ),
        ]

        contexts = dict(candidate_context(row) for row in rows)
        report = learning.build_weekly_review(
            rows,
            as_of=self.as_of,
            candidate_contexts=contexts,
        )

        self.assertEqual(report["basis"]["canonical_posts"], 1)
        self.assertEqual(report["basis"]["immature_organic_observations"]["24h"], 1)
        self.assertEqual(report["seven_day_followup"]["observations"], 1)
        self.assertIs(report["seven_day_followup"]["excluded_from_calibration"], True)
        self.assertEqual(report["paid_summary"]["observations"], 1)
        self.assertIs(report["paid_summary"]["excluded_from_learning"], True)
        winning = report["strongest_hook_by_goal"]["reach"]["references"]
        self.assertEqual([item["package_id"] for item in winning], ["2026-07-01-canonical"])

    def test_goal_vectors_drive_hook_references_and_preserve_ties(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row(
                "reach-a", published=published, non_follower_reach=500, impressions=800
            ),
            performance_row(
                "reach-b",
                published=published + timedelta(days=1),
                non_follower_reach=500,
                impressions=800,
            ),
            performance_row(
                "reach-c",
                published=published + timedelta(days=2),
                non_follower_reach=500,
                impressions=700,
            ),
            performance_row(
                "authority",
                published=published,
                goal="authority",
                saves=10,
                sends=5,
                reposts=2,
                external_comments=7,
            ),
            performance_row(
                "opportunity",
                published=published,
                goal="opportunity",
                recruiter_inbound=1,
                github_clicks=2,
            ),
        ]

        contexts = dict(candidate_context(row) for row in rows)
        report = learning.build_weekly_review(
            rows,
            as_of=self.as_of,
            candidate_contexts=contexts,
        )

        reach = report["strongest_hook_by_goal"]["reach"]["references"]
        self.assertEqual(
            [item["package_id"] for item in reach],
            ["2026-07-01-reach-a", "2026-07-02-reach-b"],
        )
        authority = report["strongest_hook_by_goal"]["authority"]["references"][0]
        self.assertEqual(authority["actual_outcome"]["values"], [17, 7, 0])
        opportunity = report["strongest_hook_by_goal"]["opportunity"]["references"][0]
        self.assertEqual(opportunity["actual_outcome"]["values"], [1, 2, 0, 0])
        self.assertEqual(reach[0]["observed_hook"]["candidate_angle"], "A decision-led opening")
        structure = report["winning_structure_by_goal"]["reach"]
        self.assertEqual(structure["status"], "OBSERVED_STRUCTURE_CONTEXT")
        self.assertEqual(
            structure["references"][0]["observed_structure"],
            {
                "planned_route": ["incident", "mechanism", "implication"],
                "paragraph_count": 6,
            },
        )
        self.assertIs(report["safety"]["contains_bounded_hook_excerpt"], True)

    def test_winning_hook_and_structure_report_explicit_missing_context(self) -> None:
        row = performance_row(
            "missing-context",
            published=datetime(2026, 7, 1, 12, tzinfo=UTC),
            non_follower_reach=100,
        )
        report = learning.build_weekly_review([row], as_of=self.as_of)
        hook = report["strongest_hook_by_goal"]["reach"]
        structure = report["winning_structure_by_goal"]["reach"]
        self.assertEqual(hook["status"], "OBSERVED_REFERENCE_CONTEXT_GAP")
        self.assertEqual(structure["status"], "OBSERVED_REFERENCE_CONTEXT_GAP")
        self.assertEqual(
            hook["context_gaps"],
            [{"package_id": row["package_id"], "candidate_id": row["candidate_id"]}],
        )
        self.assertEqual(structure["references"], [])

    def test_candidate_context_schema_is_bounded_and_package_linked(self) -> None:
        row = performance_row(
            "context", published=datetime(2026, 7, 1, 12, tzinfo=UTC)
        )
        key, context = candidate_context(row)
        hostile = dict(context)
        hostile["full_candidate_body"] = "private body"
        with self.assertRaisesRegex(ValueError, "candidate contexts"):
            learning.build_weekly_review(
                [row],
                as_of=self.as_of,
                candidate_contexts={key: hostile},
            )
        unknown_key = ("2026-07-01-unknown", "candidate-1")
        with self.assertRaisesRegex(ValueError, "candidate contexts"):
            learning.build_weekly_review(
                [row],
                as_of=self.as_of,
                candidate_contexts={unknown_key: context},
            )

    def test_candidate_context_route_must_match_the_recorded_goal(self) -> None:
        row = performance_row(
            "authority-route",
            published=datetime(2026, 7, 1, 12, tzinfo=UTC),
            goal="authority",
        )
        key, context = candidate_context(row)
        context["structure"]["planned_route"] = [  # type: ignore[index]
            "incident",
            "mechanism",
            "implication",
        ]

        with self.assertRaisesRegex(ValueError, "candidate contexts"):
            learning.build_weekly_review(
                [row],
                as_of=self.as_of,
                candidate_contexts={key: context},
            )

    def test_context_requests_include_only_anchored_canonical_tied_winners(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row(
                "winner-a", published=published, non_follower_reach=500
            ),
            performance_row(
                "winner-unanchored",
                published=published + timedelta(days=1),
                non_follower_reach=500,
                learning_context_fingerprint=None,
            ),
            performance_row(
                "nonleader",
                published=published + timedelta(days=2),
                non_follower_reach=499,
                learning_context_fingerprint="b" * 64,
            ),
            performance_row(
                "late",
                published=published + timedelta(days=3),
                observed_age_hours=120,
                non_follower_reach=999_999,
                learning_context_fingerprint="c" * 64,
            ),
            performance_row(
                "paid",
                published=published + timedelta(days=4),
                channel="paid",
                non_follower_reach=999_999,
                learning_context_fingerprint="d" * 64,
            ),
            performance_row(
                "future-correction",
                published=published + timedelta(days=5),
                updated_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
                non_follower_reach=999_999,
                learning_context_fingerprint="e" * 64,
            ),
        ]

        requests = learning.winning_candidate_context_requests(
            rows, as_of=self.as_of
        )

        self.assertEqual(
            requests,
            [("2026-07-01-winner-a", "candidate-1", "a" * 64)],
        )
        report = learning.build_weekly_review(rows, as_of=self.as_of)
        self.assertEqual(
            report["strongest_hook_by_goal"]["reach"]["context_gaps"],
            [
                {
                    "package_id": "2026-07-01-winner-a",
                    "candidate_id": "candidate-1",
                },
                {
                    "package_id": "2026-07-02-winner-unanchored",
                    "candidate_id": "candidate-1",
                },
            ],
        )

    def test_authority_conversion_and_weakest_signal_are_unweighted(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row(
                "inbound",
                published=published,
                impressions=1_000,
                recruiter_inbound=1,
                github_clicks=3,
                relevant_followers=4,
                profile_visits=20,
            ),
            performance_row(
                "clicks",
                published=published + timedelta(days=1),
                impressions=1_000,
                github_clicks=500,
                relevant_followers=50,
                profile_visits=500,
            ),
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)

        strongest = report["strongest_authority_conversion"]["reach"]["references"]
        self.assertEqual(strongest[0]["package_id"], "2026-07-01-inbound")
        weakest = report["weakest_conversion_signal"]["reach"]
        self.assertEqual(weakest["signals"][0]["name"], "qualified_inbound")
        self.assertEqual(
            weakest["signals"][0]["per_1000_impressions"],
            {"numerator": 1, "denominator": 2},
        )

    def test_zero_impressions_cannot_create_a_conversion_rate(self) -> None:
        row = performance_row(
            "zero", published=datetime(2026, 7, 1, 12, tzinfo=UTC), impressions=0
        )
        report = learning.build_weekly_review([row], as_of=self.as_of)
        self.assertEqual(
            report["weakest_conversion_signal"]["reach"]["reason_code"],
            "zero-impressions",
        )

    def test_conversion_summaries_never_compare_or_aggregate_across_goals(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row(
                "reach",
                published=published,
                impressions=100,
                recruiter_inbound=1,
            ),
            performance_row(
                "authority",
                published=published + timedelta(days=1),
                goal="authority",
                impressions=1_000,
                recruiter_inbound=100,
                github_clicks=100,
            ),
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)

        reach = report["strongest_authority_conversion"]["reach"]
        authority = report["strongest_authority_conversion"]["authority"]
        self.assertEqual(reach["references"][0]["package_id"], "2026-07-01-reach")
        self.assertEqual(
            authority["references"][0]["package_id"], "2026-07-02-authority"
        )
        self.assertEqual(
            report["weakest_conversion_signal"]["reach"]["total_impressions"],
            100,
        )
        self.assertEqual(
            report["weakest_conversion_signal"]["authority"]["total_impressions"],
            1_000,
        )

    def test_late_72h_window_observations_are_not_used_as_comparable_evidence(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row(
                "comparable",
                published=published,
                observed_age_hours=73,
                non_follower_reach=100,
            ),
            performance_row(
                "late",
                published=published + timedelta(days=1),
                observed_age_hours=120,
                non_follower_reach=999_999,
            ),
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)

        self.assertEqual(report["basis"]["canonical_posts"], 1)
        self.assertEqual(
            report["basis"]["late_organic_72h_observations_excluded"], 1
        )
        self.assertEqual(
            report["basis"]["comparison_age_window_hours"],
            {"minimum_inclusive": 72, "maximum_exclusive": 96},
        )
        winners = report["strongest_hook_by_goal"]["reach"]["references"]
        self.assertEqual(winners[0]["package_id"], "2026-07-01-comparable")

    def test_as_of_excludes_a_later_correction(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        row = performance_row(
            "corrected-later",
            published=published,
            updated_at=datetime(2026, 8, 20, 12, tzinfo=UTC),
        )

        report = learning.build_weekly_review([row], as_of=self.as_of)

        self.assertEqual(report["basis"]["canonical_posts"], 0)
        self.assertEqual(
            report["basis"]["as_of_exclusions"]["updated-after-as-of"], 1
        )

    def test_pairwise_critic_alignment_compares_only_within_goal(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row("high-a", published=published, non_follower_reach=400),
            performance_row(
                "high-b",
                published=published + timedelta(days=1),
                non_follower_reach=300,
            ),
            performance_row(
                "low-a",
                published=published + timedelta(days=2),
                lower_axis="middle_escalation",
                non_follower_reach=200,
            ),
            performance_row(
                "low-b",
                published=published + timedelta(days=3),
                lower_axis="hook_strength",
                non_follower_reach=100,
            ),
            performance_row(
                "other-goal",
                published=published,
                goal="authority",
                saves=999,
            ),
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)
        reach = report["critic_alignment"]["cross_post_score_alignment"][0]

        self.assertEqual(reach["posts"], 4)
        self.assertEqual(reach["scorable_pairs"], 4)
        self.assertEqual(reach["concordant_pairs"], 4)
        self.assertEqual(reach["predicted_ties"], 2)
        self.assertEqual(reach["verdict"], "MATCHED")
        self.assertEqual(reach["alignment_fraction"], {"numerator": 4, "denominator": 4})

    def test_inverse_pairwise_order_reports_did_not_match(self) -> None:
        published = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row("high-a", published=published, non_follower_reach=100),
            performance_row(
                "high-b",
                published=published + timedelta(days=1),
                non_follower_reach=200,
            ),
            performance_row(
                "low-a",
                published=published + timedelta(days=2),
                lower_axis="middle_escalation",
                non_follower_reach=300,
            ),
            performance_row(
                "low-b",
                published=published + timedelta(days=3),
                lower_axis="hook_strength",
                non_follower_reach=400,
            ),
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)
        reach = report["critic_alignment"]["cross_post_score_alignment"][0]
        self.assertEqual(reach["verdict"], "DID_NOT_MATCH")
        self.assertEqual(reach["discordant_pairs"], 4)

    def test_calibration_needs_three_posts_and_two_weeks_on_each_side(self) -> None:
        dates = [
            datetime(2026, 7, 1, 12, tzinfo=UTC),
            datetime(2026, 7, 2, 12, tzinfo=UTC),
            datetime(2026, 7, 8, 12, tzinfo=UTC),
        ]
        high = [
            performance_row(f"high-{index}", published=date, non_follower_reach=100)
            for index, date in enumerate(dates, 1)
        ]
        lower_dates = [
            datetime(2026, 7, 3, 12, tzinfo=UTC),
            datetime(2026, 7, 9, 12, tzinfo=UTC),
            datetime(2026, 7, 10, 12, tzinfo=UTC),
        ]
        lower = [
            performance_row(
                f"lower-{index}",
                published=date,
                lower_axis="hook_strength",
                non_follower_reach=300,
            )
            for index, date in enumerate(lower_dates, 1)
        ]

        report = learning.build_weekly_review([*high, *lower], as_of=self.as_of)
        suggestions = report["rubric_calibration"]["recommendations"]

        hook = next(item for item in suggestions if item["dimension"] == "hook_strength")
        self.assertEqual(hook["code"], "REVIEW_AXIS_CALIBRATION")
        self.assertEqual(hook["signal"], "lower-score-group-outperformed")
        self.assertEqual(hook["high_score_group"]["posts"], 3)
        self.assertEqual(hook["lower_score_group"]["publication_weeks"], 2)
        self.assertEqual(len(hook["weekly_comparisons"]), 2)
        self.assertEqual(
            {item["verdict"] for item in hook["weekly_comparisons"]},
            {"LOWER_SCORE_OUTPERFORMED"},
        )
        self.assertEqual(hook["action"], "human-review-only")
        self.assertIs(report["rubric_calibration"]["rubric_mutated"], False)

    def test_calibration_does_not_fire_from_one_week_or_two_posts(self) -> None:
        base = datetime(2026, 7, 1, 12, tzinfo=UTC)
        rows = [
            performance_row(f"high-{index}", published=base + timedelta(days=index))
            for index in range(2)
        ] + [
            performance_row(
                f"lower-{index}",
                published=base + timedelta(days=index + 2),
                lower_axis="hook_strength",
                non_follower_reach=999,
            )
            for index in range(2)
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)
        self.assertEqual(report["rubric_calibration"]["recommendations"], [])
        hook_gap = next(
            item
            for item in report["rubric_calibration"]["evidence_gaps"]
            if item["dimension"] == "hook_strength"
        )
        self.assertIn("high-score-posts-below-minimum", hook_gap["reason_codes"])
        self.assertIn("lower-score-posts-below-minimum", hook_gap["reason_codes"])

    def test_calibration_requires_the_reversal_to_repeat_in_each_shared_week(self) -> None:
        high = [
            performance_row(
                "high-1",
                published=datetime(2026, 7, 1, 12, tzinfo=UTC),
                non_follower_reach=100,
            ),
            performance_row(
                "high-2",
                published=datetime(2026, 7, 2, 12, tzinfo=UTC),
                non_follower_reach=110,
            ),
            performance_row(
                "high-3",
                published=datetime(2026, 7, 8, 12, tzinfo=UTC),
                non_follower_reach=1_000,
            ),
        ]
        lower = [
            performance_row(
                "lower-1",
                published=datetime(2026, 7, 3, 12, tzinfo=UTC),
                lower_axis="hook_strength",
                non_follower_reach=200,
            ),
            performance_row(
                "lower-2",
                published=datetime(2026, 7, 4, 12, tzinfo=UTC),
                lower_axis="hook_strength",
                non_follower_reach=210,
            ),
            performance_row(
                "lower-3",
                published=datetime(2026, 7, 9, 12, tzinfo=UTC),
                lower_axis="hook_strength",
                non_follower_reach=1,
            ),
        ]

        report = learning.build_weekly_review([*high, *lower], as_of=self.as_of)

        self.assertFalse(
            any(
                item["dimension"] == "hook_strength"
                for item in report["rubric_calibration"]["recommendations"]
            )
        )
        assessment = next(
            item
            for item in report["rubric_calibration"]["assessments"]
            if item["dimension"] == "hook_strength"
        )
        self.assertEqual(assessment["code"], "ASSESSED_NO_REPEATED_REVERSAL")
        self.assertIn(
            "lower-score-group-did-not-outperform-in-every-shared-week",
            assessment["reason_codes"],
        )
        self.assertEqual(
            [item["verdict"] for item in assessment["weekly_comparisons"]],
            ["LOWER_SCORE_OUTPERFORMED", "HIGH_SCORE_OUTPERFORMED"],
        )

    def test_fully_evaluated_non_reversal_is_explicit(self) -> None:
        dates = [
            datetime(2026, 7, 1, 12, tzinfo=UTC),
            datetime(2026, 7, 2, 12, tzinfo=UTC),
            datetime(2026, 7, 8, 12, tzinfo=UTC),
        ]
        high = [
            performance_row(
                f"high-{index}", published=date, non_follower_reach=300
            )
            for index, date in enumerate(dates, 1)
        ]
        lower_dates = [
            datetime(2026, 7, 3, 12, tzinfo=UTC),
            datetime(2026, 7, 9, 12, tzinfo=UTC),
            datetime(2026, 7, 10, 12, tzinfo=UTC),
        ]
        lower = [
            performance_row(
                f"lower-{index}",
                published=date,
                lower_axis="hook_strength",
                non_follower_reach=100,
            )
            for index, date in enumerate(lower_dates, 1)
        ]

        report = learning.build_weekly_review([*high, *lower], as_of=self.as_of)
        assessment = next(
            item
            for item in report["rubric_calibration"]["assessments"]
            if item["dimension"] == "hook_strength"
        )
        self.assertEqual(assessment["action"], "no-rubric-change")
        self.assertIn(
            "pooled-lower-score-group-did-not-outperform",
            assessment["reason_codes"],
        )

    def test_missing_output_format_is_insufficient_for_calibration(self) -> None:
        high_dates = [
            datetime(2026, 7, 1, 12, tzinfo=UTC),
            datetime(2026, 7, 2, 12, tzinfo=UTC),
            datetime(2026, 7, 8, 12, tzinfo=UTC),
        ]
        lower_dates = [
            datetime(2026, 7, 3, 12, tzinfo=UTC),
            datetime(2026, 7, 9, 12, tzinfo=UTC),
            datetime(2026, 7, 10, 12, tzinfo=UTC),
        ]
        rows = [
            performance_row(
                f"high-{index}",
                published=date,
                output_format=None,
                non_follower_reach=100,
            )
            for index, date in enumerate(high_dates, 1)
        ] + [
            performance_row(
                f"lower-{index}",
                published=date,
                output_format=None,
                lower_axis="hook_strength",
                non_follower_reach=300,
            )
            for index, date in enumerate(lower_dates, 1)
        ]

        report = learning.build_weekly_review(rows, as_of=self.as_of)

        self.assertEqual(report["rubric_calibration"]["recommendations"], [])
        hook_gap = next(
            item
            for item in report["rubric_calibration"]["evidence_gaps"]
            if item["dimension"] == "hook_strength"
        )
        self.assertIn("output-format-not-selected", hook_gap["reason_codes"])

    def test_rows_are_not_mutated_and_extra_private_fields_fail_closed(self) -> None:
        row = performance_row(
            "private", published=datetime(2026, 7, 1, 12, tzinfo=UTC)
        )
        original = copy.deepcopy(row)
        report = learning.build_weekly_review([row], as_of=self.as_of)
        self.assertEqual(row, original)
        payload = json.dumps(report, sort_keys=True)
        self.assertNotIn("candidate_text", payload)
        self.assertNotIn("source_url", payload)

        hostile = {**row, "candidate_text": "private body sentinel"}
        with self.assertRaisesRegex(ValueError, "invalid schema"):
            learning.build_weekly_review([hostile], as_of=self.as_of)

    def test_duplicate_or_changed_publication_context_fails_closed(self) -> None:
        row = performance_row(
            "duplicate", published=datetime(2026, 7, 1, 12, tzinfo=UTC)
        )
        with self.assertRaisesRegex(ValueError, "duplicate observation"):
            learning.build_weekly_review([row, dict(row)], as_of=self.as_of)

        changed = performance_row(
            "duplicate",
            published=datetime(2026, 7, 1, 12, tzinfo=UTC),
            checkpoint="7d",
        )
        changed["goal"] = "authority"
        with self.assertRaisesRegex(ValueError, "immutable publication context"):
            learning.build_weekly_review([row, changed], as_of=self.as_of)

    def test_private_writer_is_owner_only_idempotent_and_no_clobber(self) -> None:
        row = performance_row(
            "report", published=datetime(2026, 7, 1, 12, tzinfo=UTC)
        )
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "private"
            parent.mkdir(mode=0o700)
            root = parent / "weekly-reviews"

            result = learning.write_weekly_review(
                [row],
                as_of=self.as_of,
                output_root=root,
                _allow_test_output_root=True,
            )
            path = result["path"]
            self.assertIsInstance(path, Path)
            self.assertEqual(stat.S_IMODE(root.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), result["report"]
            )
            repeated = learning.write_weekly_review(
                [row],
                as_of=self.as_of,
                output_root=root,
                _allow_test_output_root=True,
            )
            self.assertEqual(repeated["path"], path)
            self.assertEqual(repeated["report"], result["report"])

            path.write_text("{}\n", encoding="utf-8")
            os.chmod(path, 0o600)
            with self.assertRaisesRegex(workflow.WorkflowError, "different weekly review"):
                learning.write_weekly_review(
                    [row],
                    as_of=self.as_of,
                    output_root=root,
                    _allow_test_output_root=True,
                )

    def test_private_writer_rejects_unapproved_roots_and_symlinks(self) -> None:
        row = performance_row(
            "report", published=datetime(2026, 7, 1, 12, tzinfo=UTC)
        )
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary) / "private"
            parent.mkdir(mode=0o700)
            root = parent / "weekly-reviews"
            with self.assertRaisesRegex(workflow.WorkflowError, "fixed private"):
                learning.write_weekly_review([row], as_of=self.as_of, output_root=root)

            target = parent / "target"
            target.mkdir(mode=0o700)
            root.symlink_to(target, target_is_directory=True)
            with self.assertRaisesRegex(workflow.WorkflowError, "written safely"):
                learning.write_weekly_review(
                    [row],
                    as_of=self.as_of,
                    output_root=root,
                    _allow_test_output_root=True,
                )

    def test_private_writer_rejects_an_intermediate_symlink_escape(self) -> None:
        row = performance_row(
            "report", published=datetime(2026, 7, 1, 12, tzinfo=UTC)
        )
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary) / "repository"
            base.mkdir(mode=0o700)
            outside = Path(temporary) / "outside"
            private = outside / "private"
            private.mkdir(mode=0o700, parents=True)
            (base / "data").symlink_to(outside, target_is_directory=True)
            root = base / "data" / "private" / "weekly-reviews"

            with self.assertRaisesRegex(workflow.WorkflowError, "written safely"):
                learning.write_weekly_review(
                    [row],
                    as_of=self.as_of,
                    output_root=root,
                    _allow_test_output_root=True,
                )

            self.assertTrue((base / "data").is_symlink())
            self.assertEqual(list(private.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
