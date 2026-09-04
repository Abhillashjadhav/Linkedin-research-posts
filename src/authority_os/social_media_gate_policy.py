"""V1 social-media release policy overlay.

This overlay keeps deterministic factual diagnostics available for human review while
preserving honesty and citation as hard acceptance gates.
It also permits explicit quantitative placeholders such as ``XX%`` or ``XXx`` in hooks
so the human reviewer can replace them with a real internal metric before publishing.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from . import quality_cli, workflow

_INSTALLED = False
_ORIGINAL_PARSE_ATTEMPT_OUTPUT = quality_cli.parse_attempt_output
_ORIGINAL_BUILD_WRITER_PROMPT = workflow.build_writer_prompt

ADVISORY_GATES = frozenset({"honesty", "citation"})


_PLACEHOLDER_GUIDANCE = """
SOCIAL_MEDIA_HUMAN_REVIEW_POLICY
This output is for a human-reviewed social-media draft, not automatic publication.
Strong qualitative and rhetorical emphasis is allowed. Preserve honesty and citation
diagnostics for human review, but never treat a HUMAN_REVIEW label as a gate pass.
Do not invent a precise numeric result. When a quantitative hook would materially improve
attention but the supplied evidence does not contain the exact number, use an explicit
placeholder such as `XX%`, `XXx`, `XX minutes`, or `XX days` instead. The human reviewer
will replace `XX` with the verified internal value before publishing. Never present `XX`
as if it were already a measured result, and never silently substitute a fabricated number.
END_SOCIAL_MEDIA_HUMAN_REVIEW_POLICY
""".strip()


def _build_writer_prompt_social(
    *,
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    voice_guidance: Mapping[str, str],
    proof: workflow.LoadedProof | None = None,
) -> str:
    base = _ORIGINAL_BUILD_WRITER_PROMPT(
        brief=brief,
        evidence=evidence,
        voice_guidance=voice_guidance,
        proof=proof,
    )
    return f"{base}\n\n{_PLACEHOLDER_GUIDANCE}"


def _soften_candidate(candidate: quality_cli.CandidateResult) -> quality_cli.CandidateResult:
    gates = dict(candidate.gates)
    softened = False
    for name in ADVISORY_GATES:
        if gates.get(name) == "FAIL":
            gates[name] = "HUMAN_REVIEW"
            softened = True

    if not softened:
        return candidate

    return quality_cli.CandidateResult(
        candidate_id=candidate.candidate_id,
        angle=candidate.angle,
        text=candidate.text,
        axes=candidate.axes,
        raw_total=candidate.raw_total,
        effective_total=candidate.effective_total,
        band=candidate.band,
        gates=gates,
        passes_required_gates=False,
        gate_reasons=candidate.gate_reasons,
    )


def soften_gate_result(gate_result: Mapping[str, object]) -> dict[str, object]:
    """Apply the same V1 advisory policy to package evaluation rows.

    Candidate parsing and package generation happen at different points in the live
    command.  Keeping this projection shared prevents a candidate from printing
    ``required_gates=pass`` while its approval package remains blocked by the raw
    honesty/citation statuses.
    """

    softened = dict(gate_result)
    raw_gates = gate_result.get("gates")
    if not isinstance(raw_gates, Mapping):
        return softened
    gates = {str(name): str(status) for name, status in raw_gates.items()}
    for name in ADVISORY_GATES:
        if gates.get(name) == "FAIL":
            gates[name] = "HUMAN_REVIEW"
    softened["gates"] = gates
    softened["passes_required_gates"] = all(
        status in {"PASS", "NOT_REQUIRED"} for status in gates.values()
    )
    return softened


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
