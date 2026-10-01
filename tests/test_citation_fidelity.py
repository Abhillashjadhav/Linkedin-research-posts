"""Source links remain exact in private evidence and safe in review packages."""

from __future__ import annotations

import hashlib
import json
import stat
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from authority_os import eval_package, package as approval_package
from authority_os import performance, quality_optimizer, storage, workflow
from tests.test_package import fixture_context, write_context


class CitationFidelityTests(unittest.TestCase):
    @staticmethod
    def _output_root(temporary: str) -> Path:
        root = Path(temporary) / "outputs"
        root.mkdir(mode=0o700)
        return root

    def test_query_free_public_citations_remain_exact_and_copy_ready(self) -> None:
        context = fixture_context(mode="live")
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self._output_root(temporary))
            documents = {
                path.name: path.read_text()
                for path in result["path"].iterdir()
                if path.is_file()
            }
            comment = json.loads(documents["evaluation.json"])["source_comment"]
            expected = [str(item["source"]) for item in context["evidence"]]
            self.assertEqual(comment["status"], "SOURCE_URLS_PRESENT")
            self.assertEqual(comment["selected_source_urls"], expected)
            self.assertEqual(comment["citation_review_source_ids"], [])
            self.assertTrue(all(url in documents["source-comment.md"] for url in expected))
            eval_package._verify_frozen_citations(documents, context["evidence"])
            legacy = dict(documents)
            legacy_evaluation = json.loads(legacy["evaluation.json"])
            del legacy_evaluation["source_comment"]["private_source_url_sha256"]
            legacy["evaluation.json"] = json.dumps(legacy_evaluation)
            eval_package._verify_frozen_citations(legacy, context["evidence"])

    def test_query_addressed_identity_is_private_and_grounded_draft_is_delivered(self) -> None:
        context = fixture_context(mode="live")
        first = context["evidence"][0]
        exact = str(first["source"]) + "?id=article-42"
        first["source"] = exact
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self._output_root(temporary))
            path = result["path"]
            documents = {
                file.name: file.read_text() for file in path.iterdir() if file.is_file()
            }
            evaluation = json.loads(documents["evaluation.json"])
            comment = evaluation["source_comment"]
            self.assertEqual(comment["status"], "CITATION_REVIEW_REQUIRED")
            self.assertEqual(comment["citation_review_source_ids"], ["source-1"])
            self.assertEqual(
                comment["private_source_url_sha256"]["source-1"],
                hashlib.sha256(exact.encode()).hexdigest(),
            )
            self.assertEqual(
                comment["selected_source_urls"],
                [str(context["evidence"][1]["source"])],
            )
            for name in ("sources.md", "source-comment.md", "final-package.md"):
                self.assertNotIn(exact, documents[name])
                self.assertNotIn(exact.split("?", 1)[0], documents[name])
                self.assertIn("source-1", documents[name])
            self.assertIn("do not publish", documents["source-comment.md"])
            self.assertEqual(documents["post.md"], context["review"]["candidates"][0]["text"])
            self.assertEqual(result["manifest"]["publishing_status"], "DISABLED")
            eval_package._verify_frozen_citations(documents, context["evidence"])
            performance.load_package_context(
                result["manifest"]["package_id"],
                result["manifest"]["recommended_candidate_id"],
                output_root=path.parents[1],
                _allow_test_output_root=True,
            )
            swapped = deepcopy(context["evidence"])
            swapped[0]["source"] = exact.replace("article-42", "article-43")
            with self.assertRaisesRegex(workflow.WorkflowError, "private source identities"):
                eval_package._verify_frozen_citations(documents, swapped)
            unbound = dict(documents)
            unbound_evaluation = json.loads(unbound["evaluation.json"])
            del unbound_evaluation["source_comment"]["private_source_url_sha256"]
            unbound["evaluation.json"] = json.dumps(unbound_evaluation)
            with self.assertRaisesRegex(workflow.WorkflowError, "private source identities"):
                eval_package._verify_frozen_citations(unbound, context["evidence"])

    def test_unknown_and_credential_queries_are_not_public_citations(self) -> None:
        context = fixture_context(mode="live")
        for query in (
            "id=looks-public",
            "token=private-sentinel",
            "hash=untrusted-value",
            "uuid=untrusted-value",
            "x=unknown-value",
        ):
            with self.subTest(query=query):
                evidence = deepcopy(context["evidence"])
                evidence[0]["source"] = str(evidence[0]["source"]) + "?" + query
                sources, _proof = approval_package._public_sources(evidence, None)
                self.assertIsNone(sources[0]["source"])
                self.assertEqual(sources[0]["id"], "source-1")

    def test_private_ledger_retains_exact_query_identity_with_private_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "data" / "private"
            private.mkdir(parents=True, mode=0o700)
            db = private / "research.sqlite"
            storage.initialise(db)
            raw = workflow.load_fixture()["research_items"][0].copy()
            raw["url"] = str(raw["url"]) + "?id=public-looking"
            prepared = workflow.prepare_research_items([raw])
            storage.insert_research_items(db, prepared, evidence_origin="private-import")
            self.assertEqual(stat.S_IMODE(db.stat().st_mode), 0o600)
            stored = storage.list_research_items_by_urls(
                db, [prepared[0]["canonical_url"]], evidence_origin="private-import"
            )
            self.assertEqual(stored[0]["canonical_url"], prepared[0]["canonical_url"])

    def test_inline_query_link_is_withheld_without_erasing_scored_provenance(self) -> None:
        context = fixture_context(mode="live")
        exact = str(context["evidence"][0]["source"]) + "?id=good"
        context["evidence"][0]["source"] = exact
        for candidate in context["review"]["candidates"]:
            candidate["text"] = str(candidate["text"]) + f" The source is {exact}."
        original = str(context["review"]["candidates"][0]["text"])
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self._output_root(temporary))
            documents = {
                path.name: path.read_text()
                for path in result["path"].iterdir()
                if path.is_file()
            }
            self.assertEqual(result["manifest"]["review_status"], "BLOCKED")
            self.assertIsNone(result["manifest"]["recommended_candidate_id"])
            self.assertEqual(result["manifest"]["publishing_status"], "DISABLED")
            for name in ("candidates.md", "post.md", "final-package.md"):
                self.assertNotIn(exact, documents[name])
                self.assertIn("citation URL for source-1 requires review", documents[name])
            self.assertIn("Reliability compounds", documents["post.md"])
            evaluation = json.loads(documents["evaluation.json"])
            self.assertIn("authority-1", evaluation["eligible_candidate_ids"])
            self.assertEqual(
                evaluation["gate_results"][0]["gates"]["citation"]["status"],
                "PASS",
            )
            export = evaluation["candidate_export"]
            self.assertEqual(export["status"], "QUERY_URLS_REDACTED_FOR_CITATION_REVIEW")
            self.assertEqual(
                export["original_text_sha256"]["authority-1"],
                hashlib.sha256(original.encode()).hexdigest(),
            )
            self.assertEqual(
                export["exported_text_sha256"]["authority-1"],
                hashlib.sha256(documents["post.md"].encode()).hexdigest(),
            )
            with self.assertRaisesRegex(workflow.WorkflowError, "cannot be rescored"):
                eval_package._require_unredacted_candidate_export(documents)
            with self.assertRaises(workflow.WorkflowError):
                performance.load_package_context(
                    result["manifest"]["package_id"],
                    "authority-1",
                    output_root=result["path"].parents[1],
                    _allow_test_output_root=True,
                )

    def test_unknown_inline_query_and_markdown_link_are_withheld(self) -> None:
        for inline in (
            "https://other.example/article?token=private-sentinel",
            "[research](https://other.example/article?token=private-sentinel)",
            "other.example/article?token=private-sentinel",
        ):
            with self.subTest(inline=inline), tempfile.TemporaryDirectory() as temporary:
                context = fixture_context(mode="live")
                for candidate in context["review"]["candidates"]:
                    candidate["text"] = str(candidate["text"]) + " See " + inline
                    candidate["angle"] = str(candidate["angle"]) + " See " + inline
                result = write_context(context, self._output_root(temporary))
                self.assertEqual(result["manifest"]["review_status"], "BLOCKED")
                for path in result["path"].iterdir():
                    if path.is_file():
                        self.assertNotIn("private-sentinel", path.read_text())
                self.assertIn("query URL withheld", (result["path"] / "post.md").read_text())

    def test_query_url_in_source_title_is_warning_only_metadata_redaction(self) -> None:
        context = fixture_context(mode="live")
        exact = str(context["evidence"][0]["source"]) + "?id=good"
        context["evidence"][0]["source"] = exact
        context["evidence"][0]["title"] = "Research detail at " + exact
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self._output_root(temporary))
            documents = {
                path.name: path.read_text()
                for path in result["path"].iterdir()
                if path.is_file()
            }
            evaluation = json.loads(documents["evaluation.json"])
            self.assertEqual(result["manifest"]["review_status"], "READY_FOR_HUMAN_REVIEW")
            self.assertNotIn("candidate_export", evaluation)
            self.assertIn("citation_metadata_export", evaluation)
            self.assertIn(
                "source.source-1.title", evaluation["citation_metadata_export"]["fields"]
            )
            for name in ("sources.md", "source-comment.md", "final-package.md"):
                self.assertNotIn(exact, documents[name])
            self.assertIn("citation URL for source-1 requires review", documents["sources.md"])
            self.assertEqual(
                documents["post.md"], context["review"]["candidates"][0]["text"]
            )
            performance.load_package_context(
                result["manifest"]["package_id"],
                result["manifest"]["recommended_candidate_id"],
                output_root=result["path"].parents[1],
                _allow_test_output_root=True,
            )

    def test_query_url_after_parenthesized_path_is_withheld_everywhere(self) -> None:
        context = fixture_context(mode="live")
        exact = "https://example.com/a(b)?token=private-sentinel"
        context["evidence"][0]["source"] = exact
        for candidate in context["review"]["candidates"]:
            candidate["text"] = str(candidate["text"]) + " The source is " + exact + "."
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self._output_root(temporary))
            self.assertEqual(result["manifest"]["review_status"], "BLOCKED")
            for path in result["path"].iterdir():
                if path.is_file():
                    self.assertNotIn("private-sentinel", path.read_text())
            self.assertIn(
                "citation URL for source-1 requires review",
                (result["path"] / "post.md").read_text(),
            )

    def test_query_url_in_brief_analysis_is_warning_only(self) -> None:
        context = fixture_context(mode="live")
        query_url = "https://example.com/analysis?token=private-sentinel"
        context["brief"]["analysis"]["dominant_take"] += " Read " + query_url
        with tempfile.TemporaryDirectory() as temporary:
            result = write_context(context, self._output_root(temporary))
            evaluation = json.loads((result["path"] / "evaluation.json").read_text())
            self.assertEqual(result["manifest"]["review_status"], "READY_FOR_HUMAN_REVIEW")
            self.assertNotIn("candidate_export", evaluation)
            self.assertIn(
                "brief.analysis.dominant_take",
                evaluation["citation_metadata_export"]["fields"],
            )
            for path in result["path"].iterdir():
                if path.is_file():
                    self.assertNotIn("private-sentinel", path.read_text())
            performance.load_package_context(
                result["manifest"]["package_id"],
                result["manifest"]["recommended_candidate_id"],
                output_root=result["path"].parents[1],
                _allow_test_output_root=True,
            )

    def test_quality_overlay_cannot_restore_unsafe_copy_ready_links(self) -> None:
        for placement in ("candidate", "title"):
            with self.subTest(placement=placement):
                context = fixture_context(mode="live")
                exact = str(context["evidence"][0]["source"]) + "?id=good"
                context["evidence"][0]["source"] = exact
                if placement == "candidate":
                    for candidate in context["review"]["candidates"]:
                        candidate["text"] = str(candidate["text"]) + " See " + exact
                else:
                    context["evidence"][0]["title"] = "Research at " + exact
                manifest, evaluation, rendered = quality_optimizer._package_data(
                    package_id="2026-07-16-agent-reliability",
                    created_at="2026-07-16T12:00:00Z",
                    mode="live",
                    brief=context["brief"],
                    evidence=context["evidence"],
                    review=context["review"],
                    proof=None,
                )
                self.assertTrue(all(exact not in value for value in rendered.values()))
                if placement == "candidate":
                    self.assertEqual(manifest["review_status"], "BLOCKED")
                    self.assertIn("candidate_export", evaluation)
                else:
                    self.assertEqual(manifest["review_status"], "READY_FOR_HUMAN_REVIEW")
                    self.assertIn("citation_metadata_export", evaluation)

    def test_public_proof_display_urls_are_sanitized_without_candidate_veto(self) -> None:
        context = fixture_context(mode="live")
        brief = approval_package._project_brief(context["brief"], mode="live")
        sources, _proof = approval_package._public_sources(context["evidence"], None)
        manifest: dict[str, object] = {
            "mode": "live",
            "review_status": "READY_FOR_HUMAN_REVIEW",
            "recommended_candidate_id": "authority-1",
        }
        evaluation: dict[str, object] = {
            "review_status": "READY_FOR_HUMAN_REVIEW",
            "recommended_candidate_id": "authority-1",
        }
        proof = {
            "proof_id": "proof-1",
            "proof_type": "work-sample",
            "public_claim": "Read https://example.com/proof?token=private-sentinel",
            "attested_personal_sentences": [
                "I wrote https://example.com/attestation?token=private-sentinel"
            ],
        }
        _brief, _candidates, _sources, safe_proof = approval_package._export_safe_views(
            manifest=manifest,
            brief=brief,
            candidates=context["review"]["candidates"],
            evaluation=evaluation,
            sources=sources,
            public_proof=proof,
        )
        self.assertIsNotNone(safe_proof)
        self.assertNotIn("private-sentinel", str(safe_proof))
        self.assertEqual(manifest["review_status"], "READY_FOR_HUMAN_REVIEW")
        self.assertNotIn("candidate_export", evaluation)
        self.assertIn("proof.public_claim", evaluation["citation_metadata_export"]["fields"])
        self.assertIn("proof.attestation.0", evaluation["citation_metadata_export"]["fields"])


if __name__ == "__main__":
    unittest.main()
