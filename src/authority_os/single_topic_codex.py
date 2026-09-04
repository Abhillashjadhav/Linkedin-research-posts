"""Codex-only model runtime for the current live V1 single-topic path.

The frozen V0 ref retains its historical provider implementation. Current V1 reuses the
same Writer/Critic prompts, schemas, evidence projections, local validators, and revision
contract while invoking them through the bounded zero-tool Codex runtime already used by
the campaign pipeline.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from . import campaign, model_runtime, workflow

_INSTALLED = False


def _require_egress(value: bool, *, stage: str) -> None:
    if type(value) is not bool or not value:
        raise workflow.WorkflowError(f"{stage} model egress requires explicit consent.")


def _require_timeout(value: int, *, stage: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise workflow.WorkflowError(f"{stage} timeout must be a positive integer.")


def _invoke_writer_codex(
    *,
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    allow_model_egress: bool = False,
    voice_guidance: Mapping[str, str] | None = None,
    proof: workflow.LoadedProof | None = None,
    timeout: int = 300,
) -> list[dict[str, object]]:
    """Run the existing Writer contract through the zero-tool Codex runtime."""

    _require_egress(allow_model_egress, stage="Writer")
    _require_timeout(timeout, stage="Writer")
    guidance = workflow.load_voice_guidance() if voice_guidance is None else voice_guidance
    prompt = workflow.build_writer_prompt(
        brief=brief,
        evidence=evidence,
        voice_guidance=guidance,
        proof=proof,
    )
    result = model_runtime.invoke_structured(
        config=campaign.StageModels.preferred().writer,
        role_prompt=workflow._writer_system_prompt(),  # type: ignore[attr-defined]
        task_prompt=prompt,
        schema=workflow.WRITER_SCHEMA,
        timeout=timeout,
        web_search=False,
        stage_label="Single-topic Writer",
    )
    raw_candidates = result.get("candidates")
    if not isinstance(raw_candidates, Sequence) or isinstance(raw_candidates, (str, bytes)):
        raise workflow.WorkflowError("Writer response must contain a candidates list.")
    return workflow.validate_draft_candidates(
        raw_candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,
    )


def _invoke_critic_codex(
    candidates: Sequence[Mapping[str, object]],
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    *,
    allow_model_egress: bool = False,
    proof: workflow.LoadedProof | None = None,
    timeout: int = 300,
) -> list[dict[str, object]]:
    """Run the existing score-only Critic contract through Codex."""

    _require_egress(allow_model_egress, stage="Critic")
    _require_timeout(timeout, stage="Critic")
    prompt = workflow.build_critic_prompt(
        candidates=candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,
    )
    result = model_runtime.invoke_structured(
        config=campaign.StageModels.preferred().critic,
        role_prompt=workflow.critic_scoring_system_prompt(),
        task_prompt=prompt,
        schema=workflow.CRITIC_SCORE_SCHEMA,
        timeout=timeout,
        web_search=False,
        stage_label="Single-topic Critic",
    )
    raw_scorecards = result.get("scorecards")
    validated = workflow.validate_critic_scorecards(raw_scorecards, candidates)  # type: ignore[arg-type]
    return [
        {
            "candidate_id": scorecard["candidate_id"],
            **{axis: scorecard[axis] for axis in workflow.CRITIC_AXES},
        }
        for scorecard in validated
    ]


def _invoke_writer_revision_codex(
    candidate: Mapping[str, object],
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    *,
    scorecard: Mapping[str, object],
    allow_model_egress: bool = False,
    voice_guidance: Mapping[str, str] | None = None,
    proof: workflow.LoadedProof | None = None,
    repair_feedback: Mapping[str, object] | None = None,
    timeout: int = 300,
) -> dict[str, object]:
    """Run one orchestrator-controlled Writer revision through Codex."""

    _require_egress(allow_model_egress, stage="Writer revision")
    _require_timeout(timeout, stage="Writer revision")
    guidance = workflow.load_voice_guidance() if voice_guidance is None else voice_guidance
    prompt = workflow._build_writer_revision_prompt(  # type: ignore[attr-defined]
        candidate=candidate,
        scorecard=scorecard,
        brief=brief,
        evidence=evidence,
        voice_guidance=guidance,
        proof=proof,
        repair_feedback=repair_feedback,
    )
    result = model_runtime.invoke_structured(
        config=campaign.StageModels.preferred().writer,
        role_prompt=workflow._writer_revision_system_prompt(),  # type: ignore[attr-defined]
        task_prompt=prompt,
        schema=workflow.WRITER_REVISION_SCHEMA,
        timeout=timeout,
        web_search=False,
        stage_label="Single-topic Writer revision",
    )
    revised = result.get("candidate")
    if not isinstance(revised, Mapping):
        raise workflow.WorkflowError("Writer revision response must contain one candidate.")
    if set(revised) != {"id", "angle", "text", "claim_ids"}:
        raise workflow.WorkflowError("Writer revision candidate has an invalid schema.")
    return dict(revised)


def install() -> None:
    """Route current live single-topic model stages through Codex only."""

    global _INSTALLED
    if _INSTALLED:
        return
    workflow.invoke_writer = _invoke_writer_codex  # type: ignore[assignment]
    workflow.invoke_critic = _invoke_critic_codex  # type: ignore[assignment]
    workflow.invoke_writer_revision = _invoke_writer_revision_codex  # type: ignore[assignment]
    _INSTALLED = True
