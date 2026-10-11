"""Contract tests use synthetic passages; they do not establish factual truth."""

import copy
import unittest

from authority_os.article_contract import (
    article_hash,
    article_text,
    validate_article,
    validate_brief,
)
from authority_os.workflow import WorkflowError


def brief():
    return {
        "contract_version": "sunday-article-v1",
        "topic_id": "topic-one",
        "topic": "A synthetic decision review",
        "reader": {"audience": "Reviewers", "stake": "A decision must be explained", "desired_outcome": "Explain a choice"},
        "thesis": "Write down the decision boundary.",
        "technical_concept": "Decision boundary",
        "worked_example": "Classify a fictional support ticket.",
        "author": {"name": "Example", "byline": "By Example", "attestations": [{"id": "author-1", "text": "I review the fictional tickets."}]},
        "sources": [{"id": "source-1", "url": "https://example.org/method", "title": "Synthetic passage", "content": "In this synthetic example, reviewers record their decision before seeing a suggestion."}],
        "claims": [
            {"id": "finding-1", "text": "The synthetic passage describes recording a decision.", "kind": "finding", "source_ids": ["source-1"]},
            {"id": "attestation-1", "text": "The author reviews fictional tickets.", "kind": "author_attestation", "source_ids": [], "attestation_id": "author-1"},
            {"id": "proposal-1", "text": "Record a decision boundary.", "kind": "proposal", "source_ids": []},
        ],
        "locked_title": "A locked title",
        "word_range": {"min": 6, "max": 8},
    }


def article():
    return {
        "topic_id": "topic-one", "thesis": "Write down the decision boundary.", "title": "A locked title",
        "sections": [
            {"id": "opening", "heading": "Why it matters", "text": "A reviewer must explain this synthetic decision.", "claim_ids": ["finding-1"]},
        ],
    }


class ArticleContractTests(unittest.TestCase):
    def test_normalizes_defaults_without_mutating_input(self):
        raw = brief()
        del raw["word_range"]
        del raw["locked_title"]
        safe = validate_brief(raw)
        self.assertEqual(safe["word_range"], {"min": 1000, "max": 1150})
        self.assertEqual(safe["voice_examples"], [])
        safe["sources"][0]["content"] = "changed"
        self.assertNotEqual(raw["sources"][0]["content"], "changed")

    def test_sources_need_content_and_findings_need_known_source(self):
        for change in ("missing_content", "blank_content", "no_finding_ref", "unknown_ref"):
            with self.subTest(change=change):
                value = brief()
                if change == "missing_content":
                    del value["sources"][0]["content"]
                elif change == "blank_content":
                    value["sources"][0]["content"] = "  "
                elif change == "no_finding_ref":
                    value["claims"][0]["source_ids"] = []
                else:
                    value["claims"][0]["source_ids"] = ["unknown"]
                with self.assertRaises(WorkflowError):
                    validate_brief(value)

    def test_author_attestation_reference_and_duplicate_ids(self):
        value = brief()
        value["claims"][1]["attestation_id"] = "unknown"
        with self.assertRaises(WorkflowError):
            validate_brief(value)
        value = brief()
        value["claims"][1]["id"] = "finding-1"
        with self.assertRaises(WorkflowError):
            validate_brief(value)
        value = brief()
        value["author"]["attestations"].append(copy.deepcopy(value["author"]["attestations"][0]))
        with self.assertRaises(WorkflowError):
            validate_brief(value)

    def test_resource_refs_and_license_need_linked_finding(self):
        value = brief()
        value["resource"] = {"name": "Method", "url": "https://example.org/method", "source_ids": ["missing"]}
        with self.assertRaises(WorkflowError):
            validate_brief(value)
        value["resource"]["source_ids"] = ["source-1"]
        value["resource"]["license"] = "Example license"
        value["resource"]["claim_ids"] = ["proposal-1"]
        with self.assertRaises(WorkflowError):
            validate_brief(value)
        value["resource"]["claim_ids"] = ["finding-1"]
        self.assertEqual(validate_brief(value)["resource"]["license"], "Example license")

    def test_locks_and_article_claim_references(self):
        for field, replacement in (("topic_id", "another"), ("thesis", "another"), ("title", "another")):
            with self.subTest(field=field):
                draft = article()
                draft[field] = replacement
                with self.assertRaises(WorkflowError):
                    validate_article(draft, brief())
        draft = article()
        draft["sections"][0]["claim_ids"] = ["unknown"]
        with self.assertRaises(WorkflowError):
            validate_article(draft, brief())
        draft = article()
        draft["sections"].append(copy.deepcopy(draft["sections"][0]))
        with self.assertRaises(WorkflowError):
            validate_article(draft, brief())

    def test_word_range_placeholders_and_hash(self):
        value = brief()
        draft = article()
        safe = validate_article(draft, value)
        self.assertIn("By Example", article_text(safe, value))
        self.assertEqual(article_hash(draft, value), article_hash(safe, validate_brief(value)))
        changed = copy.deepcopy(draft)
        changed["sections"][0]["text"] = "A reviewer must explain a different decision."
        self.assertNotEqual(article_hash(changed, value), article_hash(draft, value))
        changed["sections"][0]["text"] = "Too short."
        with self.assertRaises(WorkflowError):
            validate_article(changed, value)
        changed["sections"][0]["text"] = "A reviewer must explain this synthetic decision TODO."
        with self.assertRaises(WorkflowError):
            validate_article(changed, value)

    def test_rejects_malformed_types_as_workflow_errors(self):
        value = brief()
        value["claims"][0]["kind"] = []
        with self.assertRaises(WorkflowError):
            validate_brief(value)
        value = brief()
        value["word_range"]["min"] = True
        with self.assertRaises(WorkflowError):
            validate_brief(value)


if __name__ == "__main__":
    unittest.main()
