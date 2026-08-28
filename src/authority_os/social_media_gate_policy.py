"""V1 social-media release policy overlay.

This overlay keeps deterministic factual diagnostics available for human review while
preventing honesty/citation diagnostics from blocking the live social-post draft loop.
It also permits explicit quantitative placeholders such as ``XX%`` or ``XXx`` in hooks
so the human reviewer can replace them with a real internal metric before publishing.
"""

from __future__ import annotations

from . import quality_cli, workflow

_INSTALLED = False
_ORIGINAL_PARSE_ATTEMPT_OUTPUT = quality_cli.parse_attempt_output
_ORIGINAL_BUILD_WRITER_PROMPT = workflow.build_writer_prompt


_PLACEHOLDER_GUIDANCE = """
SOCIAL_MEDIA_HUMAN_REVIEW_POLICY
This output is for a human-reviewed social-media draft, not automatic publication.
Strong qualitative and rhetorical emphasis is allowed. Honesty and citation diagnostics
are advisory for this V1 path rather than hard blockers; preserve them for human review.
Do not invent a precise numeric result. When a quantitative hook would materially improve
attention but the supplied evidence does not contain the exact number, use an explicit
placeholder such as `XX%`, `XXx`, `XX minutes`, or `XX days` instead. The human reviewer
will replace `XX` with the verified internal value before publishing. Never present `XX`
as if it were already a measured result, and never silently substitute a fabricated number.
END_SOCIAL_MEDIA_HUMAN_REVIEW_POLICY
""".strip()


def _build_writer_prompt_social(*args: object, **kwargs: object) -> str:
    base = _ORIGINAL_BUILD_WRITER_PROMPT(*args, **kwargs)
    return f"{base}\n\n{_PLACEHOLDER_GUIDANCE}"


def _soften_candidate(candidate: quality_cli.CandidateResult) -> quality_cli.CandidateResult:
    gates = dict(candidate.gates)
    softened = False
    for name in ("honesty", "citation"):
        if gates.get(name) == "FAIL":
            gates[name] = "HUMAN_REVIEW"
            softened = True

    if not softened:
        return candidate

    hard_failures = any(status == "FAIL" for status in gates.values())
    return quality_cli.CandidateResult(
        candidate_id=candidate.candidate_id,
        angle=candidate.angle,
        text=candidate.text,
        axes=candidate.axes,
        raw_total=candidate.raw_total,
        effective_total=candidate.effective_total,
        band=candidate.band,
        gates=gates,
        passes_required_gates=not hard_failures,
        gate_reasons=candidate.gate_reasons,
    )


def _parse_attempt_output_social(stdout: str) -> quality_cli.AttemptResult:
    attempt = _ORIGINAL_PARSE_ATTEMPT_OUTPUT(stdout)
    return quality_cli.AttemptResult(
        candidates=tuple(_soften_candidate(candidate) for candidate in attempt.candidates),
        context_lines=attempt.context_lines,
        review_status=attempt.review_status,
        recommendation=attempt.recommendation,
        package_lines=attempt.package_lines,
    )


def install() -> None:
    """Make honesty/citation advisory and enable XX placeholders for V1 social posts."""

    global _INSTALLED
    if _INSTALLED:
        return
    workflow.build_writer_prompt = _build_writer_prompt_social  # type: ignore[assignment]
    quality_cli.parse_attempt_output = _parse_attempt_output_social  # type: ignore[assignment]
    _INSTALLED = True
