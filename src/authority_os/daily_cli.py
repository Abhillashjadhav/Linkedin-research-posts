"""Live internet discovery for LinkedIn Authority OS.

`./bin/linkedin-os discover` searches current public signals, creates three
high-bar authority theses, stores the evidence privately, and prints the exact
existing draft command for each human choice. It never selects or publishes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import __main__ as legacy_cli
from . import storage, workflow

AXES = ("audience_fit", "distinctiveness", "decision_strength", "proof_fit", "simplicity")
MIN_TOTAL = 23
MIN_SIMPLICITY = 4
MAX_CYCLES = 3
PRIVATE_ROOT = workflow.DEFAULT_PRIVATE_DATA
OUTPUT_ROOT = PRIVATE_ROOT / "daily-discovery"
PROFILE_KEYS = {"target_audience", "authority_goal", "proof_inventory", "avoid_topics", "recent_theses"}
PROOF_KEYS = {"id", "label", "public_safe_claim", "evidence_type"}
CARD_KEYS = {
    "id", "signal_ids", "topic", "thesis", "why_now", "reader_problem",
    "product_decision", "proof_id", "remembered_for", "plain_language_summary",
}


def _schema(kind: str) -> dict[str, object]:
    if kind == "research":
        item = {
            "type": "object",
            "properties": {
                "url": {"type": "string"}, "title": {"type": "string"},
                "body": {"type": "string"}, "source": {"type": "string"},
                "author": {"type": "string"}, "published_at": {"type": "string"},
                "source_quality": {"type": "string", "enum": ["primary", "secondary", "mixed"]},
            },
            "required": ["url", "title", "body", "source", "author", "published_at", "source_quality"],
            "additionalProperties": False,
        }
        return {"type": "object", "properties": {"items": {"type": "array", "minItems": 3, "maxItems": 7, "items": item}}, "required": ["items"], "additionalProperties": False}
    if kind == "cards":
        props = {key: {"type": "string"} for key in CARD_KEYS - {"signal_ids"}}
        props["signal_ids"] = {"type": "array", "minItems": 1, "maxItems": 2, "items": {"type": "string"}}
        card = {"type": "object", "properties": props, "required": sorted(CARD_KEYS), "additionalProperties": False}
        return {"type": "object", "properties": {"cards": {"type": "array", "minItems": 3, "maxItems": 3, "items": card}}, "required": ["cards"], "additionalProperties": False}
    score = {
        "type": "object",
        "properties": {"thesis_id": {"type": "string"}, **{axis: {"type": "integer", "minimum": 1, "maximum": 5} for axis in AXES}},
        "required": ["thesis_id", *AXES],
        "additionalProperties": False,
    }
    return {"type": "object", "properties": {"scorecards": {"type": "array", "minItems": 3, "maxItems": 3, "items": score}}, "required": ["scorecards"], "additionalProperties": False}


def _normal(value: object) -> str:
    return " ".join(str(value).casefold().split())


def _words(value: object) -> int:
    return len(re.findall(r"\b[\w'-]+\b", str(value)))


def _role(name: str) -> str:
    path = workflow.REPO_ROOT / ".claude" / "agents" / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise workflow.WorkflowError(f"{name.title()} prompt is unavailable.") from exc
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) != 3:
            raise workflow.WorkflowError(f"{name.title()} prompt is malformed.")
        text = parts[2]
    if not text.strip():
        raise workflow.WorkflowError(f"{name.title()} prompt is blank.")
    return text.strip()


def _model(prompt: str, system: str, schema: Mapping[str, object], tools: str, label: str, turns: int = 1) -> Mapping[str, object]:
    executable = shutil.which("claude")
    if not executable:
        raise workflow.WorkflowError("Claude CLI is unavailable; install and authenticate it first.")
    command = [
        executable, "--print", "--safe-mode", "--output-format", "json",
        "--json-schema", json.dumps(schema, separators=(",", ":")),
        "--system-prompt", system,
    ]
    command.extend(["--allowedTools", tools] if tools else ["--tools", ""])
    command.extend([
        "--max-turns", str(turns), "--permission-mode", "dontAsk", "--no-chrome",
        "--disable-slash-commands", "--no-session-persistence",
    ])
    try:
        result = subprocess.run(command, input=prompt, cwd=workflow.REPO_ROOT, capture_output=True, text=True, timeout=420, check=False)
    except subprocess.TimeoutExpired as exc:
        raise workflow.WorkflowError(f"{label} timed out.") from exc
    except OSError as exc:
        raise workflow.WorkflowError(f"{label} could not start.") from exc
    if result.returncode:
        raise workflow.WorkflowError(f"{label} failed. Run `claude doctor`; stderr was not printed.")
    try:
        envelope = json.loads(result.stdout)
        if isinstance(envelope, Mapping) and isinstance(envelope.get("structured_output"), Mapping):
            return envelope["structured_output"]  # type: ignore[return-value]
        if isinstance(envelope, Mapping) and isinstance(envelope.get("result"), str):
            nested = json.loads(str(envelope["result"]))
            if isinstance(nested, Mapping):
                return nested
        if isinstance(envelope, Mapping):
            return envelope
    except (json.JSONDecodeError, TypeError) as exc:
        raise workflow.WorkflowError(f"{label} returned invalid JSON.") from exc
    raise workflow.WorkflowError(f"{label} returned an unexpected response.")


def _private_json(path: Path, label: str) -> object:
    supplied = path.expanduser()
    if not supplied.is_absolute():
        supplied = Path.cwd() / supplied
    try:
        _path, text, _metadata = workflow._read_validated_local_text(  # type: ignore[attr-defined]
            supplied, root=PRIVATE_ROOT.absolute(), label=label
        )
    except AttributeError as exc:
        raise workflow.WorkflowError("Secure private-file reading is unavailable.") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise workflow.WorkflowError(f"{label} must contain valid JSON.") from exc


def validate_profile(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping) or set(raw) != PROFILE_KEYS:
        raise workflow.WorkflowError("Authority profile has an invalid schema.")
    profile = dict(raw)
    for key in ("target_audience", "authority_goal"):
        if not isinstance(profile[key], str) or not str(profile[key]).strip():
            raise workflow.WorkflowError(f"Authority profile {key} is blank.")
        profile[key] = str(profile[key]).strip()
    proofs, seen = profile["proof_inventory"], set()
    if not isinstance(proofs, Sequence) or isinstance(proofs, (str, bytes)) or not proofs:
        raise workflow.WorkflowError("proof_inventory must be a non-empty list.")
    cleaned = []
    for proof in proofs:
        if not isinstance(proof, Mapping) or set(proof) != PROOF_KEYS:
            raise workflow.WorkflowError("Authority proof has an invalid schema.")
        item = {key: str(proof[key]).strip() for key in PROOF_KEYS}
        if any(not value for value in item.values()) or re.fullmatch(r"proof-[a-z0-9][a-z0-9-]{0,62}", item["id"]) is None or item["id"] in seen:
            raise workflow.WorkflowError("Authority proofs need distinct non-blank proof-* IDs.")
        seen.add(item["id"])
        cleaned.append(item)
    profile["proof_inventory"] = cleaned
    for key in ("avoid_topics", "recent_theses"):
        values = profile[key]
        if not isinstance(values, Sequence) or isinstance(values, (str, bytes)) or any(not isinstance(value, str) or not value.strip() for value in values):
            raise workflow.WorkflowError(f"{key} must be a list of non-blank strings.")
        profile[key] = [str(value).strip() for value in values]
    return profile


def invoke_scout(topic: str | None, days: int, as_of: str) -> list[dict[str, object]]:
    prompt = f"""Find five defensible GenAI product signals published during the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, evaluations, reliability, enterprise AI and AI product management'}.
