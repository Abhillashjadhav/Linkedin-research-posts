"""Reusable writing briefs shared by Writer, Narrative Editor and Critic."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import reading_ease

STYLE_NAMES = ("standard", "short-humorous", "educational-resources", "build-video", "incident-mitigation")
CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "post-styles.json"


def contract(style: str = "standard") -> dict[str, object]:
    if style not in STYLE_NAMES:
        raise ValueError(f"Unsupported post style: {style}")
    if style == "standard":
        return {}
    return dict(json.loads(CONFIG_PATH.read_text(encoding="utf-8"))[style])


def shortlist_floor(style: str = "short-humorous") -> int:
    policy = json.loads((CONFIG_PATH.parent / "weekly-spine.json").read_text())["selection"]
    return int(policy["shortlist_total_exclusive"]) + 1


def opening(brief: Mapping[str, object]) -> str:
    spec = contract(str(brief.get("post_style", "standard")))
    return str(spec["opening"]) if spec else (
        "LINE 1 MUST lead with the strongest supported recognisable name, incident, number or scale. "
        "LINE 2 MUST state the immediate reader consequence, useful artifact, or decision payoff."
    )


def instructions(brief: Mapping[str, object]) -> str:
    style = str(brief.get("post_style", "standard"))
    spec = contract(style)
    if not spec:
        return reading_ease.instructions(style)
    lower, upper = spec["target_words"]
    return (
        reading_ease.instructions(style)
        + f"\nPOST_STYLE: {style}\n"
        f"Aim for {lower}–{upper} words, with a target ceiling of "
        f"{spec['maximum_target_words']} words. Do not pad this into a long authority post.\n"
        f"{spec['voice']}\n{spec['opening']}\n"
        f"{spec['content']} Judge the existing five axes against this requested format.\n"
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
