"""Human feedback is local, immutable and separate from model reviews."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from authority_os import article_feedback as feedback
from authority_os import article_contract
from authority_os import workflow


class ArticleFeedbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_OUTPUTS)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.private = self.root / "feedback"
        self.identity = mock.patch.object(
            feedback, "_run_identity", return_value=(self.root.name + "/run", "a" * 64, "b" * 64)
        )
        self.identity.start()
        self.addCleanup(self.identity.stop)

    def record(self, **changes: object) -> tuple[Path, bool]:
        options = {
            "decision": "accepted_light_edits", "edit_minutes": "15.5",
            "substantial_rewrites": 0, "hook_replacements": 0,
            "factual_corrections": 1, "notes": "Editor checked the attribution.",
            "feedback_dir": self.private,
        }
        options.update(changes)
        return feedback.record_feedback(self.root / "run", **options)

    def test_record_retry_is_idempotent_and_conflict_preserves_history(self) -> None:
        path, created = self.record()
        self.assertTrue(created)
        original = path.read_bytes()
        repeated, created = self.record()
        self.assertEqual(repeated, path)
        self.assertFalse(created)
        with self.assertRaisesRegex(workflow.WorkflowError, "conflicting feedback"):
            self.record(decision="rejected")
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(feedback.load_records(self.private)), 1)

    def test_summary_uses_observed_reviewed_run_denominator(self) -> None:
        self.record()
        self.identity.stop()
        with mock.patch.object(feedback, "_run_identity", return_value=(self.root.name + "/other", "c" * 64, "d" * 64)):
            self.record(decision="rejected", edit_minutes=4, factual_corrections=0)
        report = feedback.summarise(feedback.load_records(self.private))
        self.assertEqual(report["reviewed_runs"], 2)
        self.assertEqual(report["accepted_light_edits"], 1)
        self.assertEqual(report["accepted_light_edits_rate"], 0.5)
        self.assertEqual(report["median_edit_minutes"], 9.75)
        self.assertIsNone(report["factual_review_pass"])
        self.assertFalse(report["human_approval_granted"])

    def test_light_decision_and_numbers_are_strict(self) -> None:
        for invalid in (True, -1, "NaN", "Infinity", float("nan"), "-0.1"):
            with self.subTest(edit_minutes=invalid), self.assertRaises(workflow.WorkflowError):
                self.record(edit_minutes=invalid)
        for invalid in (True, -1, "1.2", "NaN", float("nan")):
            with self.subTest(count=invalid), self.assertRaises(workflow.WorkflowError):
                self.record(substantial_rewrites=invalid)
        with self.assertRaisesRegex(workflow.WorkflowError, "Light edits"):
            self.record(substantial_rewrites=1)
        with self.assertRaisesRegex(workflow.WorkflowError, "Light edits"):
            self.record(hook_replacements=1)
        self.assertEqual(list(self.root.glob("feedback/*.json")), [])

    def test_feedback_directory_symlink_and_record_symlink_are_rejected(self) -> None:
        outside = self.root / "elsewhere"
        outside.mkdir()
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaises(workflow.WorkflowError):
            self.record(feedback_dir=self.root / "link")
        self.private.mkdir(mode=0o700)
        relative = self.root.name + "/run"
        filename = __import__("hashlib").sha256(relative.encode()).hexdigest() + ".json"
        (self.private / filename).symlink_to(outside / "missing")
        with self.assertRaises(workflow.WorkflowError):
            self.record()

    def test_tampered_feedback_and_non_private_directory_fail_closed(self) -> None:
        path, _ = self.record()
        original = json.loads(path.read_text())
        original["edit_minutes"] = True
        path.write_text(json.dumps(original))
        with self.assertRaises(workflow.WorkflowError):
            feedback.load_records(self.private)
        path.unlink()
        os.chmod(self.private, 0o755)
        with self.assertRaises(workflow.WorkflowError):
            self.record()

    def test_run_path_must_be_under_outputs(self) -> None:
        for path in (workflow.REPO_ROOT / "data", "outputs/../data", self.root / "../other"):
            with self.subTest(path=path), self.assertRaises(workflow.WorkflowError):
                feedback._relative_under_outputs(path, label="run")

    def test_run_fails_closed_for_fixture_and_changed_article(self) -> None:
        self.identity.stop()
        run = self.root / "run"
        run.mkdir()
        (run / "brief.json").write_text("{}")
        (run / "article.json").write_text("{}")
        manifest = {
            "contract_version": "sunday-article-v1", "status": "FIXTURE_ONLY",
            "human_approval_status": "NOT_APPROVED", "publishing_status": "DISABLED",
            "article_file": "article.json", "artifact_sha256": "a" * 64,
        }
        (run / "manifest.json").write_text(json.dumps(manifest))
        with self.assertRaisesRegex(workflow.WorkflowError, "Fixture-only"):
            self.record()
        manifest["status"] = "READY_FOR_HUMAN_REVIEW"
        (run / "manifest.json").write_text(json.dumps(manifest))
        with mock.patch.object(feedback.article_contract, "validate_brief", return_value={"topic_id": "topic"}), mock.patch.object(feedback.article_contract, "article_hash", return_value="c" * 64):
            with self.assertRaisesRegex(workflow.WorkflowError, "changed"):
                self.record()

    def test_real_contract_artifact_and_manifest_binding(self) -> None:
        self.identity.stop()
        run = self.root / "run"
        run.mkdir()
        brief = {
            "contract_version": "sunday-article-v1", "topic_id": "topic", "topic": "Example",
            "reader": {"audience": "Builders", "stake": "Reliability", "desired_outcome": "Understand retries"},
            "thesis": "Retries need boundaries", "technical_concept": "Idempotency",
            "worked_example": "An article update", "author": {
                "name": "Author", "byline": "By Author", "attestations": []},
            "sources": [{"id": "source", "url": "https://example.com/source", "title": "Source", "content": "An example source"}],
            "claims": [{"id": "claim", "text": "A sample finding", "kind": "finding", "source_ids": ["source"]}],
            "word_range": {"min": 3, "max": 25},
        }
        article = {"topic_id": "topic", "thesis": brief["thesis"], "title": "Bounded retries",
                   "sections": [{"id": "section", "heading": "Example", "text": "Retries need an explicit boundary.", "claim_ids": ["claim"]}]}
        manifest = {
            "contract_version": "sunday-article-v1", "topic_id": "topic",
            "status": "READY_FOR_HUMAN_REVIEW", "human_approval_status": "NOT_APPROVED",
            "publishing_status": "DISABLED", "article_file": "article.json",
            "artifact_sha256": article_contract.article_hash(article, brief),
        }
        for name, value in (("brief", brief), ("article", article), ("manifest", manifest)):
            (run / f"{name}.json").write_text(json.dumps(value))
        path, created = self.record()
        self.assertTrue(created)
        self.assertEqual(json.loads(path.read_text())["article_sha256"], manifest["artifact_sha256"])
        article["sections"][0]["text"] = "Retries need a strict boundary."
        (run / "article.json").write_text(json.dumps(article))
        with self.assertRaisesRegex(workflow.WorkflowError, "changed"):
            self.record()
        self.assertEqual(len(feedback.load_records(self.private)), 1)

    def test_artifact_symlinks_are_rejected(self) -> None:
        self.identity.stop()
        run = self.root / "run"
        run.mkdir()
        (run / "brief.json").symlink_to(self.root / "outside")
        with self.assertRaises(workflow.WorkflowError):
            feedback._run_identity(run)
        (run / "brief.json").unlink()
        run.rmdir()
        run.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(workflow.WorkflowError):
            feedback._run_identity(run)


if __name__ == "__main__":
    unittest.main()