Search broadly and read each source body. Prefer official engineering/research blogs, documentation, papers, repositories, government and standards sources. Return concise evidence summaries, not copied prose or post drafts. Never access LinkedIn, email, private data, local files, credentials or authenticated services."""
    result = _model(prompt, _role("scout"), _schema("research"), "WebSearch,WebFetch", "Scout", turns=10)
    items = result.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise workflow.WorkflowError("Scout must return an items list.")
    prepared = workflow.prepare_research_items(items)
    if not 3 <= len(prepared) <= 7:
        raise workflow.WorkflowError("Discovery needs three to seven defensible signals.")
    return prepared


def project_signals(items: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "id": f"signal-{index}", "title": item["title"], "body": item["body"],
            "source": item["source"], "published_at": item["published_at"],
            "source_quality": item["source_quality"], "canonical_url": item["canonical_url"],
        }
        for index, item in enumerate(items, 1)
    ]


def validate_cards(raw: object, signals: Sequence[Mapping[str, object]], profile: Mapping[str, object]) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 3:
        raise workflow.WorkflowError("Thesis generator must return exactly three cards.")
    signal_ids = {str(signal["id"]) for signal in signals}
    proof_ids = {str(proof["id"]) for proof in profile["proof_inventory"] if isinstance(proof, Mapping)}  # type: ignore[index]
    expected, seen, thesis_texts, cards = {"thesis-1", "thesis-2", "thesis-3"}, set(), set(), []
    for raw_card in raw:
        if not isinstance(raw_card, Mapping) or set(raw_card) != CARD_KEYS:
            raise workflow.WorkflowError("Thesis card has an invalid schema.")
        card = dict(raw_card)
        for key in CARD_KEYS - {"signal_ids"}:
            if not isinstance(card[key], str) or not str(card[key]).strip():
                raise workflow.WorkflowError(f"Thesis card field {key} is blank.")
            card[key] = str(card[key]).strip()
        if card["id"] not in expected or card["id"] in seen:
            raise workflow.WorkflowError("Thesis IDs must be thesis-1 through thesis-3.")
        seen.add(card["id"])
        ids = card["signal_ids"]
        if not isinstance(ids, Sequence) or isinstance(ids, (str, bytes)) or not 1 <= len(ids) <= 2:
            raise workflow.WorkflowError("Each thesis must use one or two signal IDs.")
        ids = [str(value).strip() for value in ids]
        if any(value not in signal_ids for value in ids) or len(ids) != len(set(ids)):
            raise workflow.WorkflowError("Thesis signal IDs are invalid.")
        card["signal_ids"] = ids
        if card["proof_id"] not in proof_ids or _words(card["plain_language_summary"]) > 25:
            raise workflow.WorkflowError("Each thesis needs a valid proof and a summary of 25 words or fewer.")
        thesis_key = _normal(card["thesis"])
        if thesis_key in thesis_texts:
            raise workflow.WorkflowError("Theses must be materially distinct.")
        thesis_texts.add(thesis_key)
        cards.append(card)
    if seen != expected:
        raise workflow.WorkflowError("Thesis IDs are incomplete.")
    return cards


def generate_cards(profile: Mapping[str, object], signals: Sequence[Mapping[str, object]], feedback: Mapping[str, object] | None) -> list[dict[str, object]]:
    retry = f"\nUNTRUSTED_PREVIOUS_SCORES\n{json.dumps(feedback, indent=2, sort_keys=True)}\nEND_UNTRUSTED_PREVIOUS_SCORES\nCreate genuinely different theses." if feedback else ""
    prompt = f"""Create exactly three one-idea authority thesis cards. Turn current signals into original product judgment, name a concrete reader problem, state what a team should do differently, connect honestly to one supplied proof ID, and include a non-technical summary of no more than 25 words. The topic field must be a concise phrase using words from the selected signal title so stored evidence can be retrieved later. Do not draft a post or browse. Avoid recent_theses and avoid_topics. Use thesis-1 through thesis-3 exactly once.
