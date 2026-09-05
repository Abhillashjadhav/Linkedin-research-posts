"""Single-entrypoint integration of topic-value, resonance, high-bar, and anti-slop gates."""

from __future__ import annotations

import io
from collections.abc import Mapping
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from typing import Iterator

from . import acceptance_policy, anti_slop, quality_cli, resonance, v1_completion, workflow


_original_qualifying = quality_cli._qualifying_candidates
_original_feedback = quality_cli._quality_feedback
_original_command_draft = quality_cli.command_draft
_original_render_rejection = quality_cli._render_rejection

_active_single_selector: dict[str, object] | None = None
_active_single_topic_value: dict[str, object] | None = None
_active_resonance_diagnostics: dict[str, dict[str, object]] = {}
_active_acceptance_diagnostics: dict[str, list[str]] = {}


def _record_post_quality(candidate: object) -> None:
    candidate_id = str(getattr(candidate, "candidate_id", ""))
    text = str(getattr(candidate, "text", ""))
    axes = getattr(candidate, "axes", {})
    if not isinstance(axes, Mapping) or not text:
        return
    artifact = v1_completion._sha256_text(text)  # type: ignore[attr-defined]
    findings = anti_slop.audit(text)
    decisions = []
    for axis in workflow.CRITIC_AXES:
        score = int(axes.get(axis, 0))
        threshold = acceptance_policy.AXIS_FLOORS.get(axis)
        enforced = threshold is not None
        shortfall = max(0, threshold - score) if enforced else 0
        decisions.append(
            (
                axis,
                shortfall == 0,
                (
                    f"{axis}-{score}-of-5-meets-{threshold}"
                    if enforced and shortfall == 0
                    else f"{axis}-{score}-of-5-short-by-{shortfall}"
                    if enforced
                    else f"{axis}-{score}-of-5-recorded-for-total"
                ),
                {
                    "score": score,
                    "threshold": threshold,
                    "shortfall": shortfall,
                    "mode": "enforce" if enforced else "diagnostic",
                },
            )
        )
    decisions.append(
        (
            "anti_slop",
            not findings,
            "no-anti-slop-findings" if not findings else "anti-slop-findings-present",
            {"finding_count": len(findings), "threshold": 0, "mode": "diagnostic"},
        )
    )
    for contract, passed, reason, evidence in decisions:
        mode = str(evidence.pop("mode", "enforce"))
        v1_completion.record_decision(
            {
                "contract": contract,
                "mode": mode,
                "status": "PASS" if passed else "FAIL",
                "reason": reason,
                **evidence,
            },
            stage="post-quality",
            subject_id=candidate_id,
            artifact_sha256=artifact,
        )


def _pre_acceptance_failures(
    candidate: object,
    attempt: object,
    kwargs: Mapping[str, object],
) -> list[str]:
    reasons: list[str] = []
    score = int(getattr(candidate, "effective_total", 0))
    if score < acceptance_policy.ACCEPTABLE_QUALITY_FLOOR:
        reasons.append(
            f"critic-total:{score}/25<{acceptance_policy.ACCEPTABLE_QUALITY_FLOOR}/25;"
            f"shortfall={acceptance_policy.ACCEPTABLE_QUALITY_FLOOR - score}"
        )
    axes = getattr(candidate, "axes", {})
    if isinstance(axes, Mapping):
        for axis, detail in acceptance_policy.axis_shortfalls(axes).items():
            reasons.append(
                f"critic-axis:{axis}={detail['observed']}/5<{detail['required']}/5;"
                f"shortfall={detail['shortfall']}"
            )
    return reasons


