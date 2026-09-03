"""A day should always produce its best available topic, and say what it lacked."""

import unittest

from authority_os import topic_selection as ts


def cand(cid, topic, momentum, **scores):
    base = {"reader_relevance": 4, "reader_value": 4, "gravity": 3,
            "evidence_strength": 4, "authority_fit": 4}
    base.update(scores)
    return {"id": cid, "topic": topic, "total": momentum, "scores": base}


class TopicSelectionTests(unittest.TestCase):
    def test_measured_distribution_decides_the_order(self):
        ranked = ts.rank([
            cand("t1", "quiet topic", 15),
            cand("t2", "hot topic", 22),
            cand("t3", "warm topic", 18),
        ])
        self.assertEqual([r.topic_id for r in ranked], ["t2", "t3", "t1"])
        self.assertEqual([r.rank for r in ranked], [1, 2, 3])

    def test_a_weak_topic_is_still_selected_and_its_gap_recorded(self):
        chosen = ts.select([cand("t1", "thin but live", 21, reader_value=2, gravity=1)])
        self.assertEqual(chosen.status, "SELECTED_BELOW_TARGET")
        self.assertEqual({s.axis for s in chosen.shortfalls}, {"reader_value", "gravity"})
        self.assertEqual(chosen.total_gap, 3)

    def test_missing_evidence_is_the_only_thing_that_blocks(self):
        ranked = ts.rank([
            cand("t1", "no evidence", 25, evidence_strength=1),
            cand("t2", "weak everywhere but sourced", 8, reader_relevance=1,
                 reader_value=1, gravity=1, authority_fit=1),
        ])
        self.assertEqual(ranked[0].topic_id, "t2")
        self.assertEqual(ranked[1].status, "BLOCKED")
        self.assertEqual(ranked[1].reason_code, "insufficient-body-read-evidence")

    def test_a_day_with_no_sourced_topic_returns_nothing(self):
        self.assertIsNone(ts.select([cand("t1", "unsourced", 25, evidence_strength=2)]))

    def test_a_topic_meeting_every_target_reports_no_shortfall(self):
        chosen = ts.select([cand("t1", "strong", 20, reader_relevance=5, reader_value=5,
                                 gravity=4, evidence_strength=4, authority_fit=4)])
        self.assertEqual(chosen.status, "SELECTED")
        self.assertEqual(chosen.shortfalls, ())
        self.assertEqual(chosen.reason_code, "ok")

    def test_shortfalls_are_ordered_by_size_of_gap(self):
        chosen = ts.select([cand("t1", "x", 20, reader_value=1, authority_fit=2)])
        self.assertEqual([s.axis for s in chosen.shortfalls], ["reader_value", "authority_fit"])

    def test_diagnostic_names_the_axis_costing_the_most_topics(self):
        report = ts.diagnostic([
            cand("t1", "a", 20, reader_value=2),
            cand("t2", "b", 19, reader_value=3),
            cand("t3", "c", 18, gravity=1),
        ])
        self.assertEqual(report["candidates"], 3)
        self.assertEqual(report["axis_shortfall_counts"]["reader_value"], 2)
        self.assertEqual(report["most_limiting_axis"], "reader_value")
        self.assertEqual(report["blocked_on_evidence"], 0)

    def test_diagnostic_counts_topics_that_met_every_target(self):
        report = ts.diagnostic([cand("t1", "a", 20), cand("t2", "b", 10, reader_value=2)])
        self.assertEqual(report["at_or_above_target"], 1)
        self.assertEqual(report["below_target"], 1)
        self.assertEqual(report["selected_topic_id"], "t1")

    def test_momentum_none_sorts_below_a_measured_topic(self):
        ranked = ts.rank([cand("t1", "unmeasured", None), cand("t2", "measured", 5)])
        self.assertEqual(ranked[0].topic_id, "t2")


if __name__ == "__main__":
    unittest.main()
