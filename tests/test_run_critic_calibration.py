"""The published-post Critic calibration stays blind and records failures."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "linkedin-os"
    / "calibration"
    / "run_critic.py"
)
SPEC = importlib.util.spec_from_file_location("run_critic_calibration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
run_critic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(run_critic)


class RunCriticCalibrationTests(unittest.TestCase):
    def item(self) -> dict[str, object]:
        return {
            "item_id": "CAL-01",
            "text": "A concrete post for product leaders.",
            "label": "GOOD",
            "lift": 2.4,
            "impressions": 100,
            "engagements": 10,
            "rank_by_lift": 1,
        }

    def test_blind_projection_contains_only_id_and_text(self) -> None:
        self.assertEqual(
            run_critic._blind_item(self.item()),
            {
                "item_id": "CAL-01",
                "text": "A concrete post for product leaders.",
            },
        )

    def test_real_contract_scores_without_outcome_fields(self) -> None:
        response = {
            "scorecards": [
                {
                    "candidate_id": "CAL-01",
                    "hook_strength": 5,
                    "middle_escalation": 4,
                    "earned_closer": 4,
                    "specificity_and_source_quality": 4,
                    "voice_fidelity": 5,
                }
            ]
        }
        with patch.object(
            run_critic.model_runtime,
            "invoke_structured",
            return_value=response,
        ) as invoke:
            row = run_critic.score_item(
                self.item(), calibration_items=[self.item()], run=1, timeout=30
            )

        self.assertEqual(row["status"], "PASS")
        self.assertEqual(row["label"], "GOOD")
        self.assertEqual(row["total"], 22)
        self.assertEqual(row["band"], "one-light-revision")
        self.assertEqual(row["gates"]["proof"], "NOT_EVALUATED")
        self.assertTrue(row["primary"])
        self.assertEqual(row["prompt_leak_check"]["calibration_posts_found"], 1)
        task_prompt = invoke.call_args.kwargs["task_prompt"]
        for field in run_critic.FORBIDDEN_OUTCOME_FIELDS:
            self.assertNotIn(f'"{field}"', task_prompt)

    def test_off_schema_response_is_blocked(self) -> None:
        with patch.object(
            run_critic.model_runtime,
            "invoke_structured",
            return_value={"scorecards": []},
        ):
            row = run_critic.score_item(
                self.item(), calibration_items=[self.item()], run=2, timeout=30
            )
        self.assertEqual(row["status"], "BLOCKED")
        self.assertEqual(row["label"], "BLOCKED")

    def test_final_prompt_leak_blocks_before_model_invocation(self) -> None:
        other = {
            **self.item(),
            "item_id": "CAL-02",
            "text": "A second calibration post that must not appear.",
            "lift": 0.2,
            "rank_by_lift": 30,
        }
        contaminated = {
            "provenance": "measured-performance-anchors",
            "bad_anchor": other["text"],
        }
        with (
            patch.object(
                run_critic,
                "_calibration_voice_guidance",
                return_value=contaminated,
            ),
            patch.object(run_critic.model_runtime, "invoke_structured") as invoke,
        ):
            row = run_critic.score_item(
                self.item(),
                calibration_items=[self.item(), other],
                run=1,
                timeout=30,
            )
        self.assertEqual(row["status"], "BLOCKED")
        self.assertIn("calibration-post count is 2", row["reason"])
        invoke.assert_not_called()

    def test_sealed_field_value_pair_blocks_prompt(self) -> None:
        item = self.item()
        with self.assertRaises(run_critic.PromptLeakError):
            run_critic._audit_prompt(
                'A concrete post for product leaders.\n"lift": 2.4',
                current=item,
                calibration_items=[item],
            )

    def test_run_writes_separate_primary_retest_and_combined_files(self) -> None:
        items = [
            {
                **self.item(),
                "item_id": f"CAL-{index:02d}",
                "text": f"Unique calibration post {index}.",
            }
            for index in range(1, 31)
        ]

        def fake_score(item, *, calibration_items, run, timeout):  # type: ignore[no-untyped-def]
            return {
                "item_id": item["item_id"],
                "run": run,
                "primary": run == 1,
                "status": "PASS",
                "label": "GOOD",
            }

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run1 = root / "run1.jsonl"
            run2 = root / "run2.jsonl"
            combined = root / "combined.jsonl"
            with (
                patch.object(run_critic, "load_calibration", return_value=items),
                patch.object(run_critic, "score_item", side_effect=fake_score),
            ):
                status = run_critic.run(
                    root / "unused.json", run1, run2, combined, timeout=30
                )
            self.assertEqual(status, 0)
            rows1 = [json.loads(line) for line in run1.read_text().splitlines()]
            rows2 = [json.loads(line) for line in run2.read_text().splitlines()]
            rows = [json.loads(line) for line in combined.read_text().splitlines()]
            self.assertEqual((len(rows1), len(rows2), len(rows)), (30, 30, 60))
            self.assertTrue(all(row["primary"] for row in rows1))
            self.assertTrue(all(not row["primary"] for row in rows2))

    def test_live_voice_anchor_file_has_no_outcome_headings(self) -> None:
        guidance = run_critic.workflow.load_voice_guidance()
        anchor_text = "\n".join(
            value for key, value in guidance.items() if key != "provenance"
        )
        self.assertNotRegex(
            anchor_text,
            r"(?im)^#+.*(?:\blift\b|counter-anchor|conversion|performance|rank)",
        )


if __name__ == "__main__":
    unittest.main()
