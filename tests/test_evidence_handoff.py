"""Stable evidence identity handoff from thesis selection into drafting."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from authority_os import daily_cli, storage, workflow


class EvidenceManifestHandoffTests(unittest.TestCase):
    def test_generated_manifest_round_trips_three_and_seven_sources(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            for count in (3, 7):
                with self.subTest(source_count=count):
                    path = Path(temporary) / f"evidence-{count}.json"
                    signals = [
                        {
                            "id": f"signal-{index}",
                            "canonical_url": f"https://example.com/source-{index}",
                        }
                        for index in range(1, count + 1)
                    ]
                    card = {
                        "id": "thesis-1",
                        "topic": "Corroborated research evidence",
                        "signal_ids": [signal["id"] for signal in signals],
                    }
                    manifest = daily_cli.evidence_manifest_for(card, signals, signals)
                    daily_cli.write_private_json(path, manifest)

                    loaded = workflow.load_evidence_manifest_file(path)

                    self.assertEqual(loaded, manifest)
                    self.assertEqual(len(loaded["source_urls"]), count)

    def test_legacy_manifest_retains_the_same_source_budget(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            path = Path(temporary) / "evidence.json"
            for count in (3, 7):
                with self.subTest(source_count=count):
                    identities = [
                        {
                            "signal_id": f"signal-{index}",
                            "canonical_url": f"https://example.com/source-{index}",
                            "content_hash": f"{index:064x}",
                        }
                        for index in range(1, count + 1)
                    ]
                    path.write_text(
                        json.dumps({
                            "schema_version": 1,
                            "thesis_id": "thesis-1",
                            "display_topic": "Corroborated research evidence",
                            "evidence": identities,
                        }),
                        encoding="utf-8",
                    )

                    loaded = workflow.load_evidence_manifest_file(path)

                    self.assertEqual(loaded["schema_version"], 2)
                    self.assertEqual(
                        loaded["source_urls"],
                        [item["canonical_url"] for item in identities],
                    )

    def test_manifest_rejects_zero_and_eight_sources(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            path = Path(temporary) / "evidence.json"
            for version in (1, 2):
                for count in (0, 8):
                    with self.subTest(schema_version=version, source_count=count):
                        sources = [
                            f"https://example.com/source-{index}"
                            for index in range(1, count + 1)
                        ]
                        payload = {
                            "schema_version": version,
                            "thesis_id": "thesis-1",
                            "display_topic": "Corroborated research evidence",
                        }
                        if version == 1:
                            payload["evidence"] = [
                                {
                                    "signal_id": f"signal-{index}",
                                    "canonical_url": source,
                                    "content_hash": f"{index:064x}",
                                }
                                for index, source in enumerate(sources, start=1)
                            ]
                        else:
                            payload["source_urls"] = sources
                        path.write_text(json.dumps(payload), encoding="utf-8")

                        with self.assertRaisesRegex(
                            workflow.WorkflowError, "Evidence manifest must contain"
                        ):
                            workflow.load_evidence_manifest_file(path)


class EvidenceIdentityStorageTests(unittest.TestCase):
    def test_exact_lookup_preserves_manifest_order_and_rejects_hash_drift(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            dir=workflow.DEFAULT_PRIVATE_DATA
        ) as temporary:
            database = Path(temporary) / "authority.sqlite"
            storage.initialise(database)
            items = workflow.prepare_research_items(
                [
                    {
                        "url": "https://example.com/retry-boundary",
                        "title": "Retry budgets stop runaway agent loops",
                        "body": "A bounded retry checkpoint stops queue saturation.",
                        "source": "Runtime engineering",
                        "published_at": "2026-09-01T00:00:00Z",
                        "source_quality": "primary",
                    },
                    {
                        "url": "https://example.org/payment-approval",
                        "title": "Payment agents require human approval",
                        "body": "A human authorization boundary is required before funds move.",
                        "source": "Payments engineering",
                        "published_at": "2026-09-02T00:00:00Z",
                        "source_quality": "primary",
                    },
                ]
            )
            storage.insert_research_items(
                database,
                items,
                evidence_origin="private-import",
            )
            reversed_identities = [
                {
                    "canonical_url": item["canonical_url"],
                    "content_hash": item["content_hash"],
                }
                for item in reversed(items)
            ]
            selected = storage.list_research_items_by_identity(
                database,
                reversed_identities,
            )
            changed = storage.list_research_items_by_identity(
                database,
                [
                    {
                        "canonical_url": items[0]["canonical_url"],
                        "content_hash": "f" * 64,
                    }
                ],
            )
        self.assertEqual(
            [item["canonical_url"] for item in selected],
            [item["canonical_url"] for item in reversed(items)],
        )
        self.assertEqual(changed, [])


if __name__ == "__main__":
    unittest.main()
