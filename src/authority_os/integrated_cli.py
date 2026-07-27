"""Single-entrypoint integration of high-bar and anti-slop draft gates."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from . import anti_slop, quality_cli


_original_qualifying = quality_cli._qualifying_candidates
_original_feedback = quality_cli._quality_feedback


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


quality_cli._qualifying_candidates = _qualifying_candidates  # type: ignore[assignment]
quality_cli._quality_feedback = _quality_feedback  # type: ignore[assignment]


def main(argv: list[str] | None = None) -> int:
    return quality_cli.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
