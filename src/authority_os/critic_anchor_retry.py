"""Bounded recovery for malformed V1 Critic anchor output.

The anchor-integrity contract remains fail-closed: evidence must be copied from the
exact candidate. A judge-formatting defect may be retried once on the same candidates;
the second failure, and every unrelated workflow error, still propagates.
"""

from __future__ import annotations

from typing import Callable, Mapping, Sequence

from . import workflow

_INSTALLED = False
_ORIGINAL_RUN_CRITIC_REVIEW = workflow.run_critic_review
_ORIGINAL_CRITIC_SYSTEM_PROMPT = workflow.critic_scoring_system_prompt

_RETRYABLE_ANCHOR_ERRORS = frozenset(
    {
        "Critic anchor evidence inventory is invalid.",
        "Critic anchored scores must use valid 1-5 axes.",
        "Critic anchor detail has an invalid schema.",
        "Critic anchor_id must match the scored axis and level.",
        "Critic anchor evidence and boundary reasons must be non-blank.",
        "Critic anchor evidence must be an exact excerpt from the candidate.",
        "Score 5 must use why_not_higher=not-applicable.",
        "Only score 5 may omit why_not_higher.",
        "Score 1 must use why_not_lower=not-applicable.",
        "Only score 1 may omit why_not_lower.",
    }
)


def _retryable_anchor_error(exc: workflow.WorkflowError) -> bool:
    return str(exc) in _RETRYABLE_ANCHOR_ERRORS


def _strict_critic_system_prompt() -> str:
    return (
        _ORIGINAL_CRITIC_SYSTEM_PROMPT()
        + "\n\nANCHOR_COPY_RULE: For every `evidence` value, copy one short contiguous substring "
        "character-for-character from the exact candidate text. Do not paraphrase, normalize "
        "punctuation, add quotation marks, insert ellipses, or combine non-contiguous spans."
    )


def _retry_score_provider(
    provider: Callable[
        [Sequence[Mapping[str, object]]], Sequence[Mapping[str, object]]
    ]
) -> Callable[[Sequence[Mapping[str, object]]], Sequence[Mapping[str, object]]]:
    """Retry only malformed anchored-judge output, once, on the same candidate objects."""

    def score(candidates: Sequence[Mapping[str, object]]) -> Sequence[Mapping[str, object]]:
        try:
            return provider(candidates)
        except workflow.WorkflowError as exc:
            if not _retryable_anchor_error(exc):
                raise
        return provider(candidates)

    return score


def _run_critic_review(
    candidates,
    brief,
    evidence,
    score_provider,
    revision_provider,
    *,
    proof=None,
):
    return _ORIGINAL_RUN_CRITIC_REVIEW(
        candidates,
        brief,
        evidence,
        _retry_score_provider(score_provider),
        revision_provider,
        proof=proof,
    )


def install() -> None:
    """Install after V1 anchors and human-readability editing are already wired."""

    global _INSTALLED
    if _INSTALLED:
        return
    workflow.critic_scoring_system_prompt = _strict_critic_system_prompt  # type: ignore[assignment]
    workflow.run_critic_review = _run_critic_review  # type: ignore[assignment]
    _INSTALLED = True
