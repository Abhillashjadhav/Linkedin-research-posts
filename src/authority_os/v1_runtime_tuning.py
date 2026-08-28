"""V1 single-topic runtime tuning for advisory social gates and bounded latency."""

from __future__ import annotations

from . import campaign, quality_optimizer
from .model_runtime import ModelConfig

_INSTALLED = False
_ORIGINAL_PREFERRED = campaign.StageModels.preferred


def _failed_gates_only(candidate):
    """Only literal FAIL statuses are repair work; HUMAN_REVIEW is advisory."""
    return {
        name: status
        for name, status in candidate.gates.items()
        if status == "FAIL"
    }


def _preferred_fast_single_topic(cls):
    """Keep model quality high while avoiding max/ultra reasoning on the live social path."""
    original = _ORIGINAL_PREFERRED()
    sol = original.writer.model
    return campaign.StageModels(
        writer=ModelConfig("codex", sol, "high"),
        narrative_editor=ModelConfig("codex", sol, "high"),
        critic=ModelConfig("codex", sol, "high"),
        artisanal_editor=original.artisanal_editor,
        comment_writer=original.comment_writer,
        comment_reviewer=original.comment_reviewer,
        artifact_editor=original.artifact_editor,
        visual_qa=original.visual_qa,
    )


def install() -> None:
    """Install V1 social repair cleanup plus the single-topic fast reasoning profile."""
    global _INSTALLED
    if _INSTALLED:
        return
    quality_optimizer._failed_gates = _failed_gates_only  # type: ignore[attr-defined,assignment]
    campaign.StageModels.preferred = classmethod(_preferred_fast_single_topic)  # type: ignore[method-assign]
    _INSTALLED = True