UNTRUSTED_PROFILE
{json.dumps(dict(profile), indent=2, sort_keys=True)}
END_UNTRUSTED_PROFILE
UNTRUSTED_SIGNALS
{json.dumps(list(signals), indent=2, sort_keys=True)}
END_UNTRUSTED_SIGNALS{retry}"""
    result = _model(prompt, _role("thesis"), _schema("cards"), "", "Thesis generator")
    return validate_cards(result.get("cards"), signals, profile)


def validate_scores(raw: object, cards: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        raise workflow.WorkflowError("Thesis critic must return scorecards.")
    expected, required, by_id = [str(card["id"]) for card in cards], {"thesis_id", *AXES}, {}
    for item in raw:
        if not isinstance(item, Mapping) or set(item) != required:
            raise workflow.WorkflowError("Thesis scorecard has an invalid schema.")
        thesis_id = item["thesis_id"]
        if not isinstance(thesis_id, str) or thesis_id not in expected or thesis_id in by_id:
            raise workflow.WorkflowError("Thesis scorecard has an invalid ID.")
        score = {"thesis_id": thesis_id}
        for axis in AXES:
            if type(item[axis]) is not int or not 1 <= int(item[axis]) <= 5:
                raise workflow.WorkflowError("Thesis scores must be integers from 1 to 5.")
            score[axis] = int(item[axis])
        score["total"] = sum(int(score[axis]) for axis in AXES)
        by_id[thesis_id] = score
    if set(by_id) != set(expected):
        raise workflow.WorkflowError("Thesis critic must score every card.")
    return [by_id[thesis_id] for thesis_id in expected]


def score_cards(cards: Sequence[Mapping[str, object]], profile: Mapping[str, object], signals: Sequence[Mapping[str, object]]) -> list[dict[str, object]]:
    prompt = f"""Score each thesis from 1 to 5 on exactly {", ".join(AXES)}. Audience fit means useful to the target audience. Distinctiveness rejects generic AI-news summaries. Decision strength requires a concrete choice. Proof fit must be natural and honest. Simplicity must work for a non-engineer. Return scores only; do not rewrite, browse, select or draft.
