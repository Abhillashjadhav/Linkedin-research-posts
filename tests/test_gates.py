"""Tests for deterministic authority, proof, honesty, citation, and relevance gates."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from authority_os import workflow


def brief(goal: str = "authority") -> dict[str, object]:
    return {
        "goal": goal,
        "topic_slug": "reliability-budgets",
        "goal_purpose": "Demonstrate differentiated AI product judgement.",
        "target_reader": "AI product leaders designing reliable workflows",
        "reader_problem": "Product leaders need a reliable workflow expansion decision.",
        "core_hypothesis": "Workflow reliability must be evaluated end to end.",
        "product_decision": "Set a reliability budget before expanding the workflow.",
        "authority_statement": "Connect workflow reliability to a falsifiable product decision.",
        "strategy_input_origin": "explicit-input",
        "narrative_route": ["problem", "mechanism", "decision"],
        "analysis": {
            "why_now": "Recent body-read evidence supports the decision.",
            "dominant_take": "Evaluate the complete workflow.",
            "missing_angle": "Tie the estimate to a product decision.",
        },
    }


def evidence(
    identifier: str = "source-1",
    *,
    claim: str = "Workflow reliability needs a reliability budget before expansion.",
    source: str = "https://example.com/research/reliability",
    body_read: bool = True,
) -> dict[str, object]:
    return {
        "id": identifier,
        "title": "Workflow reliability evidence",
        "claim": claim,
        "source": source,
        "source_quality": "primary",
        "body_read": body_read,
    }


def candidate(
    *,
    identifier: str = "candidate-1",
    text: str | None = None,
    claim_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "id": identifier,
        "angle": f"angle-{identifier}",
        "text": text
        or (
            "AI product leaders need a reliable workflow expansion decision. "
            "Set a reliability budget before expanding the workflow. "
            "That connects workflow reliability to a falsifiable product decision."
        ),
        "claim_ids": claim_ids or ["source-1"],
    }


class ProofFixture:
    def __init__(
        self,
        *,
        public_claim: str = "A local reliability decision record exists.",
        attestations: list[str] | None = None,
    ) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA)
        self.root = Path(self.temporary.name)
        self.artifact = self.root / "private-artifact.txt"
        self.artifact.write_text("SECRET-ARTIFACT-CONTENT", encoding="utf-8")
        self.manifest = self.root / "proof.json"
        self.payload: dict[str, object] = {
            "schema_version": 1,
            "proof_id": "proof-decision-record",
            "proof_type": "decision-record",
            "artifact_path": self.artifact.name,
            "public_claim": public_claim,
            "attested_personal_sentences": attestations or [],
        }
        self.write()

    def write(self) -> None:
        self.manifest.write_text(json.dumps(self.payload), encoding="utf-8")

    def load(self) -> workflow.LoadedProof:
        return workflow.load_proof_manifest(self.manifest)

    def close(self) -> None:
        self.temporary.cleanup()


class ProofManifestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProofFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_valid_manifest_returns_typed_local_proof(self) -> None:
        loaded = self.fixture.load()
        self.assertIsInstance(loaded, workflow.LoadedProof)
        self.assertEqual(loaded.proof_id, "proof-decision-record")
        self.assertEqual(loaded.artifact_path, self.fixture.artifact)

    def test_manifest_schema_is_exact_and_strictly_typed(self) -> None:
        cases = [
            {**self.fixture.payload, "extra": True},
            {**self.fixture.payload, "schema_version": True},
            {**self.fixture.payload, "proof_id": "source-1"},
            {**self.fixture.payload, "proof_type": "blog-post"},
            {**self.fixture.payload, "attested_personal_sentences": "I built it."},
            {**self.fixture.payload, "public_claim": "unsafe\nclaim"},
        ]
        for payload in cases:
            with self.subTest(payload=payload):
                self.fixture.payload = payload
                self.fixture.write()
                with self.assertRaises(workflow.WorkflowError):
                    self.fixture.load()

    def test_duplicate_normalised_attestations_are_rejected(self) -> None:
        self.fixture.payload["attested_personal_sentences"] = [
            "I built it.",
            "  I BUILT IT.  ",
        ]
        self.fixture.write()
        with self.assertRaisesRegex(workflow.WorkflowError, "distinct"):
            self.fixture.load()

    def test_artifact_must_be_relative_regular_nonempty_and_present(self) -> None:
        outside = Path(self.fixture.temporary.name).parent / "outside-proof.txt"
        cases = [
            "/tmp/outside-proof.txt",
            "../outside-proof.txt",
            "missing.txt",
        ]
        for artifact_path in cases:
            with self.subTest(artifact_path=artifact_path):
                self.fixture.payload["artifact_path"] = artifact_path
                self.fixture.write()
                with self.assertRaises(workflow.WorkflowError):
                    self.fixture.load()
        self.fixture.payload["artifact_path"] = "empty.txt"
        (self.fixture.root / "empty.txt").write_text("", encoding="utf-8")
        self.fixture.write()
        with self.assertRaises(workflow.WorkflowError):
            self.fixture.load()
        self.assertFalse(outside.exists())

    def test_manifest_cannot_serve_as_its_own_proof_artifact(self) -> None:
        self.fixture.payload["artifact_path"] = self.fixture.manifest.name
        self.fixture.write()
        with self.assertRaisesRegex(workflow.WorkflowError, "distinct"):
            self.fixture.load()

        hard_link = self.fixture.root / "manifest-hard-link.json"
        os.link(self.fixture.manifest, hard_link)
        self.fixture.payload["artifact_path"] = hard_link.name
        self.fixture.write()
        with self.assertRaisesRegex(workflow.WorkflowError, "distinct"):
            self.fixture.load()

    def test_loader_reads_only_manifest_descriptor_not_artifact(self) -> None:
        real_read = os.read
        artifact_identity = (
            self.fixture.artifact.stat().st_dev,
            self.fixture.artifact.stat().st_ino,
        )

        def guarded_read(file_descriptor: int, size: int) -> bytes:
            metadata = os.fstat(file_descriptor)
            self.assertNotEqual(
                (metadata.st_dev, metadata.st_ino), artifact_identity
            )
            return real_read(file_descriptor, size)

        with patch("authority_os.workflow.os.read", side_effect=guarded_read):
            loaded = self.fixture.load()
        self.assertEqual(loaded.artifact_path, self.fixture.artifact)

    def test_oversized_manifest_fails_with_static_safe_error(self) -> None:
        self.fixture.manifest.write_bytes(
            b"{" + b"x" * workflow.MAX_PROOF_MANIFEST_BYTES + b"}"
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "too large") as captured:
            self.fixture.load()
        self.assertNotIn(str(self.fixture.root), str(captured.exception))

    def test_directory_fifo_and_symlinks_are_rejected(self) -> None:
        directory = self.fixture.root / "directory"
        directory.mkdir()
        self.fixture.payload["artifact_path"] = directory.name
        self.fixture.write()
        with self.assertRaises(workflow.WorkflowError):
            self.fixture.load()

        if hasattr(os, "mkfifo"):
            fifo = self.fixture.root / "pipe"
            os.mkfifo(fifo)
            self.fixture.payload["artifact_path"] = fifo.name
            self.fixture.write()
            with self.assertRaises(workflow.WorkflowError):
                self.fixture.load()

        link = self.fixture.root / "artifact-link"
        link.symlink_to(self.fixture.artifact)
        self.fixture.payload["artifact_path"] = link.name
        self.fixture.write()
        with self.assertRaisesRegex(workflow.WorkflowError, "symbolic"):
            self.fixture.load()

        linked_parent = self.fixture.root / "linked-parent"
        real_parent = self.fixture.root / "real-parent"
        real_parent.mkdir()
        (real_parent / "artifact.txt").write_text("proof", encoding="utf-8")
        linked_parent.symlink_to(real_parent, target_is_directory=True)
        self.fixture.payload["artifact_path"] = "linked-parent/artifact.txt"
        self.fixture.write()
        with self.assertRaisesRegex(workflow.WorkflowError, "symbolic"):
            self.fixture.load()

    def test_manifest_symlink_is_rejected_before_read(self) -> None:
        link = self.fixture.root / "manifest-link.json"
        link.symlink_to(self.fixture.manifest)
        with self.assertRaisesRegex(workflow.WorkflowError, "symbolic"):
            workflow.load_proof_manifest(link)

    def test_errors_do_not_echo_private_path_or_contents(self) -> None:
        self.fixture.payload["artifact_path"] = "missing-secret-name.txt"
        self.fixture.write()
        with self.assertRaises(workflow.WorkflowError) as captured:
            self.fixture.load()
        message = str(captured.exception)
        self.assertNotIn("missing-secret-name", message)
        self.assertNotIn(str(self.fixture.root), message)
        self.assertNotIn("SECRET-ARTIFACT-CONTENT", message)

    def test_forged_loaded_proof_fields_are_revalidated(self) -> None:
        loaded = self.fixture.load()
        forged = workflow.LoadedProof(
            proof_id="source-1",
            proof_type=loaded.proof_type,
            artifact_path=loaded.artifact_path,
            fixture_mode=loaded.fixture_mode,
            public_claim=loaded.public_claim,
            attested_personal_sentences=loaded.attested_personal_sentences,
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "validated local manifest"):
            workflow.evaluate_candidate_gates(
                candidate(), brief=brief(), evidence=[evidence()], proof=forged
            )
        outside = workflow.LoadedProof(
            proof_id="proof-forged",
            proof_type="artifact",
            artifact_path=Path("/etc/passwd"),
            fixture_mode=False,
            public_claim="A local artifact exists.",
            attested_personal_sentences=(),
        )
        with self.assertRaisesRegex(workflow.WorkflowError, "allowed local data"):
            workflow.evaluate_candidate_gates(
                candidate(), brief=brief(), evidence=[evidence()], proof=outside
            )

    def test_attestations_must_be_personal_or_ownership_sentences(self) -> None:
        self.fixture.payload["attested_personal_sentences"] = [
            "Google breached customer records."
        ]
        self.fixture.write()
        with self.assertRaisesRegex(workflow.WorkflowError, "attestations"):
            self.fixture.load()


class GateEvaluationTests(unittest.TestCase):
    def test_baseline_authority_candidate_passes_required_gates(self) -> None:
        result = workflow.evaluate_candidate_gates(
            candidate(), brief=brief(), evidence=[evidence()]
        )
        self.assertEqual(list(result["gates"]), list(workflow.GATE_ORDER))
        self.assertEqual(result["gates"]["proof"]["status"], "NOT_REQUIRED")
        self.assertTrue(result["passes_required_gates"])
        self.assertIs(result["manual_fact_verification_required"], True)

    def test_opportunity_derives_required_proof_from_goal_not_mutable_flag(self) -> None:
        routed = brief("opportunity")
        routed["proof_required"] = False
        result = workflow.evaluate_candidate_gates(
            candidate(), brief=routed, evidence=[evidence()]
        )
        self.assertEqual(result["gates"]["proof"]["status"], "FAIL")
        self.assertIn(
            "opportunity-proof-not-supplied",
            result["gates"]["proof"]["reason_codes"],
        )

    def test_non_opportunity_proof_is_not_required_not_pass(self) -> None:
        fixture = ProofFixture()
        try:
            result = workflow.evaluate_candidate_gates(
                candidate(), brief=brief("reach"), evidence=[evidence()], proof=fixture.load()
            )
            self.assertEqual(result["gates"]["proof"]["status"], "NOT_REQUIRED")
        finally:
            fixture.close()

    def test_opportunity_proof_requires_exact_id_and_public_claim(self) -> None:
        fixture = ProofFixture()
        try:
            loaded = fixture.load()
            routed = brief("opportunity")
            missing_id = workflow.evaluate_candidate_gates(
                candidate(text=f"{candidate()['text']} {loaded.public_claim}"),
                brief=routed,
                evidence=[evidence()],
                proof=loaded,
            )
            self.assertIn(
                "opportunity-proof-id-not-cited",
                missing_id["gates"]["proof"]["reason_codes"],
            )
            missing_claim = workflow.evaluate_candidate_gates(
                candidate(claim_ids=["source-1", loaded.proof_id]),
                brief=routed,
                evidence=[evidence()],
                proof=loaded,
            )
            self.assertIn(
                "opportunity-proof-claim-not-used",
                missing_claim["gates"]["proof"]["reason_codes"],
            )
            embedded_or_negated = workflow.evaluate_candidate_gates(
                candidate(
                    text=f"{candidate()['text']} Not verified: {loaded.public_claim}",
                    claim_ids=["source-1", loaded.proof_id],
                ),
                brief=routed,
                evidence=[evidence()],
                proof=loaded,
            )
            self.assertIn(
                "opportunity-proof-claim-not-used",
                embedded_or_negated["gates"]["proof"]["reason_codes"],
            )
            passed = workflow.evaluate_candidate_gates(
                candidate(
                    text=f"{candidate()['text']} {loaded.public_claim}",
                    claim_ids=["source-1", loaded.proof_id],
                ),
                brief=routed,
                evidence=[evidence()],
                proof=loaded,
            )
            self.assertEqual(passed["gates"]["proof"]["status"], "PASS")
        finally:
            fixture.close()

    def test_unsupported_ownership_fails_and_exact_attestation_passes(self) -> None:
        personal = "I built the reliability-budget workflow."
        no_attestation = ProofFixture()
        attested = ProofFixture(attestations=[personal])
        try:
            base = candidate()["text"]
            failed = workflow.evaluate_candidate_gates(
                candidate(text=f"{base} {personal}"),
                brief=brief(),
                evidence=[evidence()],
                proof=no_attestation.load(),
            )
            self.assertEqual(failed["gates"]["honesty"]["status"], "FAIL")
            passed = workflow.evaluate_candidate_gates(
                candidate(
                    text=f"{base} {personal}",
                    claim_ids=["source-1", attested.load().proof_id],
                ),
                brief=brief(),
                evidence=[evidence()],
                proof=attested.load(),
            )
            self.assertEqual(passed["gates"]["honesty"]["status"], "PASS")
            paraphrase = workflow.evaluate_candidate_gates(
                candidate(
                    text=f"{base} I personally built the reliability-budget workflow.",
                    claim_ids=["source-1", attested.load().proof_id],
                ),
                brief=brief(),
                evidence=[evidence()],
                proof=attested.load(),
            )
            self.assertEqual(paraphrase["gates"]["honesty"]["status"], "FAIL")
        finally:
            no_attestation.close()
            attested.close()

    def test_unused_proof_cannot_bless_an_ownership_statement(self) -> None:
        personal = "I built the reliability-budget workflow."
        fixture = ProofFixture(attestations=[personal])
        try:
            result = workflow.evaluate_candidate_gates(
                candidate(text=f"{candidate()['text']} {personal}"),
                brief=brief(),
                evidence=[evidence()],
                proof=fixture.load(),
            )
            self.assertEqual(result["gates"]["proof"]["status"], "NOT_REQUIRED")
            self.assertIn(
                "unsupported-personal-or-ownership-claim",
                result["gates"]["honesty"]["reason_codes"],
            )
        finally:
            fixture.close()

    def test_first_person_plural_and_named_author_ownership_are_detected(self) -> None:
        claims = [
            "I've built the workflow.",
            "My team shipped the workflow.",
            "We measured the result.",
            "Our client used the workflow.",
            "Abhillash led the deployment.",
            "The workflow was built by Abhillash.",
            "The workflow was built by me.",
            "The repository is mine.",
            "I lead the deployment.",
            "I own the workflow.",
            "I am the founder of Acme.",
            "I am leading the deployment.",
            "I run the product team.",
            "I have a decade of experience.",
            "I am certified in product management.",
            "My customers use this workflow.",
            "Our users adopted this workflow.",
            "Abhillash is the creator of the workflow.",
            "I am responsible for this workflow.",
            "I co-founded the company.",
            "I was responsible for this workflow.",
            "I have ten years of experience.",
            "My startup launched this product.",
            "The repository belongs to Abhillash.",
            "I maintain the repository.",
            "Today, I maintain the repository.",
            "In that role, I was responsible for the deployment.",
            "As a founder, I advise teams.",
            "The code belongs to me.",
            "The code is mine.",
            "I think I maintain the repository.",
            "I believe I operate the system.",
            "I think I was responsible for deployment.",
            "In my opinion, our infrastructure is reliable.",
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=f"{candidate()['text']} {claim}"),
                    brief=brief(),
                    evidence=[evidence()],
                )
                self.assertIn(
                    "unsupported-personal-or-ownership-claim",
                    result["gates"]["honesty"]["reason_codes"],
                )

    def test_benign_first_person_opinion_is_not_treated_as_ownership(self) -> None:
        text = (
            f"{candidate()['text']} I think this is useful. In my view, the rule is clear. "
            "This tells us where to start. I found this useful. "
            "I think this work is useful. I recommend a test before expansion. "
            "I use a lead measure. I think the launch decision matters. "
            "We need a better reliability rule. I agree with this decision."
        )
        result = workflow.evaluate_candidate_gates(
            candidate(text=text), brief=brief(), evidence=[evidence()]
        )
        self.assertNotIn(
            "unsupported-personal-or-ownership-claim",
            result["gates"]["honesty"]["reason_codes"],
        )

    def test_client_and_customer_incidents_require_exact_support(self) -> None:
        claims = [
            "A client told me the workflow failed.",
            "During a customer demo, the system stopped.",
            "A prospect told me the workflow failed.",
            "A user reported a production outage.",
            "The deployment failed in production.",
            "The system degraded in production.",
            "Production went down overnight.",
            "The production service crashed.",
            "Production crashed overnight.",
            "The service was unavailable in production.",
            "In production, the workflow crashed.",
            "A production deployment failed.",
            "The production service went offline.",
            "The production system became unhealthy.",
        ]
        for claim in claims:
            with self.subTest(claim=claim):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=f"{candidate()['text']} {claim}"),
                    brief=brief(),
                    evidence=[evidence()],
                )
                self.assertIn(
                    "untraceable-incident",
                    result["gates"]["honesty"]["reason_codes"],
                )
                self.assertIn(
                    "untraceable-incident",
                    result["gates"]["citation"]["reason_codes"],
                )

    def test_unsupported_number_name_and_attributed_quote_fail_both_gates(self) -> None:
        texts = [
            f"{candidate()['text']} OpenAI reported 95% reliability.",
            f'{candidate()["text"]} OpenAI said "the system never fails".',
            f'{candidate()["text"]} "The system never fails" is the documented claim.',
            f"{candidate()['text']} 'The system never fails.'",
            f"{candidate()['text']}\n> The system never fails.",
            f"{candidate()['text']} Google breached customer records.",
            f"{candidate()['text']} Acme breached customer records.",
            f"{candidate()['text']} Acme fired staff.",
            f"{candidate()['text']} Acme sells AI software.",
            f"{candidate()['text']} Acme recommends simple workflows.",
            f"{candidate()['text']} Acme made a product.",
            f"{candidate()['text']} Acme paid staff.",
            f"{candidate()['text']} A report from Acme recommends simple workflows.",
            f"{candidate()['text']} Acme dominates the market.",
            f"{candidate()['text']} Acme processes millions of requests.",
            f"{candidate()['text']} Acme runs production systems.",
            f"{candidate()['text']} Acme provides enterprise software.",
            f"{candidate()['text']} Acme is reliable.",
            f"{candidate()['text']} Acme can process requests.",
            f"{candidate()['text']} Acme will launch a product.",
            f"{candidate()['text']} Acme, the market leader, controls distribution.",
            f"{candidate()['text']} The company Acme dominates the market.",
            f"{candidate()['text']} eBay acquired Acme.",
            f"{candidate()['text']} xAI announced a model.",
            f"{candidate()['text']} iRobot released a product.",
            f"{candidate()['text']} Åcme acquired Beta.",
            f"{candidate()['text']} The company acquired Acme.",
            f"{candidate()['text']} A startup hired Beta.",
            f"{candidate()['text']} A vendor bought eBay.",
            f"{candidate()['text']} Acme defeated Beta.",
            f"{candidate()['text']} Acme purchased Beta.",
            f"{candidate()['text']} Acme partnered with Beta.",
            f"{candidate()['text']} Acme guarantees reliable results.",
            f"{candidate()['text']} Acme excels at reliability.",
            f"{candidate()['text']} Stability AI launched a model.",
            f"{candidate()['text']} The company Acme guarantees results.",
            f"{candidate()['text']} Mistral launched a model.",
            f"{candidate()['text']} Cohere acquired a startup.",
            f"{candidate()['text']} Databricks reported growth.",
            f"{candidate()['text']} The company acquired Mistral.",
            f"{candidate()['text']} A startup hired Cohere.",
            f"{candidate()['text']} The workflow uses Mistral.",
            f"{candidate()['text']} Stripe sells software.",
            f"{candidate()['text']} Oracle provides enterprise software.",
            f"{candidate()['text']} Spotify fires staff.",
            f"{candidate()['text']} Salesforce recommends simple workflows.",
            f"{candidate()['text']} Beta sells software.",
            f"{candidate()['text']} A customer said the system never fails.",
            f"{candidate()['text']} Reliability improved by ninety-five percent.",
            f"{candidate()['text']} Reliability reached one hundred percent.",
            f"{candidate()['text']} Half of workflows failed.",
            f"{candidate()['text']} The workflow served five customers.",
            f"{candidate()['text']} The product reached one million users.",
            f"{candidate()['text']} A dozen incidents happened.",
            f"{candidate()['text']} The result doubled.",
            f"{candidate()['text']} The product serves millions of users.",
            f"{candidate()['text']} Thousands use the workflow.",
            f"{candidate()['text']} The report says 「the system never fails」.",
            f"{candidate()['text']} 'The system never fails.",
            f"{candidate()['text']} ”The system never fails“.",
            f"{candidate()['text']} Reliability reached ninety-five per cent.",
            f"{candidate()['text']} A quarter of workflows failed.",
            f"{candidate()['text']} Customers saw repeated failures.",
            f"{candidate()['text']} The source is https://fabricated.example/private-claim.",
            f"{candidate()['text']} The customer outage happened last week.",
        ]
        for text in texts:
            with self.subTest(text=text):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=text), brief=brief(), evidence=[evidence()]
                )
                self.assertEqual(result["gates"]["honesty"]["status"], "FAIL")
                self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_named_number_markers_must_coexist_in_one_cited_record(self) -> None:
        text = f"{candidate()['text']} OpenAI reported 95% reliability."
        split = workflow.evaluate_candidate_gates(
            candidate(text=text, claim_ids=["source-1", "source-2"]),
            brief=brief(),
            evidence=[
                evidence(claim="OpenAI published a reliability note."),
                evidence("source-2", claim="A test reported 95% reliability."),
            ],
        )
        self.assertEqual(split["gates"]["citation"]["status"], "FAIL")
        together = workflow.evaluate_candidate_gates(
            candidate(text=text),
            brief=brief(),
            evidence=[evidence(claim="OpenAI reported 95% reliability.")],
        )
        self.assertEqual(together["gates"]["citation"]["status"], "PASS")

    def test_same_markers_cannot_hide_a_contradictory_assertion(self) -> None:
        result = workflow.evaluate_candidate_gates(
            candidate(text=f"{candidate()['text']} OpenAI lost 95% reliability."),
            brief=brief(),
            evidence=[evidence(claim="OpenAI gained 95% reliability.")],
        )
        self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_relationship_order_cannot_be_reversed_by_cited_tokens(self) -> None:
        cases = [
            ("Acme acquired Beta.", "Beta acquired Acme."),
            ("Acme acquired Beta.", "Acme was acquired by Beta."),
            ("Acme acquired Beta.", "Acme got acquired by Beta."),
            ("Zoom acquired Slack.", "A different company acquired another startup."),
            ("Acme hired Beta.", "Acme got hired by Beta."),
            ("Acme owned Beta.", "Acme became owned by Beta."),
            (
                "Acme gained 30 users and Beta gained 10 users.",
                "Acme gained 10 users and Beta gained 30 users.",
            ),
        ]
        for assertion, source_claim in cases:
            with self.subTest(assertion=assertion):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=f"{candidate()['text']} {assertion}"),
                    brief=brief(),
                    evidence=[evidence(claim=source_claim)],
                )
                self.assertEqual(result["gates"]["honesty"]["status"], "FAIL")
                self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_equivalent_active_and_passive_relationships_are_supported(self) -> None:
        cases = [
            ("Beta was acquired by Acme.", "Acme acquired Beta."),
            ("Beta has been acquired by Acme.", "Acme acquired Beta."),
            ("Beta got hired by Acme.", "Acme hired Beta."),
            ("Beta became owned by Acme.", "Acme owned Beta."),
        ]
        for assertion, source_claim in cases:
            with self.subTest(assertion=assertion):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=f"{candidate()['text']} {assertion}"),
                    brief=brief(),
                    evidence=[evidence(claim=source_claim)],
                )
                self.assertEqual(result["gates"]["honesty"]["status"], "PASS")
                self.assertEqual(result["gates"]["citation"]["status"], "PASS")

    def test_negative_evidence_cannot_support_the_opposite_positive_claim(self) -> None:
        cases = [
            (
                "OpenAI did achieve 95% reliability.",
                "OpenAI did not achieve 95% reliability.",
            ),
            ("OpenAI is reliable.", "OpenAI is not reliable."),
            (
                "OpenAI did achieve 95% reliability, not only in tests.",
                "OpenAI did not achieve 95% reliability, not even in tests.",
            ),
            (
                "OpenAI did achieve 95% reliability and did not fail any tests.",
                "OpenAI did not achieve 95% reliability and did not fail any tests.",
            ),
            (
                "OpenAI did achieve 95% reliability and it did not fail any tests.",
                "OpenAI did not achieve 95% reliability and it did not fail any tests.",
            ),
            (
                "OpenAI did achieve 95% reliability and the product team did not report failures.",
                "OpenAI did not achieve 95% reliability and the product team did not report failures.",
            ),
            (
                "OpenAI did achieve 95% reliability and its product team did not report failures.",
                "OpenAI did not achieve 95% reliability and its product team did not report failures.",
            ),
        ]
        for assertion, source_claim in cases:
            with self.subTest(assertion=assertion):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=f"{candidate()['text']} {assertion}"),
                    brief=brief(),
                    evidence=[evidence(claim=source_claim)],
                )
                self.assertEqual(result["gates"]["honesty"]["status"], "FAIL")
                self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

        supported = workflow.evaluate_candidate_gates(
            candidate(
                text=f"{candidate()['text']} OpenAI did not achieve 95% reliability."
            ),
            brief=brief(),
            evidence=[evidence(claim="OpenAI did not achieve 95% reliability.")],
        )
        self.assertEqual(supported["gates"]["honesty"]["status"], "PASS")
        self.assertEqual(supported["gates"]["citation"]["status"], "PASS")

        coordinated = (
            "OpenAI did achieve 95% reliability and the product team did not report "
            "failures."
        )
        coordinated_supported = workflow.evaluate_candidate_gates(
            candidate(text=f"{candidate()['text']} {coordinated}"),
            brief=brief(),
            evidence=[evidence(claim=coordinated)],
        )
        self.assertEqual(
            coordinated_supported["gates"]["citation"]["status"], "PASS"
        )

    def test_possessive_and_attributed_proper_names_are_markers(self) -> None:
        texts = [
            f"{candidate()['text']} Nvidia's system reached 95% reliability.",
            f"{candidate()['text']} According to Acme, the system reached 95% reliability.",
        ]
        for text in texts:
            with self.subTest(text=text):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=text),
                    brief=brief(),
                    evidence=[evidence(claim="A different system reached 95% reliability.")],
                )
                self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_signed_and_range_numbers_are_checked_individually(self) -> None:
        cases = [
            (
                f"{candidate()['text']} The workflow changed by -5%.",
                "The workflow changed by 5%.",
            ),
            (
                f"{candidate()['text']} The observed range was 10-20%.",
                "The observed range began at 10%.",
            ),
        ]
        for text, source_claim in cases:
            with self.subTest(text=text):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=text),
                    brief=brief(),
                    evidence=[evidence(claim=source_claim)],
                )
                self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_smart_quotes_and_quoted_questions_require_support(self) -> None:
        quotations = [
            "‘The system never fails.’",
            "«The system never fails.»",
            "“Can this system fail?” was the documented customer question.",
        ]
        for quotation in quotations:
            with self.subTest(quotation=quotation):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=f"{candidate()['text']} {quotation}"),
                    brief=brief(),
                    evidence=[evidence()],
                )
                self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_single_brand_names_and_number_boundaries_are_not_laundered(self) -> None:
        amazon = workflow.evaluate_candidate_gates(
            candidate(text=f"{candidate()['text']} Amazon reported reliable results."),
            brief=brief(),
            evidence=[evidence(claim="A different company reported reliable results.")],
        )
        self.assertEqual(amazon["gates"]["citation"]["status"], "FAIL")
        number = workflow.evaluate_candidate_gates(
            candidate(text=f"{candidate()['text']} The workflow had 5 failures."),
            brief=brief(),
            evidence=[evidence(claim="The workflow had 50 failures.")],
        )
        self.assertEqual(number["gates"]["citation"]["status"], "FAIL")
        near_name = workflow.evaluate_candidate_gates(
            candidate(text=f"{candidate()['text']} OpenAI reported reliable results."),
            brief=brief(),
            evidence=[evidence(claim="OpenAir reported reliable results.")],
        )
        self.assertEqual(near_name["gates"]["citation"]["status"], "FAIL")

    def test_ordinary_capitalised_sentence_starts_are_not_named_markers(self) -> None:
        text = (
            f"{candidate()['text']} Better decisions begin with evidence. "
            "Strong teams record the decision. Most workflows need a budget. "
            "Good teams make careful decisions. Clear rules help product teams. "
            "Reliable systems need explicit budgets. Simple workflows reduce uncertainty. "
            "A Senior PM needs a reliable workflow. The Product team needs an explicit budget. "
            "An AI Product Manager needs evidence. AI Product Managers need evidence. "
            "Good practices make decisions repeatable. Clear standards help teams decide. "
            "Strong signals matter to product leaders. Clear thinking improves decisions. "
            "Reliable testing reduces risk. Strategic planning supports teams. "
            "Simple testing works. Good writing builds authority."
            " Quiet confidence matters. Local evidence matters. "
            "Explicit budgets help teams decide. Human review remains essential. "
            "Missing evidence should stay visible. Trust compounds slowly. "
            "Judgment matters. Clarity beats complexity. "
            "Thoughtful testing reduces risk. Robust evaluation improves decisions. "
            "Context changes decisions. Teams' judgment matters. "
            "A team's judgment matters. Evidence supports decisions. "
            "Reliability improves with testing. Practice builds judgment. "
            "Writing earns attention. Testing reduces risk. "
            "Systems fail without budgets. Engineering builds reliable workflows. "
            "Beta testing catches failures. Beta users need clear expectations. "
            "A beta release needs monitoring. The beta cohort reveals risk. "
            "Safety matters. Privacy matters. Research matters. Proof matters. "
            "Strategy matters. Delivery matters. Design matters. Impact matters. "
            "Leadership matters. "
            "Email me@example.com."
        )
        result = workflow.evaluate_candidate_gates(
            candidate(text=text), brief=brief(), evidence=[evidence()]
        )
        self.assertEqual(result["gates"]["citation"]["status"], "PASS")

    def test_titles_and_urls_cannot_launder_factual_support(self) -> None:
        title_only_marker = workflow.evaluate_candidate_gates(
            candidate(text=f"{candidate()['text']} OpenAI reported 95% reliability."),
            brief=brief(),
            evidence=[
                {
                    **evidence(claim="The body discusses a different reliability result."),
                    "title": "OpenAI reported 95% reliability",
                }
            ],
        )
        self.assertEqual(
            title_only_marker["gates"]["citation"]["status"], "FAIL"
        )
        supported_url = workflow.evaluate_candidate_gates(
            candidate(
                text=(
                    f"{candidate()['text']} The source is "
                    "https://example.com/research/reliability."
                )
            ),
            brief=brief(),
            evidence=[evidence()],
        )
        self.assertEqual(supported_url["gates"]["citation"]["status"], "PASS")

    def test_bare_and_markdown_references_cannot_bypass_citation_checks(self) -> None:
        texts = [
            f"{candidate()['text']} The source is fake-research.com.",
            f"{candidate()['text']} The study is [here](fake-research.com).",
            f"{candidate()['text']} A source appears at fake-research.com.",
            (
                f"{candidate()['text']} The study is "
                "[fabricated.example](https://example.com/research/reliability)."
            ),
            f"{candidate()['text']} The study is [here](javascript:alert(1)).",
        ]
        for text in texts:
            with self.subTest(text=text):
                result = workflow.evaluate_candidate_gates(
                    candidate(text=text), brief=brief(), evidence=[evidence()]
                )
                self.assertIn(
                    "unsupported-source-url",
                    result["gates"]["citation"]["reason_codes"],
                )

        supported = workflow.evaluate_candidate_gates(
            candidate(
                text=(
                    f"{candidate()['text']} The source is "
                    "example.com/research/reliability."
                )
            ),
            brief=brief(),
            evidence=[evidence()],
        )
        self.assertEqual(supported["gates"]["citation"]["status"], "PASS")

        supported_markdown = workflow.evaluate_candidate_gates(
            candidate(
                text=(
                    f"{candidate()['text']} The study is "
                    "[here](example.com/research/reliability)."
                )
            ),
            brief=brief(),
            evidence=[evidence()],
        )
        self.assertEqual(
            supported_markdown["gates"]["citation"]["status"], "PASS"
        )

    def test_query_addressed_citations_require_the_exact_canonical_query(self) -> None:
        cited = evidence(source="https://example.com/research?id=good")
        swapped = workflow.evaluate_candidate_gates(
            candidate(
                text=(
                    f"{candidate()['text']} The source is "
                    "https://example.com/research?id=fake."
                )
            ),
            brief=brief(),
            evidence=[cited],
        )
        self.assertIn(
            "unsupported-source-url",
            swapped["gates"]["citation"]["reason_codes"],
        )

        exact = workflow.evaluate_candidate_gates(
            candidate(
                text=(
                    f"{candidate()['text']} The source is "
                    "https://example.com/research?id=good."
                )
            ),
            brief=brief(),
            evidence=[cited],
        )
        self.assertEqual(exact["gates"]["citation"]["status"], "PASS")

    def test_title_only_unknown_and_community_only_sources_fail_citation(self) -> None:
        title_only = workflow.evaluate_candidate_gates(
            candidate(), brief=brief(), evidence=[evidence(body_read=False)]
        )
        self.assertEqual(title_only["gates"]["honesty"]["status"], "FAIL")
        self.assertEqual(title_only["gates"]["citation"]["status"], "FAIL")

        unknown = workflow.evaluate_candidate_gates(
            candidate(claim_ids=["unknown"]), brief=brief(), evidence=[evidence()]
        )
        self.assertIn("unknown-claim-id", unknown["gates"]["citation"]["reason_codes"])

        community = workflow.evaluate_candidate_gates(
            candidate(),
            brief=brief(),
            evidence=[evidence(source="https://old.reddit.com/r/ai/comments/1")],
        )
        self.assertIn(
            "community-only-evidence", community["gates"]["citation"]["reason_codes"]
        )
        lookalike = workflow.evaluate_candidate_gates(
            candidate(),
            brief=brief(),
            evidence=[evidence(source="https://reddit.com.evil.example/research")],
        )
        self.assertNotIn(
            "community-only-evidence", lookalike["gates"]["citation"]["reason_codes"]
        )

    def test_unrelated_primary_source_cannot_launder_community_support(self) -> None:
        text = f"{candidate()['text']} OpenAI reported 95% reliability."
        result = workflow.evaluate_candidate_gates(
            candidate(text=text, claim_ids=["source-1", "source-2"]),
            brief=brief(),
            evidence=[
                evidence(
                    claim="OpenAI reported 95% reliability.",
                    source="https://reddit.com/r/ai/comments/one",
                ),
                evidence(
                    "source-2",
                    claim="A separate workflow uses a reliability budget.",
                ),
            ],
        )
        self.assertEqual(result["gates"]["citation"]["status"], "FAIL")

    def test_cited_public_proof_url_is_supported_without_local_path(self) -> None:
        public_claim = (
            "A public decision record exists at "
            "https://github.com/example/reliability-proof"
        )
        fixture = ProofFixture(public_claim=public_claim)
        try:
            loaded = fixture.load()
            result = workflow.evaluate_candidate_gates(
                candidate(
                    text=f"{candidate()['text']} {public_claim}",
                    claim_ids=["source-1", loaded.proof_id],
                ),
                brief=brief("opportunity"),
                evidence=[evidence()],
                proof=loaded,
            )
            self.assertEqual(result["gates"]["proof"]["status"], "PASS")
            self.assertEqual(result["gates"]["honesty"]["status"], "PASS")
            self.assertEqual(result["gates"]["citation"]["status"], "PASS")
            self.assertNotIn(str(fixture.root), json.dumps(result))
        finally:
            fixture.close()

    def test_authority_and_relevance_require_material_reflection(self) -> None:
        generic = candidate(text="A generic observation with no useful audience or decision.")
        result = workflow.evaluate_candidate_gates(
            generic, brief=brief(), evidence=[evidence()]
        )
        self.assertEqual(result["gates"]["authority_conversion"]["status"], "FAIL")
        self.assertEqual(result["gates"]["relevance"]["status"], "FAIL")

        bad_audience = brief()
        bad_audience["target_reader"] = "Everyone on the internet"
        result = workflow.evaluate_candidate_gates(
            candidate(), brief=bad_audience, evidence=[evidence()]
        )
        self.assertIn(
            "target-audience-not-recognised",
            result["gates"]["relevance"]["reason_codes"],
        )

        bakery = brief()
        bakery["target_reader"] = "Founder of a local bakery"
        bakery_result = workflow.evaluate_candidate_gates(
            candidate(), brief=bakery, evidence=[evidence()]
        )
        self.assertEqual(bakery_result["gates"]["relevance"]["status"], "FAIL")

        marketer = brief()
        marketer["target_reader"] = "AI product marketers promoting consumer cosmetics"
        marketer_result = workflow.evaluate_candidate_gates(
            candidate(), brief=marketer, evidence=[evidence()]
        )
        self.assertEqual(marketer_result["gates"]["relevance"]["status"], "FAIL")

    def test_reader_problem_and_authority_thesis_need_distinctive_overlap(self) -> None:
        unrelated_problem = brief()
        unrelated_problem["reader_problem"] = "Select quantum sensors for hospitals."
        problem_result = workflow.evaluate_candidate_gates(
            candidate(), brief=unrelated_problem, evidence=[evidence()]
        )
        self.assertEqual(problem_result["gates"]["relevance"]["status"], "FAIL")

        unrelated_authority = brief()
        unrelated_authority["authority_statement"] = (
            "Connect quantum procurement to a product decision."
        )
        authority_result = workflow.evaluate_candidate_gates(
            candidate(), brief=unrelated_authority, evidence=[evidence()]
        )
        self.assertEqual(
            authority_result["gates"]["authority_conversion"]["status"], "FAIL"
        )

    def test_results_are_static_schema_deterministic_and_nonmutating(self) -> None:
        candidates = [candidate(identifier=f"candidate-{index}") for index in (3, 1, 2)]
        routed = brief()
        records = [evidence()]
        baseline = deepcopy((candidates, routed, records))
        first = workflow.evaluate_candidate_set_gates(
            candidates, brief=routed, evidence=records
        )
        second = workflow.evaluate_candidate_set_gates(
            list(reversed(candidates)), brief=routed, evidence=records
        )
        self.assertEqual(first, second)
        self.assertEqual([item["candidate_id"] for item in first], [
            "candidate-1",
            "candidate-2",
            "candidate-3",
        ])
        self.assertEqual((candidates, routed, records), baseline)
        self.assertEqual(
            set(first[0]),
            {"candidate_id", "gates", "passes_required_gates", "manual_fact_verification_required"},
        )
        first[0]["gates"]["citation"]["reason_codes"].append("mutated")
        self.assertNotEqual(first, workflow.evaluate_candidate_set_gates(
            candidates, brief=routed, evidence=records
        ))

    def test_set_rejects_duplicate_normalised_candidate_ids(self) -> None:
        candidates = [
            candidate(identifier="candidate-1"),
            candidate(identifier="Candidate-1"),
            candidate(identifier="candidate-3"),
        ]
        with self.assertRaisesRegex(workflow.WorkflowError, "distinct"):
            workflow.evaluate_candidate_set_gates(
                candidates, brief=brief(), evidence=[evidence()]
            )

    @patch("authority_os.workflow.subprocess.run", side_effect=AssertionError("model called"))
    def test_gate_evaluation_never_invokes_a_model(self, mocked_run: object) -> None:
        result = workflow.evaluate_candidate_gates(
            candidate(), brief=brief(), evidence=[evidence()]
        )
        self.assertTrue(result["passes_required_gates"])
        self.assertFalse(getattr(mocked_run, "called", False))


class ProofBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = ProofFixture(attestations=["I built the reliability-budget workflow."])
        self.proof = self.fixture.load()
        self.voice = {
            "provenance": "reconstructed-style-guidance",
            "voice": "Direct practitioner voice.",
        }

    def tearDown(self) -> None:
        self.fixture.close()

    def test_model_prompts_receive_only_public_proof_projection(self) -> None:
        one = candidate(
            text=f"{candidate()['text']} {self.proof.public_claim}",
            claim_ids=["source-1", self.proof.proof_id],
        )
        prompts = [
            workflow.build_writer_prompt(
                brief=brief("opportunity"),
                evidence=[evidence()],
                voice_guidance=self.voice,
                proof=self.proof,
            ),
            workflow.build_critic_prompt(
                [one],
                brief("opportunity"),
                [evidence()],
                voice_guidance=self.voice,
                proof=self.proof,
            ),
            workflow._build_writer_revision_prompt(
                candidate=one,
                scorecard={axis: 4 for axis in workflow.CRITIC_AXES},
                brief=brief("opportunity"),
                evidence=[evidence()],
                voice_guidance=self.voice,
                proof=self.proof,
            ),
        ]
        for prompt in prompts:
            with self.subTest(prompt=prompt[:40]):
                self.assertIn(self.proof.public_claim, prompt)
                self.assertIn("I built the reliability-budget workflow.", prompt)
                self.assertNotIn(str(self.fixture.root), prompt)
                self.assertNotIn(self.fixture.artifact.name, prompt)
                self.assertNotIn("SECRET-ARTIFACT-CONTENT", prompt)
                self.assertRegex(prompt, r"UNTRUSTED_PUBLIC_PROOF_DATA")

    def test_proof_id_is_additive_and_never_replaces_research_evidence(self) -> None:
        loaded = workflow.load_fixture()
        items = workflow.prepare_research_items(loaded["research_items"])
        analysis_items, _ = workflow.deduplicate_analysis_items(items, ())
        analysis = workflow.analyse_research(
            analysis_items,
            as_of=workflow.parse_published_at(str(loaded["as_of"])),
        )
        routed = workflow.build_strategy_brief(
            analysis["pass_2"]["selected"],
            strategy_inputs=loaded["strategy_inputs"],
            strategy_input_origin="synthetic-fixture",
            goal="opportunity",
        )
        records = workflow.build_drafting_evidence(
            items, topic_slug=str(routed["topic_slug"])
        )
        fixture_proof = workflow.load_proof_manifest(
            workflow.DEFAULT_FIXTURE_PROOF,
            fixture_mode=True,
        )
        candidates = deepcopy(loaded["draft_candidates"]["opportunity"])
        validated = workflow.validate_draft_candidates(
            candidates, brief=routed, evidence=records, proof=fixture_proof
        )
        self.assertIn(fixture_proof.proof_id, validated[0]["claim_ids"])
        proof_only = deepcopy(candidates)
        proof_only[0]["claim_ids"] = [fixture_proof.proof_id]
        with self.assertRaisesRegex(workflow.WorkflowError, "research evidence"):
            workflow.validate_draft_candidates(
                proof_only, brief=routed, evidence=records, proof=fixture_proof
            )


if __name__ == "__main__":
    unittest.main()
