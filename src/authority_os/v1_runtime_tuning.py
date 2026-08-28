"""V1 single-topic runtime tuning for advisory social gates and bounded latency."""

from __future__ import annotations

from . import campaign, quality_optimizer, resonance, topic_value
from .model_runtime import ModelConfig

_INSTALLED = False
_ORIGINAL_PREFERRED = campaign.StageModels.preferred
_ORIGINAL_TOPIC_VALUE_MODEL_CONFIG = topic_value.ModelConfig
_ORIGINAL_RESONANCE_MODEL_CONFIG = resonance.ModelConfig


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


def _fast_selection_model_config(runtime: str, model: str, reasoning: str) -> ModelConfig:
    """Downgrade only expensive single-topic selector/resonance reasoning to high."""
    tuned = "high" if reasoning in {"max", "ultra"} else reasoning
    return ModelConfig(runtime, model, tuned)


def install() -> None:
    """Install V1 social repair cleanup plus the complete single-topic fast profile."""
    global _INSTALLED
    if _INSTALLED:
        return
    quality_optimizer._failed_gates = _failed_gates_only  # type: ignore[attr-defined,assignment]
    campaign.StageModels.preferred = classmethod(_preferred_fast_single_topic)  # type: ignore[method-assign]
    topic_value.ModelConfig = _fast_selection_model_config  # type: ignore[assignment]
    resonance.ModelConfig = _fast_selection_model_config  # type: ignore[assignment]
    _INSTALLED = True
