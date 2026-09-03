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


class RegisterTests(unittest.TestCase):
    def test_literary_vocabulary_is_flagged_without_being_listed(self):
        v = hs.evaluate("This underscores a pivotal paradigm for teams shipping agents.")
        self.assertEqual(v.status, "FAIL")
        self.assertEqual(v.reason_code, "off-register-word")

    def test_his_plain_and_domain_vocabulary_is_never_flagged(self):
        for line in ("A friend at a frontier AI lab making just short of a million dollars a year.",
                     "Most teams size the context window before they size the eval set.",
                     "Your first AI eval should be an Excel or a spreadsheet, not a platform.",
                     "An AI agent forgetting what it already did is the expensive case."):
            self.assertNotEqual(hs.evaluate(line).reason_code, "off-register-word", line)

    def test_the_flag_says_how_to_clear_it(self):
        self.assertIn("corpus", hs.evaluate("A quintessential crucible for teams.").evidence)

    def test_an_idiom_of_common_words_is_left_to_the_judge(self):
        # "shy of" is built from words everyone uses, so frequency cannot see it.
        # The statistical layer is a prior; it does not claim to be complete.
        v = hs.evaluate("A friend at a frontier AI lab making just shy of a million dollars.")
        self.assertEqual(v.status, "PASS")

    def test_the_profile_carries_both_word_sets(self):
        self.assertGreater(len(hs._known_words()), 10000)

    def test_a_missing_profile_flags_nothing_rather_than_everything(self):
        original = hs._profile
        try:
            hs._profile = {}
            self.assertEqual(hs.off_register_words("quintessential crucible"), [])
        finally:
            hs._profile = original

    def test_line_two_is_scored_not_just_the_opener(self):
        text = "Your first AI eval should be an Excel or a spreadsheet.\nThis underscores a pivotal paradigm."
        self.assertEqual(hs.evaluate(text).reason_code, "off-register-word")
