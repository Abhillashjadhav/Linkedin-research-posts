"""Single-entrypoint integration of topic-value, resonance, high-bar, and anti-slop gates."""

from __future__ import annotations

import io
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Any, Iterator

from . import anti_slop, quality_cli, resonance, topic_value, workflow


_original_qualifying = quality_cli._qualifying_candidates
_original_feedback = quality_cli._quality_feedback
_original_command_draft = quality_cli.command_draft

_active_single_selector: dict[str, object] | None = None
_active_single_topic_value: dict[str, object] | None = None
_active_resonance_diagnostics: dict[str, dict[str, object]] = {}


def _qualifying_candidates(*args: Any, **kwargs: Any):
    global _active_resonance_diagnostics
    candidates = _original_qualifying(*args, **kwargs)
    candidates = tuple(candidate for candidate in candidates if anti_slop.passes(candidate.text))
    if _active_single_selector is None:
        return candidates
    accepted = []
    for candidate in candidates:
        assessment = resonance.invoke_post_critic(candidate.text, _active_single_selector)
        _active_resonance_diagnostics[candidate.candidate_id] = assessment
        if assessment.get("status") == "PASS":
            accepted.append(candidate)
    return tuple(accepted)


def _quality_feedback(attempt: quality_cli.AttemptResult, cycle: int) -> dict[str, object]:
    global _active_resonance_diagnostics
    feedback = dict(_original_feedback(attempt, cycle))
    resonance_diagnostics = dict(_active_resonance_diagnostics)
    rejected = feedback.get("rejected_candidates")
    if isinstance(rejected, list):
        by_id = {candidate.candidate_id: candidate for candidate in attempt.candidates}
        enriched: list[dict[str, object]] = []
        for item in rejected:
            copied = dict(item) if isinstance(item, Mapping) else {}
            candidate_id = str(copied.get("candidate_id", ""))
            candidate = by_id.get(candidate_id)
            copied["anti_slop_findings"] = (
                [
                    {"code": finding.code, "excerpt": finding.excerpt}
                    for finding in anti_slop.audit(candidate.text)
                ]
                if candidate is not None
                else []
            )
            if candidate_id in resonance_diagnostics:
                copied["resonance_diagnostic"] = resonance_diagnostics[candidate_id]
            enriched.append(copied)
        feedback["rejected_candidates"] = enriched
    feedback["anti_slop_required"] = True
    if _active_single_selector is not None:
        feedback["resonance_required"] = True
    feedback["required_next_action"] = (
        str(feedback.get("required_next_action", ""))
        + " Remove every named anti-slop pattern without weakening the evidence, product decision, or voice."
        + (
            " If a resonance diagnostic is present, fix the feed entry, proof/value proximity, payoff distance, "
            "or value-before-ask failure without changing the selected Topic Value situation."
            if _active_single_selector is not None
            else ""
        )
    ).strip()
    if _active_single_selector is not None:
        _active_resonance_diagnostics = {}
    return feedback


def _single_day(
    brief: Mapping[str, object],
    evidence: object,
    proof: object,
) -> dict[str, object]:
    if not isinstance(evidence, list):
        try:
            evidence = list(evidence)  # type: ignore[arg-type]
        except TypeError as exc:
            raise workflow.WorkflowError("Single-topic selection requires drafting evidence.") from exc
    if not evidence or not all(isinstance(item, Mapping) for item in evidence):
        raise workflow.WorkflowError("Single-topic selection requires grounded drafting evidence.")
    analysis = brief.get("analysis")
    if not isinstance(analysis, Mapping):
        raise workflow.WorkflowError("Single-topic selection requires the strategic analysis brief.")
    proof_claim = getattr(proof, "public_claim", "") if proof is not None else ""
    artifact_policy = (
        f"A validated supplied proof is available: {proof_claim}"
        if isinstance(proof_claim, str) and proof_claim.strip()
        else "Use only the supplied research evidence; do not manufacture collateral."
    )
    return {
        "day": "Single",
        "target_reader": str(brief.get("target_reader", "")).strip(),
        "reader_problem": str(brief.get("reader_problem", "")).strip(),
        "thesis": str(brief.get("core_hypothesis", "")).strip(),
        "product_decision": str(brief.get("product_decision", "")).strip(),
        "authority_statement": str(brief.get("authority_statement", "")).strip(),
        "dominant_take": str(analysis.get("dominant_take", "")).strip(),
        "missing_angle": str(analysis.get("missing_angle", "")).strip(),
        "artifact_policy": artifact_policy,
        "evidence": [dict(item) for item in evidence if isinstance(item, Mapping)],
    }


