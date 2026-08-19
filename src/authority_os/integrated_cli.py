"""Single-entrypoint integration of topic-value, resonance, high-bar, and anti-slop gates."""

from __future__ import annotations

import io
from collections.abc import Mapping
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

from . import anti_slop, quality_cli, resonance


_original_qualifying = quality_cli._qualifying_candidates
_original_feedback = quality_cli._quality_feedback
_original_command_draft = quality_cli.command_draft


def _qualifying_candidates(*args: Any, **kwargs: Any):
    candidates = _original_qualifying(*args, **kwargs)
    return tuple(candidate for candidate in candidates if anti_slop.passes(candidate.text))


def _quality_feedback(attempt: quality_cli.AttemptResult, cycle: int) -> dict[str, object]:
    feedback = dict(_original_feedback(attempt, cycle))
    rejected = feedback.get("rejected_candidates")
    if isinstance(rejected, list):
        by_id = {candidate.candidate_id: candidate for candidate in attempt.candidates}
        enriched: list[dict[str, object]] = []
        for item in rejected:
            copied = dict(item) if isinstance(item, Mapping) else {}
            candidate = by_id.get(str(copied.get("candidate_id", "")))
            copied["anti_slop_findings"] = (
                [
                    {"code": finding.code, "excerpt": finding.excerpt}
                    for finding in anti_slop.audit(candidate.text)
                ]
                if candidate is not None
                else []
            )
            enriched.append(copied)
        feedback["rejected_candidates"] = enriched
    feedback["anti_slop_required"] = True
    feedback["required_next_action"] = (
        str(feedback.get("required_next_action", ""))
        + " Remove every named anti-slop pattern without weakening the evidence, product decision, or voice."
    ).strip()
    return feedback


def _command_draft(args: object) -> int:
    """Run Topic Value + Resonance before Writer and feed resonance after craft."""

    run_spec = getattr(args, "run_spec", None)
    output = getattr(args, "trace_output", None)
    allow_model_egress = getattr(args, "allow_model_egress", False)
    if run_spec is None or output is None or allow_model_egress is not True:
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
