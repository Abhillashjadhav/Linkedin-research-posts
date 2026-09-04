"""Resume discovery at the first failed evidence boundary."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from authority_os import daily_spine_cli, workflow


AS_OF = "2026-09-04T12:00:00Z"


def profile_payload() -> dict[str, object]:
    return {
        "target_audience": "Senior AI product leaders",
        "authority_goal": "Practical production judgment",
        "proof_inventory": [
            {
                "id": "proof-repo",
                "label": "Public repository",
                "public_safe_claim": "A public repository demonstrates the workflow.",
                "evidence_type": "repository",
            }
        ],
        "avoid_topics": [],
        "recent_theses": [],
    }


def candidate() -> dict[str, object]:
    return {
        "id": "topic-1",
        "topic": "Agent reliability boundaries",
        "why_now": "A current release makes the boundary consequential.",
        "total": 20,
        "observed_axes": 5,
        "momentum_eligible": True,
        "representative_urls": ["https://example.com/momentum"],
        "authority_fit": {"total": 22},
    }


def source_artifacts(folder: Path, profile: dict[str, object]) -> None:
    folder.mkdir(parents=True)
    dashboard = daily_spine_cli.new_run_dashboard("source-run")
    for check in dashboard["checks"]:  # type: ignore[index]
        if check["stage"] in {"conversation_discovery", "topic_admission"}:
            check["status"] = "PASS"
        elif check["stage"] == "evidence_verification":
            check["status"] = "FAIL"
    admission = next(
        check
        for check in dashboard["checks"]  # type: ignore[index]
        if check["stage"] == "topic_admission"
    )
    admission["details"] = {
        "route": "momentum-qualified",
        "admitted_topics": [candidate()["topic"]],
    }
    daily_spine_cli.base.write_private_json(folder / "run-dashboard.json", dashboard)
    daily_spine_cli.base.write_private_json(
        folder / "momentum.json",
        {
            "schema_version": 1,
            "created_at": AS_OF,
            "topic": None,
            "days": 7,
            "candidates": [candidate()],
        },
    )
    daily_spine_cli.base.write_private_json(
        folder / daily_spine_cli.ADMITTED_SCOPE_NAME,
        {
            "schema_version": 1,
            "created_at": AS_OF,
            "topic": None,
            "days": 7,
            "route": "momentum-qualified",
            "candidates": [candidate()],
            "profile_sha256": daily_spine_cli._mapping_sha256(profile),
            "scope_fingerprint": daily_spine_cli.evidence_scope_fingerprint(
                [candidate()]
            ),
        },
    )


class DiscoveryResumeTests(unittest.TestCase):
    def test_loader_restores_immutable_admitted_scope(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            source = Path(temporary) / "source"
            profile = profile_payload()
            source_artifacts(source, profile)

            resumed = daily_spine_cli.load_discovery_resume(
                source,
                days=7,
                requested_topic=None,
                profile=profile,
            )

        self.assertEqual(resumed.as_of, AS_OF)
        self.assertEqual(resumed.route, "momentum-qualified")
        self.assertEqual(list(resumed.eligible), [candidate()])

    def test_resume_skips_every_completed_discovery_call(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "resumed"
            profile_data = profile_payload()
            source_artifacts(source, profile_data)
            profile = root / "profile.json"
            profile.write_text(json.dumps(profile_data), encoding="utf-8")

            with (
                patch.object(
                    daily_spine_cli.momentum,
                    "invoke_scout",
                    side_effect=AssertionError("discovery ran during resume"),
                ) as scout,
                patch.object(
                    daily_spine_cli,
                    "update_candidate_inventory",
                    side_effect=AssertionError("inventory changed during resume"),
                ) as inventory,
                patch.object(
                    daily_spine_cli,
                    "select_topic_scope",
                    side_effect=AssertionError("topic admission repeated during resume"),
                ) as admission,
                patch.object(
                    daily_spine_cli,
                    "resolve_signal_evidence",
                    side_effect=workflow.WorkflowError("checkpoint at evidence"),
                ),
                patch.object(
                    daily_spine_cli.eval_dashboard_html,
                    "open_dashboard",
                    return_value=False,
                ),
            ):
                result = daily_spine_cli.main(
                    [
                        "--profile",
                        str(profile),
                        "--days",
                        "7",
                        "--output-dir",
                        str(output),
                        "--db",
                        str(root / "authority.sqlite"),
                        "--resume-from",
                        str(source),
                        "--allow-web-research",
                        "--allow-model-egress",
                    ]
                )

            dashboard = json.loads((output / "run-dashboard.json").read_text())

        self.assertEqual(result, 2)
        scout.assert_not_called()
        inventory.assert_not_called()
        admission.assert_not_called()
        checks = {item["stage"]: item for item in dashboard["checks"]}
        self.assertEqual(checks["conversation_discovery"]["status"], "PASS")
        self.assertEqual(checks["topic_admission"]["status"], "PASS")
        self.assertEqual(checks["evidence_verification"]["status"], "FAIL")
        self.assertEqual(checks["topic_value"]["status"], "NOT_EVALUATED")

    def test_resume_rejects_changed_profile(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            source = Path(temporary) / "source"
            profile = profile_payload()
            source_artifacts(source, profile)
            profile["authority_goal"] = "A different goal"

            with self.assertRaisesRegex(workflow.WorkflowError, "profile has changed"):
                daily_spine_cli.load_discovery_resume(
                    source,
                    days=7,
                    requested_topic=None,
                    profile=profile,
                )

    def test_legacy_rolling_resume_requires_same_run_inventory(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            source = root / "source"
            profile = profile_payload()
            source_artifacts(source, profile)
            (source / daily_spine_cli.ADMITTED_SCOPE_NAME).unlink()
            dashboard = json.loads((source / "run-dashboard.json").read_text())
            admission = next(
                item
                for item in dashboard["checks"]
                if item["stage"] == "topic_admission"
            )
            admission["details"]["route"] = "rolling seven-day inventory"
            (source / "run-dashboard.json").write_text(
                json.dumps(dashboard), encoding="utf-8"
            )
            inventory = root / "candidate-inventory.json"
            daily_spine_cli.base.write_private_json(
                inventory,
                {
                    "schema_version": 1,
                    "updated_at": AS_OF,
                    "window_days": 7,
                    "candidates": [candidate()],
                },
            )

            with patch.object(daily_spine_cli, "CANDIDATE_INVENTORY", inventory):
                resumed = daily_spine_cli.load_discovery_resume(
                    source,
                    days=7,
                    requested_topic=None,
                    profile=profile,
                )
                payload = json.loads(inventory.read_text())
                payload["updated_at"] = "2026-09-04T12:01:00Z"
                inventory.write_text(json.dumps(payload), encoding="utf-8")
                with self.assertRaisesRegex(
                    workflow.WorkflowError, "no longer matches"
                ):
                    daily_spine_cli.load_discovery_resume(
                        source,
                        days=7,
                        requested_topic=None,
                        profile=profile,
                    )

        self.assertEqual(list(resumed.eligible), [candidate()])

    def test_resume_rejects_symlinked_admitted_scope(self) -> None:
        workflow.DEFAULT_PRIVATE_DATA.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=workflow.DEFAULT_PRIVATE_DATA) as temporary:
            root = Path(temporary)
            source = root / "source"
            profile = profile_payload()
            source_artifacts(source, profile)
            scope = source / daily_spine_cli.ADMITTED_SCOPE_NAME
            copied = root / "copied-scope.json"
            copied.write_bytes(scope.read_bytes())
            scope.unlink()
            scope.symlink_to(copied)

            with self.assertRaisesRegex(workflow.WorkflowError, "must not be a symlink"):
                daily_spine_cli.load_discovery_resume(
                    source,
                    days=7,
                    requested_topic=None,
                    profile=profile,
                )


if __name__ == "__main__":
    unittest.main()
