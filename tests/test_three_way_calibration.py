"""The triangle has to distinguish a real judge from a lucky one."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evals" / "linkedin-os" / "calibration"))
import three_way  # noqa: E402


GOLD = {f"i{n}": ("GOOD" if n <= 15 else "BAD") for n in range(1, 31)}


def agree(flips=0):
    """A label set matching GOLD except for the first `flips` items."""
    out = dict(GOLD)
    for n in range(1, flips + 1):
        key = f"i{n}"
        out[key] = "BAD" if GOLD[key] == "GOOD" else "GOOD"
    return out


class ThreeWayTests(unittest.TestCase):
    def test_perfect_agreement_gives_kappa_one(self):
        result = three_way.compare("x", list(GOLD.values()), list(GOLD.values()))
        self.assertEqual(result.kappa, 1.0)
        self.assertEqual(result.verdict, "strong")

    def test_a_rubber_stamp_scores_zero_despite_high_agreement(self):
        stamp = ["GOOD"] * 30
        gold = ["GOOD"] * 24 + ["BAD"] * 6
        result = three_way.compare("x", gold, stamp)
        self.assertEqual(result.observed, 0.8)
        self.assertEqual(result.kappa, 0.0)
        self.assertEqual(result.verdict, "no better than chance")

    def test_false_positives_and_negatives_are_reported_separately(self):
        judge = dict(GOLD)
        judge["i16"] = "GOOD"   # a BAD post passed
        judge["i1"] = "BAD"     # a GOOD post blocked
        result = three_way.compare("x", list(GOLD.values()),
                                   [judge[k] for k in GOLD])
        self.assertGreater(result.false_positive_rate, 0)
        self.assertGreater(result.false_negative_rate, 0)

    def test_mismatched_lengths_are_rejected(self):
        with self.assertRaises(ValueError):
            three_way.compare("x", ["GOOD"], ["GOOD", "BAD"])

    def test_labels_outside_the_vocabulary_are_rejected(self):
        with self.assertRaises(ValueError):
            three_way.compare("x", ["GOOD", "MAYBE"], ["GOOD", "BAD"])

    def test_target_is_the_owner_when_his_taste_tracks_outcomes(self):
        result = three_way.run(GOLD, agree(1), agree(8))
        self.assertEqual(result["calibration_target"], "owner")

    def test_target_is_outcomes_when_the_owner_does_not_track_them(self):
        result = three_way.run(GOLD, agree(12), agree(1))
        self.assertEqual(result["calibration_target"], "outcome")

    def test_target_is_outcomes_when_neither_tracks_them(self):
        result = three_way.run(GOLD, agree(12), agree(11))
        self.assertEqual(result["calibration_target"], "outcome")
        self.assertIn("cannot drift", result["target_reason"])

    def test_no_shared_items_blocks_rather_than_returning_a_number(self):
        result = three_way.run(GOLD, {"other": "GOOD"}, {"another": "BAD"})
        self.assertEqual(result["status"], "BLOCKED")

    def test_all_three_pairings_are_reported(self):
        result = three_way.run(GOLD, agree(2), agree(3))
        pairs = {a["pair"] for a in result["agreements"]}
        self.assertEqual(pairs, {"outcome_vs_owner", "outcome_vs_judge", "owner_vs_judge"})

    def test_per_axis_error_is_averaged_over_shared_items(self):
        owner = {"i1": {a: 4 for a in three_way.AXES}}
        judge = {"i1": {**{a: 4 for a in three_way.AXES}, "hook_strength": 2}}
        mae = three_way.score_mae(owner, judge)
        self.assertEqual(mae["hook_strength"], 2.0)
        self.assertEqual(mae["voice_fidelity"], 0.0)

    def test_the_interval_is_reported_because_thirty_items_is_not_many(self):
        result = three_way.compare("x", list(GOLD.values()), list(agree(3).values()))
        low, high = result.agreement_interval_95
        self.assertLess(low, result.observed)
        self.assertGreater(high, result.observed)

    def test_limitations_are_always_returned(self):
        result = three_way.run(GOLD, agree(1), agree(1))
        self.assertTrue(result["limitations"])


if __name__ == "__main__":
    unittest.main()