def _qualifying_candidates(
    attempt: quality_cli.AttemptResult,
    *,
    rejected_openings: set[str],
    package_requested: bool,
    fixture_mode: bool,
    allow_factual_wording_advisory: bool = False,
) -> tuple[quality_cli.CandidateResult, ...]:
    global _active_resonance_diagnostics, _active_acceptance_diagnostics
    candidates = _original_qualifying(
        attempt,
        rejected_openings=rejected_openings,
        package_requested=package_requested,
        fixture_mode=fixture_mode,
        allow_factual_wording_advisory=allow_factual_wording_advisory,
    )
    acceptance_context = {
        "package_requested": package_requested,
        "fixture_mode": fixture_mode,
        "allow_factual_wording_advisory": allow_factual_wording_advisory,
    }
    accepted = []
    _active_acceptance_diagnostics = {}
    all_candidates = getattr(attempt, "candidates", ())
    if all_candidates:
        best_observed = max(
            all_candidates,
            key=lambda candidate: (
                int(getattr(candidate, "effective_total", 0)),
                int(getattr(candidate, "axes", {}).get("hook_strength", 0)),
                str(getattr(candidate, "candidate_id", "")),
            ),
        )
        _record_post_quality(best_observed)
    base_ids = {candidate.candidate_id for candidate in candidates}
    for candidate in all_candidates:
        if candidate.candidate_id not in base_ids:
            _active_acceptance_diagnostics[candidate.candidate_id] = (
                _pre_acceptance_failures(candidate, attempt, acceptance_context)
            )
    accepted = []
    for candidate in candidates:
        reasons = [
            f"anti-slop:{finding.code}:{finding.excerpt}"
            for finding in anti_slop.audit(candidate.text)
        ]
        resonance_passed = True
        if _active_single_selector is not None:
            assessment = resonance.invoke_post_critic(candidate.text, _active_single_selector)
            _active_resonance_diagnostics[candidate.candidate_id] = assessment
            resonance_passed = assessment.get("status") == "PASS"
            if not resonance_passed:
                reasons.append(
                    "resonance:"
                    + str(assessment.get("diagnosis", "post resonance gate failed"))
                )
        if reasons:
            _active_acceptance_diagnostics[candidate.candidate_id] = reasons
        accepted.append(candidate)
    accepted_ids = {candidate.candidate_id for candidate in accepted}
    for candidate in all_candidates:
        candidate_id = str(getattr(candidate, "candidate_id", ""))
        text = str(getattr(candidate, "text", ""))
        reasons = list(_active_acceptance_diagnostics.get(candidate_id, []))
        v1_completion.record_decision(
            {
                "contract": "candidate_acceptance",
                "mode": "enforce",
                "status": "PASS" if candidate_id in accepted_ids else "FAIL",
                "reason": "candidate-cleared-every-acceptance-check" if candidate_id in accepted_ids else " | ".join(reasons),
                "failure_codes": reasons if candidate_id not in accepted_ids else [],
                "advisory_codes": reasons if candidate_id in accepted_ids else [],
            },
            stage="candidate-acceptance",
            subject_id=candidate_id,
            artifact_sha256=v1_completion._sha256_text(text) if text else "",  # type: ignore[attr-defined]
        )
    return tuple(accepted)


def _render_rejection(
    attempt: quality_cli.AttemptResult, cycle: int, limit: int
) -> None:
    _original_render_rejection(attempt, cycle, limit)
    best = max(
        attempt.candidates,
        key=lambda candidate: (
            candidate.effective_total,
            int(candidate.axes.get("hook_strength", 0)),
            candidate.candidate_id,
        ),
    )
    reasons = _active_acceptance_diagnostics.get(best.candidate_id, [])
    if reasons:
        print(
            f"Rejection attribution: {best.candidate_id}: " + " | ".join(reasons)
        )


def _quality_feedback(attempt: quality_cli.AttemptResult, cycle: int) -> dict[str, object]:
    global _active_resonance_diagnostics, _active_acceptance_diagnostics
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
            copied["acceptance_failures"] = list(
                _active_acceptance_diagnostics.get(candidate_id, [])
            )
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
    _active_acceptance_diagnostics = {}
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
def _single_topic_selection_prompt(*, narrow_to_evidence: bool = False) -> Iterator[None]:
    """Reuse the selected thesis, run Resonance once, and inject it into every quality cycle."""

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
            selected_topic = resonance.selected_topic_value_from_day(day)
            selector = resonance.invoke_selector(
                day,
                selected_topic,
                narrow_to_evidence=narrow_to_evidence,
            )
            if selector.get("status") != "PASS":
                print(
                    "Resonance Selector advisory: "
                    f"{resonance.selector_failure_summary(selector)}"
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
        if selector.get("narrowed_to_evidence") is True:
            copied_brief["core_hypothesis"] = str(enriched_day["thesis"])
            copied_brief["product_decision"] = str(enriched_day["product_decision"])
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
        with _single_topic_selection_prompt(
            narrow_to_evidence=bool(getattr(args, "narrow_to_evidence", False))
        ):
            result = _original_command_draft(args)
            topic_result = _active_single_topic_value
            selector = _active_single_selector
            diagnostics = dict(_active_resonance_diagnostics)
            if result == 0 and isinstance(topic_result, Mapping) and isinstance(selector, Mapping):
                if topic_result.get("reader_value_type") == "UPSTREAM_SELECTION":
                    print("Topic selection: reused upstream; not reevaluated during drafting.")
                else:
                    print(
                        f"Topic Value: reused upstream PASS ({topic_result.get('total', 'n/a')}/25; "
                        f"route={topic_result.get('reader_value_type', 'n/a')}; "
                        f"gravity={topic_result.get('gravity', 'n/a')}; "
                        f"priority={topic_result.get('priority', 'n/a')})."
                    )
                print(
                    f"Resonance Selector: {selector.get('status', 'NOT_EVALUATED')} "
                    f"({selector.get('total', 'n/a')}/25)"
                    + ("; advisory." if selector.get("status") != "PASS" else ".")
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
        narrow_to_evidence=bool(getattr(args, "narrow_to_evidence", False)),
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
                f"Resonance advisory for {day}: score={assessment.get('total', 'n/a')}/25; "
                f"feed_value={assessment.get('feed_value', 'n/a')}; "
                f"value_before_ask={assessment.get('value_before_ask', 'n/a')}; "
                f"diagnosis={assessment.get('diagnosis', 'weak feed entry')}"
            )

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
quality_cli._render_rejection = _render_rejection  # type: ignore[assignment]
quality_cli.command_draft = _command_draft  # type: ignore[assignment]


def main(argv: list[str] | None = None) -> int:
    return quality_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
