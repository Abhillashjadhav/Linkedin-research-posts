"""Reusable writing briefs shared by Writer, Narrative Editor and Critic."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

STYLE_NAMES = ("standard", "short-humorous")
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "post-styles.json"


def contract(style: str = "standard") -> dict[str, object]:
    if style not in STYLE_NAMES:
        raise ValueError(f"Unsupported post style: {style}")
    if style == "standard":
        return {}
    return dict(json.loads(CONFIG_PATH.read_text(encoding="utf-8"))[style])


def shortlist_floor(style: str = "short-humorous") -> int:
    return int(contract(style)["shortlist_total_exclusive"]) + 1


def instructions(brief: Mapping[str, object]) -> str:
    style = str(brief.get("post_style", "standard"))
    spec = contract(style)
    if not spec:
        return ""
    lower, upper = spec["target_words"]
    return (
        f"\nPOST_STYLE: {style}\n"
        f"Aim for {lower}–{upper} words, with a target ceiling of "
        f"{spec['maximum_target_words']} words. Do not pad this into a long authority post.\n"
        f"{spec['voice']}\n{spec['opening']}\n"
        "Keep one concrete product implication in the post. A concise joke can carry the "
        "middle and closer; do not require a long explanation or a checklist. Judge the "
        "existing five axes against this requested format. Do not award humour points "
        "merely for fragments, sarcasm, or a tidy contrast.\n"
        "Use only verified facts supplied in the evidence. Do not insert XX placeholders "
        "or send a fact-filling task back to the reader. Distinguish a joke or conditional "
        "recommendation from a reported event.\nEND_POST_STYLE\n"
    )


def rank_scorecards(scorecards: Sequence[Mapping[str, object]]) -> list[Mapping[str, object]]:
    """The hook wins among candidates that already clear the owner's total bar."""
    return sorted(
        scorecards,
        key=lambda row: (
            int(row.get("hook_strength", 0)),
            int(row.get("effective_total", 0)),
            str(row.get("candidate_id", "")),
        ),
        reverse=True,
    )


def hook_verdict(score: object) -> str:
    """A readable label for the anchored score, never another model or veto."""
    if type(score) is not int or not 1 <= score <= 5:
        return "UNCERTAIN"
    return "PASS" if score >= 4 else "FAIL"
