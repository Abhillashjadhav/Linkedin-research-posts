"""Slot gates are calibrated against published results, so the tests are too."""

import unittest
from datetime import date

from authority_os import week_contract as wc


HUMOUR = ("Asked the model to write me exactly 200 words.\n\nIt returned 173. "
          "With full confidence.\n\nAsked again. Got 218. Equally confident.")
TEASER = ("There's a skill in GenAI product management right now that most PMs have heard of.\n\n"
          "I won't name it in this post.\n\nFor the next 7 days, I'll post one short piece every morning.")
ACHIEVEMENT = ("I shipped a working, end-to-end complex product in 7 hours and 4 minutes.\n\n"
               "18 pull requests.\n338 passing tests.\nBuilt with Claude Code on Production Engineering OS.")
BENEFIT = ("Most AI tools for Product Managers optimize for speed. I built one to improve judgment.\n\n"
           "Today I'm open-sourcing the PM operating system built to raise your PM bar.")
INCIDENT = ("Nine seconds. That is how long it took an AI coding agent to delete PocketOS's "
            "production database and its volume-level backups.\n\nYou should ask five questions "
            "before granting an agent write access.")


class SlotGateTests(unittest.TestCase):
    def test_humour_is_blocked_on_every_slot(self):
        for day in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Sunday"):
            result = wc.evaluate(HUMOUR, day_name=day)
            self.assertEqual(result["status"], "FAIL", day)
            self.assertEqual(result["reason_code"], "humour-shape", day)

    def test_teaser_is_blocked(self):
        result = wc.evaluate(TEASER, day_name="Monday")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason_code"], "teaser-shape")

    def test_build_slot_rejects_an_achievement_first_opening(self):
        result = wc.evaluate(ACHIEVEMENT, day_name="Wednesday")
        self.assertEqual(result["status"], "FAIL")
        # reader_stake now catches this earlier and more fundamentally: the
        # subject is the author's own build, which is why the framing failed.
        self.assertEqual(result["reason_code"], "subject-is-your-own-work")
        failed = {g["gate"] for g in result["gates"] if g["status"] == "FAIL"}
        self.assertIn("benefit_before_achievement", failed)

    def test_build_slot_accepts_a_benefit_first_opening(self):
        self.assertEqual(wc.evaluate(BENEFIT, day_name="Wednesday")["status"], "PASS")

    def test_named_entity_accepts_internal_caps(self):
        self.assertEqual(wc.check_gate("named_entity", INCIDENT).status, "PASS")

    def test_named_entity_rejects_a_post_with_no_real_subject(self):
        bare = "you should always ship faster and think less about the model you use."
        self.assertEqual(wc.check_gate("named_entity", bare).status, "FAIL")

    def test_saturday_is_a_dark_day(self):
        result = wc.evaluate(INCIDENT, day_name="Saturday")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["reason_code"], "dark-day")

    def test_plain_language_gate_blocks_niche_jargon_on_a_breakout_slot(self):
        jargon = INCIDENT + "\n\nCohen's kappa on the rubric calibration was 0.62."
        result = wc.evaluate(jargon, day_name="Monday")
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["reason_code"], "niche-jargon")

    def test_date_helper_resolves_the_weekday(self):
        result = wc.evaluate_for_date(INCIDENT, date(2026, 5, 25))
        self.assertEqual(result["day"], "Monday")
        self.assertEqual(result["slot"], "BREAKOUT")

    def test_every_declared_gate_is_implemented(self):
        contract = wc.load_contract()
        declared = {g for spec in contract["slots"].values() for g in spec["required_gates"]}
        self.assertTrue(declared <= set(wc.GATES))
        for gate in declared:
            self.assertIn(wc.check_gate(gate, INCIDENT).status, {"PASS", "FAIL"})

    def test_contract_covers_every_day_of_the_week(self):
        contract = wc.load_contract()
        covered = set(contract["cadence"]["posting_days"]) | set(contract["cadence"]["dark_days"])
        self.assertEqual(len(covered), 7)


if __name__ == "__main__":
    unittest.main()
