"""Tests for current-signal discovery and authority-thesis gating."""

from __future__ import annotations

import subprocess
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_cli, workflow

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "bin" / "linkedin-os"


def profile() -> dict[str, object]:
    return {
        "target_audience": "Senior product leaders and AI founders",
        "authority_goal": "Practical judgment for reliable enterprise AI products",
        "proof_inventory": [
            {
                "id": "proof-repository",
                "label": "Public decision-system repository",
                "public_safe_claim": "A public repository demonstrates the decision workflow.",
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
            "title": f"Agent evaluation update {index}",
            "body": "A body-read source describes a current product decision.",
            "source": "Research lab",
            "published_at": "2026-07-22T00:00:00Z",
            "source_quality": "primary",
            "canonical_url": f"https://example.com/{index}",
        }
        for index in range(1, 4)
    ]


def cards(prefix: str = "A") -> list[dict[str, object]]:
    return [
        {
            "id": f"thesis-{index}",
            "signal_ids": [f"signal-{index}"],
            "topic": f"Agent evaluation update {index}",
            "thesis": f"{prefix} thesis {index}: autonomy should earn its next step.",
            "why_now": "A recent source makes the decision timely.",
            "reader_problem": "Product leaders need a safe rollout decision.",
            "product_decision": "Require evidence before expanding the workflow.",
            "proof_id": "proof-repository",
            "remembered_for": "Connecting agent mechanics to product decisions.",
            "plain_language_summary": f"Agents should earn step {index} with evidence.",
        }
        for index in range(1, 4)
    ]


def scorecards(total: int = 25) -> list[dict[str, object]]:
    vectors = {
        25: (5, 5, 5, 5, 5),
        23: (5, 5, 5, 4, 4),
        22: (5, 5, 4, 4, 4),
    }
    return [
        {
            "thesis_id": f"thesis-{index}",
            **dict(zip(daily_cli.AXES, vectors[total], strict=True)),
        }
        for index in range(1, 4)
    ]


class ProfileValidationTests(unittest.TestCase):
    def test_profile_requires_exact_schema_and_distinct_proof_ids(self) -> None:
        validated = daily_cli.validate_profile(profile())
        self.assertEqual(validated["target_audience"], profile()["target_audience"])

        duplicate = profile()
        duplicate["proof_inventory"] = [
            duplicate["proof_inventory"][0],
            duplicate["proof_inventory"][0],
        ]
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_profile(duplicate)

        extra = profile()
        extra["private_note"] = "not allowed"
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_profile(extra)

    def test_profile_allows_empty_avoid_and_recent_lists(self) -> None:
        validated = daily_cli.validate_profile(profile())
        self.assertEqual(validated["avoid_topics"], [])
        self.assertEqual(validated["recent_theses"], [])


class ThesisValidationTests(unittest.TestCase):
    def test_cards_require_three_distinct_grounded_simple_theses(self) -> None:
        validated = daily_cli.validate_cards(cards(), signals(), profile())
        self.assertEqual(
            [card["id"] for card in validated],
            ["thesis-1", "thesis-2", "thesis-3"],
        )

        unknown_signal = cards()
        unknown_signal[0]["signal_ids"] = ["signal-99"]
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_cards(unknown_signal, signals(), profile())

        unknown_proof = cards()
        unknown_proof[0]["proof_id"] = "proof-missing"
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_cards(unknown_proof, signals(), profile())

        long_summary = cards()
        long_summary[0]["plain_language_summary"] = " ".join(["word"] * 26)
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_cards(long_summary, signals(), profile())

    def test_scorecards_are_strict_and_locally_totalled(self) -> None:
        validated = daily_cli.validate_scores(scorecards(23), cards())
        self.assertEqual(validated[0]["total"], 23)

        malformed = scorecards()
        malformed[0]["audience_fit"] = True
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_scores(malformed, cards())


class ThesisSearchTests(unittest.TestCase):
    def test_search_regenerates_until_all_three_clear_the_bar(self) -> None:
        generated = [cards("Rejected"), cards("Accepted")]
        scored = [scorecards(22), scorecards(25)]
        calls: list[object] = []

        def generator(_profile: object, _signals: object, feedback: object) -> list[dict[str, object]]:
            calls.append(deepcopy(feedback))
            return generated.pop(0)

        def critic(_cards: object, _profile: object, _signals: object) -> list[dict[str, object]]:
            return scored.pop(0)

        result = daily_cli.search_theses(
            profile(), signals(), generator=generator, critic=critic
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["total"], 25)
        self.assertIsNone(calls[0])
        self.assertIsInstance(calls[1], dict)

    def test_search_fails_closed_after_exhaustion(self) -> None:
        counter = 0

        def generator(_profile: object, _signals: object, _feedback: object) -> list[dict[str, object]]:
            nonlocal counter
            counter += 1
            return cards(f"Cycle-{counter}")

        with self.assertRaisesRegex(workflow.WorkflowError, "No complete three-thesis"):
            daily_cli.search_theses(
                profile(),
                signals(),
                generator=generator,
                critic=lambda _cards, _profile, _signals: scorecards(22),
            )

    def test_rejected_thesis_cannot_be_reused(self) -> None:
        first = cards("Repeated")
        responses = [first, deepcopy(first)]

        with self.assertRaisesRegex(workflow.WorkflowError, "reused a rejected thesis"):
            daily_cli.search_theses(
                profile(),
                signals(),
                generator=lambda _p, _s, _f: responses.pop(0),
                critic=lambda _cards, _profile, _signals: scorecards(22),
            )


class StrategyTests(unittest.TestCase):
    def test_strategy_maps_to_existing_five_field_contract(self) -> None:
        strategy = daily_cli.strategy_for(cards()[0], profile())
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
        self.assertEqual(strategy["core_hypothesis"], cards()[0]["thesis"])


class CliTests(unittest.TestCase):
    def test_single_entrypoint_exposes_discovery_help(self) -> None:
        result = subprocess.run(
            [str(CLI), "discover", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--allow-web-research", result.stdout)
        self.assertIn("--profile", result.stdout)

    def test_discovery_requires_both_consents_before_reading_profile(self) -> None:
        with patch.object(
            daily_cli,
            "_private_json",
            side_effect=AssertionError("profile must not be read"),
        ):
            args = daily_cli.parser().parse_args(
                ["--profile", "data/private/profile.json"]
            )
            with self.assertRaisesRegex(workflow.WorkflowError, "allow-web-research"):
                daily_cli.command(args)

            args = daily_cli.parser().parse_args(
                [
                    "--profile",
                    "data/private/profile.json",
                    "--allow-web-research",
                ]
            )
            with self.assertRaisesRegex(workflow.WorkflowError, "allow-model-egress"):
                daily_cli.command(args)


if __name__ == "__main__":
    unittest.main()
