"""Companion exports must not copy private Scout prose into review artifacts."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from authority_os import eval_package, package, public_urls, workflow
from test_package import fixture_context, write_context
from test_thursday_writing import capability_facts


class CompanionExportPrivacyTests(unittest.TestCase):
    def context(self):
        context = fixture_context()
        context["brief"]["weekly_slot"] = 3
        for source in context["evidence"]:
            source["thursday_capability"] = capability_facts()
        return context

    def exports(self, context):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            root.mkdir(mode=0o700)
            result = write_context(context, root)
            return {
                path.name: path.read_text()
                for path in result["path"].iterdir()
            }

    def assert_private_content_withheld(self, exports):
        for name, text in exports.items():
            self.assertNotIn("private-prose-sentinel", text, name)
        evaluation = json.loads(exports["evaluation.json"])
        self.assertEqual(
            evaluation["citation_metadata_export"]["status"],
            "PRIVATE_CONTENT_WITHHELD_FOR_DISPLAY",
        )
        for reasons in evaluation["citation_metadata_export"]["privacy_reasons"].values():
            self.assertTrue(reasons)
        self.assertEqual(evaluation["thursday_package"]["video"], "NOT_RENDERED")
        self.assertTrue(any(
            str(reason).startswith("source_prose_review_required:")
            for reason in evaluation["thursday_package"]["missing_inputs"]
        ))
        self.assertEqual(evaluation["thursday_package"]["post_comment_promise_check"], "MISSING_INPUTS")
        self.assertIn("PLAN_ONLY", exports["final-package.md"])
        manifest = json.loads(exports["manifest.json"])
        self.assertEqual(manifest["human_approval_status"], "NOT_APPROVED")
        self.assertEqual(manifest["publishing_status"], "DISABLED")

    def test_private_paths_are_withheld_from_every_companion_prose_field(self):
        private_paths = (
            "/Users/example/private-prose-sentinel/demo.mp4",
            "/home/example/private-prose-sentinel/demo.mp4",
            "/tmp/private-prose-sentinel/demo.mp4",
            "/private/var/private-prose-sentinel.txt",
            r"C:\Users\Example\private-prose-sentinel\demo.mp4",
            "C:/Users/Example/private-prose-sentinel/demo.mp4",
            "C:outputs/private-prose-sentinel/demo.mp4",
            r"\\workstation\share\private-prose-sentinel.mp4",
            "outputs/private-prose-sentinel/demo.mp4",
            "./outputs/private-prose-sentinel/demo.mp4",
            "../private-prose-sentinel/demo.mp4",
            "data/private/private-prose-sentinel.json",
            ".agents/private-prose-sentinel.md",
            "private-run/private-prose-sentinel/trace.json",
            "reports/private-run/private-prose-sentinel/trace.json",
            "reports/private-run-sentinel/private-prose-sentinel/trace.json",
            "private_run_sentinel/private-prose-sentinel/output.mp4",
            "notes.reports/private-run-sentinel/private-prose-sentinel/trace.json",
            "private-run-First Last/private-prose-sentinel/demo.mp4",
            "reports/private_run_First Last/private-prose-sentinel/trace.json",
            "Path:/Users/example/private-prose-sentinel/demo.mp4",
            "campaigns/private-prose-sentinel/run/thursday/trace.json",
            r"campaigns\private-prose-sentinel\run\thursday\trace.json",
        )
        for field in (
            "creator", "reader_benefit", "mechanism", "conditions",
            "limitation", "demo_observation",
        ):
            with self.subTest(field=field):
                context = self.context()
                original = deepcopy(context["evidence"])
                for source in context["evidence"]:
                    source["thursday_capability"][field] = (
                        "Private footage locations: " + " and ".join(private_paths)
                    )
                supplied = deepcopy(context["evidence"])
                exports = self.exports(context)
                self.assert_private_content_withheld(exports)
                self.assertEqual(context["evidence"], supplied)
                self.assertNotEqual(original, supplied)

    def test_each_private_path_spelling_is_detected_independently(self):
        for path in (
            "/Users/example/private-prose-sentinel/demo.mp4",
            "/tmp/private-prose-sentinel.mp4",
            r"C:\Users\Example\private-prose-sentinel.mp4",
            "C:/Users/Example/private-prose-sentinel.mp4",
            "C:outputs/private-prose-sentinel.mp4",
            r"\\workstation\share\private-prose-sentinel.mp4",
            "outputs/private-prose-sentinel/demo.mp4",
            "./outputs/private-prose-sentinel/demo.mp4",
            "../private-prose-sentinel/demo.mp4",
            "data/private/private-prose-sentinel.json",
            ".agents/private-prose-sentinel.md",
            "private-run/private-prose-sentinel/trace.json",
            "reports/private-run/private-prose-sentinel/trace.json",
            "reports/private-run-sentinel/private-prose-sentinel/trace.json",
            "private_run_sentinel/private-prose-sentinel/output.mp4",
            "notes.reports/private-run-sentinel/private-prose-sentinel/trace.json",
            "private-run-First Last/private-prose-sentinel/demo.mp4",
            "reports/private_run_First Last/private-prose-sentinel/trace.json",
            "Path:/Users/example/private-prose-sentinel/demo.mp4",
            "campaigns/private-prose-sentinel/run/thursday/trace.json",
            r"campaigns\private-prose-sentinel\run\thursday\trace.json",
        ):
            with self.subTest(path=path):
                context = self.context()
                for source in context["evidence"]:
                    source["thursday_capability"]["mechanism"] = "Inspect " + path
                self.assert_private_content_withheld(self.exports(context))

    def test_projection_covers_every_untrusted_capability_prose_field(self):
        for field in (
            "creator", "capability", "reader_benefit", "mechanism", "change_evidence",
            "limitation", "conditions", "demo_observation", "attention_evidence",
        ):
            with self.subTest(field=field):
                context = self.context()
                context["evidence"][0]["thursday_capability"][field] = (
                    "Inspect outputs/private-prose-sentinel/trace.json"
                )
                sources, _ = package._public_sources(context["evidence"], None)
                original = deepcopy(sources)
                evaluation = {}
                _, _, safe_sources, _ = package._export_safe_views(
                    manifest={"mode": "fixture"}, brief=context["brief"],
                    candidates=[], evaluation=evaluation, sources=sources, public_proof=None,
                )
                self.assertNotIn("private-prose-sentinel", json.dumps(safe_sources))
                self.assertEqual(sources, original)
                self.assertIn("citation_metadata_export", evaluation)

    def test_file_and_private_urls_in_prose_are_withheld(self):
        for url in (
            "file:///tmp/private-prose-sentinel.mp4",
            "file://workstation/private-prose-sentinel.mp4",
            "file:/tmp/private-prose-sentinel.mp4",
            "file:C:/Users/example/private-prose-sentinel.mp4",
            "localhost:8000/private-prose-sentinel",
            "https://localhost/private-prose-sentinel",
            "http://127.0.0.1/private-prose-sentinel",
            "https://192.168.1.10/private-prose-sentinel",
            "https://[::1]/private-prose-sentinel",
            "https://builder.local/private-prose-sentinel",
            "file:///Users/First Last/private-prose-sentinel/demo.mp4",
            r"file:C:\Users\First Last\private-prose-sentinel\demo.mp4",
            "http://localhost/Users/First Last/private-prose-sentinel/demo.mp4",
            "https://192.168.1.10/First Last/private-prose-sentinel/demo.mp4",
            "https://example.com/demo?path=/Users/First Last/private-prose-sentinel/demo.mp4",
            "https://example.com/demo?token=First Last/private-prose-sentinel/demo.mp4",
            "example.com/demo?token=First Last/private-prose-sentinel/demo.mp4",
            "localhost/First Last/private-prose-sentinel/demo.mp4",
            "192.168.1.10/First Last/private-prose-sentinel/demo.mp4",
            "builder.local/First Last/private-prose-sentinel/demo.mp4",
        ):
            with self.subTest(url=url):
                context = self.context()
                for source in context["evidence"]:
                    source["thursday_capability"]["conditions"] = "Open " + url
                exports = self.exports(context)
                self.assert_private_content_withheld(exports)
                urls = json.loads(exports["evaluation.json"])["source_comment"]["selected_source_urls"]
                self.assertTrue(all("private-prose-sentinel" not in value for value in urls))

    def test_url_candidate_spans_do_not_assert_usable_links(self):
        text = "Read https://example.com/outputs/demo and https://localhost/private-prose-sentinel."
        candidates = [text[start:end] for start, end in public_urls.url_text_spans(text)]
        self.assertIn("https://localhost/private-prose-sentinel", candidates)
        validated = [url for _start, _end, url in public_urls.public_url_spans(text)]
        self.assertEqual(validated, ["https://example.com/outputs/demo"])

    def test_supporting_source_title_uses_same_privacy_projection(self):
        context = self.context()
        for source in context["evidence"]:
            source["title"] = "Scout notes in outputs/private-prose-sentinel/trace.json"
        self.assert_private_content_withheld(self.exports(context))

    def test_frozen_source_title_replays_projection_with_original_binding(self):
        context = fixture_context(mode="live")
        context["evidence"][0]["title"] = "Scout notes in outputs/private-prose-sentinel/trace.json"
        exports = self.exports(context)
        eval_package._verify_frozen_citations(exports, context["evidence"])
        changed = deepcopy(context["evidence"])
        changed[0]["title"] = "Scout notes in outputs/different-private-run/trace.json"
        with self.assertRaises(workflow.WorkflowError):
            eval_package._verify_frozen_citations(exports, changed)

    def test_frozen_title_refuses_missing_or_changed_projection_fingerprints(self):
        context = fixture_context(mode="live")
        context["evidence"][0]["title"] = "Scout notes in outputs/private-prose-sentinel/trace.json"
        exports = self.exports(context)
        for field in ("original_sha256", "exported_sha256", "redactions", "privacy_reasons"):
            with self.subTest(field=field):
                evaluation = json.loads(exports["evaluation.json"])
                metadata = evaluation["citation_metadata_export"]
                if field == "privacy_reasons":
                    del metadata["privacy_reasons"]["source.source-1.title"]
                else:
                    del metadata["fields"]["source.source-1.title"][field]
                tampered = dict(exports, **{"evaluation.json": json.dumps(evaluation)})
                with self.assertRaises(workflow.WorkflowError):
                    eval_package._verify_frozen_citations(tampered, context["evidence"])

    def test_brief_and_proof_preserve_their_existing_projection(self):
        context = self.context()
        context["brief"]["analysis"]["why_now"] += " Inspect outputs/private-prose-sentinel/trace.json"
        sources, _ = package._public_sources(context["evidence"], None)
        proof = {
            "public_claim": "Inspect /tmp/private-prose-sentinel.txt",
            "attested_personal_sentences": ["Inspect C:/Users/example/private-prose-sentinel.txt"],
        }
        evaluation = {}
        safe_brief, _, _, safe_proof = package._export_safe_views(
            manifest={"mode": "fixture"}, brief=context["brief"], candidates=[],
            evaluation=evaluation, sources=sources, public_proof=proof,
        )
        self.assertEqual(safe_brief["analysis"]["why_now"], context["brief"]["analysis"]["why_now"])
        self.assertEqual(safe_proof, proof)

    def test_path_copied_into_candidate_cannot_bypass_export_projection(self):
        context = self.context()
        context["mode"] = "live"
        context["brief"]["strategy_input_origin"] = "explicit-input"
        for candidate in context["review"]["candidates"]:
            candidate["angle"] += " Inspect outputs/private-prose-sentinel/trace.json"
            candidate["text"] += " Inspect outputs/private-prose-sentinel/trace.json"
        original = deepcopy(context["review"]["candidates"])
        exports = self.exports(context)
        for name, text in exports.items():
            self.assertNotIn("private-prose-sentinel", text, name)
        manifest = json.loads(exports["manifest.json"])
        evaluation = json.loads(exports["evaluation.json"])
        self.assertEqual(manifest["review_status"], "BLOCKED")
        self.assertIsNone(manifest["recommended_candidate_id"])
        self.assertIn("candidate_export", evaluation)
        self.assertEqual(context["review"]["candidates"], original)

    def test_denied_query_with_spaced_private_fragments_in_candidate_is_wholly_withheld(self):
        for url in (
            "https://example.com/demo?token=First Last/private-prose-sentinel/demo.mp4",
            "example.com/demo?token=First Last/private-prose-sentinel/demo.mp4",
            "localhost/First Last/private-prose-sentinel/demo.mp4",
            "192.168.1.10/First Last/private-prose-sentinel/demo.mp4",
            "builder.local/First Last/private-prose-sentinel/demo.mp4",
        ):
            with self.subTest(url=url):
                context = self.context()
                for candidate in context["review"]["candidates"]:
                    candidate["text"] += " Open " + url
                original = deepcopy(context["review"]["candidates"])
                exports = self.exports(context)
                for name, text in exports.items():
                    self.assertNotIn("private-prose-sentinel", text, name)
                self.assertIn("Source prose withheld: unsafe-url", exports["post.md"])
                evaluation = json.loads(exports["evaluation.json"])
                self.assertIn("candidate_export", evaluation)
                self.assertEqual(context["review"]["candidates"], original)
                with self.assertRaises(workflow.WorkflowError):
                    eval_package._require_unredacted_candidate_export(exports)

    def test_public_links_and_normal_narrative_are_preserved(self):
        context = self.context()
        for source in context["evidence"]:
            source["thursday_capability"]["mechanism"] = (
                "The router selects 4 workers. Read https://example.com/reference. "
                "Compare hardware/cost/version. Local hardware / 12 GB. "
                "Read https://example.com/docs/local-execution and https://example.com/outputs/demo."
            )
        exports = self.exports(context)
        self.assertIn("The router selects 4 workers.", exports["source-comment.md"])
        self.assertIn("https://example.com/reference", exports["source-comment.md"])
        self.assertIn("hardware/cost/version", exports["source-comment.md"])
        self.assertIn("Local hardware / 12 GB", exports["source-comment.md"])
        self.assertIn("https://example.com/docs/local-execution", exports["source-comment.md"])
        self.assertIn("https://example.com/outputs/demo", exports["source-comment.md"])
        self.assertIn("https://example.com/demo", exports["source-comment.md"])
        self.assertNotIn("citation_metadata_export", json.loads(exports["evaluation.json"]))
        ledger = json.loads(exports["evaluation.json"])["source_comment"]["selected_source_urls"]
        self.assertNotIn("https://example.com/reference", ledger)
        self.assertNotIn("https://example.com/outputs/demo", ledger)

    def test_filename_or_embedded_prose_url_cannot_become_a_promised_link(self):
        context = self.context()
        for source in context["evidence"]:
            source["thursday_capability"]["demo_url"] = None
            source["thursday_capability"]["conditions"] = (
                "Recorded output filename trace.json; see https://example.com/other-demo."
            )
        exports = self.exports(context)
        evaluation = json.loads(exports["evaluation.json"])
        ledger = evaluation["source_comment"]["selected_source_urls"]
        self.assertNotIn("https://trace.json/", ledger)
        self.assertNotIn("https://example.com/other-demo", ledger)
        self.assertIn("demo_url", evaluation["thursday_package"]["missing_inputs"])
        self.assertEqual(evaluation["thursday_package"]["post_comment_promise_check"], "MISSING_INPUTS")

    def test_withheld_url_marker_does_not_satisfy_a_demo_link(self):
        context = self.context()
        for source in context["evidence"]:
            source["thursday_capability"]["demo_url"] = "https://example.com/demo?token=private-prose-sentinel"
        exports = self.exports(context)
        for name, text in exports.items():
            self.assertNotIn("private-prose-sentinel", text, name)
        evaluation = json.loads(exports["evaluation.json"])
        self.assertIn("demo_url", evaluation["thursday_package"]["missing_inputs"])
        self.assertEqual(evaluation["thursday_package"]["post_comment_promise_check"], "MISSING_INPUTS")
        self.assertNotIn("https://example.com/demo", evaluation["source_comment"]["selected_source_urls"])


if __name__ == "__main__":
    unittest.main()
