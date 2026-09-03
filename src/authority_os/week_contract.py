"""Deterministic slot gates derived from published performance, not opinion.

Each rule here traces to an observed result in the 50-post analytics record.
The module answers one question per candidate: may this post occupy this day's
slot? It never scores quality; the Critic still owns that.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from . import hook_stake, workflow

CONTRACT_PATH = workflow.REPO_ROOT / "config" / "week-contract.json"

# --- rule vocabularies -------------------------------------------------------

# Humour: 3 posts, 1-2 engagements each. The shape is a model doing something
# absurd, narrated for the joke, with no decision offered to the reader.
_HUMOUR = re.compile(
    r"(?:\bit (?:wrote|returned|told|said)\b.{0,80}\b(?:confiden|slightly different|again)\w*)"
    r"|\b(?:needed to rest|equally confident|with full confidence)\b"
    r"|^\s*asked (?:chatgpt|the model|claude)\b.{0,120}\bit (?:wrote|returned|gave)\b",
    re.IGNORECASE | re.MULTILINE,
)
_HUMOUR_TAGS = re.compile(r"#\s*(?:aihumor|aifail|ailol|memes?)\b", re.IGNORECASE)

# Teaser: the payload is a pointer, not a payoff. Both attempts scored 1.
_TEASER = re.compile(
    r"\b(?:guess what it is|can you guess|comment below (?:with|if)|any guesses)\b"
    r"|\b(?:wrote up something|been going deep on)\b.{0,140}$"
    r"|\bi (?:won'?t|will not) name it\b"
    r"|\bfor the next \d+ days,? i(?:'ll| will)\b"
    r"|\b(?:stay tuned|drops? (?:tomorrow|next week))\b",
    re.IGNORECASE | re.DOTALL,
)

# Named entity: every post that travelled named a real, checkable thing.
_ENTITY = re.compile(
    r"\b(?:[A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)+)\b"       # Two-word proper nouns
    r"|\b[A-Z][a-z]+[A-Z][A-Za-z0-9]*\b"                          # Internal caps: PocketOS, SaaStr
    r"|\b(?:Claude|ChatGPT|Replit|Gemini|Copilot|OpenAI|Google|Microsoft|Anthropic|GitHub|Cursor)\b"
)

# Achievement-first opening. 2026-07-29 opened this way and drew 6 engagements;
# 2026-07-15 led with the reader's benefit and drew 86.
_ACHIEVEMENT_OPENING = re.compile(
    r"^\s*(?:i\s+(?:shipped|built|launched|created|finished|completed)\b"
    r"|today i(?:'m| am)?\s+(?:shipping|launching|announcing)\b"
    r"|\d+\s+(?:pull requests|prs|tests|hours)\b)",
    re.IGNORECASE,
)
_BENEFIT_MARKER = re.compile(
    r"\b(?:you|your|so that you)\b"
    r"|\b(?:most|every|any)\s+\w+(?:\s+\w+)?\s+(?:optimi[sz]e|use|do|try|think|need|want|struggle|assume)\b"
    r"|\bto (?:improve|raise|fix|cut|save|prevent|catch)\b",
    re.IGNORECASE,
)

# Prescriptive: tells the reader to do something differently.
_PRESCRIPTIVE = re.compile(
    r"\b(?:should|stop|start|do not|don't|never|always|before you|instead of|use|ask)\b",
    re.IGNORECASE,
)

# Plain language: a breakout has to read outside the niche.
_JARGON = (
    "eval harness", "trajectory eval", "pass@k", "rubric calibration", "cohen's kappa",
    "deterministic gate", "adjudication", "observation envelope", "state contract",
)

GATES = ("no_humour", "no_teaser", "named_entity", "benefit_before_achievement",
         "prescriptive", "plain_language", "reader_stake")


@dataclass(frozen=True, slots=True)
class GateResult:
    gate: str
    status: str          # PASS | FAIL | NOT_REQUIRED
    reason_code: str
    evidence: str = ""


def load_contract(path: Path | None = None) -> dict:
    return json.loads((path or CONTRACT_PATH).read_text(encoding="utf-8"))


def _first_line(text: str) -> str:
    for line in text.splitlines():
        if line.strip():
            return line.strip()
    return ""


def _body_without_tags(text: str) -> str:
    return "\n".join(l for l in text.splitlines() if not l.strip().startswith("#"))


def check_gate(gate: str, text: str) -> GateResult:
    body = _body_without_tags(text)
    head = _first_line(body)

    if gate == "no_humour":
        if _HUMOUR.search(body) or _HUMOUR_TAGS.search(text):
            return GateResult(gate, "FAIL", "humour-shape",
                              "Humour posts scored 1, 2 and 2 engagements - the worst three on record.")
        return GateResult(gate, "PASS", "ok")

    if gate == "no_teaser":
        if _TEASER.search(body):
            return GateResult(gate, "FAIL", "teaser-shape",
                              "Both teaser posts drew a single engagement.")
        return GateResult(gate, "PASS", "ok")

    if gate == "named_entity":
        found = _ENTITY.findall(body)
        if not found:
            return GateResult(gate, "FAIL", "no-named-entity",
                              "Every post that travelled named a real, checkable thing.")
        return GateResult(gate, "PASS", "ok", found[0] if isinstance(found[0], str) else "")

    if gate == "benefit_before_achievement":
        if _ACHIEVEMENT_OPENING.match(head):
            return GateResult(gate, "FAIL", "achievement-first",
                              "2026-07-29 opened on the achievement and drew 6; 2026-07-15 opened on the benefit and drew 86.")
        if not _BENEFIT_MARKER.search(head):
            return GateResult(gate, "FAIL", "no-reader-benefit-in-line-1",
                              "The opening does not name what the reader gets.")
        return GateResult(gate, "PASS", "ok")

    if gate == "prescriptive":
        if not _PRESCRIPTIVE.search(body):
            return GateResult(gate, "FAIL", "not-prescriptive",
                              "Top posts tell the reader to do something differently.")
        return GateResult(gate, "PASS", "ok")

    if gate == "reader_stake":
        verdict = hook_stake.evaluate(text)
        if verdict.status == "FAIL":
            return GateResult(gate, "FAIL", verdict.reason_code, verdict.evidence)
        return GateResult(gate, "PASS", "ok", verdict.subject)

    if gate == "plain_language":
        hits = [j for j in _JARGON if j in body.lower()]
        if hits:
            return GateResult(gate, "FAIL", "niche-jargon", "; ".join(hits[:3]))
        return GateResult(gate, "PASS", "ok")

    raise workflow.WorkflowError(f"Unknown slot gate: {gate}")


def slot_for(day_name: str, contract: Mapping | None = None) -> dict | None:
    c = contract or load_contract()
    return c["slots"].get(day_name)


def evaluate(text: str, *, day_name: str, contract: Mapping | None = None) -> dict:
    """Return the slot decision for one candidate on one day."""
    c = contract or load_contract()
    if day_name in c["cadence"]["dark_days"]:
        return {"day": day_name, "slot": None, "status": "BLOCKED",
                "reason_code": "dark-day",
                "gates": [], "evidence": "Saturday is a dark day in this contract."}
    spec = c["slots"].get(day_name)
    if spec is None:
        return {"day": day_name, "slot": None, "status": "BLOCKED",
                "reason_code": "unknown-day", "gates": []}
    results = [check_gate(g, text) for g in spec["required_gates"]]
    failed = [r for r in results if r.status == "FAIL"]
    return {
        "day": day_name,
        "slot": spec["slot"],
        "intent": spec["intent"],
        "status": "PASS" if not failed else "FAIL",
        "reason_code": "ok" if not failed else failed[0].reason_code,
        "judge_on": spec["judge_on"],
        "gates": [asdict(r) for r in results],
    }


def evaluate_for_date(text: str, when: date, contract: Mapping | None = None) -> dict:
    return evaluate(text, day_name=when.strftime("%A"), contract=contract)
