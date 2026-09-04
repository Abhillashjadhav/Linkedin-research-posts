"""Topic-value and resonance gates around the live LinkedIn craft pipeline.

Topic Value decides whether the underlying material deserves a post for the target audience.
Resonance then packages that selected situation for fast feed comprehension. A craft-approved
post still fails closed when it withholds value, asks before giving value, or is hard to enter.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import workflow
from .model_runtime import ModelConfig, invoke_structured

SELECTOR_AXES = (
    "recognition",
    "attention_trigger",
    "situation_specificity",
    "proof_value",
    "payoff",
)
POST_AXES = (
    "stop_power",
    "five_second_comprehension",
    "payoff_distance",
    "shareability",
    "proof_proximity",
)
SELECTOR_DECISION_AXES = tuple(axis for axis in SELECTOR_AXES if axis != "proof_value")
SELECTOR_DECISION_MIN_TOTAL = 16
POST_MIN_TOTAL = 20
SELECTOR_FLOORS = {
    "recognition": 4,
    "attention_trigger": 3,
    "situation_specificity": 4,
    "payoff": 4,
}

PROOF_TYPES = (
    "EVIDENCE_SOURCE",
    "PUBLIC_REPO",
    "TERMINAL_RUN",
    "SCREENSHOT",
    "VIDEO_DEMO",
    "BEFORE_AFTER",
    "NONE",
)


def _object_schema(properties: Mapping[str, object], required: Sequence[str]) -> dict[str, object]:
    return {
        "type": "object",
        "properties": dict(properties),
        "required": list(required),
        "additionalProperties": False,
    }


SELECTOR_SCHEMA = _object_schema(
    {
        "selected_candidate_id": {"type": "string"},
        "two_line_packaging": {"type": "string"},
        "what_happened": {"type": "string"},
        "why_interesting": {"type": "string"},
        "supports_locked_thesis": {"type": "boolean"},
        "proof_type": {"type": "string", "enum": list(PROOF_TYPES)},
        "proof_available": {"type": "boolean"},
        "proof_instruction": {"type": "string"},
        "scores": _object_schema(
            {axis: {"type": "integer", "minimum": 1, "maximum": 5} for axis in SELECTOR_AXES},
            SELECTOR_AXES,
        ),
        "diagnosis": {"type": "string"},
    },
    (
        "selected_candidate_id",
        "two_line_packaging",
        "what_happened",
        "why_interesting",
        "supports_locked_thesis",
        "proof_type",
        "proof_available",
        "proof_instruction",
        "scores",
        "diagnosis",
    ),
)

NARROW_SELECTOR_SCHEMA = _object_schema(
    {
        **dict(SELECTOR_SCHEMA["properties"]),
        "evidence_bounded_thesis": {"type": "string", "minLength": 1, "maxLength": 500},
        "evidence_bounded_product_decision": {
            "type": "string",
            "minLength": 1,
            "maxLength": 500,
        },
    },
    (
        *SELECTOR_SCHEMA["required"],
        "evidence_bounded_thesis",
        "evidence_bounded_product_decision",
    ),
)

POST_SCHEMA = _object_schema(
    {
        "what_happened": {"type": "string"},
        "why_interesting": {"type": "string"},
        "feed_value": {"type": "boolean"},
        "value_before_ask": {"type": "boolean"},
        "scores": _object_schema(
            {axis: {"type": "integer", "minimum": 1, "maximum": 5} for axis in POST_AXES},
            POST_AXES,
        ),
        "status": {"type": "string", "enum": ["PASS", "BLOCKED"]},
        "diagnosis": {"type": "string"},
    },
    (
        "what_happened",
        "why_interesting",
        "feed_value",
        "value_before_ask",
        "scores",
        "status",
        "diagnosis",
    ),
)

StageInvoker = Callable[[str, ModelConfig, str, str, Mapping[str, object]], dict[str, object]]


def _default_invoker(
    _stage: str,
    config: ModelConfig,
    role_prompt: str,
    task_prompt: str,
    schema: Mapping[str, object],
) -> dict[str, object]:
    return invoke_structured(
        config=config,
        role_prompt=role_prompt,
        task_prompt=task_prompt,
        schema=schema,
    )


def _load_role(name: str) -> str:
    path = workflow.REPO_ROOT / ".claude" / "agents" / f"{name}.md"
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise workflow.WorkflowError(f"Resonance role {name!r} is unavailable.") from exc
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) != 3:
            raise workflow.WorkflowError(f"Resonance role {name!r} has malformed front matter.")
        content = parts[2]
    if not content.strip():
        raise workflow.WorkflowError(f"Resonance role {name!r} is blank.")
    return content.strip()


def _validate_scores(raw: object, axes: Sequence[str]) -> dict[str, int]:
    if not isinstance(raw, Mapping) or set(raw) != set(axes):
        raise workflow.WorkflowError("Resonance stage returned an invalid score inventory.")
    scores: dict[str, int] = {}
    for axis in axes:
        value = raw.get(axis)
        if type(value) is not int or not 1 <= value <= 5:
            raise workflow.WorkflowError("Resonance scores must be integers from 1 to 5.")
        scores[axis] = value
    return scores


def selector_passes(scores: Mapping[str, int], *, supports_locked_thesis: bool) -> bool:
    """Gate feed packaging and explicit claim support without re-scoring evidence."""

    return (
        supports_locked_thesis
        and all(
            scores.get(axis, 0) >= floor
            for axis, floor in SELECTOR_FLOORS.items()
        )
        and sum(scores.get(axis, 0) for axis in SELECTOR_DECISION_AXES)
        >= SELECTOR_DECISION_MIN_TOTAL
    )


def selector_shortfalls(
    scores: Mapping[str, int],
    *,
    supports_locked_thesis: bool,
) -> list[str]:
    """Name every deterministic reason the selected situation cannot advance."""

    failures: list[str] = []
    if not supports_locked_thesis:
        failures.append(
            "claim_support=UNSUPPORTED; choose NARROW or MORE EVIDENCE"
        )
    for axis, floor in SELECTOR_FLOORS.items():
        observed = int(scores.get(axis, 0))
        if observed < floor:
            failures.append(
                f"{axis}={observed}/5 below {floor}/5 by {floor - observed}"
            )
    total = sum(int(scores.get(axis, 0)) for axis in SELECTOR_DECISION_AXES)
    if total < SELECTOR_DECISION_MIN_TOTAL:
        failures.append(
            f"feed_packaging_total={total}/20 below {SELECTOR_DECISION_MIN_TOTAL}/20 by "
            f"{SELECTOR_DECISION_MIN_TOTAL - total}"
        )
    return failures


def selector_failure_summary(selector: Mapping[str, object]) -> str:
    raw_scores = selector.get("scores")
    scores = (
        {axis: int(raw_scores.get(axis, 0)) for axis in SELECTOR_AXES}
        if isinstance(raw_scores, Mapping)
        else {axis: 0 for axis in SELECTOR_AXES}
    )
    failures = selector_shortfalls(
        scores,
        supports_locked_thesis=selector.get("supports_locked_thesis") is True,
    )
    return "; ".join(failures) or "no deterministic shortfall was recorded"


def post_passes(
    scores: Mapping[str, int],
    *,
    feed_value: bool = True,
    value_before_ask: bool = True,
) -> bool:
    """Craft cannot compensate for withheld value or an ask-first feed experience."""

    return (
        feed_value
        and value_before_ask
        and scores.get("stop_power", 0) >= 4
        and scores.get("five_second_comprehension", 0) >= 4
        and scores.get("payoff_distance", 0) >= 3
        and scores.get("proof_proximity", 0) >= 3
        and sum(scores.get(axis, 0) for axis in POST_AXES) >= POST_MIN_TOTAL
    )


def selected_topic_value_from_day(day: Mapping[str, object]) -> dict[str, object]:
    """Reuse an upstream selection, or identify the already-selected draft without reselecting it."""

    existing = day.get("topic_value")
    if isinstance(existing, Mapping) and existing.get("status") == "PASS":
        return dict(existing)
    return {
        "id": "selected-thesis",
        "status": "PASS",
        "situation": str(day.get("thesis", "")).strip(),
        "reader_value_type": "UPSTREAM_SELECTION",
        "reader_value": str(day.get("reader_problem", "")).strip(),
        "gravity": "NOT_REEVALUATED",
        "priority": "NOT_REEVALUATED",
        "authority_add": str(day.get("product_decision", "")).strip(),
    }


def invoke_selector(
    day: Mapping[str, object],
    selected_topic_value: Mapping[str, object],
    *,
    narrow_to_evidence: bool = False,
    invoker: StageInvoker = _default_invoker,
) -> dict[str, object]:
    if selected_topic_value.get("status") != "PASS":
        raise workflow.WorkflowError("Blocked Topic Value material cannot enter Resonance.")
    selected_id = str(selected_topic_value.get("id", "")).strip()
    if not selected_id:
        raise workflow.WorkflowError("Resonance requires an identified Topic Value situation.")
    config = ModelConfig("codex", "gpt-5.6-sol", "ultra")
    narrowing_instruction = ""
    if narrow_to_evidence:
        narrowing_instruction = (
            "\n\nNARROW_TO_EVIDENCE\n"
            "The human author chose to narrow the claim instead of acquiring new evidence. "
            "Keep the selected Topic Value situation and every evidence identity unchanged. "
            "Return evidence_bounded_thesis and evidence_bounded_product_decision that are "
            "directly supported by the supplied evidence bodies. Remove claims of causation, "
            "correlation, or generality when the evidence shows only a test, observation, or "
            "specific behavior. Score supports_locked_thesis and proof_value against these "
            "narrowed fields, not against the original broader wording."
        )
    task = (
        "Package the already-selected Topic Value situation for the feed. Do not choose a different topic, "
        "invent a stronger event, or turn the thesis itself into the opening. The two_line_packaging must "
        "contain exactly two non-blank lines. Line 1 should make the concrete situation legible; line 2 "
        "should expose the reason to care. The attention trigger can be contradiction, pain, immediate "
        "utility, or a meaningful observed change; surprise is not mandatory. Situation specificity can be "
        "behavioral, visual, numeric, or artifact-based. Proof/value must be visible early enough that the "
        "reader is not asked to trust an abstract conclusion. Numbers only help when the target reader can "
        "interpret them. Prefer supported abstraction: omit incidental precision or map an instance to its "
        "true parent category when meaning is preserved. Two failure modes that are central findings may "
        "become key failure modes, but major, production, or customer-impacting failures require evidence "
        "for that added meaning. Never add severity, prevalence, causality, scope, materiality, or certainty. "
        "Use only supplied evidence and honest artifact availability.\n\n"
        f"SELECTED_TOPIC_VALUE\n{json.dumps(dict(selected_topic_value), indent=2, sort_keys=True)}\n"
        f"LOCKED_THESIS\n{day.get('thesis', '')}\n"
        f"TARGET_READER\n{day.get('target_reader', '')}\n"
        f"READER_PROBLEM\n{day.get('reader_problem', '')}\n"
        f"PRODUCT_DECISION\n{day.get('product_decision', '')}\n"
        f"ARTIFACT_POLICY\n{day.get('artifact_policy', '')}\n"
        f"EVIDENCE\n{json.dumps(day.get('evidence', []), indent=2, sort_keys=True)}"
        f"{narrowing_instruction}"
    )
    result = invoker(
        "resonance_selector",
        config,
        _load_role("resonance_selector"),
        task,
        NARROW_SELECTOR_SCHEMA if narrow_to_evidence else SELECTOR_SCHEMA,
    )
    result_id = result.get("selected_candidate_id")
    if not isinstance(result_id, str) or result_id != selected_id:
        raise workflow.WorkflowError("Resonance Selector changed the Topic Value selection.")
    packaging = result.get("two_line_packaging")
    if not isinstance(packaging, str):
        raise workflow.WorkflowError("Resonance Selector packaging must be text.")
    lines = [line.strip() for line in packaging.splitlines() if line.strip()]
    if len(lines) != 2 or len(packaging) > 500:
        raise workflow.WorkflowError("Resonance Selector packaging must be exactly two bounded lines.")
    scores = _validate_scores(result.get("scores"), SELECTOR_AXES)
    supports = result.get("supports_locked_thesis")
    if type(supports) is not bool:
        raise workflow.WorkflowError("Resonance Selector thesis-fit flag must be boolean.")
    proof_type = result.get("proof_type")
    proof_available = result.get("proof_available")
    if proof_type not in PROOF_TYPES or type(proof_available) is not bool:
        raise workflow.WorkflowError("Resonance Selector returned an invalid proof plan.")
    if proof_type == "NONE" and proof_available:
        raise workflow.WorkflowError("A NONE proof plan cannot claim proof is available.")
    narrowed_fields: dict[str, object] = {}
    effective_support = supports
    if narrow_to_evidence:
        bounded_thesis = result.get("evidence_bounded_thesis")
        bounded_decision = result.get("evidence_bounded_product_decision")
        if (
            not isinstance(bounded_thesis, str)
            or not bounded_thesis.strip()
            or len(bounded_thesis) > 500
            or not isinstance(bounded_decision, str)
            or not bounded_decision.strip()
            or len(bounded_decision) > 500
        ):
            raise workflow.WorkflowError(
                "Evidence narrowing requires bounded thesis and product-decision text."
            )
        narrowed_fields = {
            "evidence_bounded_thesis": bounded_thesis.strip(),
            "evidence_bounded_product_decision": bounded_decision.strip(),
            "narrowed_to_evidence": True,
            "original_locked_thesis": str(day.get("thesis", "")).strip(),
            "original_product_decision": str(day.get("product_decision", "")).strip(),
        }
        # NARROW is the human's recovery decision. Once the provider satisfies
        # the bounded-field contract, the original thesis-fit flag is diagnostic
        # only; the final honesty and citation gates still validate the draft.
        effective_support = True
    computed = selector_passes(
        scores,
        supports_locked_thesis=effective_support,
    )
    expected_status = "PASS" if computed else "BLOCKED"
    return {
        **dict(result),
        **narrowed_fields,
        "model_claim_support": supports,
        "supports_locked_thesis": effective_support,
        "status": expected_status,
        "status_owner": "python-deterministic-selector-v1",
        "claim_support": (
            "SUPPORTED"
            if supports
            else "NARROWED_TO_EVIDENCE"
            if narrow_to_evidence
            else "UNSUPPORTED"
        ),
        "two_line_packaging": "\n".join(lines),
        "scores": scores,
        "total": sum(scores.values()),
        "topic_value": dict(selected_topic_value),
        "shortfalls": selector_shortfalls(
            scores,
            supports_locked_thesis=effective_support,
        ),
    }


def enrich_day(
    day: Mapping[str, object],
    selector: Mapping[str, object],
    selected_topic_value: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Project Topic Value, feed packaging, and proof plan into the existing trusted brief fields."""

    if selector.get("status") != "PASS":
        raise workflow.WorkflowError("A blocked resonance selection cannot enter Writer.")
    topic_result = selected_topic_value or selector.get("topic_value")
    if not isinstance(topic_result, Mapping) or topic_result.get("status") != "PASS":
        raise workflow.WorkflowError("Writer enrichment requires a passed Topic Value selection.")
    enriched = dict(day)
    if selector.get("narrowed_to_evidence") is True:
        enriched["thesis"] = str(selector["evidence_bounded_thesis"]).strip()
        enriched["product_decision"] = str(
            selector["evidence_bounded_product_decision"]
        ).strip()
    packaging = str(selector["two_line_packaging"]).strip()
    what_happened = str(selector["what_happened"]).strip()
    why_interesting = str(selector["why_interesting"]).strip()
    proof_type = str(selector["proof_type"])
    proof_instruction = str(selector["proof_instruction"]).strip()
    original_dominant = str(day.get("dominant_take", "")).strip()
    original_missing = str(day.get("missing_angle", "")).strip()
    original_artifact = str(day.get("artifact_policy", "")).strip()
    enriched["dominant_take"] = (
        "TOPIC VALUE SELECTED BEFORE WRITING:\n"
        f"SITUATION: {topic_result.get('situation', '')}\n"
        f"READER VALUE ROUTE: {topic_result.get('reader_value_type', '')}\n"
        f"READER VALUE: {topic_result.get('reader_value', '')}\n"
        f"GRAVITY: {topic_result.get('gravity', '')}\n"
        f"PRIORITY: {topic_result.get('priority', '')}\n"
        f"AUTHORITY CONTRIBUTION: {topic_result.get('authority_add', '')}\n"
        f"FIVE-SECOND PACKAGING:\n{packaging}\n"
        f"ORIGINAL DOMINANT TAKE: {original_dominant}"
    )
    enriched["missing_angle"] = (
        f"SELECTED SITUATION: {what_happened}\nWHY THE READER CARES: {why_interesting}\n"
        "WRITING RULE: situation first, insight second; preserve one primary capability/problem/decision.\n"
        f"ORIGINAL MISSING ANGLE: {original_missing}"
    )
    enriched["artifact_policy"] = (
        f"PROOF PLAN DECIDED BEFORE DRAFTING: {proof_type}. {proof_instruction}\n"
        "FEED VALUE RULE: the LinkedIn post must deliver meaningful value before any click, registration, repo, or other ask.\n"
        f"ORIGINAL ARTIFACT POLICY: {original_artifact}"
    )
    return enriched


