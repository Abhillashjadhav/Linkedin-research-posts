"""Sunday route: independent exact-hash reviews and bounded section edits."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from authority_os import article_workflow as aw
from authority_os.article_contract import article_hash
from authority_os.workflow import WorkflowError

ROOT = Path(__file__).resolve().parents[1]


def brief() -> dict:
    return {"contract_version": "sunday-article-v1", "topic_id": "test-topic", "topic": "Reliable systems",
            "reader": {"audience": "Product leaders", "stake": "Expensive failures",
                       "desired_outcome": "Make a measured decision"},
            "thesis": "A measured rollout needs traceable evidence.", "technical_concept": "Evidence gates",
            "worked_example": "A staged rollout", "author": {"name": "Test Author", "byline": "Test author",
            "attestations": []}, "sources": [{"id": "s1", "url": "https://example.com/a",
            "title": "Test source", "content": "Synthetic test evidence about staged rollouts."}],
            "claims": [{"id": "c1", "text": "A staged rollout can limit exposure.", "kind": "finding",
                        "source_ids": ["s1"]}], "word_range": {"min": 10, "max": 100}}


def article() -> dict:
    return {"topic_id": "test-topic", "thesis": "A measured rollout needs traceable evidence.",
            "title": "Evidence before rollout", "sections": [
                {"id": "a", "heading": "The decision", "text": "Teams need specific evidence before a launch grows beyond a narrow cohort.",
                 "claim_ids": ["c1"]},
                {"id": "b", "heading": "The example", "text": "This staged example gives leaders a concrete decision to examine together.",
                 "claim_ids": ["c1"]}]}


def models() -> dict:
    return aw.load_models({role: {"runtime": "codex", "model": "configured-test-model", "reasoning": "high"}
                           for role in aw.ROLES})


def review(role: str, article_value: dict, brief_value: dict, *, blocked: bool = False) -> dict:
    value = {"artifact_sha256": article_hash(article_value, brief_value), "verdict": "BLOCKED" if blocked else "PASS",
             "findings": [{"section_id": "a", "code": "REVISE", "message": "Make this clearer.",
                           "severity": "blocking"}] if blocked else []}
    if role == "factual_reviewer":
        value["claim_checks"] = [{"claim_id": "c1", "status": "SUPPORTED", "source_ids": ["s1"],
                                  "message": "Supported by the supplied source body, subject to human verification."}]
    return value


class ReviewValidationTests(unittest.TestCase):
    def test_stale_hash_unknown_section_and_missing_claim_coverage_fail_closed(self):
        for mutation in (lambda r: r.update(artifact_sha256="0" * 64),
                         lambda r: r["findings"].append({"section_id": "missing", "code": "X",
                           "message": "Unknown section", "severity": "blocking"}),
                         lambda r: r["claim_checks"].clear(),
                         lambda r: r["claim_checks"][0].update(source_ids=[]),
                         lambda r: r["claim_checks"][0].update(source_ids=["foreign"])):
            with self.subTest(mutation=mutation):
                result = review("factual_reviewer", article(), brief())
                mutation(result)
                with self.assertRaises(WorkflowError):
                    aw.validate_review(result, "factual_reviewer", article(), brief())

    def test_contradictory_pass_and_malformed_field_fail_closed(self):
        value = review("narrative_reviewer", article(), brief())
        value["findings"].append({"section_id": "a", "code": "X", "message": "Problem", "severity": "blocking"})
        with self.assertRaises(WorkflowError):
            aw.validate_review(value, "narrative_reviewer", article(), brief())
        value["verdict"] = []
        with self.assertRaises(WorkflowError):
            aw.validate_review(value, "narrative_reviewer", article(), brief())

    def test_editor_may_only_change_blocked_section(self):
        original = article()
        edit = deepcopy(original["sections"][1])
        edit["text"] += " Another thought."
        with self.assertRaises(WorkflowError):
            aw.apply_edits({"artifact_sha256": article_hash(original, brief()), "edits": [edit]},
                           original, brief(), {"a"})
        edit = deepcopy(original["sections"][0])
        edit["heading"] = "Changed heading"
        with self.assertRaises(WorkflowError):
            aw.apply_edits({"artifact_sha256": article_hash(original, brief()), "edits": [edit]},
                           original, brief(), {"a"})

    def test_writer_topic_thesis_and_locked_title_are_immutable(self):
        from authority_os.article_contract import validate_article
        for field, changed in (("topic_id", "foreign"), ("thesis", "A different thesis.")):
            with self.subTest(field=field):
                altered = article()
                altered[field] = changed
                with self.assertRaises(WorkflowError):
                    validate_article(altered, brief())
        locked = {**brief(), "locked_title": "Fixed title"}
        with self.assertRaises(WorkflowError):
            validate_article(article(), locked)

    def test_explicit_model_assignments_required(self):
        raw = {r: {"runtime": "codex", "model": "selected-model", "reasoning": "high"} for r in aw.ROLES}
        del raw["factual_reviewer"]
        with self.assertRaises(WorkflowError):
            aw.load_models(raw)
        raw["factual_reviewer"] = {"runtime": "other", "model": "selected-model", "reasoning": "high"}
        with self.assertRaises(WorkflowError):
            aw.load_models(raw)


class WorkflowTests(unittest.TestCase):
    def test_changed_article_gets_two_new_hash_bound_reviews(self):
        calls = []
        def fake(**kw):
            role = kw["stage_label"].split()[-1]
            payload = json.loads(kw["task_prompt"])
            calls.append((role, payload, kw["role_prompt"]))
            if role == "writer":
                return article()
            if role == "section_editor":
                replacement = deepcopy(payload["article"]["sections"][0])
                replacement["text"] += " A revised sentence clarifies how to inspect the evidence."
                return {"artifact_sha256": payload["artifact_sha256"], "edits": [replacement]}
            return review(role, payload["article"], payload["brief"], blocked=(role == "narrative_reviewer" and
                          not any("revised sentence" in s["text"] for s in payload["article"]["sections"])))
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as parent, patch.object(aw, "invoke_structured", side_effect=fake):
            run = Path(parent) / "fresh"
            result = aw.run(brief(), models(), run)
            self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
            self.assertEqual(result["review_rounds"], 2)
            self.assertEqual([r for r, _, _ in calls], ["writer", "narrative_reviewer", "factual_reviewer",
                                                       "section_editor", "narrative_reviewer", "factual_reviewer"])
            prompts = {role: prompt for role, _, prompt in calls}
            self.assertIn("reader's professional stake", prompts["writer"])
            self.assertIn("supplied worked example", prompts["writer"])
            self.assertIn("author's supplied voice examples", prompts["writer"])
            self.assertIn("first paragraph should give this reader", prompts["narrative_reviewer"])
            self.assertIn("subgroup/denominator swaps", prompts["factual_reviewer"])
            self.assertIn("reader's professional stake", prompts["section_editor"])
            self.assertIn("first paragraph should give this reader", prompts["section_editor"])
            self.assertIn("ONLY for blocked section IDs", prompts["section_editor"])
            self.assertEqual(calls[3][1]["blocked_section_ids"], ["a"])
            self.assertEqual(json.loads((run / "review.json").read_text())["artifact_sha256"], result["artifact_sha256"])
            self.assertEqual(json.loads((run / "manifest.json").read_text())["publishing_status"], "DISABLED")
            self.assertEqual((run / "article.json").stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads((run / "article.json").read_text())["sections"][1], article()["sections"][1])
            with self.assertRaises(WorkflowError):
                aw.run(brief(), models(), run)

    def test_missing_factual_coverage_blocks_without_editor_call(self):
        calls = []
        def fake(**kw):
            role = kw["stage_label"].split()[-1]
            calls.append(role)
            if role == "writer":
                return article()
            payload = json.loads(kw["task_prompt"])
            result = review(role, payload["article"], payload["brief"])
            if role == "factual_reviewer":
                result["claim_checks"] = []
            return result
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as parent, patch.object(aw, "invoke_structured", side_effect=fake):
            run = Path(parent) / "failed"
            with self.assertRaises(WorkflowError):
                aw.run(brief(), models(), run)
            self.assertEqual(calls, ["writer", "narrative_reviewer", "factual_reviewer"])
            self.assertEqual(json.loads((run / "manifest.json").read_text())["status"], "BLOCKED")
            self.assertEqual(json.loads((run / "trace.json").read_text())["status"], "BLOCKED")

    def test_bounded_editor_stops_after_two_edits_and_rechecks_both_each_time(self):
        calls = []
        def fake(**kw):
            role = kw["stage_label"].split()[-1]
            calls.append(role)
            if role == "writer":
                return article()
            payload = json.loads(kw["task_prompt"])
            if role == "section_editor":
                replacement = deepcopy(payload["article"]["sections"][0])
                replacement["text"] += " More specific evidence is needed before the rollout can proceed."
                return {"artifact_sha256": payload["artifact_sha256"], "edits": [replacement]}
            return review(role, payload["article"], payload["brief"], blocked=(role == "narrative_reviewer"))
        with tempfile.TemporaryDirectory(dir=ROOT / "outputs") as parent, patch.object(aw, "invoke_structured", side_effect=fake):
            run = Path(parent) / "bounded"
            result = aw.run(brief(), models(), run)
            self.assertEqual(result["status"], "BLOCKED")
            self.assertEqual(result["review_rounds"], 3)
            self.assertEqual(calls.count("section_editor"), 2)
            self.assertEqual(calls.count("narrative_reviewer"), 3)
            self.assertEqual(calls.count("factual_reviewer"), 3)


if __name__ == "__main__":
    unittest.main()
