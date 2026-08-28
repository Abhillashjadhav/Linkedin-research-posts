"""V1-only social-post length policy.

Frozen V0 keeps its historical word ranges. Current live V1 authority drafts only enforce
that the post is non-empty and no longer than 300 words; quality and hook gates decide
whether a shorter post is good enough for human review.
"""

from __future__ import annotations

from . import workflow

_INSTALLED = False


def install() -> None:
    """Relax only the V1 authority lower word bound while preserving the 300-word cap."""
    global _INSTALLED
    if _INSTALLED:
        return
    workflow.TEXT_WORD_LIMITS = dict(workflow.TEXT_WORD_LIMITS)
    workflow.TEXT_WORD_LIMITS["authority"] = (1, 300)
    _INSTALLED = True