@contextmanager
def _single_topic_selection_prompt() -> Iterator[None]:
    """Run Topic Value + Resonance once, then inject that decision into every quality cycle."""

    global _active_single_selector, _active_single_topic_value, _active_resonance_diagnostics
    original = workflow.build_writer_prompt
    cached: dict[str, object] = {}

    def build_with_selection(*args: object, **kwargs: object) -> str:
        nonlocal cached
        global _active_single_selector, _active_single_topic_value
        brief = kwargs.get("brief")
        evidence = kwargs.get("evidence")
        proof = kwargs.get("proof")
        if not isinstance(brief, Mapping):
            raise workflow.WorkflowError("Single-topic selection could not inspect the Writer brief.")
        if not cached:
            day = _single_day(brief, evidence, proof)
            selected_topic = topic_value.invoke_campaign_selector(day)
            selector = resonance.invoke_selector(day, selected_topic)
            if selector.get("status") != "PASS":
                raise workflow.WorkflowError(
                    f"Resonance Selector blocked the single-topic draft: {selector.get('diagnosis', 'weak feed entry')}"
                )
            cached = {"day": day, "topic_value": selected_topic, "selector": selector}
            _active_single_topic_value = selected_topic
            _active_single_selector = selector

        day = cached["day"]
        selected_topic = cached["topic_value"]
        selector = cached["selector"]
        if not isinstance(day, Mapping) or not isinstance(selected_topic, Mapping) or not isinstance(selector, Mapping):
            raise workflow.WorkflowError("Single-topic selection cache is malformed.")
        enriched_day = resonance.enrich_day(day, selector, selected_topic)
        copied_brief = dict(brief)
        analysis = copied_brief.get("analysis")
        if not isinstance(analysis, Mapping):
            raise workflow.WorkflowError("Writer brief analysis is unavailable for selection enrichment.")
        copied_analysis = dict(analysis)
        copied_analysis["dominant_take"] = str(enriched_day["dominant_take"])
        copied_analysis["missing_angle"] = (
            f"{enriched_day['missing_angle']}\n{enriched_day['artifact_policy']}"
        )
        copied_brief["analysis"] = copied_analysis
        kwargs["brief"] = copied_brief
        return original(*args, **kwargs)

    workflow.build_writer_prompt = build_with_selection  # type: ignore[assignment]
    _active_single_selector = None
    _active_single_topic_value = None
    _active_resonance_diagnostics = {}
    try:
        yield
    finally:
        workflow.build_writer_prompt = original  # type: ignore[assignment]
        _active_single_selector = None
        _active_single_topic_value = None
        _active_resonance_diagnostics = {}


