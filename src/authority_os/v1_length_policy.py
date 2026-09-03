"""V1 social-post length policy, calibrated against measured conversion.

The earlier V1 policy removed the lower bound entirely and kept a 300-word cap,
on the reasoning that the quality and hook gates would decide whether a short
post was good enough. The published record does not support that: across 21
posts with recovered bodies, word count correlates with lift at r = +0.58, and
the relationship survives removing the humour and teaser posts, so it is not
merely a proxy for "this one had something to say".

Median lift by band:

    under 200 words   0.57
    200-279 words     1.92
    280+ words        2.87

Every post below 200 words sat in the bottom half. The 300-word cap also cut
across the shape of the two strongest posts, at 316 and 359 words.

So V1 inverts the previous policy: it restores a floor and lifts the ceiling.
The floor is the load-bearing half. Length is not the cause of conversion -
substance is - but a short post is reliably a thin one, and capping length cuts
the substance out with it.
"""

from __future__ import annotations

from . import workflow

_INSTALLED = False

# Floor, ceiling. Derived from the bands above, with the ceiling set beyond the
# longest observed strong post rather than at it.
V1_AUTHORITY_WORDS = (200, 380)


def install() -> None:
    """Apply the evidence-calibrated V1 authority word range."""
    global _INSTALLED
    if _INSTALLED:
        return
    workflow.TEXT_WORD_LIMITS = dict(workflow.TEXT_WORD_LIMITS)
    workflow.TEXT_WORD_LIMITS["authority"] = V1_AUTHORITY_WORDS
    _INSTALLED = True
