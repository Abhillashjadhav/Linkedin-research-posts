"""The reader must have a stake in the hook.

Derived from 30 published posts with measured outcomes. The strongest single
signal in the corpus is negative: when the hook's subject is the author's own
work, the post underperforms. It appeared in 60% of the posts that flopped and
13% of the posts that landed.

    "Our AI feature had great adoption at launch"        lift 0.34
    "I shipped a working product in 7 hours 4 minutes"   lift 0.49
    "Why does it think I'm based in Belgium?"            lift 0.50

    "Nine seconds. That is how long it took an agent
     to delete PocketOS's production database"           lift 3.83
    "Most decision-makers use AI to write faster.
     The 1% use it to think better."                     lift 4.13

Same author, same craft, same niche. The difference is whose problem it is.
A workplace anecdote is good writing that nobody else has a stake in; a named
external failure is everyone's problem and is checkable.

First person is not the fault. Three posts that landed open in first person -
a salary benchmark, a reading list, a pricing decision - because the author is
the vehicle and the reader owns the outcome. The rule is about the SUBJECT, not
the pronoun.

With the existing humour and teaser gates, this reaches kappa 0.80 and a false
positive rate of 0.0 on the calibration set: it never passes a post that flopped.
The fit is in-sample on 30 items and needs out-of-sample confirmation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

HOOK_LINES = 2

# Register is measured, not listed. A blocklist of literary words runs to
# millions and still misses the next one; his own corpus plus a frozen
# common-English list generalises with nothing to maintain. The list is frozen
# at build time so the runtime keeps this repository's zero-dependency boundary.
# See data/voice/voice-profile.json.
#
# It catches rare literary vocabulary. It does not catch idioms built from
# common words - "shy of" rather than "short of" - which is why the result is a
# flag handed to the judge rather than a verdict on its own.
_PROFILE_PATH = Path(__file__).resolve().parents[2] / "data" / "voice" / "voice-profile.json"
_profile: dict | None = None


def _load() -> dict:
    global _profile
    if _profile is None:
        try:
            _profile = json.loads(_PROFILE_PATH.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _profile = {}
    return _profile


def _known_words() -> set[str]:
    profile = _load()
    return set(profile.get("corpus_words", ())) | set(profile.get("common_english_words", ()))


def off_register_words(text: str) -> list[str]:
    """Words that are neither common English nor his. A prior, not a verdict.

    Capitalised tokens are skipped: a proper noun is not a register choice, and
    a rare-word check that flags PocketOS or Jason Lemkin is measuring the wrong
    thing. Sentence-initial words are skipped with them, which costs little
    because openers are ordinary words.
    """
    known = _known_words()
    if not known:
        return []
    found: list[str] = []
    for token in re.findall(r"\b[A-Za-z][A-Za-z']{2,}\b", text):
        if token[0].isupper() or any(c.isupper() for c in token[1:]):
            continue
        word = token.lower()
        for suffix in ("'s", "'"):
            if word.endswith(suffix):
                word = word[: -len(suffix)]
                break
        if word and word not in known and word not in found:
            found.append(word)
    return found


# A checkable third party. Not an exhaustive list - a maintained one, because a
# regex that tries to detect "any proper noun" also matches the author's own
# product names, which is exactly the failure case.
NAMED_EXTERNAL = re.compile(
    r"\b(Claude|ChatGPT|OpenAI|Anthropic|Google|Gemini|Microsoft|Copilot|Replit|"
    r"Cursor|GitHub|Meta|Amazon|Netflix|Stripe|Figma|Notion|Salesforce|"
    r"Karpathy|Willison|SaaStr|PocketOS|Jason Lemkin|"
    r"Institute of Product Leadership)\b"
)

# The reader, or a group the reader belongs to.
READER_GROUP = re.compile(
    r"^\W*(most \w+|your |every \w+|an ai agent|any \w+)"
    r"|\b(ai pms should|pms should|teams should|most (?:pms|teams|decision-makers|"
    r"people|engineers|founders|ai tools)|we keep saying|you (?:should|need|cannot|can't))\b",
    re.IGNORECASE,
)

# The author's own work as the SUBJECT of the hook.
OWN_WORK = re.compile(
    r"\b(our (?:ai|new|feature|agent|team|product|shopping|summari|lowest|customer)"
    r"|i shipped|i tried|i wired|i'm calling|i am calling|my linkedin|we run an"
    r"|i had already|i started a|our agent|i spent (?:last )?(?:week|weekend)"
    r"|this week i (?:tried|built|shipped))",
    re.IGNORECASE,
)

# A stake the reader owns even when the sentence is first person: a figure they
# benchmark against, a decision they will face, a resource they can take.
READER_STAKE = re.compile(
    r"\b(\$\d|\d+\s*(?:%|x\b)|million|per seat|per month|price|pricing|salary|offer|paid"
    r"|books?|courses?|resources?|reading|playbook|template|checklist"
    r"|budget|cost|invoice|finance|hiring|interview)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class StakeVerdict:
    status: str          # PASS | FAIL
    reason_code: str
    subject: str         # named-external | reader-group | reader-stake | own-work | unclear
    evidence: str = ""


def hook_of(text: str, lines: int = HOOK_LINES) -> str:
    body = [l.strip() for l in text.splitlines()
            if l.strip() and not l.strip().startswith("#")]
    return " ".join(body[:lines])


def evaluate(text: str) -> StakeVerdict:
    """Does the reader have a stake in this hook?"""
    hook = hook_of(text)
    if not hook:
        return StakeVerdict("FAIL", "empty-hook", "unclear")

    off = off_register_words(hook)
    if off:
        return StakeVerdict(
            "FAIL", "off-register-word", "unclear",
            f"{', '.join(off[:3])} — neither common English nor in his corpus. "
            f"If one is a domain term, publishing the post adds it and the flag stops.",
        )

    named = NAMED_EXTERNAL.search(hook)
    group = READER_GROUP.search(hook)
    stake = READER_STAKE.search(hook)
    own = OWN_WORK.search(hook)

    # A group opener does not rescue a hook whose subject is still your project:
    # "Most PMs talk about AI agents. I built one to run my LinkedIn" scored 0.66.
    # Only a named external party or a concrete reader stake overrides own-work.
    if own and not (named or stake):
        return StakeVerdict(
            "FAIL", "subject-is-your-own-work", "own-work",
            f"'{own.group(0)}' — rewrite so the reader owns the outcome, "
            f"or name the external party this happened to.",
        )
    if named:
        return StakeVerdict("PASS", "ok", "named-external", named.group(0))
    if group:
        return StakeVerdict("PASS", "ok", "reader-group", group.group(0).strip())
    if stake:
        return StakeVerdict("PASS", "ok", "reader-stake", stake.group(0))
    return StakeVerdict(
        "FAIL", "no-reader-stake", "unclear",
        "The hook names no external party, addresses no group, and offers the "
        "reader nothing to benchmark or decide against.",
    )
