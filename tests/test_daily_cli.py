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
            "conversation_surface": (
                f"Practitioners can challenge whether evidence should precede autonomy at step {index}."
            ),
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
    def test_locked_discovery_contract_is_unchanged(self) -> None:
        self.assertEqual(
            daily_cli.AXES,
            (
                "audience_fit",
                "distinctiveness",
                "decision_strength",
                "proof_fit",
                "simplicity",
            ),
        )
        self.assertEqual(daily_cli.MIN_TOTAL, 23)
        self.assertEqual(daily_cli.MIN_SIMPLICITY, 4)
        self.assertEqual(daily_cli.MAX_CYCLES, 3)
        self.assertEqual(daily_cli._schema("cards")["properties"]["cards"]["minItems"], 3)  # type: ignore[index]
        self.assertEqual(daily_cli._schema("cards")["properties"]["cards"]["maxItems"], 3)  # type: ignore[index]

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

    def test_conversation_surface_is_required_and_cannot_be_engagement_bait(self) -> None:
        missing = cards()
        del missing[0]["conversation_surface"]
        with self.assertRaisesRegex(workflow.WorkflowError, "invalid schema"):
            daily_cli.validate_cards(missing, signals(), profile())

        generic = cards()
        generic[0]["conversation_surface"] = "What do you think?"
        with self.assertRaisesRegex(workflow.WorkflowError, "Conversation surface"):
            daily_cli.validate_cards(generic, signals(), profile())

        concise = cards()
        concise[0]["conversation_surface"] = "Latency versus answer quality"
        validated = daily_cli.validate_cards(concise, signals(), profile())
        self.assertEqual(validated[0]["conversation_surface"], "Latency versus answer quality")

    def test_scorecards_are_strict_and_locally_totalled(self) -> None:
        validated = daily_cli.validate_scores(scorecards(23), cards())
        self.assertEqual(validated[0]["total"], 23)

        malformed = scorecards()
        malformed[0]["audience_fit"] = True
        with self.assertRaises(workflow.WorkflowError):
            daily_cli.validate_scores(malformed, cards())

    def test_critic_scores_conversation_surface_inside_existing_rubric(self) -> None:
        with patch.object(
            daily_cli,
            "invoke_structured",
            return_value={"scorecards": scorecards(25)},
        ) as invoke:
            validated = daily_cli.score_cards(cards(), profile(), signals())
        self.assertEqual(validated[0]["total"], 25)
        prompt = str(invoke.call_args.kwargs["task_prompt"]).casefold()
        self.assertIn("conversation surface", prompt)
        self.assertIn("distinctiveness", prompt)
        self.assertIn("2 or lower", prompt)


class ThesisSearchTests(unittest.TestCase):
    def test_search_regenerates_until_all_three_clear_the_bar(self) -> None:
        generated = [cards("Rejected"), cards("Accepted")]
        scored = [scorecards(22), scorecards(25)]
        calls: list[object] = []

        def generator(_profile: object, _signals: object, feedback: object) -> list[dict[str, object]]:
            calls.append(deepcopy(feedback))
            return generated.pop(0)

        def critic(current_cards: object, _profile: object, _signals: object) -> list[dict[str, object]]:
            assert isinstance(current_cards, list)
            return daily_cli.validate_scores(scored.pop(0), current_cards)

        result = daily_cli.search_theses(
            profile(), signals(), generator=generator, critic=critic
        )
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["total"], 25)
        self.assertIsNone(calls[0])
        self.assertIsInstance(calls[1], dict)
        assert isinstance(calls[1], dict)
        self.assertIn("conversation_surface", calls[1]["rejected"][0])

    def test_search_fails_closed_after_exhaustion(self) -> None:
        counter = 0

        def generator(_profile: object, _signals: object, _feedback: object) -> list[dict[str, object]]:
            nonlocal counter
            counter += 1
            return cards(f"Cycle-{counter}")

        def critic(current_cards: object, _profile: object, _signals: object) -> list[dict[str, object]]:
            assert isinstance(current_cards, list)
            return daily_cli.validate_scores(scorecards(22), current_cards)

        with self.assertRaisesRegex(workflow.WorkflowError, "No complete three-thesis"):
            daily_cli.search_theses(
                profile(), signals(), generator=generator, critic=critic
            )
        self.assertEqual(counter, 3)

    def test_search_rejects_high_total_when_simplicity_is_below_four(self) -> None:
        counter = 0

        def generator(_profile: object, _signals: object, _feedback: object) -> list[dict[str, object]]:
            nonlocal counter
            counter += 1
            return cards(f"Low-simplicity-{counter}")

        low_simplicity = scorecards(25)
        for score in low_simplicity:
            score["simplicity"] = 3

        def critic(current_cards: object, _profile: object, _signals: object) -> list[dict[str, object]]:
            assert isinstance(current_cards, list)
            return daily_cli.validate_scores(low_simplicity, current_cards)

        with self.assertRaisesRegex(workflow.WorkflowError, "No complete three-thesis"):
            daily_cli.search_theses(
                profile(), signals(), generator=generator, critic=critic
            )
        self.assertEqual(counter, 3)

    def test_rejected_thesis_cannot_be_reused(self) -> None:
        first = cards("Repeated")
        responses = [first, deepcopy(first)]

        def critic(current_cards: object, _profile: object, _signals: object) -> list[dict[str, object]]:
            assert isinstance(current_cards, list)
            return daily_cli.validate_scores(scorecards(22), current_cards)

        with self.assertRaisesRegex(workflow.WorkflowError, "reused a rejected thesis"):
            daily_cli.search_theses(
                profile(),
                signals(),
                generator=lambda _p, _s, _f: responses.pop(0),
                critic=critic,
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
    @patch("authority_os.daily_cli.invoke_structured")
    def test_scout_uses_codex_live_web_path_without_private_profile(
        self, invoke: object
    ) -> None:
        invoke.return_value = {"items": []}  # type: ignore[attr-defined]
        with patch.object(daily_cli, "_role", return_value="Scout role"), patch.object(
            workflow, "prepare_research_items", return_value=signals()
        ):
            result = daily_cli.invoke_scout("agent evals", 7, "2026-08-14T00:00:00Z")

        self.assertEqual(result, signals())
        kwargs = invoke.call_args.kwargs  # type: ignore[attr-defined]
        self.assertEqual(kwargs["config"].runtime, "codex")
        self.assertTrue(kwargs["web_search"])
        self.assertNotIn("proof_inventory", kwargs["task_prompt"])

    @patch("authority_os.daily_cli.invoke_structured")
    def test_thesis_generator_and_critic_use_zero_tool_codex_calls(
        self, invoke: object
    ) -> None:
        invoke.side_effect = [  # type: ignore[attr-defined]
            {"cards": cards()},
            {"scorecards": scorecards(25)},
        ]
        with patch.object(daily_cli, "_role", return_value="Thesis role"):
            generated = daily_cli.generate_cards(profile(), signals(), None)
        scored = daily_cli.score_cards(generated, profile(), signals())

        self.assertEqual(len(generated), 3)
        self.assertEqual(scored[0]["total"], 25)
        for call in invoke.call_args_list:  # type: ignore[attr-defined]
            self.assertEqual(call.kwargs["config"].runtime, "codex")
            self.assertFalse(call.kwargs["web_search"])

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
