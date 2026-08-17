"""Tests for advisory narrative-spine routing in daily discovery."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from authority_os import daily_spine_cli


def profile() -> dict[str, object]:
    return {
        "target_audience": "Senior AI product leaders",
        "authority_goal": "Practical judgment for production AI",
        "proof_inventory": [
            {
                "id": "proof-repo",
                "label": "Public repository",
                "public_safe_claim": "A public repository demonstrates the workflow.",
                "evidence_type": "repository",
            }
        ],
        "avoid_topics": [],
        "recent_theses": [],
    }


def signals() -> list[dict[str, object]]:
    return [
        {
            "id": f"signal-{index}",
            "title": f"Agent reliability update {index}",
            "body": "A primary source describes a current product decision.",
            "source": "Research lab",
            "published_at": "2026-08-17T00:00:00Z",
            "source_quality": "primary",
            "canonical_url": f"https://example.com/{index}",
        }
        for index in range(1, 4)
    ]


def cards() -> list[dict[str, object]]:
    spines = (
        "counterposition",
        "failure_reversal",
        "research_discovery",
    )
    return [
        {
            "id": f"thesis-{index}",
            "signal_ids": [f"signal-{index}"],
            "topic": f"Agent reliability update {index}",
            "thesis": f"Thesis {index}: autonomy should earn its next step.",
            "why_now": "A current signal makes the decision timely.",
            "reader_problem": "Leaders need a safe rollout decision.",
            "product_decision": "Require evidence before expanding autonomy.",
            "proof_id": "proof-repo",
            "remembered_for": "Connecting agent mechanics to product decisions.",
            "plain_language_summary": f"Agents should earn step {index} with evidence.",
            "conversation_surface": "Autonomy versus reversibility in production systems.",
            "recommended_spine": spines[index - 1],
            "spine_fit_reason": "The evidence naturally exposes a decision that practitioners can challenge.",
        }
        for index in range(1, 4)
    ]


class SpineCardTests(unittest.TestCase):
    def test_extended_card_contract_accepts_only_stable_spines(self) -> None:
        validated = daily_spine_cli.validate_cards(cards(), signals(), profile())
        self.assertEqual(validated[0]["recommended_spine"], "counterposition")

        invalid = cards()
        invalid[0]["recommended_spine"] = "viral_story"
        with self.assertRaisesRegex(Exception, "recommended_spine"):
            daily_spine_cli.validate_cards(invalid, signals(), profile())

    def test_spine_reason_is_required_and_bounded(self) -> None:
        blank = cards()
        blank[0]["spine_fit_reason"] = ""
        with self.assertRaisesRegex(Exception, "spine_fit_reason"):
            daily_spine_cli.validate_cards(blank, signals(), profile())

        long = cards()
        long[0]["spine_fit_reason"] = "x" * 321
        with self.assertRaisesRegex(Exception, "spine_fit_reason"):
            daily_spine_cli.validate_cards(long, signals(), profile())

    def test_schema_exposes_exact_five_spines(self) -> None:
        schema = daily_spine_cli._schema("cards")
        enum = schema["properties"]["cards"]["items"]["properties"]["recommended_spine"]["enum"]
        self.assertEqual(tuple(enum), daily_spine_cli.CONTENT_SPINES)

    def test_generation_marks_spine_as_advisory_not_weekday_routing(self) -> None:
        with patch.object(
            daily_spine_cli.base,
            "invoke_structured",
            return_value={"cards": cards()},
        ) as invoke:
            result = daily_spine_cli.generate_cards(profile(), signals(), None)
        self.assertEqual(len(result), 3)
        prompt = str(invoke.call_args.kwargs["task_prompt"]).casefold()
        self.assertIn("spine is advisory only", prompt)
        self.assertIn("do not force a template", prompt)
        self.assertIn("do not draft a post", prompt)
        self.assertIn("weekday", prompt)

    def test_downstream_strategy_contract_remains_five_fields(self) -> None:
        card = daily_spine_cli.validate_cards(cards(), signals(), profile())[0]
        strategy = daily_spine_cli.base.strategy_for(card, profile())
        self.assertEqual(
            set(strategy),
            {
                "target_reader",
                "reader_problem",
                "core_hypothesis",
                "product_decision",
                "authority_statement",
            },
        )
        self.assertNotIn("recommended_spine", strategy)


if __name__ == "__main__":
    unittest.main()
