"""Stable evidence identity handoff from thesis selection into drafting."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from authority_os import storage, workflow


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
