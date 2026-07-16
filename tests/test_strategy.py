"""Tests for strategic goal routing and the default weekly mix."""

from __future__ import annotations

import itertools
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from authority_os import workflow


def selected_cluster(*, stale: bool | None = False) -> dict[str, object]:
    return {
        "slug": "agent-reliability",
        "why_now": "Recent primary evidence supports a product decision.",
        "dominant_take": "Reliability compounds across workflow steps",
        "missing_angle": "Name the decision and what would falsify it.",
        "primary_sources": ["https://standards.example/reliability"],
        "source_quality_sufficient": True,
        "body_read_sufficient": True,
        "recency_sufficient": True,
        "stale": stale,
    }


def strategy_inputs() -> dict[str, object]:
    return {
        "target_reader": "AI product leaders",
        "reader_problem": "They need a defensible reliability decision.",
        "core_hypothesis": "Workflow reliability compounds across steps.",
        "product_decision": "Set an end-to-end reliability budget first.",
        "authority_statement": "Connect the mechanism to a falsifiable decision.",
    }


def build_brief(**kwargs: object) -> dict[str, object]:
    return workflow.build_strategy_brief(
        selected_cluster(),
        strategy_inputs=strategy_inputs(),
        strategy_input_origin="explicit-input",
        **kwargs,
    )


