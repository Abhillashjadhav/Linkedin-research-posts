"""Review provenance, companion coverage, rendering and image placement boundaries."""

from __future__ import annotations

import hashlib
import io
import json
import struct
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from authority_os.article_package import main, package_reviewed_article
from authority_os.article_contract import article_hash
from authority_os import article_workflow
from authority_os.model_runtime import ModelConfig
from authority_os.workflow import WorkflowError


def _write_json(path: Path, value: object) -> str:
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


class ArticlePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        private_outputs = Path(__file__).resolve().parents[1] / "outputs"
        private_outputs.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=private_outputs)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.article = {
            "topic_id": "topic-1", "title": "Proof <script>alert(1)</script>",
            "thesis": "A useful & precise thesis.",
            "sections": [{"id": "opening", "heading": "Evidence <b>",
                          "text": "Body <img src=x onerror=alert(1)> & context.",
                          "claim_ids": ["claim-1"]}],
        }
        self.brief = {
            "contract_version": "sunday-article-v1", "topic_id": "topic-1", "topic": "Evidence",
            "reader": {"audience": "Leaders", "stake": "Decisions", "desired_outcome": "Better review"},
            "thesis": self.article["thesis"], "technical_concept": "Source lineage",
            "worked_example": "One finding", "author": {"name": "Person", "byline": "By Person", "attestations": []},
            "word_range": {"min": 1, "max": 100},
            "sources": [{"id": "src-1", "url": "https://example.org/source?a=1&b=2",
                         "title": "Original study", "content": "Evidence"}],
            "claims": [{"id": "claim-1", "text": "One grounded finding", "kind": "finding",
                        "source_ids": ["src-1"]}],
        }
        self.status = "FIXTURE_ONLY"
        self._rewrite()

    def _rewrite(self) -> None:
        digest = article_hash(self.article, self.brief)
        _write_json(self.root / "article.json", self.article)
        _write_json(self.root / "brief.json", self.brief)
        _write_json(self.root / "article-claim-map.json", {
            "artifact_sha256": digest,
            "sections": [{"section_id": section["id"], "claim_ids": section["claim_ids"]}
                         for section in self.article["sections"]],
            "claims": self.brief["claims"], "sources": self.brief["sources"],
            "author_attestations": self.brief["author"]["attestations"],
        })
        verdict = "PASS" if self.status == "READY_FOR_HUMAN_REVIEW" else "BLOCKED"
        _write_json(self.root / "review.json", {
            "status": self.status, "artifact_sha256": digest,
            "narrative": {"artifact_sha256": digest, "verdict": verdict, "findings": []},
            "factual": {"artifact_sha256": digest, "verdict": verdict, "findings": [],
                        "claim_checks": [{"claim_id": "claim-1", "status": "SUPPORTED",
                                          "source_ids": ["src-1"], "message": "Source supports text"}]},
            "manual_fact_verification_required": True,
        })
        _write_json(self.root / "manifest.json", {"status": self.status, "artifact_sha256": digest,
                                                   "contract_version": "sunday-article-v1", "topic_id": "topic-1",
                                                   "article_file": "article.json", "review_file": "review.json",
                                                   "claim_map_file": "article-claim-map.json",
                                                   "model_config": {"writer": {"runtime": "codex", "model": "test", "reasoning": "low"}} if self.status == "READY_FOR_HUMAN_REVIEW" else {},
                                                   "review_rounds": 1 if self.status == "READY_FOR_HUMAN_REVIEW" else 0,
                                                   "human_approval_status": "NOT_APPROVED", "publishing_status": "DISABLED"})

    def _live(self, *, broken: str | None = None):
        self.status = "READY_FOR_HUMAN_REVIEW"
        self._rewrite()
        calls = []

        def invoke(**kwargs):
            calls.append(kwargs["stage_label"])
            if kwargs["stage_label"] == "Article companion copy":
                ids = ["claim-2"] if broken == "unknown" else ["claim-1"]
                return {"post": {"text": "One grounded finding", "claim_ids": ids},
                        "first_comment": {"text": "One grounded finding: see source ledger.",
                                          "claim_ids": ["claim-1"]}}
            return {"covered_claim_ids": [] if broken == "coverage" else ["claim-1"],
                    "source_ids": ["src-1"], "missing_claim_ids": [],
                    "unreviewed_claim_ids": [], "factual_alignment": True, "notes": "Aligned"}

        return invoke, calls

    def test_fixture_never_invokes_model_and_marks_incomplete(self) -> None:
        def forbidden(**_):
            self.fail("Fixture mode called the model")
        result = package_reviewed_article(self.root, invoker=forbidden)
        self.assertEqual(result["status"], "FIXTURE_ONLY")
        self.assertEqual(result["full_package_status"], "INCOMPLETE")
        self.assertIn("SYNTHETIC FIXTURE", (self.root / "package/post.md").read_text())
        self.assertFalse(result["manifest"]["human_approved"])
        rendered = (self.root / "package/article.html").read_text()
        self.assertIn("&lt;script&gt;", rendered)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", rendered)
        self.assertIn("class=\"byline\">By Person", rendered)
        self.assertNotIn(self.article["thesis"], rendered)
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<img src=x", rendered)
        self.assertIn("a=1&b=2", (self.root / "package/sources.md").read_text())

    def test_cli_fixture_does_not_need_model_config(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main(["--run", str(self.root), "--require-asset", "inline:opening"]), 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "FIXTURE_ONLY")
        self.assertEqual(json.loads(output.getvalue())["missing_required_assets"],
                         ["cover", "inline:opening"])

    def test_runtime_fixture_artifacts_package_without_model(self) -> None:
        run = self.root / "runtime-fixture"
        article_workflow.fixture(run)
        result = package_reviewed_article(run, invoker=lambda **_: self.fail("Model called"))
        self.assertEqual((result["status"], result["full_package_status"]),
                         ("FIXTURE_ONLY", "INCOMPLETE"))

    def test_stale_hash_and_incompatible_status_block(self) -> None:
        self.article["title"] = "mutated"
        _write_json(self.root / "article.json", self.article)
        with self.assertRaisesRegex(WorkflowError, "hash"):
            package_reviewed_article(self.root)
        self._rewrite()
        review = json.loads((self.root / "review.json").read_text())
        review["status"] = "NEEDS_REVIEW"
        _write_json(self.root / "review.json", review)
        with self.assertRaisesRegex(WorkflowError, "status"):
            package_reviewed_article(self.root)

    def test_live_requires_consent_and_rejects_unsupported_claims(self) -> None:
        invoke, calls = self._live(broken="unknown")
        with self.assertRaisesRegex(WorkflowError, "consent"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"), invoker=invoke)
        with self.assertRaisesRegex(WorkflowError, "unsupported"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=invoke)
        self.assertEqual(calls, ["Article companion copy"])

    def test_separate_reviews_bind_text_and_article_hash(self) -> None:
        invoke, calls = self._live()
        result = package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                          live_consent=True, invoker=invoke)
        self.assertEqual(calls, ["Article companion copy", "Article post factual review",
                                 "Article first_comment factual review"])
        self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(result["full_package_status"], "INCOMPLETE")
        evaluations = result["evaluation"]["copy_reviews"]
        self.assertEqual(evaluations["post"]["article_sha256"], result["manifest"]["article_sha256"])
        self.assertEqual(evaluations["first_comment"]["source_ids"], ["src-1"])
        self.assertEqual(result["manifest"]["files_sha256"]["article.html"], hashlib.sha256(
            (self.root / "package/article.html").read_bytes()).hexdigest())

    def test_missing_review_coverage_blocks_eligibility(self) -> None:
        invoke, _ = self._live(broken="coverage")
        result = package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                          live_consent=True, invoker=invoke)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertFalse(result["evaluation"]["copy_reviews"]["post"]["eligible"])

    def test_nested_review_hash_and_claim_source_mapping_are_required(self) -> None:
        invoke, _ = self._live()
        review = json.loads((self.root / "review.json").read_text())
        review["factual"]["artifact_sha256"] = "0" * 64
        _write_json(self.root / "review.json", review)
        with self.assertRaisesRegex(WorkflowError, "Nested.*hash"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=invoke)
        review["factual"]["artifact_sha256"] = article_hash(self.article, self.brief)
        review["factual"]["claim_checks"][0]["source_ids"] = ["unlinked-source"]
        _write_json(self.root / "review.json", review)
        with self.assertRaisesRegex(WorkflowError, "claim/source mapping"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=invoke)

    def test_supplied_resource_is_explicitly_attributed(self) -> None:
        self.brief["resource"] = {"name": "Original code", "url": "https://example.org/tool",
                                  "source_ids": ["src-1"], "claim_ids": ["claim-1"],
                                  "license": "MIT (supplied by caller)"}
        self._rewrite()
        result = package_reviewed_article(self.root)
        self.assertEqual(result["evaluation"]["resource"]["claim_ids"], ["claim-1"])
        self.assertIn("Supplied license: MIT", (self.root / "package/sources.md").read_text())

    def test_inline_asset_embeds_at_mapped_section_and_detects_unowned_output(self) -> None:
        image = self.root / "inline.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                          + struct.pack(">II", 1200, 900) + b"\x08\x02\0\0\0")
        result = package_reviewed_article(self.root, assets={"inline:opening": image})
        self.assertIn("data:image/png;base64,", (self.root / "package/article.html").read_text())
        self.assertEqual(result["manifest"]["asset_placements"], {"inline:opening": "inline-opening.png"})
        foreign = self.root / "foreign"
        foreign.mkdir()
        (foreign / "article.md").write_text("Do not replace", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "not owned"):
            package_reviewed_article(self.root, output_dir=foreign)
        self.assertEqual((foreign / "article.md").read_text(), "Do not replace")

    def test_rerun_preserves_user_edits_and_rejects_tracked_output(self) -> None:
        package_reviewed_article(self.root)
        target = self.root / "package/post.md"
        original_post = target.read_bytes()
        target.write_text("Human edits", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "changed"):
            package_reviewed_article(self.root)
        self.assertEqual(target.read_text(), "Human edits")
        target.write_bytes(original_post)
        article = self.root / "package/article.md"
        article.write_text("Human article revision", encoding="utf-8")
        with self.assertRaisesRegex(WorkflowError, "changed"):
            package_reviewed_article(self.root)
        self.assertEqual(article.read_text(), "Human article revision")
        with self.assertRaisesRegex(WorkflowError, "ignored article run"):
            package_reviewed_article(self.root, output_dir=Path(__file__).resolve().parents[1] / "docs")

    def test_finding_review_requires_nonempty_source_refs(self) -> None:
        invoke, _ = self._live()
        review = json.loads((self.root / "review.json").read_text())
        review["factual"]["claim_checks"][0]["source_ids"] = []
        _write_json(self.root / "review.json", review)
        with self.assertRaisesRegex(WorkflowError, "claim/source mapping|requires a source"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=invoke)

    def test_resource_url_requires_linked_cited_finding(self) -> None:
        self.brief["resource"] = {"name": "Original code", "url": "https://example.org/tool",
                                  "source_ids": ["src-1"], "claim_ids": ["claim-1"]}
        self.status = "READY_FOR_HUMAN_REVIEW"
        self._rewrite()
        calls = []
        def invoke(**kwargs):
            calls.append(kwargs)
            if kwargs["stage_label"] == "Article companion copy":
                self.assertEqual(kwargs["schema"]["type"], "object")
                self.assertIn("eligible_claim_ids", kwargs["task_prompt"])
                return {"post": {"text": "One finding: https://example.org/tool", "claim_ids": ["claim-1"]},
                        "first_comment": {"text": "Source: https://example.org/source?a=1&b=2",
                                          "claim_ids": ["claim-1"]}}
            self.assertIn("resource", kwargs["task_prompt"])
            return {"covered_claim_ids": ["claim-1"], "source_ids": ["src-1"],
                    "missing_claim_ids": [], "unreviewed_claim_ids": [],
                    "factual_alignment": True, "notes": "Aligned"}
        result = package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                          live_consent=True, invoker=invoke)
        self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(len(calls), 3)

    def test_resource_url_and_license_cannot_be_added_without_support(self) -> None:
        self.brief["sources"].append({"id": "src-2", "url": "https://example.org/other",
                                      "title": "Other", "content": "Other finding"})
        self.brief["claims"].append({"id": "claim-2", "text": "Other finding", "kind": "finding",
                                     "source_ids": ["src-2"]})
        self.brief["resource"] = {"name": "Original code", "url": "https://example.org/tool",
                                  "source_ids": ["src-1"], "claim_ids": ["claim-1"]}
        self.article["sections"][0]["claim_ids"].append("claim-2")
        self.status = "READY_FOR_HUMAN_REVIEW"
        self._rewrite()
        review = json.loads((self.root / "review.json").read_text())
        review["factual"]["claim_checks"].append({"claim_id": "claim-2", "status": "SUPPORTED",
                                                   "source_ids": ["src-2"], "message": "Aligned"})
        _write_json(self.root / "review.json", review)
        def unrelated(**_):
            return {"post": {"text": "Other finding https://example.org/tool", "claim_ids": ["claim-2"]},
                    "first_comment": {"text": "Other finding", "claim_ids": ["claim-2"]}}
        with self.assertRaisesRegex(WorkflowError, "outside cited sources"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=unrelated)
        def invented_license(**_):
            return {"post": {"text": "Original code https://example.org/tool is under MIT license",
                             "claim_ids": ["claim-1"]},
                    "first_comment": {"text": "One finding", "claim_ids": ["claim-1"]}}
        with self.assertRaisesRegex(WorkflowError, "license that was not supplied"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=invented_license)

    def test_companion_only_resource_license_claim_gets_its_own_factual_review(self) -> None:
        self.brief["sources"][0]["content"] = "The project repository states its license is MIT."
        self.brief["claims"].append({"id": "resource-license", "text": "The project uses the MIT license",
                                     "kind": "finding", "source_ids": ["src-1"]})
        self.brief["resource"] = {"name": "Original project", "url": "https://example.org/project",
                                  "source_ids": ["src-1"], "claim_ids": ["resource-license"],
                                  "license": "MIT"}
        self.status = "READY_FOR_HUMAN_REVIEW"
        self._rewrite()
        calls = []
        def invoke(**kwargs):
            calls.append(kwargs)
            context = json.loads(kwargs["task_prompt"])
            if kwargs["stage_label"] == "Article companion copy":
                self.assertEqual(context["resource_companion_claim_ids"], ["resource-license"])
                return {"post": {"text": "Original project: https://example.org/project uses the MIT license",
                                 "claim_ids": ["resource-license"]},
                        "first_comment": {"text": "The original finding is grounded.",
                                          "claim_ids": ["claim-1"]}}
            self.assertIn("The project repository states its license is MIT.",
                          context["sources"][0]["content"])
            self.assertIn("author_attestations", context)
            ids = context["claim_ids"]
            return {"covered_claim_ids": ids, "source_ids": ["src-1"],
                    "missing_claim_ids": [], "unreviewed_claim_ids": [],
                    "factual_alignment": True, "notes": "Checked supplied source content"}
        cover = self.root / "cover.png"
        cover.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                          + struct.pack(">II", 1920, 1080) + b"\x08\x02\0\0\0")
        result = package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                          live_consent=True, invoker=invoke, assets={"cover": cover})
        self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(result["full_package_status"], "COMPLETE_FOR_HUMAN_REVIEW")
        post_review = result["evaluation"]["copy_reviews"]["post"]
        self.assertEqual(post_review["companion_only_resource_claim_ids"], ["resource-license"])
        self.assertEqual(post_review["reviewed_resource_claim_ids"], ["resource-license"])
        self.assertEqual(post_review["resource_claim_review_status"], "REVIEWED")
        self.assertNotIn("Original project", (self.root / "package/article.md").read_text())
        self.assertIn("resource-license: src-1", (self.root / "package/sources.md").read_text())
        self.assertEqual(len(calls), 3)

    def test_companion_only_resource_claim_missing_coverage_blocks(self) -> None:
        self.brief["claims"].append({"id": "resource-license", "text": "MIT license",
                                     "kind": "finding", "source_ids": ["src-1"]})
        self.brief["resource"] = {"name": "Original project", "url": "https://example.org/project",
                                  "source_ids": ["src-1"], "claim_ids": ["resource-license"]}
        invoke, _ = self._live()
        def omit_resource_coverage(**kwargs):
            if kwargs["stage_label"] == "Article companion copy":
                return {"post": {"text": "Resource: https://example.org/project",
                                 "claim_ids": ["resource-license"]},
                        "first_comment": {"text": "Original finding", "claim_ids": ["claim-1"]}}
            return {"covered_claim_ids": ["claim-1"], "source_ids": ["src-1"],
                    "missing_claim_ids": [], "unreviewed_claim_ids": [],
                    "factual_alignment": True, "notes": "Resource not checked"}
        result = package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                          live_consent=True, invoker=omit_resource_coverage)
        self.assertEqual(result["status"], "NEEDS_REVIEW")
        self.assertEqual(result["evaluation"]["copy_reviews"]["post"]["resource_claim_review_status"],
                         "NEEDS_REVIEW")

    def test_cover_required_even_when_inline_asset_is_present(self) -> None:
        invoke, _ = self._live()
        inline = self.root / "inline.png"
        inline.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                           + struct.pack(">II", 1200, 900) + b"\x08\x02\0\0\0")
        result = package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                          live_consent=True, invoker=invoke,
                                          assets={"inline:opening": inline})
        self.assertEqual(result["status"], "READY_FOR_HUMAN_REVIEW")
        self.assertEqual(result["full_package_status"], "INCOMPLETE")
        self.assertEqual(result["evaluation"]["missing_required_assets"], ["cover"])
        with self.assertRaisesRegex(WorkflowError, "Required asset placement"):
            package_reviewed_article(self.root, model_config=ModelConfig("codex", "test", "low"),
                                     live_consent=True, invoker=invoke,
                                     required_asset_placements=["inline:missing"])

    def test_asset_dimensions_and_mapping(self) -> None:
        image = self.root / "cover.png"
        image.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
                          + struct.pack(">II", 1920, 1080) + b"\x08\x02\0\0\0")
        with self.assertRaisesRegex(WorkflowError, "dimensions"):
            package_reviewed_article(self.root, assets={"inline:opening": image})
        with self.assertRaisesRegex(WorkflowError, "placement"):
            package_reviewed_article(self.root, assets={"inline:missing": image})
        result = package_reviewed_article(self.root, assets={"cover": image})
        self.assertEqual(result["manifest"]["asset_placements"], {"cover": "cover.png"})
        self.assertIn("cover", result["evaluation"]["provided_assets"])
        self.assertNotIn("rendered_assets", result["evaluation"])
        self.assertEqual((self.root / "package/cover.png").read_bytes(), image.read_bytes())
        self.assertNotIn("data:image/png", (self.root / "package/article.html").read_text())
        package_reviewed_article(self.root)
        self.assertFalse((self.root / "package/cover.png").exists())

    def test_url_validation_and_no_fabricated_link(self) -> None:
        self.brief["sources"][0]["url"] = "http://example.org/source"
        self._rewrite()
        with self.assertRaisesRegex(WorkflowError, "HTTPS"):
            package_reviewed_article(self.root)
        self.brief["sources"][0]["url"] = "https://example.org/source"
        self._rewrite()
        with self.assertRaisesRegex(WorkflowError, "HTTPS"):
            package_reviewed_article(self.root, article_url="file:///etc/passwd")
        result = package_reviewed_article(self.root)
        self.assertIsNone(result["manifest"]["article_url"])
        self.assertNotIn("article URL", (self.root / "package/source-comment.md").read_text())

    def test_article_repository_call_to_action_is_rejected(self) -> None:
        self.article["sections"][0]["text"] += " Check out my GitHub repo."
        self._rewrite()
        with self.assertRaisesRegex(WorkflowError, "repository call to action"):
            package_reviewed_article(self.root)
        self.article["sections"][0]["text"] = "Body without CTA."
        self.article["sections"][0]["heading"] = "Visit the GitHub repo"
        self._rewrite()
        with self.assertRaisesRegex(WorkflowError, "repository call to action"):
            package_reviewed_article(self.root)
        self.article["sections"][0]["heading"] = "Evidence"
        self.brief["author"]["byline"] = "By Person — check out my GitHub repo"
        self._rewrite()
        with self.assertRaisesRegex(WorkflowError, "repository call to action"):
            package_reviewed_article(self.root)


if __name__ == "__main__":
    unittest.main()
