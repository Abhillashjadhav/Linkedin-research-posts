"""Deterministic anti-AI-slop checks for public LinkedIn draft candidates.

The rules are adapted from the separate no-ai-slop repository. They are a
hygiene gate, not a truth checker, style score, approval, or engagement model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


BANNED_WORDS = (
    "delve",
    "foster",
    "leverage",
    "utilize",
    "facilitate",
    "empower",
    "streamline",
    "robust",
    "cutting-edge",
    "paradigm shift",
    "game changer",
    "this is huge",
    "this changes everything",
    "tapestry",
    "realm",
    "beacon",
    "multifaceted",
    "meticulous",
    "intricate",
    "paramount",
    "transformative",
    "elevate",
    "embark",
    "supercharge",
    "ever-evolving",
)

_PATTERN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "citation-placeholder",
        re.compile(r"(?i)\[(?:source|claim)-[a-z0-9._-]+\]"),
    ),
    (
        "binary-contrast",
        re.compile(
            r"(?i)\b(?:this|it|the question)\s+(?:is|isn't|is not)\s+not?\b.*?\b(?:it is|it's|is)\b"
        ),
    ),
    (
        "throat-clearing",
        re.compile(
            r"(?im)^\s*(?:here(?:'s| is) the thing|here(?:'s| is) what i mean|let me be clear|i'll be honest|the uncomfortable truth is)\b"
        ),
    ),
    (
        "faux-insight",
        re.compile(
            r"(?i)\b(?:what (?:most people|nobody) (?:miss|get wrong|tell you)|the part (?:everyone|most people) (?:miss|skip))\b"
        ),
    ),
    (
        "rhetorical-setup",
        re.compile(r"(?i)\b(?:what if i told you|think about it:|plot twist:)"),
    ),
    (
        "importance-puffery",
        re.compile(
            r"(?i)\b(?:marks a pivotal moment|stands as a testament|plays a vital role|solidifies its position|underscores its significance)\b"
        ),
    ),
    (
        "hype-harness",
        re.compile(r"(?i)\bharness\s+(?:the\s+)?(?:power|potential)\b"),
    ),
    (
        "weasel-attribution",
        re.compile(r"(?i)\b(?:experts agree|industry reports suggest|many argue|widely regarded as|studies show)\b"),
    ),
    (
        "superficial-analysis",
        re.compile(r"(?i),\s+(?:highlighting|underscoring|reflecting|showcasing)\b"),
    ),
    (
        "fake-profound-kicker",
        re.compile(
            r"(?im)^\s*(?:that(?:'s| is) the whole thing|the future belongs to|the winners? will be|in the end,? .{0,100})\s*[.!]?\s*$"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class Finding:
    code: str
    excerpt: str


def _excerpt(text: str, match: re.Match[str]) -> str:
    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end < 0:
        line_end = len(text)
    return " ".join(text[line_start:line_end].strip().split())[:180]


def audit(text: str) -> tuple[Finding, ...]:
    """Return stable, checkable slop findings for one draft."""

    if not isinstance(text, str) or not text.strip():
        return (Finding("empty-draft", ""),)

    findings: list[Finding] = []
    folded = text.casefold()
    for word in BANNED_WORDS:
        if re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", folded):
            findings.append(Finding("banned-language", word))

    for code, pattern in _PATTERN_RULES:
        match = pattern.search(text)
        if match:
            findings.append(Finding(code, _excerpt(text, match)))

    nonblank_lines = [line.strip() for line in text.splitlines() if line.strip()]
    short_fragments = [
        line
        for line in nonblank_lines
        if len(re.findall(r"[A-Za-z0-9']+", line)) <= 4
        and line.endswith((".", "!", "?"))
    ]
    if len(short_fragments) >= 3:
        findings.append(Finding("dramatic-fragment-stack", " | ".join(short_fragments[:3])[:180]))

    bullet_lines = [
        line for line in nonblank_lines if re.match(r"^(?:[-*•]|\d+[.)])\s+", line)
    ]
    if len(bullet_lines) >= 5:
        findings.append(Finding("decorative-list", " | ".join(bullet_lines[:3])[:180]))

    colon_reveal = re.search(
        r"(?m)^\s*[A-Z][^\n:]{2,70}:\s+[a-z][^\n]{3,120}$", text
    )
    if colon_reveal:
        findings.append(Finding("colon-reveal", _excerpt(text, colon_reveal)))

    return tuple(findings)


def passes(text: str) -> bool:
    return not audit(text)
