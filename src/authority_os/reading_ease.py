"""Local English Flesch estimate, not a comprehension or humour verdict.

Formula: 206.835 - 1.015 * words/sentences - 84.6 * syllables/words.
Syllables are heuristic; short posts, names, acronyms and numerals are noisy.
No model calls, dependencies, acceptance veto or regeneration loop.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

_WORD = re.compile(r"[A-Za-z]+(?:['’][A-Za-z]+)?|\d+(?:\.\d+)?")


def _syllables(word: str) -> int:
    if word.isupper() and len(word) <= 5:
        return sum(3 if letter == "W" else 1 for letter in word)
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 1  # Numerals are an approximate single spoken unit.
    count = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and not re.search(r"[^aeiouy]le$", word) and count > 1:
        count -= 1
    if word.endswith("ed") and not word.endswith(("ted", "ded")) and count > 1:
        count -= 1
    return max(1, count)


def measure(text: str, style: str = "standard") -> dict:
    # Preserve link labels but exclude URL spelling from prose difficulty.
    prose = re.sub(r"\[([^\]]+)\]\(https?://[^\s)]+\)", r"\1", text)
    prose = re.sub(r"https?://\S+", "", prose)
    # A decimal point is not a sentence boundary.
    prose = re.sub(r"(?<=\d)\.(?=\d)", "", prose)
    words = _WORD.findall(prose)
    sentences = [part for part in re.split(r"[.!?]+|\n\s*\n", prose) if _WORD.search(part)]
    target = 80 if style == "short-humorous" else 70
    result = {"method": "flesch-english-heuristic-v1", "estimated": True,
              "advisory_only": True, "target": target, "words": len(words),
              "sentences": len(sentences), "score": None, "status": "NOT_EVALUATED"}
    if not words or not sentences:
        return result
    syllables = sum(_syllables(word) for word in words)
    score = round(206.835 - 1.015 * len(words) / len(sentences) - 84.6 * syllables / len(words), 1)
    result.update(score=score, syllables=syllables,
                  status="ON_TARGET" if score >= target else "SIMPLIFY")
    return result


def label(result: Mapping | None) -> str:
    if not result or result.get("score") is None:
        return "Flesch Reading Ease: not evaluated"
    return (f"Flesch Reading Ease (estimated): {result['score']}; target >= {result['target']}; "
            f"{result['status']} (advisory; not a humour score)")


def instructions(style: str) -> str:
    target = 80 if style == "short-humorous" else 70
    return (
        f"\nPLAIN_LANGUAGE: Aim for estimated Flesch Reading Ease >= {target}. "
        "Use familiar words and short natural sentences. State who did what and why it matters. "
        "Translate necessary jargon where it appears; avoid abstract noun stacks and obscure metaphors. "
        "Preserve every factual qualifier: simpler language must not exaggerate the finding. "
        "Do not game readability by chopping sentences or deleting important context. "
        "A high score does not establish understanding or humour.\n"
    )
