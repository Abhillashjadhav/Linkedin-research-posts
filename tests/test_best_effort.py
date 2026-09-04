"""Tests for the private BEST_EFFORT handoff."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import best_effort, workflow


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

    def test_hard_gate_failure_writes_nothing_and_names_gate(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            target = Path(temporary) / "best-effort-post.md"
            with patch.dict(os.environ, {best_effort.OUTPUT_ENV: str(target)}):
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
