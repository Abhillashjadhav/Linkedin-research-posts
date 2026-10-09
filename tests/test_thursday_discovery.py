"""Offline contracts for Thursday discovery and evidence-to-draft continuity."""
from __future__ import annotations

import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_cli as base
from authority_os import daily_spine_cli as discovery
from authority_os import individual_launch_runtime_tuning as launch
from authority_os import momentum_surface_parallel as surface
from authority_os import thursday_capability as policy
from authority_os import workflow

AS_OF = "2026-10-08T12:00:00Z"


def evidence(**changes):
    record = {
        "kind": "EXECUTABLE_CAPABILITY", "creator": "Independent builder",
        "capability": "Run a language model on an ordinary laptop.",
        "reader_benefit": "Try the task locally without a hosted model call.",
        "mechanism": "The demo loads only the parts needed for the next operation.",
        "original_release_date": "2026-10-07T12:00:00Z",
        "substantive_change_date": None, "change_kind": "RELEASE",
        "change_evidence": "The release body names the newly supported laptop runtime.",
        "primary_url": "https://example.com/releases/v1",
        "executable_url": "https://github.com/example/capability",
        "demo_url": "https://example.com/demo",
        "conditions": "Source reports 16 GB RAM; no independent benchmark available.",
        "demo_observation": "The source video shows a local prompt and completed answer.",
        "result_provenance": "SOURCE_REPORTED",
        "limitation": "Latency and correctness have not been independently compared.",
        "attention_url": None, "attention_observed_at": None,
        "attention_metric": None, "attention_count": None,
        "attention_evidence": "No count was observable; popularity is unknown.",
    }
    record.update(changes)
    return record


def item(**changes):
    payload = {
        "url": "https://example.com/releases/v1", "title": "Laptop runtime release",
        "body": "The release describes a working local runtime and a demonstration.",
        "source": "Builder", "author": "Builder", "published_at": "2026-10-07T12:00:00Z",
        "source_quality": "primary", "thursday_capability": evidence(),
    }
    payload.update(changes)
    prepared = workflow.prepare_research_items([payload])[0]
    prepared["thursday_capability"] = payload["thursday_capability"]
    return prepared


def lead(policy_marker=True):
    value = {"topic": "A working laptop capability", "why_now": "New release", "total": 20,
             "authority_fit": {"total": 20}, "representative_urls": ["https://example.com/launch"]}
    if policy_marker:
        value["discovery_policy"] = policy.POLICY_VERSION
    return value


