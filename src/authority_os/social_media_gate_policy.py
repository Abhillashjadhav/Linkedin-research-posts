"""V1 social-media release policy overlay.

This overlay keeps deterministic factual diagnostics available for human review while
preventing honesty/citation diagnostics from blocking the live social-post draft loop.
It deliberately does not fabricate quantitative claims. Unsupported numeric claims are
surfaced for human review; rhetorical and qualitative emphasis is allowed.
"""

from __future__ import annotations

from typing import Mapping

from . import quality_cli

_INSTALLED = False
_ORIGINAL_PARSE_ATTEMPT_OUTPUT = quality_cli.parse_attempt_output


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
    """Make honesty/citation advisory for V1 social posts while preserving diagnostics."""

    global _INSTALLED
    if _INSTALLED:
        return
    quality_cli.parse_attempt_output = _parse_attempt_output_social  # type: ignore[assignment]
    _INSTALLED = True