class StrategyRoutingTests(unittest.TestCase):
    def test_synthetic_fixture_supplies_complete_topic_substituted_strategy_inputs(self) -> None:
        fixture = workflow.load_fixture(topic="AI reliability")
        inputs = fixture["strategy_inputs"]
        self.assertTrue(fixture["synthetic"])
        self.assertEqual(set(inputs), set(workflow.STRATEGY_INPUT_FIELDS))
        self.assertIn("AI reliability", inputs["core_hypothesis"])
        self.assertNotIn("{{topic}}", " ".join(inputs.values()))

    def test_fixture_snapshot_prevents_wall_clock_ageing(self) -> None:
        fixture = workflow.load_fixture()
        items = workflow.prepare_research_items(fixture["research_items"])
        snapshot = workflow.parse_published_at(str(fixture["as_of"]))
        at_snapshot = workflow.analyse_research(items, as_of=snapshot)
        far_future = workflow.analyse_research(
            items, as_of=datetime(2030, 1, 1, tzinfo=timezone.utc)
        )
        self.assertTrue(at_snapshot["selected_recency_sufficient"])
        self.assertFalse(far_future["selected_recency_sufficient"])

    def test_research_fixture_loading_does_not_require_strategy_inputs(self) -> None:
        payload = {
            "fixture_mode": True,
            "synthetic": True,
            "as_of": "2026-07-16T12:00:00Z",
            "topic": "research only",
            "research_items": [],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "research-only.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            fixture = workflow.load_fixture(path)
        self.assertEqual(fixture["research_items"], [])
        self.assertNotIn("strategy_inputs", fixture)

    def test_each_goal_has_the_exact_purpose_route_and_proof_semantics(self) -> None:
        expected = {
            "reach": (
                "Earn attention from relevant non-followers.",
                ["incident", "mechanism", "implication"],
                False,
            ),
            "authority": (
                "Demonstrate differentiated GenAI product judgement.",
                ["incident-or-problem", "mechanism", "decision"],
                False,
            ),
            "opportunity": (
                "Convert credibility into profile visits, tool adoption, and inbound opportunities.",
                ["problem", "decision", "artifact", "evidence"],
                True,
            ),
        }
        for goal, (purpose, route, proof_required) in expected.items():
            with self.subTest(goal=goal):
                brief = build_brief(goal=goal)
                self.assertEqual(brief["goal_purpose"], purpose)
                self.assertEqual(brief["narrative_route"], route)
                self.assertIs(brief["proof_required"], proof_required)

    def test_goal_and_format_are_independent_across_the_full_matrix(self) -> None:
        for goal, output_format in itertools.product(
            workflow.STRATEGIC_GOALS, workflow.OUTPUT_FORMATS
        ):
            with self.subTest(goal=goal, output_format=output_format):
                brief = build_brief(goal=goal, output_format=output_format)
                self.assertEqual(brief["goal"], goal)
                self.assertEqual(brief["output_format"], output_format)

    def test_omitted_goal_defaults_to_authority_without_inventing_a_format(self) -> None:
        brief = build_brief()
        self.assertEqual(brief["goal"], "authority")
        self.assertIsNone(brief["output_format"])
        self.assertIsNone(brief["weekly_slot"])

    def test_first_four_weekly_slots_match_the_default_mix(self) -> None:
        actual = [
            workflow.resolve_strategic_goal(week_slot=slot) for slot in range(1, 5)
        ]
        self.assertEqual(actual, ["reach", "authority", "authority", "opportunity"])
        self.assertEqual(actual.count("reach"), 1)
        self.assertEqual(actual.count("authority"), 2)
        self.assertEqual(actual.count("opportunity"), 1)

    def test_explicit_goal_must_agree_with_a_default_weekly_slot(self) -> None:
        self.assertEqual(
            workflow.resolve_strategic_goal(goal="reach", week_slot=1), "reach"
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "reserved for reach"):
            workflow.resolve_strategic_goal(goal="authority", week_slot=1)

    def test_optional_fifth_slot_requires_a_strong_signal_and_explicit_goal(self) -> None:
        with self.assertRaisesRegex(workflow.WorkflowError, "strong current incident or launch"):
            workflow.resolve_strategic_goal(goal="reach", week_slot=5)
        with self.assertRaisesRegex(workflow.WorkflowError, "explicit strategic goal"):
            workflow.resolve_strategic_goal(week_slot=5, strong_current_signal=True)
        self.assertEqual(
            workflow.resolve_strategic_goal(
                goal="opportunity", week_slot=5, strong_current_signal=True
            ),
            "opportunity",
        )

    def test_strong_signal_cannot_expand_an_ordinary_or_unplanned_slot(self) -> None:
        for week_slot in (None, 1, 4):
            with self.subTest(week_slot=week_slot):
                with self.assertRaisesRegex(workflow.WorkflowError, "only used.*slot 5"):
                    workflow.resolve_strategic_goal(
                        goal="reach",
                        week_slot=week_slot,
                        strong_current_signal=True,
                    )

    def test_invalid_goal_slot_format_and_signal_fail_honestly(self) -> None:
        with self.assertRaisesRegex(workflow.WorkflowError, "Strategic goal"):
            workflow.resolve_strategic_goal(goal="educatory")
        for week_slot in (0, 6, True, 1.5):
            with self.subTest(week_slot=week_slot):
                with self.assertRaisesRegex(workflow.WorkflowError, "integer from 1 to 5"):
                    workflow.resolve_strategic_goal(week_slot=week_slot)  # type: ignore[arg-type]
        with self.assertRaisesRegex(workflow.WorkflowError, "Output format"):
            build_brief(goal="reach", output_format="thread")
        with self.assertRaisesRegex(workflow.WorkflowError, "boolean assertion"):
            workflow.resolve_strategic_goal(
                week_slot=5,
                goal="reach",
                strong_current_signal="false",  # type: ignore[arg-type]
            )

    def test_brief_carries_the_complete_explicit_strategy_and_sources(self) -> None:
        inputs = strategy_inputs()
        selected = selected_cluster(stale=None)
        brief = workflow.build_strategy_brief(
            selected,
            strategy_inputs=inputs,
            strategy_input_origin="explicit-input",
            goal="authority",
        )
        for name, value in inputs.items():
            self.assertEqual(brief[name], value)
        self.assertEqual(
            brief["primary_sources"], ["https://standards.example/reliability"]
        )
        self.assertEqual(brief["strategy_input_origin"], "explicit-input")
        self.assertIsNone(brief["analysis"]["stale"])
        self.assertEqual(
            brief["evidence_status"]["limitations"],
            ["recent-post-similarity-not-evaluated"],
        )
        self.assertNotIn("draft", brief)
        self.assertNotIn("approval", brief)

    def test_each_evidence_shortfall_is_visible_without_applying_a_gate(self) -> None:
        cases = (
            ("source_quality_sufficient", "readable-primary-or-mixed-source-missing"),
            ("body_read_sufficient", "readable-body-missing"),
            ("recency_sufficient", "recent-evidence-missing"),
        )
        for field, reason in cases:
            with self.subTest(field=field):
                selected = selected_cluster()
                selected[field] = False
                brief = workflow.build_strategy_brief(
                    selected,
                    strategy_inputs=strategy_inputs(),
                    strategy_input_origin="explicit-input",
                )
                self.assertIn(reason, brief["evidence_status"]["limitations"])
                self.assertNotIn("ready_for_drafting", brief["evidence_status"])
                self.assertNotIn("status", brief["evidence_status"])

    def test_stale_topic_and_missing_traceable_source_are_visible(self) -> None:
        stale = workflow.build_strategy_brief(
            selected_cluster(stale=True),
            strategy_inputs=strategy_inputs(),
            strategy_input_origin="explicit-input",
        )
        no_source = selected_cluster()
        no_source["primary_sources"] = []
        missing_source = workflow.build_strategy_brief(
            no_source,
            strategy_inputs=strategy_inputs(),
            strategy_input_origin="explicit-input",
        )
        self.assertIn(
            "topic-similar-to-recent-post", stale["evidence_status"]["limitations"]
        )
        self.assertIn(
            "traceable-primary-source-missing",
            missing_source["evidence_status"]["limitations"],
        )

    def test_incomplete_or_malformed_analysis_cannot_be_routed(self) -> None:
        cases = (
            ("why_now", None, "non-blank text"),
            ("slug", None, "non-blank text"),
            ("dominant_take", 7, "non-blank text"),
            ("source_quality_sufficient", "yes", "must be boolean"),
            ("body_read_sufficient", None, "must be boolean"),
            ("recency_sufficient", 1, "must be boolean"),
            ("stale", "unknown", "boolean or null"),
            ("primary_sources", "https://example.com", "list of URLs"),
        )
        for field, value, error in cases:
            with self.subTest(field=field):
                selected = selected_cluster()
                selected[field] = value
                with self.assertRaisesRegex(workflow.WorkflowError, error):
                    workflow.build_strategy_brief(
                        selected,
                        strategy_inputs=strategy_inputs(),
                        strategy_input_origin="explicit-input",
                    )
        with self.assertRaisesRegex(workflow.WorkflowError, "analysis must be a mapping"):
            workflow.build_strategy_brief(  # type: ignore[arg-type]
                None,
                strategy_inputs=strategy_inputs(),
                strategy_input_origin="explicit-input",
            )

    def test_missing_analysis_and_strategy_fields_fail_honestly(self) -> None:
        selected = selected_cluster()
        del selected["why_now"]
        with self.assertRaisesRegex(workflow.WorkflowError, "missing required field.*why_now"):
            workflow.build_strategy_brief(
                selected,
                strategy_inputs=strategy_inputs(),
                strategy_input_origin="explicit-input",
            )
        inputs = strategy_inputs()
        inputs["authority_statement"] = " "
        with self.assertRaisesRegex(workflow.WorkflowError, "authority_statement.*non-blank"):
            workflow.build_strategy_brief(
                selected_cluster(),
                strategy_inputs=inputs,
                strategy_input_origin="explicit-input",
            )

    def test_strategy_input_origin_distinguishes_fixture_from_explicit_input(self) -> None:
        explicit = build_brief()
        synthetic = workflow.build_strategy_brief(
            selected_cluster(),
            strategy_inputs=strategy_inputs(),
            strategy_input_origin="synthetic-fixture",
        )
        self.assertEqual(explicit["strategy_input_origin"], "explicit-input")
        self.assertEqual(synthetic["strategy_input_origin"], "synthetic-fixture")
        with self.assertRaisesRegex(workflow.WorkflowError, "Strategy input origin"):
            workflow.build_strategy_brief(
                selected_cluster(),
                strategy_inputs=strategy_inputs(),
                strategy_input_origin="inferred",
            )


if __name__ == "__main__":
    unittest.main()