class ThursdayRouteTests(unittest.TestCase):
    def test_explicit_slot_wins_over_local_weekday(self):
        self.assertTrue(discovery.discovery_is_thursday(as_of=AS_OF, week_slot=None))
        self.assertFalse(discovery.discovery_is_thursday(as_of=AS_OF, week_slot=2))
        self.assertTrue(discovery.discovery_is_thursday(as_of="2026-10-09T12:00:00Z", week_slot=3))
        self.assertTrue(discovery.discovery_is_thursday(as_of="2026-10-07T20:00:00Z", week_slot=None))
        self.assertFalse(discovery.discovery_is_thursday(as_of="2026-10-08T20:00:00Z", week_slot=None))

    def test_route_context_is_bounded_even_on_failed_command(self):
        def fail(_):
            base._THURSDAY_DISCOVERY.set(True)
            raise workflow.WorkflowError("offline stop")
        from authority_os import daily_discovery_cli
        with patch.object(discovery, "_command", side_effect=fail):
            with self.assertRaisesRegex(workflow.WorkflowError, "offline stop"):
                daily_discovery_cli._ORIGINAL_COMMAND(object())
        self.assertFalse(base.thursday_discovery_active())

    def test_builder_source_lanes_only_change_thursday(self):
        baseline = surface.discovery_surfaces()
        with base.discovery_route(thursday=True):
            labels = " ".join(str(row["label"]) for row in surface.discovery_surfaces())
            self.assertIn("GitHub trending + releases", labels)
            self.assertIn("Hugging Face", labels)
            self.assertEqual(len(surface.discovery_surfaces()), len(baseline))
        self.assertIs(surface.discovery_surfaces(), surface.SURFACES)

    def test_installed_surface_and_consolidation_paths_receive_policy(self):
        # Import the real composition root so tests catch later runtime overrides.
        from authority_os import daily_discovery_cli  # noqa: F401
        response = {"status": "NO_SIGNAL", "signals": [], "caveat": "No visible signal."}
        with base.discovery_route(thursday=True), patch.object(surface, "invoke_structured", return_value=response) as invoke, patch.object(surface, "_write_surface_file"), patch.object(surface, "_trace_event"):
            surface._run_surface(surface.discovery_surfaces()[0], topic=None, days=7, as_of=AS_OF)
            task = invoke.call_args.kwargs["task_prompt"]
            self.assertIn("48-hour", task)
            self.assertIn(policy.POLICY_VERSION, task)
            self.assertIn("GitHub trending + releases", task)
        for active in (False, True):
            with base.discovery_route(thursday=active), patch.object(surface, "invoke_structured", return_value={"clusters": []}) as invoke, patch.object(surface, "_validate_clusters", return_value=[]):
                surface._consolidate([{"id": "test-1"}], as_of=AS_OF)
                self.assertEqual(policy.POLICY_VERSION in invoke.call_args.kwargs["task_prompt"], active)

    def test_old_inventory_cannot_override_thursday_route(self):
        incident = {"topic": "Outage with very high attention", "total": 25, "authority_fit": {"total": 25}, "representative_urls": ["https://example.com/incident"]}
        with base.discovery_route(thursday=True):
            selected, _ = discovery.select_topic_scope([incident, lead()])
        self.assertEqual([row["topic"] for row in selected], [lead()["topic"]])
        selected, _ = discovery.select_topic_scope([incident, lead()])
        self.assertEqual(selected[0]["topic"], incident["topic"])

    def test_evidence_scope_fingerprint_distinguishes_route(self):
        self.assertNotEqual(discovery.evidence_scope_fingerprint([lead()]), discovery.evidence_scope_fingerprint([lead(False)]))

    def test_parallel_evidence_workers_receive_bounded_route(self):
        observed = []
        def verify(*args, **kwargs):
            observed.append(base.thursday_discovery_active())
            return [item()]
        with base.discovery_route(thursday=True), patch.object(discovery, "_invoke_signal_scout", side_effect=verify):
            result = discovery._resolve_parallel_evidence(None, 7, AS_OF, [lead(), lead()], [], "scope")
        self.assertEqual(observed, [True, True])
        self.assertEqual(len(result.items), 1)
        self.assertFalse(base.thursday_discovery_active())

    def test_selector_guidance_does_not_spill_into_other_days(self):
        baseline = launch._augment_task("Select supplied evidence.")
        with base.discovery_route(thursday=True):
            task = launch._augment_task("Select supplied evidence.")
            self.assertIn("THURSDAY SELECTION", task)
            self.assertIn(policy.POLICY_VERSION, task)
        self.assertEqual(baseline, launch._augment_task("Select supplied evidence."))


