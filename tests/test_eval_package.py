"""Focused tests for frozen-package evaluation-only execution."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from authority_os import __main__ as cli
from authority_os import acceptance_policy, eval_package, workflow


def _candidate(index: int) -> dict[str, object]:
    return {
        "id": f"candidate-{index}",
        "angle": f"Angle {index}",
        "text": f"A direct human opening for candidate {index}.\n\nThe consequence is clear.",
        "claim_ids": ["source-1"],
    }


def _gate(candidate_id: str) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        "gates": {
            name: {
                "status": "NOT_REQUIRED" if name == "proof" else "PASS",
                "reason_codes": ["test-pass"],
            }
            for name in workflow.GATE_ORDER
        },
        "passes_required_gates": True,
        "manual_fact_verification_required": True,
    }


class EvalPackageTests(unittest.TestCase):
    def test_parser_exposes_required_eval_only_inputs(self) -> None:
        args = cli.build_parser().parse_args(
            [
                "eval-package",
                "--package",
                "outputs/2026-09-04/topic",
                "--strategy-input",
                "strategy.json",
                "--evidence-manifest",
                "data/private/evidence.json",
                "--db",
                "data/private/authority.sqlite",
                "--allow-model-egress",
            ]
        )

        self.assertEqual(args.command, "eval-package")
        self.assertIsNone(args.candidate)
        self.assertTrue(args.allow_model_egress)

    def test_command_calls_critic_once_and_never_calls_writer_or_revision(self) -> None:
        candidates = [_candidate(index) for index in range(1, 4)]
        brief = {
            "goal": "authority",
            "topic_slug": "topic",
            "goal_purpose": "purpose",
            "narrative_route": ["incident", "decision"],
            "target_reader": "product leaders",
            "reader_problem": "unclear ownership",
            "core_hypothesis": "ownership changes reliability",
            "product_decision": "name the owner",
            "authority_statement": "clear ownership matters",
            "strategy_input_origin": "explicit-input",
            "analysis": {
                "why_now": "now",
                "dominant_take": "common take",
                "missing_angle": "missing decision",
            },
        }
        evidence = [
            {
                "id": "source-1",
                "title": "Source",
                "claim": "Grounded claim",
                "source": "https://example.com/source",
                "source_quality": "primary",
                "body_read": True,
            }
        ]
        raw_scores = [
            {
                "candidate_id": candidate["id"],
                **{axis: 5 for axis in workflow.CRITIC_AXES},
            }
            for candidate in candidates
        ]
        context = {
            "package_path": workflow.REPO_ROOT / "outputs" / "2026-09-04" / "topic",
            "manifest": {"package_id": "2026-09-04-topic"},
            "brief": brief,
            "evidence": evidence,
            "proof": None,
            "all_candidates": candidates,
            "selected_candidates": candidates,
        }
        captured: dict[str, object] = {}

        def persist(**kwargs: object) -> tuple[Path, Path, Path, bool]:
            captured.update(kwargs)
            return (
                workflow.REPO_ROOT / "eval.json",
                workflow.REPO_ROOT / "run.json",
                workflow.REPO_ROOT / "eval.html",
                False,
            )

        args = SimpleNamespace(allow_model_egress=True)
        with (
            patch.object(eval_package, "_load_context", return_value=context),
            patch.object(
                eval_package,
                "_rubric_identity",
                return_value={"path": "config/current.json", "rubric_id": "current", "sha256": "a" * 64},
            ),
            patch.object(workflow, "invoke_critic", return_value=raw_scores) as critic,
            patch.object(
                workflow,
                "evaluate_candidate_set_gates",
                return_value=[_gate(str(candidate["id"])) for candidate in candidates],
            ),
            patch.object(workflow, "invoke_writer", side_effect=AssertionError("Writer called")),
            patch.object(
                workflow,
                "invoke_writer_revision",
                side_effect=AssertionError("Writer revision called"),
            ),
            patch.object(
                workflow,
                "run_critic_review",
                side_effect=AssertionError("revision review called"),
            ),
        ):
            self.assertEqual(eval_package.command(args, persist=persist), 0)

        critic.assert_called_once()
        self.assertEqual(critic.call_args.args[0], candidates)
        results = captured["results"]
        self.assertIsInstance(results, list)
        self.assertTrue(all(item["acceptance"]["status"] == "PASS" for item in results))
        self.assertEqual(
            results[0]["acceptance"]["contract_version"],
            acceptance_policy.ACCEPTANCE_CONTRACT_VERSION,
        )

    def test_rubric_identity_hashes_the_current_loaded_rubric(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            rubric_path = Path(temporary) / "rubric.json"
            raw = json.dumps({"rubric_id": "current-test"}).encode("utf-8")
            rubric_path.write_bytes(raw)
            with (
                patch.object(workflow, "CRITIC_RUBRIC_PATH", rubric_path),
                patch.object(workflow, "critic_scoring_system_prompt") as loader,
            ):
                identity = eval_package._rubric_identity()

        loader.assert_called_once_with()
        self.assertEqual(identity["rubric_id"], "current-test")
        self.assertEqual(identity["sha256"], hashlib.sha256(raw).hexdigest())

    def test_acceptance_identity_is_the_approved_file_not_a_parallel_target(self) -> None:
        identity = eval_package._acceptance_identity()

        self.assertEqual(identity["status"], "APPROVED")
        self.assertEqual(
            identity["minimum_total"], acceptance_policy.ACCEPTABLE_QUALITY_FLOOR
        )
        self.assertEqual(identity["axis_floors"], dict(acceptance_policy.AXIS_FLOORS))
        self.assertNotIn("quality_target", identity)
        contract_path = workflow.REPO_ROOT / str(identity["path"])
        self.assertEqual(identity["sha256"], hashlib.sha256(contract_path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
