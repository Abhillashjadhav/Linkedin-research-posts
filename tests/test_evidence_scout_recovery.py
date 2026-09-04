"""Bounded recovery tests for the live evidence Scout boundary."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli, workflow


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
    def test_primary_timeout_retries_inside_one_120_second_budget(self) -> None:
        expected = workflow.prepare_research_items(research_items())
        with patch.object(
            daily_spine_cli,
            "_invoke_signal_scout",
            side_effect=[workflow.WorkflowError("Evidence Scout primary timed out."), expected],
        ) as invoke:
            result = daily_spine_cli.resolve_signal_evidence(
                None,
                7,
                AS_OF,
                admitted(),
                folder=workflow.DEFAULT_PRIVATE_DATA / "current",
                db_path=workflow.DEFAULT_DB,
            )

        self.assertEqual(result.route, "live-retry")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(
            [call.kwargs["timeout"] for call in invoke.call_args_list],
            [
                daily_spine_cli.EVIDENCE_PRIMARY_TIMEOUT_SECONDS,
                daily_spine_cli.EVIDENCE_RETRY_TIMEOUT_SECONDS,
            ],
        )
        self.assertEqual([call.kwargs["target_count"] for call in invoke.call_args_list], [5, 3])

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
            with patch.object(daily_spine_cli.base, "OUTPUT_ROOT", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                result = daily_spine_cli.resolve_signal_evidence(
                    None,
                    7,
                    AS_OF,
                    candidates,
                    folder=current,
                    db_path=root / "unused.sqlite",
                )

        self.assertEqual(result.route, "verified-cache")
        self.assertEqual(len(result.items), 3)

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
            with patch.object(daily_spine_cli.base, "OUTPUT_ROOT", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "no exact-scope body-verified evidence"
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
            with patch.object(daily_spine_cli.base, "OUTPUT_ROOT", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "no exact-scope body-verified evidence"
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
            with patch.object(daily_spine_cli.base, "OUTPUT_ROOT", root), patch.object(
                daily_spine_cli,
                "_invoke_signal_scout",
                side_effect=workflow.WorkflowError("Evidence Scout timed out."),
            ):
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "no exact-scope body-verified evidence"
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


if __name__ == "__main__":
    unittest.main()
