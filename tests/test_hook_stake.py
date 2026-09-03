"""The hook belongs to the reader, not to the author's project."""

import unittest

from authority_os import hook_stake as hs


class HookStakeTests(unittest.TestCase):
    def test_a_named_external_failure_passes(self):
        v = hs.evaluate("Nine seconds. That is how long it took an AI coding agent to "
                        "delete PocketOS's production database.")
        self.assertEqual(v.status, "PASS")
        self.assertEqual(v.subject, "named-external")

    def test_a_claim_about_the_readers_group_passes(self):
        v = hs.evaluate("Most decision-makers use AI to write faster.\n\nThe 1% use it to think better.")
        self.assertEqual(v.status, "PASS")
        self.assertEqual(v.subject, "reader-group")

    def test_your_own_feature_as_the_subject_fails(self):
        v = hs.evaluate("Our AI feature had great adoption at launch. Three months later, "
                        "same feature, same metrics.")
        self.assertEqual(v.status, "FAIL")
        self.assertEqual(v.reason_code, "subject-is-your-own-work")

    def test_an_achievement_announcement_fails(self):
        v = hs.evaluate("I shipped a working, end-to-end complex product in 7 hours "
                        "and 4 minutes.\n\n18 pull requests.")
        self.assertEqual(v.status, "FAIL")
        self.assertEqual(v.subject, "own-work")

    def test_first_person_passes_when_the_reader_owns_the_stake(self):
        v = hs.evaluate("Last month I handed finance one flat number for our AI feature — "
                        "one price, per seat, per month.")
        self.assertEqual(v.status, "PASS")
        self.assertEqual(v.subject, "reader-stake")

    def test_a_group_opener_does_not_rescue_a_hook_about_your_project(self):
        v = hs.evaluate("Most PMs talk about AI agents. I built one to run my LinkedIn.")
        self.assertEqual(v.status, "FAIL")
        self.assertEqual(v.subject, "own-work")

    def test_a_hook_with_no_external_party_group_or_stake_fails(self):
        v = hs.evaluate("Something felt off about the way this was going.")
        self.assertEqual(v.status, "FAIL")
        self.assertEqual(v.reason_code, "no-reader-stake")

    def test_an_empty_hook_fails_rather_than_raising(self):
        self.assertEqual(hs.evaluate("#genai\n#aipm").reason_code, "empty-hook")

    def test_the_hook_is_only_the_first_two_body_lines(self):
        text = "A vague opening line.\nStill vague.\n\nClaude deleted the database."
        self.assertNotIn("Claude", hs.hook_of(text))
        self.assertEqual(hs.evaluate(text).status, "FAIL")

    def test_hashtags_are_not_part_of_the_hook(self):
        text = "#genai #aipm\nMost teams ship without evals."
        self.assertTrue(hs.hook_of(text).startswith("Most teams"))

    def test_a_failure_names_what_to_change(self):
        v = hs.evaluate("This week I tried something I'm calling Behavioral Diffing.")
        self.assertEqual(v.status, "FAIL")
        self.assertIn("reader owns the outcome", v.evidence)


if __name__ == "__main__":
    unittest.main()