def _command_draft(args: object) -> int:
    """Run selection before Writer and feed resonance after craft in every live draft path."""

    run_spec = getattr(args, "run_spec", None)
    output = getattr(args, "trace_output", None)
    allow_model_egress = getattr(args, "allow_model_egress", False)
    if allow_model_egress is not True:
        return _original_command_draft(args)

    if run_spec is None:
        with _single_topic_selection_prompt():
            result = _original_command_draft(args)
            topic_result = _active_single_topic_value
            selector = _active_single_selector
            diagnostics = dict(_active_resonance_diagnostics)
            if result == 0 and isinstance(topic_result, Mapping) and isinstance(selector, Mapping):
                print(
                    f"Topic Value Selector: PASS ({topic_result.get('total', 'n/a')}/25; "
                    f"route={topic_result.get('reader_value_type', 'n/a')}; "
                    f"gravity={topic_result.get('gravity', 'n/a')}; "
                    f"priority={topic_result.get('priority', 'n/a')})."
                )
                print(
                    f"Resonance Selector: PASS ({selector.get('total', 'n/a')}/25)."
                )
                passed = [
                    item for item in diagnostics.values() if item.get("status") == "PASS"
                ]
                if passed:
                    best = max(passed, key=lambda item: int(item.get("total", 0)))
                    print(
                        f"Resonance Critic: PASS ({best.get('total', 'n/a')}/25; "
                        f"feed_value={best.get('feed_value', 'n/a')}; "
                        f"value_before_ask={best.get('value_before_ask', 'n/a')})."
                    )
            return result

    if output is None:
        return _original_command_draft(args)

    output_root = Path(output)
    original_spec = run_spec
    prepared_spec, selectors = resonance.prepare_campaign_spec(
        Path(run_spec),
        output_root=output_root,
        only_day=getattr(args, "campaign_day", None),
    )
    setattr(args, "run_spec", prepared_spec)
    captured = io.StringIO()
    try:
        with redirect_stdout(captured):
            result = _original_command_draft(args)
    finally:
        setattr(args, "run_spec", original_spec)

    if result != 0:
        print(captured.getvalue(), end="")
        return result

    overlays = resonance.apply_post_gate(
        output_root,
        selectors,
        only_day=getattr(args, "campaign_day", None),
    )
    blocked = {
        day: assessment
        for day, assessment in overlays.items()
        if assessment.get("status") == "BLOCKED"
    }
    if blocked:
        for day, assessment in blocked.items():
            print(
                f"Resonance gate blocked {day}: score={assessment.get('total', 'n/a')}/25; "
                f"feed_value={assessment.get('feed_value', 'n/a')}; "
                f"value_before_ask={assessment.get('value_before_ask', 'n/a')}; "
                f"diagnosis={assessment.get('diagnosis', 'weak feed entry')}"
            )
        print(
            "Craft approval cannot override Topic Value, resonance, or feed-value failure. "
            "Publishing remains disabled."
        )
        return 1

    print(captured.getvalue(), end="")
    for day, selector in selectors.items():
        if getattr(args, "campaign_day", None) not in (None, day):
            continue
        topic_result = selector.get("topic_value")
        if isinstance(topic_result, Mapping):
            print(
                f"Topic Value Selector: {day} {topic_result.get('status')} "
                f"({topic_result.get('total', 'n/a')}/25; "
                f"route={topic_result.get('reader_value_type', 'n/a')}; "
                f"gravity={topic_result.get('gravity', 'n/a')}; "
                f"priority={topic_result.get('priority', 'n/a')})."
            )
        assessment = overlays.get(day)
        print(
            f"Resonance Selector: {day} {selector.get('status')} "
            f"({selector.get('total', 'n/a')}/25)."
        )
        if assessment is not None:
            print(
                f"Resonance Critic: {day} {assessment.get('status')} "
                f"({assessment.get('total', 'n/a')}/25; "
                f"feed_value={assessment.get('feed_value', 'n/a')}; "
                f"value_before_ask={assessment.get('value_before_ask', 'n/a')})."
            )
    return result


quality_cli._qualifying_candidates = _qualifying_candidates  # type: ignore[assignment]
quality_cli._quality_feedback = _quality_feedback  # type: ignore[assignment]
quality_cli.command_draft = _command_draft  # type: ignore[assignment]


def main(argv: list[str] | None = None) -> int:
    return quality_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
