"""Approval, scoping, and cross-process invariants for local corrections."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from workflow_beacon.corrections import CorrectionError, CorrectionStore, MAX_CONTEXT_CHARS


class CorrectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = CorrectionStore(self.root)

    def approved(self, text="Avoid unsupported example numbers.", **kwargs):
        identifier = self.store.add(text, source_ref="test fixture explicit correction", source_kind="user", **kwargs)
        self.store.approve(identifier, reviewed_by="fixture reviewer")
        return identifier

    def test_pending_machine_and_user_entries_never_enter_context(self):
        for kind in ("user", "machine"):
            self.store.add("Pending " + kind, source_ref="fixture", source_kind=kind)
        snapshot = self.store.snapshot("linkedin-os", "writer", "run-1")
        self.assertEqual(snapshot.context, "")
        self.assertEqual(snapshot.rule_ids, ())

    def test_project_workflow_and_role_isolation(self):
        expected = self.approved(workflow="linkedin-os", roles=("writer",))
        self.approved("PMOS-only fixture rule.", workflow="pmos")
        writer = self.store.snapshot("linkedin-os", "writer", "run-1")
        critic = self.store.snapshot("linkedin-os", "critic", "run-1")
        self.assertEqual(writer.rule_ids, (expected,))
        self.assertEqual(critic.rule_ids, ())
        self.assertEqual(writer.digest, critic.digest)
        other = self.root / "other-project"
        other.mkdir()
        self.assertEqual(CorrectionStore(other).snapshot("linkedin-os").rule_ids, ())

    def test_revocation_changes_next_run_not_existing_snapshot(self):
        identifier = self.approved()
        before = self.store.snapshot("linkedin-os", "writer", "run-1")
        self.store.revoke(identifier, reviewed_by="fixture reviewer")
        current = self.store.snapshot("linkedin-os", "critic", "run-1")
        next_run = self.store.snapshot("linkedin-os", "writer", "run-2")
        self.assertEqual(before.digest, current.digest)
        self.assertEqual(current.rule_ids, (identifier,))
        self.assertEqual(next_run.rule_ids, ())
        self.assertNotEqual(before.digest, next_run.digest)

    def test_separate_processes_share_frozen_snapshot(self):
        identifier = self.approved()
        script = (
            "import json,sys; from workflow_beacon.corrections import CorrectionStore; "
            "s=CorrectionStore(sys.argv[1]).snapshot('linkedin-os',sys.argv[2],sys.argv[3]); "
            "print(json.dumps(s.metadata()))"
        )
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
        def run(role, run_id):
            return json.loads(subprocess.check_output([sys.executable, "-c", script, str(self.root), role, run_id], env=env, text=True))
        writer = run("writer", "same-run")
        self.store.revoke(identifier, reviewed_by="fixture reviewer")
        critic = run("critic", "same-run")
        fresh = run("writer", "next-run")
        self.assertEqual(writer["correction_digest"], critic["correction_digest"])
        self.assertEqual(critic["correction_ids"], [identifier])
        self.assertEqual(fresh["correction_ids"], [])

    def test_named_conflicts_need_explicit_supersession(self):
        first = self.approved("Use an incident-led opening.", key="opening", workflow="linkedin-os")
        second = self.store.add("Use a decision-led opening.", source_ref="fixture", source_kind="user", key="opening", workflow="linkedin-os")
        with self.assertRaises(CorrectionError):
            self.store.approve(second, reviewed_by="fixture reviewer")
        self.store.approve(second, reviewed_by="fixture reviewer", supersedes=first)
        self.assertEqual(self.store.snapshot("linkedin-os").rule_ids, (second,))
        self.assertEqual(self.store.list_rules()[0]["status"], "superseded")

    def test_metadata_omits_text_and_provenance(self):
        self.approved("PRIVATE_RULE_SENTINEL")
        metadata = json.dumps(self.store.snapshot("linkedin-os").metadata())
        self.assertNotIn("PRIVATE_RULE_SENTINEL", metadata)
        self.assertNotIn("fixture reviewer", metadata)
        self.assertNotIn("test fixture", metadata)

    def test_approval_refuses_excess_context_instead_of_dropping_rules(self):
        accepted = []
        for index in range(35):
            identifier = self.store.add(f"Rule {index}: " + "x" * 1100, source_ref="fixture")
            try:
                self.store.approve(identifier, reviewed_by="fixture reviewer")
            except CorrectionError:
                break
            accepted.append(identifier)
        snapshot = self.store.snapshot("linkedin-os")
        self.assertLessEqual(len(snapshot.context), MAX_CONTEXT_CHARS)
        self.assertEqual(snapshot.omitted_count, 0)
        self.assertEqual(list(snapshot.rule_ids), accepted)
        self.assertLess(len(accepted), 35)

    def test_approval_flag_without_review_history_is_rejected(self):
        self.store.add("Pending fixture.", source_ref="fixture")
        payload = json.loads(self.store.registry_path.read_text())
        payload["rules"][0]["status"] = "approved"
        self.store.registry_path.write_text(json.dumps(payload))
        snapshot = self.store.snapshot("linkedin-os")
        self.assertEqual(snapshot.rule_ids, ())
        self.assertTrue(snapshot.registry_fallback)

    def test_corrupt_current_uses_last_good_without_reviving_revoked_rule(self):
        identifier = self.approved()
        self.store.revoke(identifier, reviewed_by="fixture reviewer")
        self.store.registry_path.write_text("corrupt")
        snapshot = self.store.snapshot("linkedin-os", run_id="after-revoke")
        self.assertTrue(snapshot.registry_fallback)
        self.assertEqual(snapshot.rule_ids, ())

    def test_literal_checks_distinguish_pass_violation_and_subjective(self):
        forbidden = self.approved("Avoid a perfect score claim.", forbidden_literal="100% correct")
        required = self.approved("Name the source.", required_literal="Source:")
        subjective = self.approved("Use plain language.")
        snapshot = self.store.snapshot("linkedin-os")
        failed = snapshot.evaluate("This is 100% correct.")
        passed = snapshot.evaluate("Source: the supplied report.")
        self.assertEqual(failed["status"], "violated")
        self.assertEqual(failed["violation_count"], 2)
        self.assertEqual({item["rule_id"] for item in failed["rules"] if item["status"] == "violated"}, {forbidden, required})
        self.assertEqual(passed["status"], "partially_evaluated")
        self.assertEqual(passed["violation_count"], 0)
        self.assertEqual(passed["passed_count"], 2)
        self.assertIn({"rule_id": subjective, "status": "not_evaluated", "reason": "subjective_rule"}, passed["rules"])
        self.assertNotIn("Source: the supplied report", json.dumps(passed))

    def test_cli_machine_import_cannot_self_approve(self):
        text_file = self.root / "proposal.txt"
        text_file.write_text("A machine proposal.")
        result = subprocess.run([
            sys.executable, "-m", "workflow_beacon.corrections", "--project-root", str(self.root),
            "add", "--text-file", str(text_file), "--source-ref", "fixture", "--source-kind", "machine",
            "--approve", "--reviewed-by", "fixture reviewer",
        ], env=dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src")), capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.store.registry_path.exists())


if __name__ == "__main__":
    unittest.main()