UNTRUSTED_PROFILE
{json.dumps(dict(profile), indent=2, sort_keys=True)}
END_UNTRUSTED_PROFILE
UNTRUSTED_SIGNALS
{json.dumps(list(signals), indent=2, sort_keys=True)}
END_UNTRUSTED_SIGNALS
UNTRUSTED_CARDS
{json.dumps(list(cards), indent=2, sort_keys=True)}
END_UNTRUSTED_CARDS"""
    result = _model(prompt, "You are a strict authority-thesis critic. Score only.", _schema("scores"), "", "Thesis critic")
    return validate_scores(result.get("scorecards"), cards)


def search_theses(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    generator: Callable[[Mapping[str, object], Sequence[Mapping[str, object]], Mapping[str, object] | None], list[dict[str, object]]] = generate_cards,
    critic: Callable[[Sequence[Mapping[str, object]], Mapping[str, object], Sequence[Mapping[str, object]]], list[dict[str, object]]] = score_cards,
) -> list[dict[str, object]]:
    feedback, rejected = None, set()
    for cycle in range(1, MAX_CYCLES + 1):
        cards = generator(profile, signals, feedback)
        if any(_normal(card["thesis"]) in rejected for card in cards):
            raise workflow.WorkflowError("Thesis generator reused a rejected thesis.")
        scores = {str(score["thesis_id"]): score for score in critic(cards, profile, signals)}
        combined = [{**card, "scores": {axis: int(scores[str(card["id"])][axis]) for axis in AXES}, "total": int(scores[str(card["id"])]["total"])} for card in cards]
        combined.sort(key=lambda card: (-int(card["total"]), -int(card["scores"]["distinctiveness"]), str(card["id"])))  # type: ignore[index]
        if all(int(card["total"]) >= MIN_TOTAL and int(card["scores"]["simplicity"]) >= MIN_SIMPLICITY for card in combined):  # type: ignore[index]
            return combined
        rejected.update(_normal(card["thesis"]) for card in cards)
        feedback = {"cycle": cycle, "required_total": MIN_TOTAL, "required_simplicity": MIN_SIMPLICITY, "rejected": [{"id": card["id"], "thesis": card["thesis"], "scores": card["scores"], "total": card["total"]} for card in combined]}
    raise workflow.WorkflowError("No complete three-thesis set cleared the authority bar. Improve the audience, proof inventory or signals.")


def _under_private(path: Path) -> Path:
    target = Path(os.path.abspath(path.expanduser() if path.is_absolute() else Path.cwd() / path))
    root = Path(os.path.abspath(PRIVATE_ROOT))
    try:
        target.relative_to(root)
    except ValueError:
        raise workflow.WorkflowError("Discovery paths must stay under data/private.") from None
    return target


def write_private_json(path: Path, payload: Mapping[str, object]) -> Path:
    target = _under_private(path)
    legacy_cli._ensure_owner_only_directory(target.parent)
    data = (json.dumps(dict(payload), indent=2, sort_keys=True) + "\n").encode()
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    except FileExistsError:
        raise workflow.WorkflowError("Discovery output already exists.") from None
    try:
        offset = 0
        while offset < len(data):
            count = os.write(descriptor, data[offset:])
            if count < 1:
                raise workflow.WorkflowError("Discovery output was not written completely.")
            offset += count
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    return target


def strategy_for(card: Mapping[str, object], profile: Mapping[str, object]) -> dict[str, str]:
    return {
        "target_reader": str(profile["target_audience"]),
        "reader_problem": str(card["reader_problem"]),
        "core_hypothesis": str(card["thesis"]),
        "product_decision": str(card["product_decision"]),
        "authority_statement": str(card["remembered_for"]),
    }


def command(args: argparse.Namespace) -> int:
    if not args.allow_web_research:
        raise workflow.WorkflowError("Discovery requires --allow-web-research.")
    if not args.allow_model_egress:
        raise workflow.WorkflowError("Discovery requires --allow-model-egress before the private profile reaches thesis models.")
    profile = validate_profile(_private_json(args.profile, "Authority profile"))
    as_of = args.as_of or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    workflow.parse_published_at(as_of)
    items = invoke_scout(args.topic, args.days, as_of)
    signals = project_signals(items)
    theses = search_theses(profile, signals)

    db = _under_private(args.db)
    legacy_cli.initialise_paths(db)
    inserted, duplicates = storage.insert_research_items(db, items, evidence_origin="private-import")
    folder = _under_private(args.output_dir or OUTPUT_ROOT / as_of[:10] / as_of[11:19].replace(":", ""))
    legacy_cli._ensure_owner_only_directory(folder)
    package = write_private_json(folder / "theses.json", {
        "schema_version": 1, "created_at": as_of, "topic": args.topic, "days": args.days,
        "signals": signals, "theses": theses, "publishing_status": "DISABLED",
        "human_selection_required": True,
    })
    db_rel = db.relative_to(workflow.REPO_ROOT).as_posix()
    print(f"Live research stored: inserted={inserted}; duplicates={duplicates}; package={package.relative_to(workflow.REPO_ROOT)}.")
    print("Three theses cleared the locked authority bar:")
    for card in theses:
        strategy = write_private_json(folder / f"strategy-{card['id']}.json", strategy_for(card, profile))
        strategy_rel = strategy.relative_to(workflow.REPO_ROOT).as_posix()
        draft = f"./bin/linkedin-os draft --topic {json.dumps(str(card['topic']))} --goal authority --format text --strategy-input {json.dumps(strategy_rel)} --db {json.dumps(db_rel)} --allow-model-egress --package"
        print(f"{card['id']}: {card['plain_language_summary']} [{card['total']}/25; simplicity={card['scores']['simplicity']}/5]")
        print(f"Decision: {card['product_decision']}")
        print(f"Draft command: {draft}")
    print("No thesis was selected and no post was generated or published.")
    return 0


def _days(value: str) -> int:
    try:
        number = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("days must be an integer") from exc
    if not 1 <= number <= 30:
        raise argparse.ArgumentTypeError("days must be between 1 and 30")
    return number


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="linkedin-os discover", description="Search current signals and return three high-bar authority theses.")
    result.add_argument("--profile", type=Path, required=True)
    result.add_argument("--topic")
    result.add_argument("--days", type=_days, default=7)
    result.add_argument("--as-of")
    result.add_argument("--output-dir", type=Path)
    result.add_argument("--db", type=Path, default=workflow.DEFAULT_DB)
    result.add_argument("--allow-web-research", action="store_true")
    result.add_argument("--allow-model-egress", action="store_true")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        return command(parser().parse_args(argv))
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