def prepare_campaign_spec(
    spec_path: Path,
    *,
    output_root: Path,
    only_day: str | None = None,
    narrow_to_evidence: bool = False,
    invoker: StageInvoker = _default_invoker,
) -> tuple[Path, dict[str, dict[str, object]]]:
    """Run Topic Value then Resonance before Writer and emit a compatible enriched spec."""

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError("Selection preflight could not read the campaign spec.") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("days"), list):
        raise workflow.WorkflowError("Selection preflight needs a valid campaign spec.")
    preserve = set(str(value) for value in spec.get("preserve_days", []))
    results: dict[str, dict[str, object]] = {}
    topic_results: dict[str, dict[str, object]] = {}
    enriched_days: list[object] = []
    for raw_day in spec["days"]:
        if not isinstance(raw_day, dict):
            raise workflow.WorkflowError("Campaign day must be an object.")
        day_name = str(raw_day.get("day", ""))
        should_run = day_name not in preserve and (only_day is None or day_name == only_day)
        if not should_run:
            enriched_days.append(raw_day)
            continue
        selected_topic = selected_topic_value_from_day(raw_day)
        topic_results[day_name] = selected_topic
        selector = invoke_selector(
            raw_day,
            selected_topic,
            narrow_to_evidence=narrow_to_evidence,
            invoker=invoker,
        )
        results[day_name] = selector
        if selector["status"] != "PASS":
            raise workflow.WorkflowError(
                f"Resonance Selector blocked {day_name}: "
                f"{selector_failure_summary(selector)}"
            )
        enriched_days.append(enrich_day(raw_day, selector, selected_topic))
    spec["days"] = enriched_days
    selection_dir = output_root / "_resonance"
    selection_dir.mkdir(parents=True, exist_ok=True)
    prepared = selection_dir / "prepared-spec.json"
    topic_path = selection_dir / "topic-value.json"
    selector_path = selection_dir / "selector.json"
    prepared.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    topic_path.write_text(json.dumps(topic_results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    selector_path.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return prepared, results


def invoke_post_critic(
    post_text: str,
    selector: Mapping[str, object],
    *,
    invoker: StageInvoker = _default_invoker,
) -> dict[str, object]:
    config = ModelConfig("codex", "gpt-5.6-sol", "ultra")
    task = (
        "Evaluate feed resonance only. Do not reward technical sophistication by itself and do not rewrite. "
        "A reader should be able to explain the concrete situation and why it matters after roughly five seconds. "
        "Specificity may be behavioral, visual, numeric, or artifact-based; do not require numbers. Shareability "
        "means the reader gains practical or social value by passing the post to someone else. Proof proximity asks "
        "whether inspectable evidence, a mechanism, artifact, run, screenshot, source, or measured result appears close "
        "enough to the central claim. feed_value is true only if the reader receives meaningful value in the LinkedIn "
        "post without needing to click a link. value_before_ask is true only if the post gives the useful idea, evidence, "
        "or method before asking the reader to click, register, join, star, subscribe, comment, or perform another action.\n\n"
        f"SELECTION_RESULT\n{json.dumps(dict(selector), indent=2, sort_keys=True)}\n"
        f"POST\n{post_text}"
    )
    result = invoker(
        "resonance_critic",
        config,
        _load_role("resonance_critic"),
        task,
        POST_SCHEMA,
    )
    scores = _validate_scores(result.get("scores"), POST_AXES)
    feed_value = result.get("feed_value")
    value_before_ask = result.get("value_before_ask")
    if type(feed_value) is not bool or type(value_before_ask) is not bool:
        raise workflow.WorkflowError("Resonance Critic feed-value gates must be boolean.")
    computed = post_passes(
        scores,
        feed_value=feed_value,
        value_before_ask=value_before_ask,
    )
    expected_status = "PASS" if computed else "BLOCKED"
    if result.get("status") != expected_status:
        raise workflow.WorkflowError("Resonance Critic status contradicts its scores or feed-value gates.")
    return {
        **dict(result),
        "scores": scores,
        "total": sum(scores.values()),
    }


def _rewrite_summary(
    output_root: Path,
    overlays: Mapping[str, Mapping[str, object]],
    selectors: Mapping[str, Mapping[str, object]],
) -> None:
    summary_path = output_root / "summary.json"
    try:
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    days = summary.get("days")
    if not isinstance(days, list):
        return
    for item in days:
        if not isinstance(item, dict):
            continue
        day = str(item.get("day", ""))
        selector = selectors.get(day)
        overlay = overlays.get(day)
        if selector is not None:
            topic_result = selector.get("topic_value")
            if isinstance(topic_result, Mapping):
                item["topic_value_total"] = topic_result.get("total")
                item["topic_value_priority"] = topic_result.get("priority")
                item["topic_gravity"] = topic_result.get("gravity")
                item["reader_value_type"] = topic_result.get("reader_value_type")
        if overlay is None:
            continue
        item["resonance_status"] = overlay["status"]
        item["resonance_total"] = overlay["total"]
        item["feed_value"] = overlay.get("feed_value")
        item["value_before_ask"] = overlay.get("value_before_ask")
        if overlay["status"] == "BLOCKED":
            item["status"] = "BLOCKED"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    table = [
        "# Campaign summary",
        "",
        "| Day | Status | Topic value | Gravity | Critic | Hook | Resonance | Feed value | Artifact | Visual QA |",
        "|---|---|---:|---|---:|---:|---:|---|---|---|",
    ]
    for item in days:
        if not isinstance(item, Mapping):
            continue
        table.append(
            f"| {item.get('day', '')} | {item.get('status', '')} | "
            f"{item.get('topic_value_total') or 'n/a'} | {item.get('topic_gravity') or 'n/a'} | "
            f"{item.get('critic_effective_total') or 'n/a'} | {item.get('hook_strength') or 'n/a'} | "
            f"{item.get('resonance_total') or 'n/a'} | {item.get('feed_value', 'n/a')} | "
            f"{item.get('artifact_format') or 'n/a'} | {item.get('visual_qa') or 'n/a'} |"
        )
    table.extend(["", "Human approval: `NOT_APPROVED`", "", "Publishing: `DISABLED`", ""])
    (output_root / "summary.md").write_text("\n".join(table), encoding="utf-8")


def apply_post_gate(
    output_root: Path,
    selectors: Mapping[str, Mapping[str, object]],
    *,
    only_day: str | None = None,
    invoker: StageInvoker = _default_invoker,
) -> dict[str, dict[str, object]]:
    """Apply resonance after craft approval and fail closed by pruning publishable files."""

    overlays: dict[str, dict[str, object]] = {}
    for day, selector in selectors.items():
        if only_day is not None and day != only_day:
            continue
        directory = output_root / day.casefold()
        trace_path = directory / "trace.json"
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        final = trace.get("final")
        if not isinstance(final, dict) or final.get("status") != "READY_FOR_HUMAN_REVIEW":
            continue
        post = final.get("post")
        if not isinstance(post, str) or not post.strip():
            raise workflow.WorkflowError("Resonance Critic found a READY trace without a post.")
        assessment = invoke_post_critic(post, selector, invoker=invoker)
        overlays[day] = assessment
        topic_result = selector.get("topic_value")
        if isinstance(topic_result, Mapping):
            trace["topic_value_selector"] = dict(topic_result)
        trace["resonance_selector"] = dict(selector)
        trace["resonance_critic"] = assessment
        (directory / "resonance-critic.json").write_text(
            json.dumps(assessment, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if assessment["status"] == "BLOCKED":
            trace["final"] = {
                "status": "BLOCKED",
                "reason": "Craft cleared, but the post failed the resonance/feed-value gate.",
                "human_approval_status": "NOT_APPROVED",
                "publishing_status": "DISABLED",
            }
            for name in ("post.md", "first-comment.md"):
                path = directory / name
                if path.is_file():
                    path.unlink()
        trace_path.write_text(json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _rewrite_summary(output_root, overlays, selectors)
    return overlays
