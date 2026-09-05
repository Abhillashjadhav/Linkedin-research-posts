"""Native export must preserve actual product behavior without any network call."""

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_monitoring_export import context

from authority_os.monitoring_export import build_normalized_export


def decisions(run_id: str) -> list[dict[str, object]]:
    return [
        {
            "run_id": run_id,
            "recorded_at": "2026-08-30T12:00:00Z",
            "contract": contract,
            "status": "PASS",
            "subject_id": "candidate-1",
            "mode": "diagnostic",
            "evidence": {"observed_status": "FAIL", "cycle": cycle, "score": 3},
        }
        for contract, cycle in [
            ("research_trust", 1),
            ("gate_citation", 1),
            ("gate_citation", 2),
        ]
    ]


class MonitoringConnectionTests(unittest.TestCase):
    def test_cycle_score_facts_do_not_inherit_candidate_failure_or_rejection(self):
        from authority_os.monitoring_dashboard_export import export_completed_dashboard

        ctx = context()
        run = {"run_id": ctx["run_id"], "outcome": "COMPLETED_WITH_WARNINGS"}
        axes = {
            "hook_strength": 3,
            "middle_escalation": 3,
            "earned_closer": 5,
            "specificity_and_source_quality": 4,
            "voice_fidelity": 4,
        }
        evaluation = {
            "run_id": ctx["run_id"],
            "acceptance_contract": {
                "minimum_total": 18,
                "axis_floors": dict(axes, hook_strength=4, earned_closer=3),
            },
            "critic_scorecards": [
                {
                    "candidate_id": "candidate-1",
                    "cycle": cycle,
                    "status": status,
                    "total": 19,
                    "threshold": 18,
                    "axes": axes,
                    "failure_codes": ["hook_strength"],
                    "advisory_codes": [],
                }
                for cycle, status in ((1, "FAIL"), (2, "REJECTED"))
            ],
        }
        with patch(
            "authority_os.monitoring_dashboard_export._read_dashboard",
            side_effect=[run, evaluation],
        ):
            result = export_completed_dashboard(ctx, Path("unused"))
        for cycle in (1, 2):
            facts = {
                fact["contract"]: fact
                for fact in result["source_facts"]
                if fact["cycle"] == cycle
            }
            self.assertEqual(facts["critic_total"]["observed_status"], "PASS")
            self.assertEqual(facts["hook_strength"]["observed_status"], "FAIL")
            self.assertEqual(facts["earned_closer"]["observed_status"], "PASS")
            self.assertEqual(facts["earned_closer"]["reason_codes"], [])
            self.assertEqual(
                facts["critic_candidate_status"]["recorded_status"],
                "FAIL" if cycle == 1 else "REJECTED",
            )
        evaluation.pop("acceptance_contract")
        with patch(
            "authority_os.monitoring_dashboard_export._read_dashboard",
            side_effect=[run, evaluation],
        ):
            unknown_policy = export_completed_dashboard(ctx, Path("unused"))
        hook = next(
            fact
            for fact in unknown_policy["source_facts"]
            if fact["contract"] == "hook_strength"
        )
        self.assertEqual(hook["observed_status"], "NOT_EVALUATED")
        self.assertEqual(hook["value"], 3)
        total = next(
            fact
            for fact in unknown_policy["source_facts"]
            if fact["contract"] == "critic_total"
        )
        self.assertEqual(total["observed_status"], "PASS")

    def test_dashboard_reader_rejects_symlinks_and_special_files(self) -> None:
        from authority_os import workflow
        from authority_os.monitoring_dashboard_export import _read_dashboard

        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "private.json"
            target.write_text("{}")
            target.chmod(0o600)
            link = root / "linked.json"
            link.symlink_to(target)
            fifo = root / "pipe.json"
            os.mkfifo(fifo, mode=0o600)
            with patch.object(workflow, "DEFAULT_PRIVATE_DATA", root):
                with self.assertRaises(OSError):
                    _read_dashboard(root, link.name)
                with self.assertRaisesRegex(workflow.WorkflowError, "regular file"):
                    _read_dashboard(root, fifo.name)

    def test_explicit_identity_survives_run_change(self) -> None:
        first = dict(
            context(),
            case_id="frozen-input-1",
            input_fingerprint="sha256:" + "a" * 64,
            comparison_sha256="sha256:" + "b" * 64,
        )
        second = dict(first, run_id="linkedin-production-2")
        a = build_normalized_export(first, decisions(first["run_id"]))
        b = build_normalized_export(second, decisions(second["run_id"]))
        assert a["cases"][0]["case"] == b["cases"][0]["case"]
        assert a["comparison"]["sha256"] == first["comparison_sha256"]

    def test_raw_advisories_and_cycles_survive_export(self) -> None:
        ctx = context()
        result = build_normalized_export(ctx, decisions(ctx["run_id"]))
        facts = result["source_facts"]
        citation = [f for f in facts if f["contract"] == "gate_citation"]
        assert [f["cycle"] for f in citation] == [1, 2]
        assert all(
            f["recorded_status"] == "PASS" and f["observed_status"] == "FAIL"
            for f in citation
        )
        checks = {c["definition_id"]: c for c in result["cases"][0]["checks"]}
        assert "claim-body-support" in checks
        assert checks["claim-body-support"]["status"] == "NOT_EVALUATED"

    def test_completed_package_preserves_nested_gates_and_evaluates_actual_scores(self):
        import json

        from test_eval_package import _evaluated_result

        from authority_os import workflow
        from authority_os.monitoring_dashboard_export import export_completed_dashboard

        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        patcher = patch.object(workflow, "DEFAULT_PRIVATE_DATA", tmp_path)
        patcher.start()
        self.addCleanup(patcher.stop)
        folder = tmp_path / "finished"
        folder.mkdir(mode=0o700)
        ctx = dict(
            context(), case_id="fixed-case", input_fingerprint="sha256:" + "a" * 64
        )
        first = _evaluated_result((4, 4, 4, 4, 4), hard_gates_pass=False)
        second = _evaluated_result((5, 4, 4, 4, 4))
        second["candidate_id"] = "candidate-3"
        second["acceptance"]["status"] = "NOT_EVALUATED"
        run = {"run_id": ctx["run_id"], "outcome": "COMPLETED_WITH_WARNINGS"}
        evaluation = {
            "run_id": ctx["run_id"],
            "acceptance_contract": {
                "minimum_total": 18,
                "axis_floors": {"hook_strength": 4, "voice_fidelity": 4},
            },
            "checks": [],
            "results": [first, second],
            "critic_scorecards": [],
        }
        for filename, payload in [
            ("run-dashboard.json", run),
            ("eval-dashboard.json", evaluation),
        ]:
            path = folder / filename
            path.write_text(json.dumps(payload))
            path.chmod(0o600)
        exported = export_completed_dashboard(ctx, folder)
        assert exported["delivery_outcome"] == "COMPLETED_WITH_WARNINGS"
        candidates = [
            case
            for case in exported["cases"]
            if case["case_type"] == "linkedin-candidate"
        ]
        assert len(candidates) == 2
        assert candidates[0]["case"]["case_id"] != candidates[1]["case"]["case_id"]
        acceptance_check = next(
            check
            for check in candidates[1]["checks"]
            if check["definition_id"] == "candidate-acceptance"
        )
        assert acceptance_check["status"] == "NOT_EVALUATED"
        assert acceptance_check["current_value"] is None
        historical_axis = next(
            check
            for check in candidates[0]["checks"]
            if check["definition_id"] == "middle-escalation"
        )
        assert historical_axis["status"] == "NOT_EVALUATED"
        assert historical_axis["current_value"] == 4
        assert historical_axis["recorded_threshold"] == {"value": None}
        assert (
            next(
                check
                for check in candidates[0]["checks"]
                if check["definition_id"] == "critic-total"
            )["current_value"]
            == first["scorecard"]["effective_total"]
        )
        facts = exported["source_facts"]
        assert any(
            f["contract"] == "gate_honesty" and f["observed_status"] == "FAIL"
            for f in facts
        )
        assert (
            len(
                {
                    f["subject_id"]
                    for f in facts
                    if f["contract"] == "candidate_acceptance"
                }
            )
            == 2
        )
        evaluation.pop("acceptance_contract")
        (folder / "eval-dashboard.json").write_text(json.dumps(evaluation))
        unversioned = export_completed_dashboard(ctx, folder)
        unversioned_candidate = next(
            case
            for case in unversioned["cases"]
            if case["case_type"] == "linkedin-candidate"
        )
        score_check = next(
            check
            for check in unversioned_candidate["checks"]
            if check["definition_id"] == "critic-total"
        )
        assert score_check["current_value"] == first["scorecard"]["effective_total"]
        assert score_check["status"] == "NOT_EVALUATED"
        assert score_check["recorded_threshold"] == {"value": None}
        assert (
            next(
                check
                for check in unversioned_candidate["checks"]
                if check["definition_id"] == "candidate-acceptance"
            )["status"]
            == first["acceptance"]["status"]
        )
