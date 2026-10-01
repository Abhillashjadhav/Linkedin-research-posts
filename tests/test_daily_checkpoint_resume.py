"""Offline, run-bound daily checkpoint and deadline regressions."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli as daily, runtime_budget, storage, workflow
from tests.test_discovery_resume import AS_OF, candidate, profile_payload


class CheckpointResumeTests(unittest.TestCase):
    def setUp(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        self.source.mkdir()
        self.profile = profile_payload()
        self.profile_path = self.root / "profile.json"
        self.profile_path.write_text(json.dumps(self.profile), encoding="utf-8")
        self.args = daily.parser().parse_args([
            "--profile", str(self.profile_path), "--as-of", AS_OF,
            "--output-dir", str(self.root / "resumed"),
            "--db", str(self.root / "authority.sqlite"),
            "--allow-web-research", "--allow-model-egress",
        ])
        self.fingerprint = daily._run_input_fingerprint(self.args, self.profile, AS_OF)
        daily.base.write_private_json(self.source / "run-input.json", {
            "schema_version": 1, "run_id": "source-unique-run", "as_of": AS_OF,
            "input_fingerprint": self.fingerprint,
            "contract_sha256": daily._contract_sha256(),
            "implementation_sha256": daily._implementation_sha256(),
        })

    def _checkpoint_discovery(self) -> None:
        daily.base.write_private_json(self.source / "momentum.json", {
            "schema_version": 1, "created_at": AS_OF, "topic": None,
            "days": 7, "candidates": [candidate()],
        })
        daily._write_stage_checkpoint(self.source, "conversation_discovery", self.fingerprint)

    def _checkpoint_admission(self) -> None:
        self._checkpoint_discovery()
        daily.base.write_private_json(self.source / daily.ADMITTED_SCOPE_NAME, {
            "schema_version": 1, "created_at": AS_OF, "topic": None,
            "days": 7, "route": "momentum-qualified", "candidates": [candidate()],
            "scope_fingerprint": daily.evidence_scope_fingerprint([candidate()]),
            "profile_sha256": daily._mapping_sha256(self.profile),
        })
        daily._write_stage_checkpoint(self.source, "topic_admission", self.fingerprint)

    def _checkpoint_evidence(self) -> dict[str, object]:
        self._checkpoint_admission()
        raw = {
            "id": "signal-1", "canonical_url": "https://example.com/source",
            "title": "A documented product update", "body": "The product update changes a documented decision.",
            "source": "Research lab", "author": "", "published_at": "2026-09-03T12:00:00Z",
            "source_quality": "primary",
        }
        item = workflow.prepare_research_items([raw])[0]
        database = self.root / "authority.sqlite"
        storage.initialise(database)
        storage.insert_research_items(database, [item], evidence_origin="private-import")
        daily.base.write_private_json(self.source / daily.EVIDENCE_CACHE_NAME, {
            "schema_version": 1, "scope_fingerprint": daily.evidence_scope_fingerprint([candidate()]),
            "items": [item],
        })
        daily._write_stage_checkpoint(self.source, "evidence_verification", self.fingerprint)
        return item

    def test_resume_reuses_only_verified_completed_prefix(self) -> None:
        self._checkpoint_admission()
        resumed = daily.load_stage_resume(self.source, args=self.args, profile=self.profile)
        self.assertEqual(resumed.completed_stages, ("conversation_discovery", "topic_admission"))
        self.assertEqual(list(resumed.eligible), [candidate()])
        self.assertEqual(resumed.source_run_id, "source-unique-run")

    def test_changed_topic_implementation_or_contract_rejects_reuse(self) -> None:
        self._checkpoint_admission()
        changed = daily.parser().parse_args([
            "--profile", str(self.profile_path), "--topic", "Different topic",
            "--as-of", AS_OF, "--db", str(self.root / "authority.sqlite"),
            "--allow-web-research", "--allow-model-egress",
        ])
        with self.assertRaisesRegex(workflow.WorkflowError, "input or approved contract differs"):
            daily.load_stage_resume(self.source, args=changed, profile=self.profile)
        with patch.object(daily, "_implementation_sha256", return_value="different"):
            with self.assertRaisesRegex(workflow.WorkflowError, "input or approved contract differs"):
                daily.load_stage_resume(self.source, args=self.args, profile=self.profile)
        with patch.object(daily, "_contract_sha256", return_value="different"):
            with self.assertRaisesRegex(workflow.WorkflowError, "input or approved contract differs"):
                daily.load_stage_resume(self.source, args=self.args, profile=self.profile)

    def test_changed_selected_url_or_deleted_output_rejects_reuse(self) -> None:
        self._checkpoint_admission()
        scope = self.source / daily.ADMITTED_SCOPE_NAME
        text = scope.read_text(encoding="utf-8")
        scope.write_text(text.replace("https://example.com/momentum", "https://example.com/replaced"), encoding="utf-8")
        with self.assertRaisesRegex(workflow.WorkflowError, "output hash changed"):
            daily.load_stage_resume(self.source, args=self.args, profile=self.profile)
        scope.unlink()
        with self.assertRaises(workflow.WorkflowError):
            daily.load_stage_resume(self.source, args=self.args, profile=self.profile)

    def test_checkpoint_copied_to_different_run_directory_is_rejected(self) -> None:
        self._checkpoint_discovery()
        other = self.root / "other"
        other.mkdir()
        for name in ("run-input.json", "momentum.json", "checkpoint-conversation_discovery.json"):
            shutil.copyfile(self.source / name, other / name)
        with self.assertRaisesRegex(workflow.WorkflowError, "does not match"):
            daily.load_stage_resume(other, args=self.args, profile=self.profile)

    def test_replaced_selected_evidence_at_same_database_path_rejects_reuse(self) -> None:
        item = self._checkpoint_evidence()
        resumed = daily.load_stage_resume(self.source, args=self.args, profile=self.profile)
        self.assertIn("evidence_verification", resumed.completed_stages)
        self.assertEqual(resumed.evidence_items[0]["fetched_at"], item["fetched_at"])
        with sqlite3.connect(self.root / "authority.sqlite") as connection:
            connection.execute(
                "UPDATE research_items SET body = ? WHERE canonical_url = ?",
                ("A changed body with the stale stored hash.", "https://example.com/source"),
            )
        with self.assertRaisesRegex(workflow.WorkflowError, "body no longer matches"):
            daily.load_stage_resume(self.source, args=self.args, profile=self.profile)

    def test_child_is_killed_at_shared_deadline_and_keeps_private_log(self) -> None:
        prior = os.environ.get(runtime_budget.DEADLINE_ENV)
        os.environ[runtime_budget.DEADLINE_ENV] = str(time.time() + 0.15)
        try:
            result = daily.run_drafting_child(
                [sys.executable, "-c", "import time; print('began', flush=True); time.sleep(5)"],
                cwd=workflow.REPO_ROOT, folder=self.root,
            )
        finally:
            if prior is None:
                os.environ.pop(runtime_budget.DEADLINE_ENV, None)
            else:
                os.environ[runtime_budget.DEADLINE_ENV] = prior
        self.assertEqual(result.returncode, 124)
        self.assertIn("TIME_BUDGET_EXCEEDED", (self.root / "drafting.log").read_text())


if __name__ == "__main__":
    unittest.main()
