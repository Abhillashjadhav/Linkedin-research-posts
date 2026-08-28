"""V1 runtime contract for deterministic Topic Value candidate IDs.

Topic IDs are transport bookkeeping, but the base validator requires the model to return
``topic-1..topic-N`` exactly. Keep that fail-closed validator and make the structured
schema/prompt express the same contract so a semantically valid selection cannot fail only
because the model invented a different label.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from . import topic_value, workflow

_INSTALLED = False
_ORIGINAL_SCHEMA = topic_value._schema  # type: ignore[attr-defined]
_ORIGINAL_INVOKE_SELECTOR = topic_value.invoke_selector
_ORIGINAL_DEFAULT_INVOKER = topic_value._default_invoker  # type: ignore[attr-defined]


def allowed_ids(count: int) -> tuple[str, ...]:
    if type(count) is not int or count < 1:
        raise workflow.WorkflowError(
            "Topic Value candidate count must be a positive integer."
        )
    return tuple(f"topic-{index}" for index in range(1, count + 1))


def schema_with_exact_ids(count: int) -> dict[str, object]:
    """Return the current Topic Value schema with an exact count-specific ID enum."""

    schema = _ORIGINAL_SCHEMA(count)
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        raise workflow.WorkflowError("Topic Value schema is malformed.")
    candidates = properties.get("candidates")
    if not isinstance(candidates, dict):
        raise workflow.WorkflowError("Topic Value candidate schema is malformed.")
    item_schema = candidates.get("items")
    if not isinstance(item_schema, dict):
        raise workflow.WorkflowError("Topic Value candidate item schema is malformed.")
    item_properties = item_schema.get("properties")
    required = item_schema.get("required")
    if (
        not isinstance(item_properties, dict)
        or not isinstance(required, list)
        or "id" not in required
    ):
        raise workflow.WorkflowError("Topic Value candidate ID schema is unavailable.")
    item_properties["id"] = {
        "type": "string",
        "enum": list(allowed_ids(count)),
    }
    return schema


def invoke_selector(
    *,
    target_reader: str,
    authority_goal: str,
    evidence: Sequence[Mapping[str, object]],
    count: int,
    candidate_hints: Sequence[Mapping[str, object]] = (),
    invoker=_ORIGINAL_DEFAULT_INVOKER,
) -> list[dict[str, object]]:
    """Add the exact ID contract to the model task while preserving base validation."""

    ids = allowed_ids(count)

    def contracted_invoker(stage, config, role_prompt, task_prompt, schema):
        exact = ", ".join(ids)
        task = (
            f"{task_prompt}\n\n"
            "CANDIDATE_ID_CONTRACT\n"
            f"Return exactly these candidate IDs once each and no others: {exact}. "
            "Candidate IDs are bookkeeping labels; do not rename them based on the "
            "topic, situation, or source."
        )
        return invoker(stage, config, role_prompt, task, schema)

    return _ORIGINAL_INVOKE_SELECTOR(
        target_reader=target_reader,
        authority_goal=authority_goal,
        evidence=evidence,
        count=count,
        candidate_hints=candidate_hints,
        invoker=contracted_invoker,
    )


def install() -> None:
    """Install after the V1 schema overlay so atomic-value fields are preserved."""

    global _INSTALLED
    if _INSTALLED:
        return
    topic_value._schema = schema_with_exact_ids  # type: ignore[attr-defined,assignment]
    topic_value.invoke_selector = invoke_selector  # type: ignore[assignment]
    _INSTALLED = True
