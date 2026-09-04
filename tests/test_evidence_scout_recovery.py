"""Bounded recovery tests for the live evidence Scout boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli, storage, workflow


AS_OF = "2026-09-04T12:00:00Z"


def admitted(topic: str = "Agent reliability boundaries") -> list[dict[str, object]]:
    return [
        {
            "topic": topic,
            "representative_urls": ["https://example.com/momentum"],
        }
    ]


def research_items(count: int = 3) -> list[dict[str, object]]:
    return [
        {
            "url": f"https://example.com/research-{index}",
            "title": f"Agent reliability evidence {index}",
            "body": f"A body-read primary source records decision {index}.",
            "source": "Research lab",
            "author": "Research lab",
            "published_at": "2026-09-01T00:00:00Z",
            "source_quality": "primary",
        }
        for index in range(1, count + 1)
    ]


class EvidenceScoutRecoveryTests(unittest.TestCase):
    def test_one_body_read_primary_source_is_sufficient(self) -> None:
        prepared = daily_spine_cli._validate_body_verified_evidence(
            research_items(1),
            days=7,
            as_of=AS_OF,
        )

        self.assertEqual(len(prepared), 1)

    def test_research_schema_allows_one_source(self) -> None:
        items = daily_spine_cli._schema("research")["properties"]["items"]
        self.assertEqual(items["minItems"], 1)
        self.assertEqual(items["maxItems"], 7)

    def test_targeted_scout_runs_once_without_repeating_discovery(self) -> None:
        expected = workflow.prepare_research_items(research_items())
        with patch.object(
            daily_spine_cli,
            "_invoke_signal_scout",
            return_value=expected,
        ) as invoke:
            result = daily_spine_cli.resolve_signal_evidence(
                None,
                7,
                AS_OF,
                admitted(),
                folder=workflow.DEFAULT_PRIVATE_DATA / "current",
                db_path=workflow.DEFAULT_DB,
            )

        self.assertEqual(result.route, "live-targeted")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(
            [call.kwargs["timeout"] for call in invoke.call_args_list],
            [daily_spine_cli.EVIDENCE_TIMEOUT_SECONDS],
        )
        self.assertEqual([call.kwargs["target_count"] for call in invoke.call_args_list], [3])

    def test_two_timeouts_use_only_an_exact_scope_verified_cache(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            previous = root / "2026-09-03" / "100000"
            current = root / "2026-09-04" / "120000"
            previous.mkdir(parents=True)
            current.mkdir(parents=True)
            candidates = admitted()
            prepared = workflow.prepare_research_items(
                research_items(), fetched_at="2026-09-03T10:00:00Z"
            )
            daily_spine_cli.base.write_private_json(
                previous / daily_spine_cli.EVIDENCE_CACHE_NAME,
                {
                    "schema_version": 1,
                    "created_at": "2026-09-03T10:00:00Z",
                    "scope_fingerprint": daily_spine_cli.evidence_scope_fingerprint(candidates),
                    "origin": "body-verified-private-web",
                    "items": prepared,
                },
            )
            with patch.object(daily_spine_cli.workflow, "DEFAULT_PRIVATE_DATA", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ) as scout:
                result = daily_spine_cli.resolve_signal_evidence(
                    None,
                    7,
                    AS_OF,
                    candidates,
                    folder=current,
                    db_path=root / "unused.sqlite",
                )

        self.assertEqual(result.route, "verified-cache")
        self.assertEqual(result.attempts, 0)
        self.assertEqual(len(result.items), 3)
        scout.assert_not_called()

    def test_exact_database_urls_are_reused_without_refreshing_provenance(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            database = root / "authority.sqlite"
            storage.initialise(database)
            fetched_at = "2026-09-02T08:00:00Z"
            prepared = workflow.prepare_research_items(
                research_items(), fetched_at=fetched_at
            )
            storage.insert_research_items(
                database, prepared, evidence_origin="private-import"
            )
            candidates = [
                {
                    "topic": "Agent reliability boundaries",
                    "representative_urls": [
                        item["canonical_url"] for item in prepared
                    ],
                }
            ]
            with patch.object(
                daily_spine_cli, "_invoke_signal_scout"
            ) as scout:
                result = daily_spine_cli.resolve_signal_evidence(
                    None,
                    7,
                    AS_OF,
                    candidates,
                    folder=root / "current",
                    db_path=database,
                )

        self.assertEqual(result.route, "verified-database")
        self.assertEqual(result.attempts, 0)
        self.assertEqual(
            {item["fetched_at"] for item in result.items}, {fetched_at}
        )
        scout.assert_not_called()

    def test_scope_mismatch_does_not_reuse_cached_bodies(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            previous = root / "2026-09-03" / "100000"
            current = root / "2026-09-04" / "120000"
            previous.mkdir(parents=True)
            current.mkdir(parents=True)
            daily_spine_cli.base.write_private_json(
                previous / daily_spine_cli.EVIDENCE_CACHE_NAME,
                {
                    "schema_version": 1,
                    "created_at": "2026-09-03T10:00:00Z",
                    "scope_fingerprint": daily_spine_cli.evidence_scope_fingerprint(
                        admitted("Different product topic")
                    ),
                    "origin": "body-verified-private-web",
                    "items": workflow.prepare_research_items(research_items()),
                },
            )
            with patch.object(daily_spine_cli.workflow, "DEFAULT_PRIVATE_DATA", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "Targeted Evidence Scout timed out"
                ):
                    daily_spine_cli.resolve_signal_evidence(
                        None,
                        7,
                        AS_OF,
                        admitted(),
                        folder=current,
                        db_path=root / "unused.sqlite",
                    )

    def test_explicit_requested_topic_is_part_of_the_cache_scope(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            previous = root / "2026-09-03" / "100000"
            current = root / "2026-09-04" / "120000"
            previous.mkdir(parents=True)
            current.mkdir(parents=True)
            candidates = admitted()
            daily_spine_cli.base.write_private_json(
                previous / daily_spine_cli.EVIDENCE_CACHE_NAME,
                {
                    "schema_version": 1,
                    "created_at": "2026-09-03T10:00:00Z",
                    "scope_fingerprint": daily_spine_cli.evidence_scope_fingerprint(
                        candidates,
                        requested_topic="Topic A",
                    ),
                    "origin": "body-verified-private-web",
                    "items": workflow.prepare_research_items(research_items()),
                },
            )
            with patch.object(daily_spine_cli.workflow, "DEFAULT_PRIVATE_DATA", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "Targeted Evidence Scout timed out"
                ):
                    daily_spine_cli.resolve_signal_evidence(
                        "Topic B",
                        7,
                        AS_OF,
                        candidates,
                        folder=current,
                        db_path=root / "unused.sqlite",
                    )

    def test_cache_body_drift_cannot_be_hidden_by_hash_recomputation(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            previous = root / "2026-09-03" / "100000"
            current = root / "2026-09-04" / "120000"
            previous.mkdir(parents=True)
            current.mkdir(parents=True)
            candidates = admitted()
            prepared = workflow.prepare_research_items(research_items())
            prepared[0]["body"] = "The cached body was altered after verification."
            daily_spine_cli.base.write_private_json(
                previous / daily_spine_cli.EVIDENCE_CACHE_NAME,
                {
                    "schema_version": 1,
                    "created_at": "2026-09-03T10:00:00Z",
                    "scope_fingerprint": daily_spine_cli.evidence_scope_fingerprint(candidates),
                    "origin": "body-verified-private-web",
                    "items": prepared,
                },
            )
            with patch.object(daily_spine_cli.workflow, "DEFAULT_PRIVATE_DATA", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "Targeted Evidence Scout timed out"
                ):
                    daily_spine_cli.resolve_signal_evidence(
                        None,
                        7,
                        AS_OF,
                        candidates,
                        folder=current,
                        db_path=root / "unused.sqlite",
                    )

    def test_body_and_requested_window_are_deterministic_requirements(self) -> None:
        blank = research_items()
        blank[0]["body"] = ""
        with self.assertRaisesRegex(workflow.WorkflowError, "non-blank source body"):
            daily_spine_cli._validate_body_verified_evidence(blank, days=7, as_of=AS_OF)

        expired = research_items()
        expired[0]["published_at"] = "2026-08-01T00:00:00Z"
        with self.assertRaisesRegex(workflow.WorkflowError, "outside the requested time window"):
            daily_spine_cli._validate_body_verified_evidence(expired, days=7, as_of=AS_OF)

    def test_month_only_publication_is_accepted_when_month_overlaps_window(self) -> None:
        items = research_items()
        for item in items:
            item["published_at"] = "2026-09"

        prepared = daily_spine_cli._validate_body_verified_evidence(
            items, days=7, as_of=AS_OF
        )

        self.assertTrue(all(item["publication_date_uncertain"] for item in prepared))
        self.assertEqual(
            {item["publication_date_precision"] for item in prepared}, {"month"}
        )

    def test_month_only_publication_is_rejected_when_month_misses_window(self) -> None:
        items = research_items()
        items[0]["published_at"] = "2026-07"
        with self.assertRaisesRegex(
            workflow.WorkflowError, "outside the requested time window"
        ):
            daily_spine_cli._validate_body_verified_evidence(
                items, days=7, as_of=AS_OF
            )


if __name__ == "__main__":
    unittest.main()
