"""An exhausted day should hand back the closest safe candidate, not nothing."""

import unittest

from authority_os import best_effort


def cycle(n, *candidates):
    return {
        "cycle": n,
        "scores": [c["score"] for c in candidates],
        "gates": {c["score"]["candidate_id"]: c["gates"] for c in candidates},
        "anti_slop": {c["score"]["candidate_id"]: c.get("slop", []) for c in candidates},
    }


def cand(cid, total, hook, gates=None, slop=None):
    return {
        "score": {"candidate_id": cid, "effective_total": total, "hook_strength": hook},
        "gates": gates or {g: {"status": "PASS"} for g in best_effort.BLOCKING_GATES},
        "slop": slop or [],
    }


class BestEffortTests(unittest.TestCase):
    def test_closest_candidate_to_the_bar_wins(self):
        result = best_effort.select([
            cycle(1, cand("c1", 20, 4), cand("c2", 23, 5)),
            cycle(2, cand("c3", 21, 5)),
        ])
        self.assertEqual(result.candidate_id, "c2")
        self.assertEqual(result.total_gap, 1.0)

    def test_a_blocking_gate_failure_is_never_selected(self):
        failing = {g: {"status": "PASS"} for g in best_effort.BLOCKING_GATES}
        failing["honesty"] = {"status": "FAIL"}
        result = best_effort.select([
            cycle(1, cand("unsafe", 23, 5, gates=failing), cand("safe", 18, 3)),
        ])
        self.assertEqual(result.candidate_id, "safe")

    def test_all_candidates_unsafe_returns_none_and_blocks(self):
        failing = {g: {"status": "PASS"} for g in best_effort.BLOCKING_GATES}
        failing["citation"] = {"status": "FAIL"}
        result = best_effort.select([cycle(1, cand("x", 24, 5, gates=failing))])
        self.assertIsNone(result)
        self.assertEqual(best_effort.package(result)["status"], "BLOCKED")

    def test_shortfalls_name_every_missed_bar(self):
        result = best_effort.select([
            cycle(1, cand("c1", 21, 3, slop=[{"code": "colon-reveal", "excerpt": "x"}])),
        ])
        bars = {s.bar for s in result.shortfalls}
        self.assertEqual(bars, {"score", "hook", "anti_slop"})

    def test_package_is_never_ready_for_human_review(self):
        result = best_effort.select([cycle(1, cand("c1", 23, 5))])
        payload = best_effort.package(result)
        self.assertEqual(payload["status"], "BEST_EFFORT")
        self.assertEqual(payload["publishing_status"], "DISABLED")
        self.assertEqual(payload["human_approval_status"], "NOT_APPROVED")
        self.assertTrue(payload["manual_fact_verification_required"])

    def test_a_candidate_that_clears_everything_has_no_shortfall(self):
        result = best_effort.select([cycle(1, cand("c1", 25, 5))])
        self.assertEqual(result.shortfalls, ())
        self.assertEqual(result.total_gap, 0.0)

    def test_every_shortfall_carries_a_fix_hint(self):
        result = best_effort.select([cycle(1, cand("c1", 20, 4, slop=[{"code": "hedge"}]))])
        for shortfall in result.shortfalls:
            self.assertTrue(shortfall.fix_hint.strip())


if __name__ == "__main__":
    unittest.main()
