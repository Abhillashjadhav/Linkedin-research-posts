from __future__ import annotations

import inspect
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from authority_os import storage, v1_gates, workflow


CANDIDATE_TEXT = (
    "This outage exposed a retry loop that kept amplifying queue pressure. "
    "Teams should cap retries before queue saturation turns a local failure into a system failure."
)


def _anchor(axis: str, score: int) -> dict[str, str]:
    return {
        "anchor_id": f"{axis}:{score}",
        "evidence": "This outage exposed a retry loop that kept amplifying queue pressure.",
        "why_not_higher": "not-applicable" if score == 5 else "The post does not yet satisfy the next behavioral anchor completely.",
        "why_not_lower": "not-applicable" if score == 1 else "The cited excerpt clearly exceeds the lower behavioral anchor.",
    }


def _anchored_scorecard(candidate_id: str = "candidate-1", score: int = 4) -> dict[str, object]:
    return {
        "candidate_id": candidate_id,
        **{axis: score for axis in workflow.CRITIC_AXES},
        "anchors": {axis: _anchor(axis, score) for axis in workflow.CRITIC_AXES},
    }


class V1ContractTests(unittest.TestCase):
    def test_v1_config_is_per_contract_and_reversible(self) -> None:
        contracts = v1_gates.load_config()["contracts"]
        self.assertEqual(contracts["atomic_value_novelty"]["mode"], "enforce")
        self.assertEqual(contracts["research_trust"]["mode"], "enforce")
        self.assertEqual(contracts["critic_anchor_integrity"]["mode"], "enforce")
        self.assertEqual(contracts["solution_plausibility"]["mode"], "shadow")
        self.assertEqual(contracts["reader_attention"]["mode"], "shadow")

    def test_critic_rubric_has_all_twenty_five_behavioral_anchors(self) -> None:
        axes = v1_gates.load_critic_rubric()["axes"]
        self.assertEqual(set(axes), set(workflow.CRITIC_AXES))
        self.assertEqual(sum(len(levels) for levels in axes.values()), 25)
        self.assertTrue(
            all(set(levels) == {"1", "2", "3", "4", "5"} for levels in axes.values())
        )

    def test_atomic_value_novelty_uses_separate_private_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            v1_gates, "STATE_ROOT", Path(directory)
        ):
            original = "Use trace checkpoints to find the first handoff where an agent workflow loses state."
            v1_gates.record_atomic_value(original)
            repeated = v1_gates.evaluate_atomic_novelty(original)
            different = v1_gates.evaluate_atomic_novelty(
                "Treat model scores as measurements and require behavioral evidence before they control routing."
            )
            self.assertEqual(repeated["status"], "FAIL")
            self.assertGreaterEqual(repeated["max_similarity"], 0.72)
            self.assertEqual(different["status"], "PASS")

    def test_social_source_cannot_be_laundered_as_primary_evidence(self) -> None:
        decision = v1_gates.evaluate_research_trust(
            {"source_ids": ["signal-1"]},
            [
                {
                    "id": "signal-1",
                    "canonical_url": "https://www.reddit.com/r/LocalLLaMA/example",
                    "body": "A public discussion of a claim.",
                    "source_quality": "primary",
                }
            ],
        )
        self.assertEqual(decision["status"], "FAIL")
        self.assertEqual(
            decision["reason"],
            "social-source-cannot-be-laundered-as-primary-factual-evidence",
        )

    def test_body_read_non_social_source_passes_research_trust(self) -> None:
        decision = v1_gates.evaluate_research_trust(
            {"source_ids": ["signal-1"]},
            [
                {
                    "id": "signal-1",
                    "canonical_url": "https://openai.com/research/example",
                    "body": "The engineering report describes the mechanism and observed result.",
                    "source_quality": "primary",
                }
            ],
        )
        self.assertEqual(decision["status"], "PASS")

    def test_claim_body_support_is_shadow_diagnostic_not_truth_oracle(self) -> None:
        decision = v1_gates.evaluate_claim_body_support(
            {
                "source_ids": ["signal-1"],
                "situation": "A deployment changed retry behavior",
                "what_changed": "The system reported 99% reliability after the change",
            },
            [
                {
                    "id": "signal-1",
                    "canonical_url": "https://example.com/report",
                    "body": "The deployment changed retry behavior but reported no reliability percentage.",
                    "source_quality": "primary",
                }
            ],
        )
        self.assertEqual(decision["mode"], "shadow")
        self.assertEqual(decision["status"], "FAIL")
        self.assertIs(decision["numbers_supported"], False)

    def test_anchored_critic_requires_exact_artifact_evidence(self) -> None:
        candidate = {
            "id": "candidate-1",
            "angle": "retries",
            "text": CANDIDATE_TEXT,
            "claim_ids": ["source-1"],
        }
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            v1_gates, "STATE_ROOT", Path(directory)
        ):
            validated = v1_gates._validate_critic_scorecards_v1(
                [_anchored_scorecard()], [candidate]
            )
            self.assertEqual(validated[0]["raw_total"], 20)
            self.assertTrue((Path(directory) / v1_gates.CRITIC_AUDIT_NAME).is_file())
            sanitized = {
                "candidate_id": "candidate-1",
                **{axis: 4 for axis in workflow.CRITIC_AXES},
            }
            second = v1_gates._validate_critic_scorecards_v1([sanitized], [candidate])
            self.assertEqual(second[0]["raw_total"], 20)

    def test_unanchored_live_score_cannot_route_without_prior_anchor_validation(self) -> None:
        candidate = {
            "id": "candidate-unseen",
            "angle": "state",
            "text": "A different candidate that has never been anchor validated.",
            "claim_ids": ["source-1"],
        }
        sanitized = {
            "candidate_id": "candidate-unseen",
            **{axis: 3 for axis in workflow.CRITIC_AXES},
        }
        with self.assertRaisesRegex(workflow.WorkflowError, "anchor evidence is required"):
            v1_gates._validate_critic_scorecards_v1([sanitized], [candidate])

    def test_anchor_evidence_must_be_copied_from_candidate(self) -> None:
        candidate = {
            "id": "candidate-1",
            "angle": "retries",
            "text": CANDIDATE_TEXT,
            "claim_ids": ["source-1"],
        }
        anchored = _anchored_scorecard()
        anchored["anchors"]["hook_strength"]["evidence"] = (
            "This sentence does not exist in the candidate."
        )
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            v1_gates, "STATE_ROOT", Path(directory)
        ):
            with self.assertRaisesRegex(workflow.WorkflowError, "exact excerpt"):
                v1_gates._validate_critic_scorecards_v1([anchored], [candidate])

    def test_repeated_score_disagreement_is_measurable_without_new_runtime_stage(self) -> None:
        first = [
            {"candidate_id": "candidate-1", **{axis: 4 for axis in workflow.CRITIC_AXES}}
        ]
        second = [
            {
                "candidate_id": "candidate-1",
                **{
                    axis: 5 if axis == "hook_strength" else 4
                    for axis in workflow.CRITIC_AXES
                },
            }
        ]
        result = v1_gates.score_disagreement(first, second)
        self.assertEqual(result["max_axis_disagreement"], 1)
        self.assertIs(result["stable_within_one_point"], True)

    def test_v1_state_does_not_change_v0_sqlite_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db_path = root / "authority_os.sqlite"
            storage.initialise(db_path)
            before = storage.inspect_database_health(db_path)
            state_root = root / "v1-state"
            with mock.patch.object(v1_gates, "STATE_ROOT", state_root):
                v1_gates.record_atomic_value(
                    "Use atomic value tracking to prevent a new post from repackaging the same reader insight."
                )
            after = storage.inspect_database_health(db_path)
            self.assertEqual(before, after)
            self.assertEqual(after["schema_version"], storage.SCHEMA_VERSION)
            self.assertEqual(storage.SCHEMA_VERSION, 4)
            self.assertTrue((state_root / v1_gates.ATOMIC_LEDGER_NAME).is_file())

    def test_solution_plausibility_extends_existing_resonance_schema_without_new_stage(self) -> None:
        schema = v1_gates.resonance_post_schema_v1()
        self.assertIn("solution_plausibility", schema["properties"])
        self.assertIn("solution_plausibility_reason", schema["properties"])
        self.assertIn("solution_plausibility", schema["required"])
        self.assertIn("solution_plausibility_reason", schema["required"])

    def test_topic_value_schema_adds_one_atomic_value_not_another_selector(self) -> None:
        schema = v1_gates._topic_candidate_schema_v1()
        self.assertIn("atomic_value", schema["properties"])
        self.assertIn("atomic_value", schema["required"])

    def test_discovery_selector_forwards_observer_to_observable_base_selector(self) -> None:
        observer = mock.Mock()
        invoker = mock.Mock()
        candidates = [{"id": "topic-value-1"}]
        with (
            mock.patch.object(
                v1_gates,
                "_ORIGINAL_DISCOVERY_SELECTOR",
                return_value=candidates,
            ) as selector,
            mock.patch.object(
                v1_gates,
                "_evaluate_topic_candidates",
                return_value=candidates,
            ),
        ):
            result = v1_gates._discovery_selector_v1(
                {"target_audience": "AI product leaders"},
                [{"id": "signal-1"}],
                invoker=invoker,
                observer=observer,
            )

        self.assertEqual(result, candidates)
        selector.assert_called_once_with(
            {"target_audience": "AI product leaders"},
            [{"id": "signal-1"}],
            invoker=invoker,
            observer=observer,
        )

    def test_v1_wrapper_keeps_base_selector_keyword_contract(self) -> None:
        base = inspect.signature(v1_gates._ORIGINAL_DISCOVERY_SELECTOR).parameters
        wrapper = inspect.signature(v1_gates._discovery_selector_v1).parameters
        base_keywords = {
            name
            for name, parameter in base.items()
            if parameter.kind
            in (parameter.POSITIONAL_OR_KEYWORD, parameter.KEYWORD_ONLY)
        }
        self.assertLessEqual(base_keywords, set(wrapper))

    def test_installed_v1_stack_accepts_public_observer_callback(self) -> None:
        script = textwrap.dedent(
            """
            from authority_os import topic_value, v1_gates

            seen = []
            candidate = {"id": "topic-value-1", "v1_evals": {}}

            def base_selector(profile, signals, *, invoker, observer=None):
                if observer is not None:
                    observer([candidate])
                return [candidate]

            def evaluator(candidates, evidence, *, decision_observer=None):
                if decision_observer is not None:
                    for item in candidates:
                        decision_observer(item)
                return list(candidates)

            v1_gates._ORIGINAL_DISCOVERY_SELECTOR = base_selector
            v1_gates._evaluate_topic_candidates = evaluator
            v1_gates.install()

            from authority_os import v1_completion
            v1_completion.install()

            result = topic_value.invoke_discovery_selector(
                {}, [], observer=lambda rows: seen.extend(rows)
            )
            assert result == [candidate]
            assert seen == [candidate]
            """
        )
        environment = dict(os.environ)
        environment["PYTHONPATH"] = str(workflow.REPO_ROOT / "src")
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=workflow.REPO_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)


if __name__ == "__main__":
    unittest.main()
