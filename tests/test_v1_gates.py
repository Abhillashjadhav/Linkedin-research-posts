from __future__ import annotations

from pathlib import Path

import pytest

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


def test_v1_config_is_per_contract_and_reversible() -> None:
    config = v1_gates.load_config()
    contracts = config["contracts"]
    assert contracts["atomic_value_novelty"]["mode"] == "enforce"
    assert contracts["research_trust"]["mode"] == "enforce"
    assert contracts["critic_anchor_integrity"]["mode"] == "enforce"
    assert contracts["solution_plausibility"]["mode"] == "shadow"
    assert contracts["reader_attention"]["mode"] == "shadow"


def test_critic_rubric_has_all_twenty_five_behavioral_anchors() -> None:
    rubric = v1_gates.load_critic_rubric()
    axes = rubric["axes"]
    assert set(axes) == set(workflow.CRITIC_AXES)
    assert sum(len(levels) for levels in axes.values()) == 25
    assert all(set(levels) == {"1", "2", "3", "4", "5"} for levels in axes.values())


def test_atomic_value_novelty_uses_separate_private_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v1_gates, "STATE_ROOT", tmp_path)
    original = "Use trace checkpoints to find the first handoff where an agent workflow loses state."
    v1_gates.record_atomic_value(original)

    repeated = v1_gates.evaluate_atomic_novelty(
        "Use trace checkpoints to find the first handoff where an agent workflow loses state."
    )
    different = v1_gates.evaluate_atomic_novelty(
        "Treat model scores as measurements and require behavioral evidence before they control routing."
    )

    assert repeated["status"] == "FAIL"
    assert repeated["max_similarity"] >= 0.72
    assert different["status"] == "PASS"


def test_social_source_cannot_be_laundered_as_primary_evidence() -> None:
    candidate = {"source_ids": ["signal-1"]}
    evidence = [
        {
            "id": "signal-1",
            "canonical_url": "https://www.reddit.com/r/LocalLLaMA/example",
            "body": "A public discussion of a claim.",
            "source_quality": "primary",
        }
    ]
    decision = v1_gates.evaluate_research_trust(candidate, evidence)
    assert decision["status"] == "FAIL"
    assert decision["reason"] == "social-source-cannot-be-laundered-as-primary-factual-evidence"


def test_body_read_non_social_source_passes_research_trust() -> None:
    candidate = {"source_ids": ["signal-1"]}
    evidence = [
        {
            "id": "signal-1",
            "canonical_url": "https://openai.com/research/example",
            "body": "The engineering report describes the mechanism and observed result.",
            "source_quality": "primary",
        }
    ]
    decision = v1_gates.evaluate_research_trust(candidate, evidence)
    assert decision["status"] == "PASS"


def test_claim_body_support_is_shadow_diagnostic_not_a_truth_oracle() -> None:
    candidate = {
        "source_ids": ["signal-1"],
        "situation": "A deployment changed retry behavior",
        "what_changed": "The system reported 99% reliability after the change",
    }
    evidence = [
        {
            "id": "signal-1",
            "canonical_url": "https://example.com/report",
            "body": "The deployment changed retry behavior but reported no reliability percentage.",
            "source_quality": "primary",
        }
    ]
    decision = v1_gates.evaluate_claim_body_support(candidate, evidence)
    assert decision["mode"] == "shadow"
    assert decision["status"] == "FAIL"
    assert decision["numbers_supported"] is False


def test_anchored_critic_requires_exact_artifact_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v1_gates, "STATE_ROOT", tmp_path)
    candidate = {"id": "candidate-1", "angle": "retries", "text": CANDIDATE_TEXT, "claim_ids": ["source-1"]}
    anchored = _anchored_scorecard()

    validated = v1_gates._validate_critic_scorecards_v1([anchored], [candidate])
    assert validated[0]["raw_total"] == 20
    assert (tmp_path / v1_gates.CRITIC_AUDIT_NAME).is_file()

    sanitized = {"candidate_id": "candidate-1", **{axis: 4 for axis in workflow.CRITIC_AXES}}
    second = v1_gates._validate_critic_scorecards_v1([sanitized], [candidate])
    assert second[0]["raw_total"] == 20


def test_unanchored_live_score_cannot_route_without_prior_anchor_validation() -> None:
    candidate = {
        "id": "candidate-unseen",
        "angle": "state",
        "text": "A different candidate that has never been anchor validated.",
        "claim_ids": ["source-1"],
    }
    sanitized = {"candidate_id": "candidate-unseen", **{axis: 3 for axis in workflow.CRITIC_AXES}}
    with pytest.raises(workflow.WorkflowError, match="anchor evidence is required"):
        v1_gates._validate_critic_scorecards_v1([sanitized], [candidate])


def test_anchor_evidence_must_be_copied_from_candidate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(v1_gates, "STATE_ROOT", tmp_path)
    candidate = {"id": "candidate-1", "angle": "retries", "text": CANDIDATE_TEXT, "claim_ids": ["source-1"]}
    anchored = _anchored_scorecard()
    anchored["anchors"]["hook_strength"]["evidence"] = "This sentence does not exist in the candidate."
    with pytest.raises(workflow.WorkflowError, match="exact excerpt"):
        v1_gates._validate_critic_scorecards_v1([anchored], [candidate])


def test_repeated_score_disagreement_is_measurable_without_another_runtime_stage() -> None:
    first = [{"candidate_id": "candidate-1", **{axis: 4 for axis in workflow.CRITIC_AXES}}]
    second = [{"candidate_id": "candidate-1", **{axis: (5 if axis == "hook_strength" else 4) for axis in workflow.CRITIC_AXES}}]
    result = v1_gates.score_disagreement(first, second)
    assert result["max_axis_disagreement"] == 1
    assert result["stable_within_one_point"] is True


def test_v1_state_does_not_change_v0_sqlite_schema(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    db_path = tmp_path / "authority_os.sqlite"
    storage.initialise(db_path)
    before = storage.inspect_database_health(db_path)

    state_root = tmp_path / "v1-state"
    monkeypatch.setattr(v1_gates, "STATE_ROOT", state_root)
    v1_gates.record_atomic_value(
        "Use atomic value tracking to prevent a new post from repackaging the same reader insight."
    )

    after = storage.inspect_database_health(db_path)
    assert before == after
    assert after["schema_version"] == storage.SCHEMA_VERSION == 4
    assert (state_root / v1_gates.ATOMIC_LEDGER_NAME).is_file()


def test_solution_plausibility_extends_existing_resonance_schema_without_new_stage() -> None:
    schema = v1_gates.resonance_post_schema_v1()
    properties = schema["properties"]
    required = schema["required"]
    assert "solution_plausibility" in properties
    assert "solution_plausibility_reason" in properties
    assert "solution_plausibility" in required
    assert "solution_plausibility_reason" in required


def test_topic_value_schema_adds_one_atomic_value_not_another_selector() -> None:
    schema = v1_gates._topic_candidate_schema_v1()
    assert "atomic_value" in schema["properties"]
    assert "atomic_value" in schema["required"]
