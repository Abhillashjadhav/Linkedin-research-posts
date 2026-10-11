"""Thursday URL validation must preserve the source-body evidence identity."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_cli as base
from authority_os import daily_spine_cli as discovery
from authority_os import storage, thursday_capability as policy, workflow
from tests.test_discovery_resume import profile_payload
from tests.test_thursday_discovery import AS_OF, evidence, lead


class ThursdayEvidenceIdentityTests(unittest.TestCase):
    def setUp(self):
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        private_root = patch.object(workflow, "DEFAULT_PRIVATE_DATA", self.root)
        private_root.start()
        self.addCleanup(private_root.stop)
        self.source = self.root / "source"
        self.current = self.root / "current"
        self.database = self.root / "authority.sqlite"
        self.scope = discovery.evidence_scope_fingerprint([lead()])

    def _fresh_selected(self, suffix):
        facts = evidence(
            primary_url="https://example.com/releases/v1" + suffix,
            executable_url="https://github.com/example/capability" + suffix,
            demo_url="https://example.com/demo" + suffix,
            attention_url="https://example.com/attention" + suffix,
            attention_count=5, attention_metric="stars", attention_observed_at=AS_OF,
        )
        response = {
            "url": facts["primary_url"], "title": "Laptop runtime release",
            "body": "The release describes a working local runtime and a demonstration.",
            "source": "Builder", "author": "Builder", "published_at": "2026-10-07T12:00:00Z",
            "source_quality": "primary", "thursday_capability": facts,
            "lead_id": "lead-1", "lead_url": "https://example.com/launch",
        }
        with base.discovery_route(thursday=True), patch.object(base, "invoke_structured", return_value={"items": [response]}):
            prepared = discovery._invoke_signal_scout(None, 7, AS_OF, [lead()])
            selected, excluded = discovery.select_thursday_evidence(prepared, as_of=AS_OF, days=7)
        self.assertEqual(excluded, [])
        self.assertEqual(len(selected), 1)
        return facts, prepared[0], selected[0]

    def _write_snapshot(self, selected):
        # Each replacement is a test fixture; production output remains write-once.
        (self.source / discovery.EVIDENCE_CACHE_NAME).unlink(missing_ok=True)
        base.write_private_json(self.source / discovery.EVIDENCE_CACHE_NAME, {
            "schema_version": 1, "created_at": AS_OF,
            "scope_fingerprint": self.scope, "origin": "body-verified-private-web",
            "items": [selected], "publishing_status": "DISABLED",
        })

    def _checkpoint(self, selected):
        profile = profile_payload()
        profile_path = self.root / "profile.json"
        base.write_private_json(profile_path, profile)
        args = discovery.parser().parse_args([
            "--profile", str(profile_path), "--as-of", AS_OF, "--week-slot", "3",
            "--output-dir", str(self.current), "--db", str(self.database),
        ])
        fingerprint = discovery._run_input_fingerprint(args, profile, AS_OF)
        base.write_private_json(self.source / "run-input.json", {
            "schema_version": 1, "run_id": "thursday-identity-run", "as_of": AS_OF,
            "input_fingerprint": fingerprint, "contract_sha256": discovery._contract_sha256(),
            "implementation_sha256": discovery._implementation_sha256(),
        })
        base.write_private_json(self.source / "momentum.json", {
            "schema_version": 1, "created_at": AS_OF, "topic": None,
            "days": 7, "candidates": [lead()],
        })
        discovery._write_stage_checkpoint(self.source, "conversation_discovery", fingerprint)
        base.write_private_json(self.source / discovery.ADMITTED_SCOPE_NAME, {
            "schema_version": 1, "created_at": AS_OF, "topic": None, "days": 7,
            "route": "momentum-qualified", "candidates": [lead()],
            "scope_fingerprint": self.scope, "profile_sha256": discovery._mapping_sha256(profile),
        })
        discovery._write_stage_checkpoint(self.source, "topic_admission", fingerprint)
        storage.initialise(self.database)
        storage.insert_research_items(self.database, [selected], evidence_origin="private-import")
        self._write_snapshot(selected)
        discovery._write_stage_checkpoint(self.source, "evidence_verification", fingerprint)
        return args, profile

    def test_fresh_selection_keeps_raw_urls_bound_to_hashed_capsule(self):
        for suffix in ("/", "?utm_source=scout&utm_campaign=release"):
            with self.subTest(suffix=suffix):
                facts, prepared, selected = self._fresh_selected(suffix)
                self.assertEqual(selected["canonical_url"], "https://example.com/releases/v1")
                self.assertEqual(selected["thursday_capability"], facts)
                self.assertEqual(prepared["thursday_capability"], facts)
                self.assertEqual(policy.extract_evidence(selected["body"]), facts)
                self.assertEqual(selected["body"], prepared["body"])
                self.assertEqual(selected["content_hash"], prepared["content_hash"])
                restored = discovery._validate_body_verified_evidence([selected], days=7, as_of=AS_OF, require_stored_hash=True)
                self.assertEqual(restored[0]["thursday_capability"], facts)

    def test_selected_snapshot_is_reusable_without_new_scout_calls(self):
        for suffix in ("/", "?utm_source=scout"):
            with self.subTest(suffix=suffix):
                facts, _, selected = self._fresh_selected(suffix)
                self._write_snapshot(selected)
                with base.discovery_route(thursday=True), patch.object(base, "invoke_structured", side_effect=AssertionError("cache started a Scout")):
                    result = discovery.resolve_signal_evidence(None, 7, AS_OF, [lead()], folder=self.current, db_path=self.database)
                self.assertEqual(result.route, "verified-cache")
                self.assertEqual(result.attempts, 0)
                self.assertEqual(result.items[0]["thursday_capability"], facts)
                self.assertEqual(result.items[0]["content_hash"], selected["content_hash"])
                self.assertEqual(result.items[0]["fetched_at"], selected["fetched_at"])

    def test_stage_resume_restores_selected_raw_urls_and_original_identity(self):
        facts, _, selected = self._fresh_selected("/?utm_source=scout")
        args, profile = self._checkpoint(selected)
        resumed = discovery.load_stage_resume(self.source, args=args, profile=profile)
        self.assertIn("evidence_verification", resumed.completed_stages)
        self.assertEqual(resumed.evidence_items[0]["thursday_capability"], facts)
        self.assertEqual(resumed.evidence_items[0]["content_hash"], selected["content_hash"])
        self.assertEqual(resumed.evidence_items[0]["fetched_at"], selected["fetched_at"])

    def test_semantically_equivalent_metadata_tampering_still_fails_exact_capsule_check(self):
        _, _, selected = self._fresh_selected("/")
        changed = copy.deepcopy(selected)
        changed["thursday_capability"]["demo_url"] = "https://example.com/demo"
        with self.assertRaisesRegex(workflow.WorkflowError, "differs from its hashed"):
            discovery._validate_body_verified_evidence([changed], days=7, as_of=AS_OF, require_stored_hash=True)

    def test_changed_capsule_and_metadata_cannot_be_rehashed_during_reload(self):
        _, _, selected = self._fresh_selected("/")
        changed = copy.deepcopy(selected)
        changed["thursday_capability"]["demo_url"] = "https://example.com/other-demo"
        source_body = changed["body"].rsplit(policy.CAPSULE_MARKER, 1)[0]
        changed["body"] = source_body + policy.CAPSULE_MARKER + json.dumps({
            "policy_version": policy.POLICY_VERSION,
            "evidence": changed["thursday_capability"],
        }, sort_keys=True)
        with self.assertRaisesRegex(workflow.WorkflowError, "content hash no longer matches"):
            discovery._validate_body_verified_evidence([changed], days=7, as_of=AS_OF, require_stored_hash=True)
        self._write_snapshot(changed)
        with base.discovery_route(thursday=True):
            cached = discovery._cached_evidence_for_scope(scope_fingerprint=self.scope, days=7, as_of=AS_OF, current_folder=self.current, db_path=self.database)
        self.assertEqual(cached, [])

    def test_changed_checkpoint_evidence_cannot_be_rehashed_during_resume(self):
        _, _, selected = self._fresh_selected("/")
        args, profile = self._checkpoint(selected)
        selected["thursday_capability"]["demo_url"] = "https://example.com/other-demo"
        self._write_snapshot(selected)
        with self.assertRaisesRegex(workflow.WorkflowError, "output hash changed"):
            discovery.load_stage_resume(self.source, args=args, profile=profile)


if __name__ == "__main__":
    unittest.main()
