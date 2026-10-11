"""A promised original demo keeps its safe semantic URL across the handoff."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from authority_os import campaign, daily_spine_cli, eval_package, performance, public_urls, workflow
from test_package import fixture_context, write_context
from test_thursday_discovery import AS_OF, evidence as capability_facts, item


DEMO_URL = "https://www.youtube.com/watch?v=AbCdEfG_h12"


class PublicSemanticURLTests(unittest.TestCase):
    def test_semantic_allowlist_and_tracking_normalization(self):
        for raw, expected in (
            (DEMO_URL, DEMO_URL),
            (DEMO_URL + "&utm_source=private-tracker&fbclid=ignored", DEMO_URL),
            ("https://example.com/article?", "https://example.com/article"),
            ("https://example.com/article?utm_source=launch", "https://example.com/article"),
        ):
            with self.subTest(raw=raw):
                result = public_urls.project_public_url(raw)
                self.assertEqual(result.url, expected)
                self.assertIsNone(result.reason)

    def test_unsupported_and_sensitive_queries_have_safe_reasons(self):
        for raw in (
            DEMO_URL + "&v=AbCdEfG_h13", DEMO_URL + "&token=private-sentinel",
            DEMO_URL + "&redirect=https://localhost/private-sentinel",
            "https://www.youtube.com/watch?v=VIDEO_ID",
            "https://youtube.com.evil.org/watch?v=AbCdEfG_h12",
            "https://example.com/watch?v=AbCdEfG_h12",
            "https://www.youtube.com/other?v=AbCdEfG_h12",
            "https://www.youtube.com:8443/watch?v=AbCdEfG_h12",
            "https://www.youtube.com/watch?v=", "https://www.youtube.com/watch?",
            "https://example.com/article?unknown=private-sentinel",
            "https://example.com/article?token=private-sentinel",
            "https://example.com/article?x-amz-signature=private-sentinel",
            "https://example.com/article?%GG=private-sentinel",
        ):
            with self.subTest(raw=raw):
                result = public_urls.project_public_url(raw)
                self.assertIsNone(result.url)
                self.assertTrue(result.reason)
                self.assertNotIn("private-sentinel", result.reason)
                with self.assertRaises(ValueError) as raised:
                    public_urls.require_public_url(raw)
                self.assertNotIn("private-sentinel", str(raised.exception))

    def test_non_public_destinations_controls_and_placeholders_are_unusable(self):
        for raw in (
            "https://user:private-sentinel@example.com/demo",
            "http://localhost./demo", "http://sub.localhost/demo",
            "https://intranet/demo", "https://build.internal/demo",
            "https://build.local/demo", "https://build.test/demo", "https://router.home.arpa/demo",
            "https://home.arpa/private-sentinel",
            "https://printer.localdomain/demo",
            "https://127.0.0.1/demo", "http://127.1/demo", "http://2130706433/demo",
            "http://0x7f000001/demo", "http://0177.0.0.1/demo", "https://[::1]/demo",
            "http://10.0.0.1/demo", "http://169.254.169.254/demo",
            "file:///tmp/private-sentinel", "file:/tmp/private-sentinel",
            "file:C:/Users/private-sentinel", "https://public.example\\@localhost/demo",
            "https://exa\nmple.com/demo", "\ahttps://example.com/demo",
            "https://example.com/de\tmo", "[citation URL for source-1 requires review]",
        ):
            with self.subTest(raw=raw):
                result = public_urls.project_public_url(raw)
                self.assertIsNone(result.url)
                self.assertNotIn("private-sentinel", result.reason)
                if raw.startswith("https://home.arpa/"):
                    self.assertEqual(public_urls.extract_public_urls(raw), [])
                    exported, count = public_urls.redact_public_urls(raw)
                    self.assertEqual(count, 1)
                    self.assertNotIn("private-sentinel", exported)

    def test_prose_uses_same_policy_and_balanced_url_delimiters(self):
        text = (f"Demo: {DEMO_URL}&utm_source=launch. "
                "Private: https://example.com/link?token=private-sentinel. "
                "File: file:/tmp/private-sentinel; Local: localhost:3000/private-sentinel")
        exported, count = public_urls.redact_public_urls(text)
        self.assertEqual(count, 3)
        self.assertIn(DEMO_URL, exported)
        self.assertNotIn("private-sentinel", exported)
        self.assertNotIn("utm_source", exported)
        self.assertEqual(public_urls.extract_public_urls(exported), [DEMO_URL])
        for raw, expected in (
            ("https://[2606:4700:4700::1111]", "https://[2606:4700:4700::1111]/"),
            ("https://example.com/wiki/Some_(topic)", "https://example.com/wiki/Some_(topic)"),
        ):
            with self.subTest(raw=raw):
                prose = f"Read [{raw}]({raw})."
                self.assertEqual(public_urls.redact_public_urls(prose)[1], 0)
                self.assertEqual(public_urls.extract_public_urls(prose), [expected])

    def test_unsafe_demo_cannot_satisfy_discovery_or_comment_promise(self):
        for raw in (DEMO_URL + "&token=private-sentinel",
                    "https://www.youtube.com/watch?v=VIDEO_ID",
                    "[URL withheld: missing-url]"):
            with self.subTest(raw=raw):
                facts = capability_facts(demo_url=raw)
                selected, rejected = daily_spine_cli.select_thursday_evidence(
                    [item(thursday_capability=facts)], as_of=AS_OF, days=7)
                self.assertFalse(selected)
                self.assertEqual(len(rejected), 1)
                self.assertNotIn("private-sentinel", rejected[0]["reason"])
                context = fixture_context()
                context["evidence"][0]["thursday_capability"] = facts
                result = campaign._comment_evidence_gates(
                    {"text": "Original demo: " + raw},
                    post_text="Original demo in the first comment.",
                    evidence=context["evidence"], day={"day": "Thursday"})
                self.assertFalse(result["passes"])
                self.assertEqual(result["promised_demo_link"], "FAIL")

    def test_malformed_private_reference_cannot_hide_behind_valid_comment_link(self):
        context = fixture_context()
        for unsafe in (r"http:\\localhost\private-sentinel", "http:/localhost/private-sentinel",
                       "http://127.0.0.1/private-sentinel", "file:C:/Users/private-sentinel"):
            with self.subTest(unsafe=unsafe):
                text = "Public: " + context["evidence"][0]["source"] + ". Hidden: " + unsafe
                result = campaign._comment_evidence_gates(
                    {"text": text}, post_text="Sources in the first comment.", evidence=context["evidence"])
                self.assertFalse(result["passes"])
                exported, count = public_urls.redact_public_urls(text)
                self.assertGreater(count, 0)
                self.assertNotIn("private-sentinel", exported)

    def test_ordinary_filenames_and_bare_link_spelling_are_preserved(self):
        text = "Open README.md and docs/trace.json; inspect source.py and preview.mp4."
        self.assertEqual(public_urls.redact_public_urls(text), (text, 0))
        self.assertEqual(public_urls.extract_public_urls(text), [])
        self.assertEqual(public_urls.public_url_spans(text), [])
        bare = "Read example.com/project before trying it."
        self.assertEqual(public_urls.redact_public_urls(bare), (bare, 0))
        explicit = "Read https://readme.md/project."
        self.assertEqual(public_urls.extract_public_urls(explicit), ["https://readme.md/project"])
        start, end, url = public_urls.public_url_spans(explicit)[0]
        self.assertEqual(explicit[start:end], url)
        context = fixture_context()
        context["evidence"][0]["claim"] = text
        self.assertEqual(workflow._writer_evidence_projection(context["evidence"])[0]["claim"], text)
        self.assertTrue(campaign._comment_evidence_gates(
            {"text": text + " Source: " + context["evidence"][0]["source"]},
            post_text="Sources in the first comment.", evidence=context["evidence"])["passes"])

    def test_unsafe_prose_urls_fail_candidate_citation_policy(self):
        context = fixture_context()
        for raw in ("file:/tmp/private-sentinel", r"http:\\localhost\private-sentinel",
                    "https://example.com/demo?token=private-sentinel"):
            with self.subTest(raw=raw):
                self.assertFalse(workflow._candidate_urls_supported(
                    "Source: " + context["evidence"][0]["source"] + " Hidden: " + raw,
                    context["evidence"]))

    def test_semantic_link_identifiers_are_not_factual_measurements(self):
        context = fixture_context()
        context["evidence"][0]["source"] = DEMO_URL
        for citation in (DEMO_URL, f"[demo]({DEMO_URL})", f"[{DEMO_URL}]({DEMO_URL})"):
            with self.subTest(citation=citation):
                candidate = copy.deepcopy(context["review"]["candidates"][0])
                candidate["text"] += " Source: " + citation
                result = workflow.evaluate_candidate_gates(
                    candidate, brief=context["brief"], evidence=context["evidence"])
                self.assertEqual(result["gates"]["citation"]["status"], "PASS")

    def test_source_controls_are_rejected_before_parser_normalization(self):
        for raw in ("\nhttps://example.com/demo", "https://exa\nmple.com/demo",
                    "https://example.com/de\tmo"):
            with self.subTest(raw=raw):
                context = fixture_context()
                context["evidence"][0]["source"] = raw
                with self.assertRaisesRegex(workflow.WorkflowError, "invalid public source URL"):
                    workflow._writer_evidence_projection(context["evidence"])

    def test_safe_title_normalization_remains_bound_to_frozen_evidence(self):
        context = fixture_context(mode="live")
        context["evidence"][0]["title"] = "Evidence https://example.com/demo?utm_source=private-origin"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            root.mkdir(mode=0o700)
            result = write_context(context, root)
            documents = {path.name: path.read_text() for path in result["path"].iterdir()}
            eval_package._verify_frozen_citations(documents, context["evidence"])
            evaluation = json.loads(documents["evaluation.json"])
            self.assertEqual(evaluation["citation_metadata_export"]["fields"]["source.source-1.title"]["redactions"], 0)
            del evaluation["citation_metadata_export"]
            documents["evaluation.json"] = json.dumps(evaluation)
            with self.assertRaisesRegex(workflow.WorkflowError, "source title export is unbound"):
                eval_package._verify_frozen_citations(documents, context["evidence"])

    def test_ordinary_semantic_source_package_round_trips_and_refuses_tampering(self):
        context = fixture_context(mode="live")
        context["evidence"][0]["source"] = DEMO_URL
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            root.mkdir(mode=0o700)
            result = write_context(context, root)
            documents = {path.name: path.read_text() for path in result["path"].iterdir()}
            eval_package._verify_frozen_citations(documents, context["evidence"])
            performance.load_package_context(
                result["manifest"]["package_id"], result["manifest"]["recommended_candidate_id"],
                output_root=result["path"].parents[1], _allow_test_output_root=True)
            changed = copy.deepcopy(context["evidence"])
            changed[0]["source"] = DEMO_URL.replace("h12", "h13")
            with self.assertRaisesRegex(workflow.WorkflowError, "source index|private source identities"):
                eval_package._verify_frozen_citations(documents, changed)

    def test_normalized_candidate_keeps_original_and_exported_fingerprints(self):
        context = fixture_context(mode="live")
        context["evidence"][0]["source"] = DEMO_URL
        original = context["review"]["candidates"][0]["text"] + " Source: " + DEMO_URL + "&utm_source=launch"
        context["review"]["candidates"][0]["text"] = original
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            root.mkdir(mode=0o700)
            target = write_context(context, root)["path"]
            evaluation = json.loads((target / "evaluation.json").read_text())
            export = evaluation["candidate_export"]
            self.assertEqual(export["status"], "PUBLIC_URLS_NORMALIZED_FOR_DISPLAY")
            self.assertNotEqual(export["original_text_sha256"]["authority-1"],
                                export["exported_text_sha256"]["authority-1"])
            self.assertEqual(export["redaction_counts"]["authority-1"], 0)
            self.assertNotIn("utm_source", (target / "post.md").read_text())
            documents = {path.name: path.read_text() for path in target.iterdir()}
            with self.assertRaisesRegex(workflow.WorkflowError, "cannot be rescored"):
                eval_package._require_unredacted_candidate_export(documents)
            with self.assertRaisesRegex(workflow.WorkflowError, "scored publication"):
                performance.load_package_context(
                    json.loads(documents["manifest.json"])["package_id"], "authority-1",
                    output_root=target.parents[1], _allow_test_output_root=True)

    def test_youtube_demo_survives_discovery_writer_comment_and_exports(self):
        raw_demo = DEMO_URL + "&utm_source=launch"
        facts = capability_facts(demo_url=raw_demo)
        raw = item(thursday_capability=facts)
        original = copy.deepcopy(raw)
        selected, rejected = daily_spine_cli.select_thursday_evidence(
            [raw], as_of=AS_OF, days=7)
        self.assertFalse(rejected)
        self.assertEqual(len(selected), 1)

        context = fixture_context()
        context["brief"]["weekly_slot"] = 3
        for row in context["evidence"]:
            row["thursday_capability"] = copy.deepcopy(facts)
        projected = workflow._writer_evidence_projection(context["evidence"])
        self.assertEqual(projected[0]["thursday_capability"]["demo_url"], DEMO_URL)
        gates = campaign._comment_evidence_gates(
            {"text": "Original demo: " + DEMO_URL},
            post_text="Original demo in the first comment.",
            evidence=context["evidence"], day={"day": "Thursday"})
        self.assertTrue(gates["passes"], gates)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "output"
            root.mkdir(mode=0o700)
            target = Path(write_context(context, root)["path"])
            for name in ("source-comment.md", "final-package.md", "evaluation.json"):
                text = (target / name).read_text()
                self.assertIn(DEMO_URL, text, name)
                self.assertNotIn("utm_source", text, name)
            evaluation = json.loads((target / "evaluation.json").read_text())
            self.assertEqual(evaluation["thursday_package"]["post_comment_promise_check"],
                             "LINKS_PRESENT_REVIEW_REQUIRED")
            self.assertEqual(evaluation["thursday_package"]["video"], "NOT_RENDERED")
        self.assertEqual(raw, original)
        self.assertEqual(context["evidence"][0]["thursday_capability"]["demo_url"], raw_demo)


if __name__ == "__main__":
    unittest.main()
