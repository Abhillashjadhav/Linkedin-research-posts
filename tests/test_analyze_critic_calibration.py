"""The calibration analysis is fixed before any real judge scores exist."""

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
    / "analyze.py"
)
SPEC = importlib.util.spec_from_file_location("analyze_critic_calibration", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
analyze = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analyze)


class AnalyzeCriticCalibrationTests(unittest.TestCase):
    def write_json(self, path: Path, value: object) -> None:
        path.write_text(json.dumps(value), encoding="utf-8")

    def write_jsonl(self, path: Path, rows: list[dict[str, object]]) -> None:
        path.write_text(
            "".join(json.dumps(row) + "\n" for row in rows),
            encoding="utf-8",
        )

    def fixture(self, root: Path) -> dict[str, Path]:
        axes = analyze.AXES
        calibration: list[dict[str, object]] = []
        owner: list[dict[str, object]] = []
        run1: list[dict[str, object]] = []
        run2: list[dict[str, object]] = []
        for index in range(1, 31):
            item_id = f"CAL-{index:02d}"
            outcome = "GOOD" if index <= 15 else "BAD"
            calibration.append({"item_id": item_id, "label": outcome})
            owner_value = 4 if outcome == "GOOD" else 2
            owner.append(
                {
                    "item_id": item_id,
                    "label": outcome,
                    "scores": {axis: owner_value for axis in axes},
                }
            )

            if index == 1:
                run1_label, run1_value, run1_total = "BAD", 4, 20
            elif index == 16:
                run1_label, run1_value, run1_total = "GOOD", 5, 25
            elif outcome == "GOOD":
                run1_label, run1_value, run1_total = "GOOD", 5, 25
            else:
                run1_label, run1_value, run1_total = "BAD", 3, 15
            row = {
                "item_id": item_id,
                "run": 1,
                "primary": True,
                "status": "PASS",
                "label": run1_label,
                "effective_total": run1_total,
                "scores": {axis: run1_value for axis in axes},
            }
            run1.append(row)
            retest = {**row, "run": 2, "primary": False}
            if index == 2:
                retest = {
                    **retest,
                    "label": "BAD",
                    "effective_total": 20,
                    "scores": {axis: 4 for axis in axes},
                }
            run2.append(retest)

        paths = {
            "calibration": root / "calibration-set.json",
            "owner": root / "owner-labels.jsonl",
            "run1": root / "judge-labels.run1.jsonl",
            "run2": root / "judge-labels.run2.jsonl",
            "results": root / "three-way-results.json",
            "findings": root / "judge-calibration-findings.md",
        }
        self.write_json(paths["calibration"], calibration)
        self.write_jsonl(paths["owner"], owner)
        self.write_jsonl(paths["run1"], run1)
        self.write_jsonl(paths["run2"], run2)
        return paths

    def test_known_answers_and_deliberate_retest_flip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(Path(temporary))
            result = analyze.analyze(**{f"{key}_path": value for key, value in paths.items()})

            agreements = {
                row["pair"]: row for row in result["agreements"]
            }
            self.assertEqual(result["status"], "PASS")
            self.assertEqual(agreements["outcome_vs_owner"]["kappa"], 1.0)
            self.assertEqual(agreements["outcome_vs_judge"]["kappa"], 0.867)
            self.assertEqual(agreements["owner_vs_judge"]["kappa"], 0.867)
            self.assertEqual(result["test_retest"]["label_flip_count"], 1)
            self.assertEqual(result["test_retest"]["label_flip_rate"], 0.033)
            self.assertEqual(
                result["test_retest"]["per_axis_mean_absolute_difference"]["hook_strength"],
                0.033,
            )
            self.assertEqual(result["winner_false_negatives"]["count"], 1)
            self.assertEqual(result["winner_false_negatives"]["item_ids"], ["CAL-01"])
            self.assertEqual(
                result["effective_total_threshold_sweep"]["at_live_threshold"]["kappa"],
                0.867,
            )
            self.assertEqual(
                result["effective_total_threshold_sweep"]["maximum_kappa"],
                0.933,
            )
            self.assertEqual(
                result["effective_total_threshold_sweep"]["maximising_thresholds"],
                [16, 17, 18, 19, 20],
            )
            for variant in result["variants"].values():
                self.assertEqual(variant["proportional_live_threshold"], 19)
                self.assertEqual(
                    variant["at_proportional_live_threshold"]["kappa"], 0.867
                )
                self.assertTrue(variant["overfitted_to_n_30"])
            findings = paths["findings"].read_text(encoding="utf-8")
            self.assertLess(
                findings.index("Operational result first"),
                findings.index("Three-way agreement"),
            )
            for phrase in (
                "1 of 15 known winners",
                "Label flips: **1 of 30** (0.033)",
                "Voice fidelity used the outcome-free voice guide",
                "Specificity has a known downward bias",
            ):
                self.assertIn(phrase, findings)

    def test_blocked_row_exits_before_three_way(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(Path(temporary))
            rows = [
                json.loads(line)
                for line in paths["run2"].read_text(encoding="utf-8").splitlines()
            ]
            rows[0]["status"] = "BLOCKED"
            rows[0]["label"] = "BLOCKED"
            self.write_jsonl(paths["run2"], rows)
            with patch.object(analyze.three_way, "run") as comparison:
                status = analyze.main(
                    [
                        "--calibration", str(paths["calibration"]),
                        "--owner", str(paths["owner"]),
                        "--run1", str(paths["run1"]),
                        "--run2", str(paths["run2"]),
                        "--results", str(paths["results"]),
                        "--findings", str(paths["findings"]),
                    ]
                )
            self.assertEqual(status, 2)
            comparison.assert_not_called()
            self.assertFalse(paths["results"].exists())

    def test_combined_judge_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(Path(temporary))
            combined = Path(temporary) / "judge-labels.jsonl"
            combined.write_text(paths["run1"].read_text(encoding="utf-8"))
            with self.assertRaisesRegex(
                analyze.AnalysisFailure, "combined judge-labels.jsonl"
            ):
                analyze.analyze(
                    paths["calibration"],
                    paths["owner"],
                    combined,
                    paths["run2"],
                    paths["results"],
                    paths["findings"],
                )


if __name__ == "__main__":
    unittest.main()
