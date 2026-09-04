"""An exhausted day should hand back the closest safe candidate, not nothing."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import best_effort, workflow


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


class BestEffortSelectionTests(unittest.TestCase):
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
def candidate(*, honesty: str = "PASS") -> SimpleNamespace:
    return SimpleNamespace(
        candidate_id="candidate-1",
        text="A grounded candidate that remains private.",
        effective_total=20,
        axes={
            "hook_strength": 4,
            "middle_escalation": 4,
            "earned_closer": 4,
            "specificity_and_source_quality": 4,
            "voice_fidelity": 4,
        },
        gates={
            "authority_conversion": "PASS",
            "proof": "NOT_REQUIRED",
            "honesty": honesty,
            "citation": "PASS",
            "relevance": "PASS",
        },
        passes_required_gates=honesty == "PASS",
    )


class BestEffortTests(unittest.TestCase):
    def test_safe_candidate_is_written_as_best_effort_with_shortfalls(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            target = Path(temporary) / "best-effort-post.md"
            with (
                patch.dict(os.environ, {best_effort.OUTPUT_ENV: str(target)}),
                patch.object(best_effort.v1_completion, "_read_jsonl", return_value=[]),
                patch.object(best_effort.v1_completion, "record_decision") as record,
            ):
                written = best_effort.write(
                    candidate(),
                    SimpleNamespace(review_status=None, recommendation=None),
                    cycle=4,
                    failure_reason="quality search exhausted",
                )
            rendered = written.read_text(encoding="utf-8")
            self.assertIn("BEST_EFFORT — NOT READY_FOR_HUMAN_REVIEW", rendered)
            self.assertIn("A grounded candidate that remains private.", rendered)
            self.assertIn("`honesty` — PASS", rendered)
            self.assertIn("`critic_total` — observed 20/25", rendered)
            self.assertIn("`hook_strength` — observed 4/5", rendered)
            self.assertEqual(stat.S_IMODE(written.stat().st_mode), 0o600)
            privacy = record.call_args.args[0]
            self.assertEqual(privacy["contract"], "gate_privacy")
            self.assertEqual(privacy["status"], "PASS")

    def test_hard_gate_failure_writes_nothing_and_names_gate(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            target = Path(temporary) / "best-effort-post.md"
            with (
                patch.dict(os.environ, {best_effort.OUTPUT_ENV: str(target)}),
                patch.object(best_effort.v1_completion, "record_decision"),
            ):
                with self.assertRaisesRegex(workflow.WorkflowError, "honesty"):
                    best_effort.write(
                        candidate(honesty="FAIL"),
                        SimpleNamespace(review_status=None, recommendation=None),
                        cycle=4,
                        failure_reason="quality search exhausted",
                    )
            self.assertFalse(target.exists())


if __name__ == "__main__":
    unittest.main()
