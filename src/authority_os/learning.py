"""Build deterministic weekly learning reports from private performance rows.

The learner is intentionally observation-only. It accepts only bounded hook and
structure snapshots from validated private packages, never changes the Critic
rubric, and never performs a publishing action.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import stat
import unicodedata
from datetime import datetime
from fractions import Fraction
from itertools import combinations
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from . import storage, workflow


REPORT_SCHEMA_VERSION = 1
DEFAULT_REPORT_ROOT = workflow.DEFAULT_PRIVATE_DATA / "weekly-reviews"
MAX_REPORT_BYTES = 1024 * 1024
MIN_CALIBRATION_POSTS = 3
MIN_CALIBRATION_WEEKS = 2
MIN_CANONICAL_AGE_HOURS = 72
MAX_CANONICAL_AGE_HOURS = 96

_ROW_FIELDS = frozenset(
    (
        *storage.PUBLISHED_POST_FIELDS,
        *storage.PERFORMANCE_OBSERVATION_FIELDS,
        "recorded_at",
        "updated_at",
    )
)
_GOALS = ("reach", "authority", "opportunity")
_CHECKPOINT_ORDER = {name: index for index, name in enumerate(storage.PERFORMANCE_CHECKPOINTS)}
_CRITIC_VECTOR_FIELDS = ("critic_effective_total", "critic_raw_total")
_CALIBRATION_DIMENSIONS = (*workflow.CRITIC_AXES, "critic_effective_total")
_CONTEXT_FIELDS = frozenset(
    {
        "package_id",
        "candidate_id",
        "hook_excerpt",
        "hook_excerpt_truncated",
        "candidate_angle",
        "structure",
    }
)
_FILE_FLAGS = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)
_DIRECTORY_FLAGS = (
    os.O_RDONLY
    | getattr(os, "O_DIRECTORY", 0)
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
)


def _normalised_timestamp(value: object, *, field: str) -> str:
    return storage.normalise_performance_timestamp(value, field=field)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _observation_age_seconds(row: Mapping[str, object]) -> float:
    return (
        _timestamp(str(row["observed_at"]))
        - _timestamp(str(row["published_at"]))
    ).total_seconds()


def _validate_rows(rows: Iterable[Mapping[str, object]]) -> list[dict[str, object]]:
    validated_rows: list[dict[str, object]] = []
    keys: set[tuple[str, str, str]] = set()
    contexts: dict[str, tuple[object, ...]] = {}
    for raw in rows:
        if not isinstance(raw, Mapping) or set(raw) != _ROW_FIELDS:
            raise ValueError("weekly learning row has an invalid schema")
        recorded_at = _normalised_timestamp(raw["recorded_at"], field="recorded_at")
        updated_at = _normalised_timestamp(raw["updated_at"], field="updated_at")
        if updated_at < recorded_at:
            raise ValueError("weekly learning row predates its first recording")
        record = {
            field: raw[field]
            for field in storage.PERFORMANCE_RECORD_FIELDS
            if field != "recorded_at"
        }
        # A correction retains the original recorded_at in SQLite.  Its current
        # snapshot is instead bounded by updated_at.
        record["recorded_at"] = updated_at
        validated = storage.validate_performance_record(
            record,
            allow_unanchored_learning_context=True,
        )
        validated["recorded_at"] = recorded_at
        validated["updated_at"] = updated_at
        if validated["critic_band"] != "advance-to-gates":
            raise ValueError("weekly learning accepts only gate-eligible Critic snapshots")
        if bool(validated["was_revised"]) and int(validated["revision_count"]) != 1:
            raise ValueError("weekly learning revision provenance is inconsistent")
        if str(validated["package_id"])[:10] != str(validated["package_created_at"])[:10]:
            raise ValueError("weekly learning package date provenance is inconsistent")
        key = (
            str(validated["package_id"]),
            str(validated["checkpoint"]),
            str(validated["channel"]),
        )
        if key in keys:
            raise ValueError("weekly learning input contains a duplicate observation")
        keys.add(key)
        context = tuple(validated[field] for field in storage.PUBLISHED_POST_FIELDS)
        previous = contexts.setdefault(str(validated["package_id"]), context)
        if previous != context:
            raise ValueError("weekly learning input changes immutable publication context")
        validated_rows.append(validated)
    return validated_rows


def _bounded_context_text(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise ValueError("weekly learning candidate context is invalid")
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs", "Zl", "Zp"}
        and character not in "\n\t"
        for character in value
    ):
        raise ValueError("weekly learning candidate context is invalid")
    return value


def _validate_candidate_contexts(
    contexts: Mapping[tuple[str, str], Mapping[str, object]] | None,
    *,
    valid_goals: Mapping[tuple[str, str], str],
) -> dict[tuple[str, str], dict[str, object]]:
    if contexts is None:
        return {}
    if not isinstance(contexts, Mapping):
        raise ValueError("weekly learning candidate contexts are invalid")
    validated: dict[tuple[str, str], dict[str, object]] = {}
    for key, raw in contexts.items():
        if (
            not isinstance(key, tuple)
            or len(key) != 2
            or any(not isinstance(part, str) or not part for part in key)
            or key not in valid_goals
            or not isinstance(raw, Mapping)
            or set(raw) != _CONTEXT_FIELDS
            or raw.get("package_id") != key[0]
            or raw.get("candidate_id") != key[1]
            or type(raw.get("hook_excerpt_truncated")) is not bool
        ):
            raise ValueError("weekly learning candidate contexts are invalid")
        structure = raw.get("structure")
        if not isinstance(structure, Mapping) or set(structure) != {
            "planned_route",
            "paragraph_count",
        }:
            raise ValueError("weekly learning candidate contexts are invalid")
        route = structure.get("planned_route")
        paragraphs = structure.get("paragraph_count")
        goal = valid_goals[key]
        if (
            not isinstance(route, list)
            or not 2 <= len(route) <= 8
            or len(route) != len(set(route))
            or any(
                not isinstance(stage, str)
                or len(stage) > 80
                or re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", stage) is None
                for stage in route
            )
            or route != list(workflow.GOAL_ROUTES[goal]["narrative_route"])
            or type(paragraphs) is not int
            or not 1 <= paragraphs <= 100
        ):
            raise ValueError("weekly learning candidate contexts are invalid")
        validated[key] = {
            "package_id": key[0],
            "candidate_id": key[1],
            "hook_excerpt": _bounded_context_text(
                raw["hook_excerpt"], maximum=280
            ),
            "hook_excerpt_truncated": raw["hook_excerpt_truncated"],
            "candidate_angle": _bounded_context_text(
                raw["candidate_angle"], maximum=500
            ),
            "structure": {
                "planned_route": list(route),
                "paragraph_count": paragraphs,
            },
        }
    return validated


def _qualified_inbound(row: Mapping[str, object]) -> int:
    return sum(
        int(row[field])
        for field in (
            "recruiter_inbound",
            "founder_advisor_inbound",
            "speaking_podcast_inbound",
        )
    )


def _goal_outcome(row: Mapping[str, object]) -> tuple[tuple[str, ...], tuple[int, ...]]:
    goal = str(row["goal"])
    if goal == "reach":
        return (
            ("non_follower_reach", "impressions"),
            (int(row["non_follower_reach"]), int(row["impressions"])),
        )
    if goal == "authority":
        return (
            ("durable_actions", "external_comments", "profile_visits"),
            (
                int(row["saves"]) + int(row["sends"]) + int(row["reposts"]),
                int(row["external_comments"]),
                int(row["profile_visits"]),
            ),
        )
    if goal == "opportunity":
        return (
            (
                "qualified_inbound",
                "github_clicks",
                "relevant_followers",
                "profile_visits",
            ),
            (
                _qualified_inbound(row),
                int(row["github_clicks"]),
                int(row["relevant_followers"]),
                int(row["profile_visits"]),
            ),
        )
    raise ValueError("weekly learning goal is invalid")


def _outcome_document(row: Mapping[str, object]) -> dict[str, object]:
    names, values = _goal_outcome(row)
    return {"components": list(names), "values": list(values)}


def _critic_vector(row: Mapping[str, object]) -> tuple[int, ...]:
    return tuple(int(row[field]) for field in _CRITIC_VECTOR_FIELDS)


def _reference(row: Mapping[str, object], *, include_hook: bool) -> dict[str, object]:
    reference: dict[str, object] = {
        "package_id": row["package_id"],
        "candidate_id": row["candidate_id"],
        "goal": row["goal"],
        "output_format": row["output_format"],
        "observed_at": row["observed_at"],
        "actual_outcome": _outcome_document(row),
    }
    if include_hook:
        reference["critic_hook_strength"] = row["hook_strength"]
    return reference


def _goal_winners(
    rows: Sequence[Mapping[str, object]], goal: str
) -> list[Mapping[str, object]]:
    cohort = [row for row in rows if row["goal"] == goal]
    if not cohort:
        return []
    strongest = max(_goal_outcome(row)[1] for row in cohort)
    return sorted(
        (row for row in cohort if _goal_outcome(row)[1] == strongest),
        key=lambda row: (str(row["package_id"]), str(row["candidate_id"])),
    )


def _strongest_hooks(
    rows: Sequence[Mapping[str, object]],
    contexts: Mapping[tuple[str, str], Mapping[str, object]],
) -> dict[str, object]:
    report: dict[str, object] = {}
    for goal in _GOALS:
        winners = _goal_winners(rows, goal)
        if not winners:
            report[goal] = {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason_code": "no-mature-organic-posts",
                "references": [],
                "context_gaps": [],
            }
            continue
        references: list[dict[str, object]] = []
        missing: list[dict[str, str]] = []
        for row in winners:
            reference = _reference(row, include_hook=True)
            key = (str(row["package_id"]), str(row["candidate_id"]))
            context = contexts.get(key)
            if context is None:
                missing.append({"package_id": key[0], "candidate_id": key[1]})
            else:
                reference["observed_hook"] = {
                    "excerpt": context["hook_excerpt"],
                    "excerpt_truncated": context["hook_excerpt_truncated"],
                    "candidate_angle": context["candidate_angle"],
                }
            references.append(reference)
        report[goal] = {
            "status": (
                "OBSERVED_HOOK_CONTEXT"
                if not missing
                else "OBSERVED_REFERENCE_CONTEXT_GAP"
            ),
            "reason_code": "top-observed-outcome-not-causal",
            "references": references,
            "context_gaps": missing,
        }
    return report


def _winning_structures(
    rows: Sequence[Mapping[str, object]],
    contexts: Mapping[tuple[str, str], Mapping[str, object]],
) -> dict[str, object]:
    report: dict[str, object] = {}
    for goal in _GOALS:
        winners = _goal_winners(rows, goal)
        if not winners:
            report[goal] = {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason_code": "no-mature-organic-posts",
                "references": [],
                "context_gaps": [],
            }
            continue
        references: list[dict[str, object]] = []
        gaps: list[dict[str, str]] = []
        for row in winners:
            key = (str(row["package_id"]), str(row["candidate_id"]))
            context = contexts.get(key)
            if context is None:
                gaps.append({"package_id": key[0], "candidate_id": key[1]})
                continue
            references.append(
                {
                    **_reference(row, include_hook=False),
                    "candidate_angle": context["candidate_angle"],
                    "observed_structure": dict(context["structure"]),
                }
            )
        report[goal] = {
            "status": (
                "OBSERVED_STRUCTURE_CONTEXT"
                if references and not gaps
                else "OBSERVED_REFERENCE_CONTEXT_GAP"
            ),
            "reason_code": "top-observed-outcome-not-causal",
            "references": references,
            "context_gaps": gaps,
        }
    return report


def _authority_conversion(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    def vector(row: Mapping[str, object]) -> tuple[int, ...]:
        return (
            _qualified_inbound(row),
            int(row["github_clicks"]),
            int(row["relevant_followers"]),
            int(row["profile_visits"]),
        )

    report: dict[str, object] = {}
    for goal in _GOALS:
        cohort = [row for row in rows if row["goal"] == goal]
        if not cohort:
            report[goal] = {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason_code": "no-mature-organic-posts-for-goal",
                "references": [],
            }
            continue
        strongest = max(vector(row) for row in cohort)
        winners = sorted(
            (row for row in cohort if vector(row) == strongest),
            key=lambda row: (str(row["package_id"]), str(row["candidate_id"])),
        )
        report[goal] = {
            "status": "OBSERVED_REFERENCE",
            "components": [
                "qualified_inbound",
                "github_clicks",
                "relevant_followers",
                "profile_visits",
            ],
            "references": [
                {
                    "package_id": row["package_id"],
                    "candidate_id": row["candidate_id"],
                    "goal": row["goal"],
                    "values": list(vector(row)),
                }
                for row in winners
            ],
        }
    return report


def _weakest_conversion(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    report: dict[str, object] = {}
    for goal in _GOALS:
        cohort = [row for row in rows if row["goal"] == goal]
        impressions = sum(int(row["impressions"]) for row in cohort)
        if not cohort or impressions == 0:
            report[goal] = {
                "status": "INSUFFICIENT_EVIDENCE",
                "reason_code": (
                    "no-mature-organic-posts-for-goal"
                    if not cohort
                    else "zero-impressions"
                ),
                "signals": [],
            }
            continue
        totals = {
            "profile_visits": sum(int(row["profile_visits"]) for row in cohort),
            "relevant_followers": sum(
                int(row["relevant_followers"]) for row in cohort
            ),
            "github_clicks": sum(int(row["github_clicks"]) for row in cohort),
            "qualified_inbound": sum(_qualified_inbound(row) for row in cohort),
        }
        rates = {
            name: Fraction(value * 1000, impressions)
            for name, value in totals.items()
        }
        weakest = min(rates.values())
        tied = sorted(name for name, rate in rates.items() if rate == weakest)
        report[goal] = {
            "status": "OBSERVED_SIGNAL",
            "reason_code": "not-a-causal-funnel",
            "total_impressions": impressions,
            "signals": [
                {
                    "name": name,
                    "observed_total": totals[name],
                    "per_1000_impressions": {
                        "numerator": rates[name].numerator,
                        "denominator": rates[name].denominator,
                    },
                }
                for name in tied
            ],
        }
    return report


def _critic_alignment(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_goal: list[dict[str, object]] = []
    for goal in _GOALS:
        cohort = sorted(
            (row for row in rows if row["goal"] == goal),
            key=lambda row: str(row["package_id"]),
        )
        counts = {
            "total_pairs": 0,
            "scorable_pairs": 0,
            "concordant_pairs": 0,
            "discordant_pairs": 0,
            "predicted_ties": 0,
            "actual_ties": 0,
        }
        for left, right in combinations(cohort, 2):
            counts["total_pairs"] += 1
            predicted_left = _critic_vector(left)
            predicted_right = _critic_vector(right)
            actual_left = _goal_outcome(left)[1]
            actual_right = _goal_outcome(right)[1]
            if predicted_left == predicted_right:
                counts["predicted_ties"] += 1
                continue
            if actual_left == actual_right:
                counts["actual_ties"] += 1
                continue
            counts["scorable_pairs"] += 1
            if (predicted_left > predicted_right) == (actual_left > actual_right):
                counts["concordant_pairs"] += 1
            else:
                counts["discordant_pairs"] += 1
        if len(cohort) < 3 or counts["scorable_pairs"] < 3:
            verdict = "INSUFFICIENT_EVIDENCE"
        elif counts["concordant_pairs"] > counts["discordant_pairs"]:
            verdict = "MATCHED"
        elif counts["concordant_pairs"] < counts["discordant_pairs"]:
            verdict = "DID_NOT_MATCH"
        else:
            verdict = "MIXED"
        by_goal.append(
            {
                "goal": goal,
                "posts": len(cohort),
                **counts,
                "verdict": verdict,
                "alignment_fraction": {
                    "numerator": counts["concordant_pairs"],
                    "denominator": counts["scorable_pairs"],
                },
            }
        )
    return {
        "within_package_ranking": {
            "status": "NOT_TESTABLE",
            "reason_code": "one-observed-candidate-per-package",
        },
        "cross_post_score_alignment": by_goal,
    }


def _iso_week(row: Mapping[str, object]) -> tuple[int, int]:
    calendar = _timestamp(str(row["published_at"])).date().isocalendar()
    return (calendar.year, calendar.week)


def _iso_weeks(rows: Sequence[Mapping[str, object]]) -> set[tuple[int, int]]:
    return {_iso_week(row) for row in rows}


def _median(values: Sequence[int]) -> Fraction:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return Fraction(ordered[middle], 1)
    return Fraction(ordered[middle - 1] + ordered[middle], 2)


def _median_outcome(
    rows: Sequence[Mapping[str, object]],
) -> tuple[tuple[str, ...], tuple[Fraction, ...]]:
    names = _goal_outcome(rows[0])[0]
    vectors = [_goal_outcome(row)[1] for row in rows]
    return names, tuple(
        _median([vector[index] for vector in vectors])
        for index in range(len(names))
    )


def _fraction_document(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _group_document(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    names, medians = _median_outcome(rows)
    return {
        "posts": len(rows),
        "publication_weeks": len(_iso_weeks(rows)),
        "median_outcome": {
            "components": list(names),
            "values": [_fraction_document(value) for value in medians],
        },
    }


def _weekly_calibration_comparisons(
    high: Sequence[Mapping[str, object]],
    lower: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    comparisons: list[dict[str, object]] = []
    for year, week in sorted(_iso_weeks(high) & _iso_weeks(lower)):
        high_week = [row for row in high if _iso_week(row) == (year, week)]
        lower_week = [row for row in lower if _iso_week(row) == (year, week)]
        _names, high_median = _median_outcome(high_week)
        _names, lower_median = _median_outcome(lower_week)
        if lower_median > high_median:
            verdict = "LOWER_SCORE_OUTPERFORMED"
        elif lower_median < high_median:
            verdict = "HIGH_SCORE_OUTPERFORMED"
        else:
            verdict = "TIED"
        comparisons.append(
            {
                "iso_week": f"{year}-W{week:02d}",
                "verdict": verdict,
                "high_score_group": _group_document(high_week),
                "lower_score_group": _group_document(lower_week),
            }
        )
    return comparisons


def _rubric_calibration(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    recommendations: list[dict[str, object]] = []
    evidence_gaps: list[dict[str, object]] = []
    assessments: list[dict[str, object]] = []
    formats = sorted(
        {(str(row["goal"]), row["output_format"]) for row in rows},
        key=lambda item: (item[0], "" if item[1] is None else str(item[1])),
    )
    for goal, output_format in formats:
        cohort = [
            row
            for row in rows
            if row["goal"] == goal and row["output_format"] == output_format
        ]
        for dimension in _CALIBRATION_DIMENSIONS:
            high_value = 25 if dimension == "critic_effective_total" else 5
            high = [row for row in cohort if int(row[dimension]) == high_value]
            lower = [row for row in cohort if int(row[dimension]) < high_value]
            shared_weeks = _iso_weeks(high) & _iso_weeks(lower)
            weekly_comparisons = _weekly_calibration_comparisons(high, lower)
            reasons: list[str] = []
            if output_format is None:
                reasons.append("output-format-not-selected")
            if len(high) < MIN_CALIBRATION_POSTS:
                reasons.append("high-score-posts-below-minimum")
            if len(lower) < MIN_CALIBRATION_POSTS:
                reasons.append("lower-score-posts-below-minimum")
            if len(_iso_weeks(high)) < MIN_CALIBRATION_WEEKS:
                reasons.append("high-score-weeks-below-minimum")
            if len(_iso_weeks(lower)) < MIN_CALIBRATION_WEEKS:
                reasons.append("lower-score-weeks-below-minimum")
            if len(shared_weeks) < MIN_CALIBRATION_WEEKS:
                reasons.append("shared-score-weeks-below-minimum")
            base = {
                "goal": goal,
                "output_format": output_format,
                "dimension": dimension,
            }
            if reasons:
                evidence_gaps.append(
                    {
                        **base,
                        "reason_codes": reasons,
                        "high_score_posts": len(high),
                        "lower_score_posts": len(lower),
                        "high_score_weeks": len(_iso_weeks(high)),
                        "lower_score_weeks": len(_iso_weeks(lower)),
                        "shared_score_weeks": len(shared_weeks),
                        "weekly_comparisons": weekly_comparisons,
                    }
                )
                continue
            _names, high_median = _median_outcome(high)
            _names, lower_median = _median_outcome(lower)
            pooled_reversal = lower_median > high_median
            repeated_reversal = all(
                comparison["verdict"] == "LOWER_SCORE_OUTPERFORMED"
                for comparison in weekly_comparisons
            )
            if pooled_reversal and repeated_reversal:
                recommendations.append(
                    {
                        **base,
                        "code": (
                            "REVIEW_TOTAL_THRESHOLD"
                            if dimension == "critic_effective_total"
                            else "REVIEW_AXIS_CALIBRATION"
                        ),
                        "signal": "lower-score-group-outperformed",
                        "high_score_group": _group_document(high),
                        "lower_score_group": _group_document(lower),
                        "weekly_comparisons": weekly_comparisons,
                        "action": "human-review-only",
                    }
                )
            else:
                no_reversal_reasons: list[str] = []
                if not pooled_reversal:
                    no_reversal_reasons.append(
                        "pooled-lower-score-group-did-not-outperform"
                    )
                if not repeated_reversal:
                    no_reversal_reasons.append(
                        "lower-score-group-did-not-outperform-in-every-shared-week"
                    )
                assessments.append(
                    {
                        **base,
                        "code": "ASSESSED_NO_REPEATED_REVERSAL",
                        "reason_codes": no_reversal_reasons,
                        "high_score_group": _group_document(high),
                        "lower_score_group": _group_document(lower),
                        "weekly_comparisons": weekly_comparisons,
                        "action": "no-rubric-change",
                    }
                )
    return {
        "minimum_posts_per_score_cohort": MIN_CALIBRATION_POSTS,
        "minimum_publication_weeks_per_score_cohort": MIN_CALIBRATION_WEEKS,
        "minimum_shared_publication_weeks": MIN_CALIBRATION_WEEKS,
        "recommendations": recommendations,
        "evidence_gaps": evidence_gaps,
        "assessments": assessments,
        "rubric_mutated": False,
    }


def _metric_totals(rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    return {
        metric: sum(int(row[metric]) for row in rows)
        for metric in storage.PERFORMANCE_METRICS
    }


def _paid_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    checkpoints: list[dict[str, object]] = []
    for checkpoint in storage.PERFORMANCE_CHECKPOINTS:
        cohort = [row for row in rows if row["checkpoint"] == checkpoint]
        if cohort:
            checkpoints.append(
                {
                    "checkpoint": checkpoint,
                    "observations": len(cohort),
                    "unique_posts": len({str(row["package_id"]) for row in cohort}),
                    "metric_totals": _metric_totals(cohort),
                }
            )
    return {
        "excluded_from_learning": True,
        "observations": len(rows),
        "unique_posts": len({str(row["package_id"]) for row in rows}),
        "checkpoints": checkpoints,
    }


def _seven_day_summary(rows: Sequence[Mapping[str, object]]) -> dict[str, object]:
    by_goal: list[dict[str, object]] = []
    for goal in _GOALS:
        cohort = [row for row in rows if row["goal"] == goal]
        if not cohort:
            continue
        names = _goal_outcome(cohort[0])[0]
        vectors = [_goal_outcome(row)[1] for row in cohort]
        by_goal.append(
            {
                "goal": goal,
                "posts": len(cohort),
                "outcome_totals": {
                    "components": list(names),
                    "values": [
                        sum(vector[index] for vector in vectors)
                        for index in range(len(names))
                    ],
                },
            }
        )
    return {
        "separate_from_canonical_learning": True,
        "excluded_from_calibration": True,
        "observations": len(rows),
        "unique_posts": len({str(row["package_id"]) for row in rows}),
        "by_goal": by_goal,
    }


def _visible_rows(
    rows: Sequence[dict[str, object]], as_of_moment: datetime
) -> tuple[list[dict[str, object]], dict[str, int]]:
    visible: list[dict[str, object]] = []
    excluded = {
        "package-created-after-as-of": 0,
        "published-after-as-of": 0,
        "observed-after-as-of": 0,
        "updated-after-as-of": 0,
    }
    for row in rows:
        reason: str | None = None
        for field, code in (
            ("package_created_at", "package-created-after-as-of"),
            ("published_at", "published-after-as-of"),
            ("observed_at", "observed-after-as-of"),
            ("updated_at", "updated-after-as-of"),
        ):
            if _timestamp(str(row[field])) > as_of_moment:
                reason = code
                break
        if reason is None:
            visible.append(row)
        else:
            excluded[reason] += 1
    return visible, excluded


def _canonical_rows(
    rows: Sequence[Mapping[str, object]],
) -> list[Mapping[str, object]]:
    canonical = [
        row
        for row in rows
        if row["channel"] == "organic"
        and row["checkpoint"] == "72h"
        and MIN_CANONICAL_AGE_HOURS * 3600
        <= _observation_age_seconds(row)
        < MAX_CANONICAL_AGE_HOURS * 3600
    ]
    canonical.sort(
        key=lambda row: (str(row["published_at"]), str(row["package_id"]))
    )
    return canonical


def winning_candidate_context_requests(
    rows: Iterable[Mapping[str, object]], *, as_of: object
) -> list[tuple[str, str, str]]:
    """Select only provenance-anchored canonical winners whose context may be read."""

    as_of_text = _normalised_timestamp(as_of, field="as_of")
    visible, _excluded = _visible_rows(
        _validate_rows(rows), _timestamp(as_of_text)
    )
    canonical = _canonical_rows(visible)
    requests: list[tuple[str, str, str]] = []
    for goal in _GOALS:
        for row in _goal_winners(canonical, goal):
            fingerprint = row["learning_context_fingerprint"]
            if fingerprint is None:
                continue
            requests.append(
                (
                    str(row["package_id"]),
                    str(row["candidate_id"]),
                    str(fingerprint),
                )
            )
    return requests


def build_weekly_review(
    rows: Iterable[Mapping[str, object]],
    *,
    as_of: object,
    candidate_contexts: Mapping[
        tuple[str, str], Mapping[str, object]
    ] | None = None,
) -> dict[str, object]:
    """Build one reproducible review without mutating the rows or the rubric."""

    as_of_text = _normalised_timestamp(as_of, field="as_of")
    as_of_moment = _timestamp(as_of_text)
    validated_rows = _validate_rows(rows)
    valid_context_goals = {
        (str(row["package_id"]), str(row["candidate_id"])): str(row["goal"])
        for row in validated_rows
        if row["learning_context_fingerprint"] is not None
    }
    contexts = _validate_candidate_contexts(
        candidate_contexts,
        valid_goals=valid_context_goals,
    )
    visible, excluded = _visible_rows(validated_rows, as_of_moment)
    organic_72h = [
        row
        for row in visible
        if row["channel"] == "organic" and row["checkpoint"] == "72h"
    ]
    canonical = _canonical_rows(visible)
    late_72h = [
        row
        for row in organic_72h
        if _observation_age_seconds(row) >= MAX_CANONICAL_AGE_HOURS * 3600
    ]
    seven_day = [
        row
        for row in visible
        if row["channel"] == "organic" and row["checkpoint"] == "7d"
    ]
    paid = [row for row in visible if row["channel"] == "paid"]
    immature = {
        checkpoint: sum(
            row["channel"] == "organic" and row["checkpoint"] == checkpoint
            for row in visible
        )
        for checkpoint in ("2h", "24h")
    }
    seven_day.sort(key=lambda row: (str(row["published_at"]), str(row["package_id"])))
    paid.sort(
        key=lambda row: (
            _CHECKPOINT_ORDER[str(row["checkpoint"])],
            str(row["package_id"]),
        )
    )
    hook_report = _strongest_hooks(canonical, contexts)
    structure_report = _winning_structures(canonical, contexts)
    contains_hook_excerpt = any(
        "observed_hook" in reference
        for goal_report in hook_report.values()
        if isinstance(goal_report, Mapping)
        for reference in goal_report.get("references", [])
        if isinstance(reference, Mapping)
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "as_of": as_of_text,
        "basis": {
            "learning_channel": "organic",
            "learning_checkpoint": "72h",
            "comparison_age_window_hours": {
                "minimum_inclusive": MIN_CANONICAL_AGE_HOURS,
                "maximum_exclusive": MAX_CANONICAL_AGE_HOURS,
            },
            "canonical_posts": len(canonical),
            "late_organic_72h_observations_excluded": len(late_72h),
            "visible_observations": len(visible),
            "as_of_exclusions": excluded,
            "immature_organic_observations": immature,
            "organic_7d_followups": len(seven_day),
            "paid_descriptive_observations": len(paid),
            "channels_combined": False,
            "checkpoints_combined": False,
        },
        "strongest_hook_by_goal": hook_report,
        "winning_structure_by_goal": structure_report,
        "strongest_authority_conversion": _authority_conversion(canonical),
        "weakest_conversion_signal": _weakest_conversion(canonical),
        "critic_alignment": _critic_alignment(canonical),
        "rubric_calibration": _rubric_calibration(canonical),
        "seven_day_followup": _seven_day_summary(seven_day),
        "paid_summary": _paid_summary(paid),
        "safety": {
            "rubric_mutated": False,
            "publishing_status": "DISABLED",
            "automatic_linkedin_actions": False,
            "contains_full_candidate_body": False,
            "contains_bounded_hook_excerpt": contains_hook_excerpt,
            "contains_source_or_proof_data": False,
        },
    }


def _verify_private_directory(descriptor: int) -> None:
    metadata = os.fstat(descriptor)
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise workflow.WorkflowError("Weekly review directory is unavailable or unsafe.")


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _safe_directory_component(metadata: os.stat_result) -> bool:
    permissions = stat.S_IMODE(metadata.st_mode)
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid in {0, os.geteuid()}
        and (
            permissions & 0o022 == 0
            or permissions & stat.S_ISVTX != 0
        )
    )


def _report_parent_plan(root: Path) -> tuple[Path, tuple[str, ...]]:
    if root == DEFAULT_REPORT_ROOT:
        try:
            components = root.parent.relative_to(workflow.REPO_ROOT).parts
        except ValueError as exc:
            raise workflow.WorkflowError(
                "Weekly review output root is unavailable or unsafe."
            ) from exc
        anchor = workflow.REPO_ROOT
    else:
        anchor = Path(root.anchor)
        components = root.parent.parts[1:]
        if components and components[0] in {"tmp", "var"}:
            alias = Path(root.anchor) / components[0]
            try:
                alias_metadata = os.lstat(alias)
                alias_target = os.readlink(alias)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISLNK(alias_metadata.st_mode)
                    and alias_metadata.st_uid == 0
                    and alias_target == f"private/{components[0]}"
                ):
                    components = ("private", components[0], *components[1:])
    cleaned = tuple(part for part in components if part not in {"", "."})
    if any(part == ".." for part in cleaned):
        raise workflow.WorkflowError(
            "Weekly review output root is unavailable or unsafe."
        )
    return anchor, cleaned


def _open_report_parent(
    root: Path,
) -> tuple[
    list[int],
    Path,
    list[tuple[int, ...]],
    list[tuple[int, str, tuple[int, ...]]],
]:
    anchor, components = _report_parent_plan(root)
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    edges: list[tuple[int, str, tuple[int, ...]]] = []
    try:
        descriptor = os.open(anchor, _DIRECTORY_FLAGS)
        metadata = os.fstat(descriptor)
        if not _safe_directory_component(metadata):
            raise workflow.WorkflowError(
                "Weekly review output root is unavailable or unsafe."
            )
        descriptors.append(descriptor)
        identities.append(_directory_identity(metadata))
        for component in components:
            parent_descriptor = descriptors[-1]
            descriptor = os.open(
                component,
                _DIRECTORY_FLAGS,
                dir_fd=parent_descriptor,
            )
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            identity = _directory_identity(metadata)
            current = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if (
                not _safe_directory_component(metadata)
                or _directory_identity(current) != identity
            ):
                raise workflow.WorkflowError(
                    "Weekly review output root is unavailable or unsafe."
                )
            identities.append(identity)
            edges.append((parent_descriptor, component, identity))
        _verify_private_directory(descriptors[-1])
        return descriptors, anchor, identities, edges
    except Exception:
        for opened in reversed(descriptors):
            os.close(opened)
        raise


def _report_parent_is_current(
    descriptors: Sequence[int],
    anchor: Path,
    identities: Sequence[tuple[int, ...]],
    edges: Sequence[tuple[int, str, tuple[int, ...]]],
) -> bool:
    try:
        if _directory_identity(os.stat(anchor, follow_symlinks=False)) != identities[0]:
            return False
        if any(
            _directory_identity(os.fstat(descriptor)) != expected
            for descriptor, expected in zip(descriptors, identities, strict=True)
        ):
            return False
        return all(
            _directory_identity(
                os.stat(name, dir_fd=parent, follow_symlinks=False)
            )
            == expected
            for parent, name, expected in edges
        )
    except OSError:
        return False


def _write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise OSError("short weekly review write")
        remaining = remaining[written:]


def _existing_report_matches(
    directory_descriptor: int, filename: str, payload: bytes
) -> bool:
    descriptor = -1
    try:
        descriptor = os.open(
            filename,
            os.O_RDONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_CLOEXEC", 0),
            dir_fd=directory_descriptor,
        )
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != os.geteuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size != len(payload)
            or before.st_size > MAX_REPORT_BYTES
        ):
            return False
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                return False
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            return False
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            return False
        return b"".join(chunks) == payload
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def write_weekly_review(
    rows: Iterable[Mapping[str, object]],
    *,
    as_of: object,
    candidate_contexts: Mapping[
        tuple[str, str], Mapping[str, object]
    ] | None = None,
    output_root: Path | str = DEFAULT_REPORT_ROOT,
    _allow_test_output_root: bool = False,
) -> dict[str, object]:
    """Write a no-clobber owner-only JSON report under the ignored private root."""

    if type(_allow_test_output_root) is not bool:
        raise workflow.WorkflowError("Weekly review test output scope must be boolean.")
    root = Path(output_root)
    if not root.is_absolute():
        raise workflow.WorkflowError("Weekly review output root must be absolute.")
    if root != DEFAULT_REPORT_ROOT and not _allow_test_output_root:
        raise workflow.WorkflowError(
            "Weekly reviews can only be written under the fixed private output root."
        )
    if root.name in {"", ".", ".."} or not all(
        (
            getattr(os, "O_DIRECTORY", 0),
            getattr(os, "O_NOFOLLOW", 0),
            hasattr(os, "geteuid"),
            hasattr(os, "fchmod"),
            hasattr(os, "fsync"),
            hasattr(os, "link"),
        )
    ):
        raise workflow.WorkflowError(
            "Secure weekly review filesystem operations are unavailable."
        )
    report = build_weekly_review(
        rows,
        as_of=as_of,
        candidate_contexts=candidate_contexts,
    )
    payload = (
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_REPORT_BYTES:
        raise workflow.WorkflowError("Weekly review exceeds the private size limit.")
    stamp = _timestamp(str(report["as_of"])).strftime("%Y%m%dT%H%M%SZ")
    filename = f"weekly-review-{stamp}.json"
    stage_name = f".weekly-review-stage-{secrets.token_hex(16)}"
    directory_descriptors: list[int] = []
    directory_anchor = Path(".")
    directory_identities: list[tuple[int, ...]] = []
    directory_edges: list[tuple[int, str, tuple[int, ...]]] = []
    parent_fd = root_fd = stage_fd = -1
    root_identity: tuple[int, ...] | None = None
    stage_created = False
    try:
        (
            directory_descriptors,
            directory_anchor,
            directory_identities,
            directory_edges,
        ) = _open_report_parent(root)
        parent_fd = directory_descriptors[-1]
        try:
            os.mkdir(root.name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
        root_fd = os.open(root.name, _DIRECTORY_FLAGS, dir_fd=parent_fd)
        _verify_private_directory(root_fd)
        root_identity = _directory_identity(os.fstat(root_fd))
        stage_fd = os.open(stage_name, _FILE_FLAGS, 0o600, dir_fd=root_fd)
        stage_created = True
        _write_all(stage_fd, payload)
        os.fchmod(stage_fd, 0o600)
        os.fsync(stage_fd)
        metadata = os.fstat(stage_fd)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise workflow.WorkflowError("Weekly review staging file is unsafe.")
        try:
            os.link(
                stage_name,
                filename,
                src_dir_fd=root_fd,
                dst_dir_fd=root_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            if not _existing_report_matches(root_fd, filename, payload):
                raise workflow.WorkflowError(
                    "A different weekly review already exists for this as-of timestamp."
                ) from None
        os.fsync(root_fd)
        os.unlink(stage_name, dir_fd=root_fd)
        stage_created = False
        os.fsync(root_fd)
        root_current = os.stat(
            root.name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
        if (
            not _report_parent_is_current(
                directory_descriptors,
                directory_anchor,
                directory_identities,
                directory_edges,
            )
            or _directory_identity(root_current) != root_identity
            or _directory_identity(os.fstat(root_fd)) != root_identity
        ):
            raise workflow.WorkflowError(
                "Weekly review output path changed while it was written."
            )
    except workflow.WorkflowError:
        raise
    except OSError as exc:
        raise workflow.WorkflowError(
            "Weekly review could not be written safely."
        ) from exc
    finally:
        if stage_fd >= 0:
            os.close(stage_fd)
        if stage_created and root_fd >= 0:
            try:
                os.unlink(stage_name, dir_fd=root_fd)
            except OSError:
                pass
        if root_fd >= 0:
            os.close(root_fd)
        for directory_descriptor in reversed(directory_descriptors):
            os.close(directory_descriptor)
    return {"path": root / filename, "report": report}
