"""Drift tests for the approved LinkedIn post contract."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from authority_os import acceptance_policy


ROOT = Path(__file__).resolve().parents[1]


def load_json(relative_path: str) -> dict[str, Any]:
    return json.loads((ROOT / relative_path).read_text(encoding="utf-8"))


class LinkedInPostContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contract = load_json("config/linkedin-post-contract-v1.json")
        cls.rubric = load_json("config/critic-rubric-v2.json")

    def test_contract_is_approved_v1(self) -> None:
        metadata = self.contract["metadata"]
        self.assertEqual(metadata["status"], "APPROVED")
        self.assertEqual(metadata["version"], "1.3.0")

    def test_critic_matches_executable_acceptance_policy(self) -> None:
        critic = self.contract["critic"]
        expected_floors = dict(acceptance_policy.AXIS_FLOORS)

        self.assertEqual(
            critic["axis_order"],
            [
                "hook_strength",
                "middle_escalation",
                "earned_closer",
                "specificity_and_source_quality",
                "voice_fidelity",
            ],
        )
        self.assertEqual(list(critic["axes"]), critic["axis_order"])
        self.assertEqual(critic["axis_floors"], expected_floors)
        self.assertEqual(
            critic["minimum_total"],
            acceptance_policy.ACCEPTABLE_QUALITY_FLOOR,
        )
        self.assertEqual(critic["total_formula"], "sum_of_five_axes")
        self.assertEqual(critic["total_out_of"], 25)

    def test_critic_anchor_text_is_canonical_v2_rubric_text(self) -> None:
        for axis in self.contract["critic"]["axis_order"]:
            with self.subTest(axis=axis):
                contract_anchors = {
                    str(level): self.contract["critic"]["axes"][axis][str(level)]
                    for level in range(1, 6)
                }
                rubric_anchors = {
                    str(level): self.rubric["axes"][axis][str(level)]
                    for level in range(1, 6)
                }
                self.assertEqual(contract_anchors, rubric_anchors)

        self.assertEqual(
            self.contract["critic"]["axes"]["voice_fidelity"],
            {
                key: value
                for key, value in self.rubric["axes"]["voice_fidelity"].items()
                if key
                in {
                    "type",
                    "1",
                    "2",
                    "3",
                    "4",
                    "5",
                    "line_two_rule",
                    "short_emphasis_rule",
                    "optional_human_devices_rule",
                    "calibration_examples",
                }
            },
        )

    def test_legacy_quality_target_is_not_part_of_contract(self) -> None:
        critic = self.contract["critic"]
        self.assertIsNone(critic.get("optimization_target"))
        self.assertIsNone(critic.get("quality_target"))
        self.assertIsNone(self.contract.get("quality_target"))
        self.assertNotIn("bonus", self.rubric["release_rule"])

    def test_hook_contract_keeps_names_scale_and_reader_stake(self) -> None:
        hook = self.contract["writing"]["hook"]
        self.assertIs(hook["score_both_first_lines"], True)
        self.assertIs(hook["reader_stake_required"], True)
        self.assertEqual(
            hook["line_one"],
            "Lead with the strongest supported recognizable name or company and "
            "the strongest supported number, loss, scale, or incident when available.",
        )
        self.assertEqual(
            hook["line_two"],
            "Establish the reader's immediate consequence, decision, risk, "
            "opportunity, or useful tension.",
        )
        self.assertIs(hook["supported_names_are_not_removed"], True)
        self.assertIs(hook["never_invent_scale_loss_incident_or_number"], True)
        self.assertIs(
            hook["line_two_must_not_become_explanatory_or_consultant_register"],
            True,
        )

    def test_voice_contract_is_broad_human_plain_and_emotionally_real(self) -> None:
        writing = self.contract["writing"]
        style_target = writing["style_target"]
        emotional_reality = writing["emotional_reality"]

        self.assertIn("Clearly human", style_target)
        self.assertIn("sharp conversational product leader", style_target)
        self.assertIn("Exact imitation of the owner's speech is not required", style_target)
        self.assertEqual(writing["consultant_register"], "prohibited")
        self.assertEqual(writing["presentation_register"], "prohibited")
        self.assertEqual(
            writing["wit"],
            "Allowed when it sharpens the point; never required or forced.",
        )
        for human_note in ("empathy", "frustration", "helplessness"):
            with self.subTest(human_note=human_note):
                self.assertIn(human_note, emotional_reality)
        self.assertIn("Do not manufacture emotion for effect", emotional_reality)
        self.assertEqual(
            writing["personal_experience"]["invented_experience"], "prohibited"
        )
        self.assertEqual(
            writing["personal_experience"]["invented_emotion"], "prohibited"
        )
        self.assertTrue(writing["plain_language"]["prohibited_register_examples"])
        voice = self.contract["critic"]["axes"]["voice_fidelity"]
        self.assertIn("stacked punchy fragments", voice["short_emphasis_rule"])
        self.assertIn("never a checklist", voice["optional_human_devices_rule"])
        self.assertIn("complete post", voice["3"])
        self.assertIn("directly publishable", voice["4"])

    def test_progressive_editor_contract_is_monotonic_and_bounded(self) -> None:
        repair = self.contract["repair"]

        self.assertEqual(repair["maximum_quality_cycles"], 4)
        self.assertEqual(repair["progressive_editor_candidate_count"], 1)
        self.assertIn(
            "ID, angle, and claim IDs exactly",
            repair["progressive_editor_identity_rule"],
        )
        monotonic = repair["progressive_editor_monotonic_rule"]
        for requirement in (
            "overall total",
            "hook and voice",
            "may trade off",
            "hard gate",
            "improves",
        ):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, monotonic)

    def test_every_recorded_decision_is_resolved_and_none_are_open(self) -> None:
        decisions = self.contract["resolved_decisions"]
        self.assertTrue(decisions)
        self.assertTrue(all(item["decision_status"] == "RESOLVED" for item in decisions))
        self.assertFalse(self.contract.get("open_decisions"))

        def decision_statuses(value: object) -> list[str]:
            if isinstance(value, dict):
                statuses = (
                    [str(value["decision_status"])]
                    if "decision_status" in value
                    else []
                )
                for nested in value.values():
                    statuses.extend(decision_statuses(nested))
                return statuses
            if isinstance(value, list):
                statuses: list[str] = []
                for nested in value:
                    statuses.extend(decision_statuses(nested))
                return statuses
            return []

        self.assertTrue(
            all(status == "RESOLVED" for status in decision_statuses(self.contract))
        )


if __name__ == "__main__":
    unittest.main()