class ThursdayEvidenceTests(unittest.TestCase):
    def test_valid_current_capability_and_unknown_attention_are_retained(self):
        selected, excluded = discovery.select_thursday_evidence([item()], as_of=AS_OF, days=7)
        self.assertEqual(len(selected), 1)
        self.assertEqual(excluded, [])
        self.assertIsNone(selected[0]["thursday_capability"]["attention_count"])

    def test_incidents_resources_missing_demo_and_activity_only_fail(self):
        bad = [
            evidence(kind="INCIDENT"), evidence(kind="SKILL_LIST"), evidence(kind="PROMPT_PACK"),
            evidence(demo_url=None), evidence(original_release_date="2026-09-01T00:00:00Z", attention_url="https://example.com/trending", attention_count=500, attention_metric="stars", attention_observed_at=AS_OF),
            evidence(original_release_date=None), evidence(original_release_date="2026-10"),
            evidence(original_release_date="2026-10-09T12:00:00Z"),
            evidence(primary_url="https://example.com/different-primary"),
            evidence(attention_count=5),
        ]
        for metadata in bad:
            with self.subTest(metadata=metadata):
                selected, rejected = discovery.select_thursday_evidence([item(thursday_capability=metadata)], as_of=AS_OF, days=30)
                self.assertEqual(selected, [])
                self.assertEqual(len(rejected), 1)

    def test_old_project_with_real_recent_update_is_eligible(self):
        selected, _ = discovery.select_thursday_evidence([item(thursday_capability=evidence(original_release_date="2025-01-01", substantive_change_date="2026-10-07", change_kind="SUBSTANTIVE_UPDATE"))], as_of=AS_OF, days=7)
        self.assertEqual(len(selected), 1)

    def test_evidence_capsule_survives_source_normalisation_and_selected_projection(self):
        model_item = item()
        response = {key: value for key, value in model_item.items() if key in {"title", "body", "source", "author", "published_at", "source_quality", "thursday_capability"}}
        response.update(url=model_item["canonical_url"], lead_id="lead-1", lead_url="https://example.com/launch")
        with base.discovery_route(thursday=True), patch.object(base, "invoke_structured", return_value={"items": [response]}) as invoke:
            prepared = discovery._invoke_signal_scout(None, 7, AS_OF, [lead()])
        self.assertIn("thursday_capability", invoke.call_args.kwargs["schema"]["properties"]["items"]["items"]["required"])
        self.assertNotIn("already included a freshest-48-hour pass", invoke.call_args.kwargs["task_prompt"])
        stored_shape = workflow.prepare_research_items(prepared)
        self.assertEqual(stored_shape[0]["content_hash"], prepared[0]["content_hash"])
        restored = discovery._validate_body_verified_evidence(stored_shape, days=7, as_of=AS_OF, require_stored_hash=True)
        projected = base.project_signals(restored)
        self.assertEqual(projected[0]["thursday_capability"]["demo_url"], evidence()["demo_url"])
        self.assertEqual(policy.extract_evidence(stored_shape[0]["body"]), evidence())

    def test_non_thursday_evidence_call_keeps_existing_schema(self):
        original = item()
        response = {key: original[key] for key in ("title", "body", "source", "author", "published_at", "source_quality")}
        response.update(url=original["canonical_url"], lead_id="lead-1", lead_url="https://example.com/launch")
        with patch.object(base, "invoke_structured", return_value={"items": [response]}) as invoke:
            prepared = discovery._invoke_signal_scout(None, 7, AS_OF, [lead(False)])
        self.assertNotIn("thursday_capability", invoke.call_args.kwargs["schema"]["properties"]["items"]["items"]["properties"])
        self.assertNotIn(policy.CAPSULE_MARKER, prepared[0]["body"])

    def test_metadata_cannot_substitute_for_real_source_body_or_disagree_with_capsule(self):
        capsule = policy.CAPSULE_MARKER + json.dumps({"policy_version": policy.POLICY_VERSION, "evidence": evidence()})
        with self.assertRaisesRegex(workflow.WorkflowError, "non-blank source body"):
            discovery._validate_body_verified_evidence([item(body=capsule)], days=7, as_of=AS_OF)
        changed = item(body="Real source body." + capsule, thursday_capability=evidence(demo_url="https://example.com/altered"))
        with self.assertRaisesRegex(workflow.WorkflowError, "differs from its hashed"):
            discovery._validate_body_verified_evidence([changed], days=7, as_of=AS_OF)
        model_item = {"url": "https://example.com/releases/v1", "title": "Release", "body": " ", "source": "Builder", "author": "Builder", "published_at": "2026-10-07", "source_quality": "primary", "lead_id": "lead-1", "lead_url": "https://example.com/launch", "thursday_capability": evidence()}
        with base.discovery_route(thursday=True), patch.object(base, "invoke_structured", return_value={"items": [model_item]}), self.assertRaisesRegex(workflow.WorkflowError, "before adding"):
            discovery._invoke_signal_scout(None, 7, AS_OF, [lead()])

    def test_capsule_schema_rejects_untrusted_private_urls_and_bad_counts(self):
        for url in ("https://localhost/demo", "https://127.0.0.1/demo", "https://127.1/demo", "https://user:pw@example.com/demo"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                policy.validate_evidence(evidence(demo_url=url))
        for count in (True, -1, float("nan")):
            with self.subTest(count=count), self.assertRaises(ValueError):
                policy.validate_evidence(evidence(attention_count=count))
        self.assertIsNone(policy.extract_evidence(policy.CAPSULE_MARKER + "{}"))

    def test_prepolicy_database_record_triggers_new_verification_on_thursday(self):
        old = item()
        old.pop("thursday_capability")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "ledger.sqlite3"
            database.touch()
            candidates = [{"representative_urls": [old["canonical_url"]]}]
            with patch.object(discovery.storage, "list_research_items_by_urls", return_value=[old]), base.discovery_route(thursday=True):
                result = discovery._database_evidence_for_scope(admitted_candidates=candidates, days=7, as_of=AS_OF, db_path=database)
            self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
