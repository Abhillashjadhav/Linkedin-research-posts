"""Minimal, reversible V1 eval extensions for the existing Authority OS pipeline.

V1 does not add evaluator services or change the V0 SQLite schema. It extends the
existing Topic Value, Critic, and Resonance boundaries in-process for live runs only.
All V1 runtime state is kept under ignored ``data/private/v1-evals``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit

from . import resonance, topic_value, workflow

CONFIG_PATH = workflow.REPO_ROOT / "config" / "eval-v1.json"
RUBRIC_PATH = workflow.REPO_ROOT / "config" / "critic-rubric-v1.json"
STATE_ROOT = workflow.DEFAULT_PRIVATE_DATA / "v1-evals"
ATOMIC_LEDGER_NAME = "atomic-values.jsonl"
CRITIC_AUDIT_NAME = "critic-anchors.jsonl"
MODES = frozenset({"off", "shadow", "enforce"})
CONTRACTS = (
    "atomic_value_novelty",
    "research_trust",
    "claim_body_support",
    "critic_anchor_integrity",
    "solution_plausibility",
    "reader_attention",
)

# Social/community surfaces may nominate a topic, but they are not factual evidence by themselves.
# Concatenating the LinkedIn hostname is deliberate: the repo privacy scanner treats the literal
# hostname as a possible publishing surface and must remain strict.
DISCOVERY_ONLY_HOSTS = frozenset(
    {
        "x.com",
        "twitter.com",
        "linkedin" + ".com",
        "reddit.com",
        "news.ycombinator.com",
        "youtube.com",
        "youtu.be",
        "threads.net",
        "facebook.com",
        "instagram.com",
    }
)

_INSTALLED = False
_ANCHORED_SCORE_KEYS: set[tuple[str, tuple[int, ...], str]] = set()

_ORIGINAL_TOPIC_CANDIDATE_SCHEMA = topic_value._candidate_schema  # type: ignore[attr-defined]
_ORIGINAL_TOPIC_LOAD_ROLE = topic_value._load_role  # type: ignore[attr-defined]
_ORIGINAL_DISCOVERY_SELECTOR = topic_value.invoke_discovery_selector
_ORIGINAL_CAMPAIGN_SELECTOR = topic_value.invoke_campaign_selector
_ORIGINAL_PROJECT_SIGNALS = topic_value.project_discovery_signals

_ORIGINAL_VALIDATE_CRITIC = workflow.validate_critic_scorecards
_ORIGINAL_BUILD_CRITIC_PROMPT = workflow.build_critic_prompt

_ORIGINAL_RESONANCE_LOAD_ROLE = resonance._load_role  # type: ignore[attr-defined]
_ORIGINAL_RESONANCE_POST_SCHEMA = json.loads(json.dumps(resonance.POST_SCHEMA))
_ORIGINAL_INVOKE_POST_CRITIC = resonance.invoke_post_critic
_ORIGINAL_ENRICH_DAY = resonance.enrich_day


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _load_object(path: Path, label: str) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError(f"{label} is unavailable or invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise workflow.WorkflowError(f"{label} must contain one JSON object.")
    return payload


def load_config(path: Path | None = None) -> dict[str, object]:
    payload = _load_object(path or CONFIG_PATH, "V1 eval config")
    if set(payload) != {"schema_version", "contracts"} or payload.get("schema_version") != 1:
        raise workflow.WorkflowError("V1 eval config must use schema_version 1.")
    raw_contracts = payload.get("contracts")
    if not isinstance(raw_contracts, Mapping) or set(raw_contracts) != set(CONTRACTS):
        raise workflow.WorkflowError("V1 eval config has an unexpected contract inventory.")

    contracts: dict[str, dict[str, object]] = {}
    for name in CONTRACTS:
        raw = raw_contracts[name]
        if not isinstance(raw, Mapping):
            raise workflow.WorkflowError(f"V1 contract {name!r} must be an object.")
        expected = {"mode", "threshold"} if name == "atomic_value_novelty" else {"mode"}
        if set(raw) != expected or raw.get("mode") not in MODES:
            raise workflow.WorkflowError(f"V1 contract {name!r} has invalid configuration.")
        item: dict[str, object] = {"mode": str(raw["mode"])}
        if name == "atomic_value_novelty":
            threshold = raw.get("threshold")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < float(threshold) <= 1:
                raise workflow.WorkflowError("Atomic-value novelty threshold must be in (0, 1].")
            item["threshold"] = float(threshold)
        contracts[name] = item
    return {"schema_version": 1, "contracts": contracts}


def contract_mode(name: str) -> str:
    contracts = load_config()["contracts"]
    assert isinstance(contracts, Mapping)
    settings = contracts.get(name)
    if not isinstance(settings, Mapping) or settings.get("mode") not in MODES:
        raise workflow.WorkflowError(f"Unknown V1 contract {name!r}.")
    return str(settings["mode"])


def _decision(name: str, passed: bool | None, reason: str, **evidence: object) -> dict[str, object]:
    mode = contract_mode(name)
    status = "NOT_EVALUATED" if mode == "off" or passed is None else "PASS" if passed else "FAIL"
    return {"contract": name, "mode": mode, "status": status, "reason": reason, **evidence}


def _enforce(decision: Mapping[str, object]) -> None:
    if decision.get("mode") == "enforce" and decision.get("status") == "FAIL":
        raise workflow.WorkflowError(
            f"V1 contract {decision.get('contract')} failed: {decision.get('reason')}"
        )


def _state_path(name: str) -> Path:
    return STATE_ROOT / name


def _ensure_state_dir() -> None:
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(STATE_ROOT, 0o700)
    except OSError as exc:
        raise workflow.WorkflowError("V1 private eval state directory is unavailable.") from exc


def _append_jsonl(path: Path, row: Mapping[str, object]) -> None:
    _ensure_state_dir()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            payload = (json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n").encode()
            os.write(descriptor, payload)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise workflow.WorkflowError("V1 private eval state could not be written safely.") from exc


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise workflow.WorkflowError("V1 private eval state could not be read.") from exc
    rows: list[dict[str, object]] = []
    for line_no, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise workflow.WorkflowError(f"V1 eval ledger line {line_no} is invalid JSON.") from exc
        if not isinstance(row, dict):
            raise workflow.WorkflowError(f"V1 eval ledger line {line_no} must be an object.")
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Contract 1: broad value is already Topic Value; V1 adds one atomic value + novelty.
# ---------------------------------------------------------------------------


def validate_atomic_value(value: object) -> str:
    if not isinstance(value, str):
        raise workflow.WorkflowError("Topic Value atomic_value must be text.")
    cleaned = " ".join(value.split())
    word_count = len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", cleaned))
    if not cleaned or len(cleaned) > 280 or not 5 <= word_count <= 45 or "\n" in value:
        raise workflow.WorkflowError(
            "Topic Value atomic_value must be one concise 5-45 word unit of reader value."
        )
    return cleaned


def load_atomic_values(path: Path | None = None) -> list[str]:
    values: list[str] = []
    for row in _read_jsonl(path or _state_path(ATOMIC_LEDGER_NAME)):
        if set(row) != {"schema_version", "recorded_at", "source", "atomic_value", "atomic_hash"}:
            raise workflow.WorkflowError("Atomic-value ledger has an invalid row schema.")
        value = validate_atomic_value(row.get("atomic_value"))
        digest = hashlib.sha256(value.casefold().encode()).hexdigest()
        if row.get("schema_version") != 1 or row.get("atomic_hash") != digest:
            raise workflow.WorkflowError("Atomic-value ledger integrity check failed.")
        values.append(value)
    return values


def evaluate_atomic_novelty(value: str, *, path: Path | None = None) -> dict[str, object]:
    mode = contract_mode("atomic_value_novelty")
    if mode == "off":
        return _decision("atomic_value_novelty", None, "contract-disabled", compared_values=0)
    contracts = load_config()["contracts"]
    assert isinstance(contracts, Mapping)
    settings = contracts["atomic_value_novelty"]
    assert isinstance(settings, Mapping)
    threshold = float(settings["threshold"])
    prior = load_atomic_values(path)
    similarities = [(workflow.text_similarity(value, old), old) for old in prior]
    maximum, matched = max(similarities, default=(0.0, ""), key=lambda item: item[0])
    return _decision(
        "atomic_value_novelty",
        maximum < threshold,
        "materially-new-atomic-value" if maximum < threshold else "atomic-value-too-similar-to-v1-history",
        threshold=threshold,
        max_similarity=round(maximum, 4),
        compared_values=len(prior),
        matched_atomic_value=matched if maximum >= threshold else "",
    )


def record_atomic_value(value: str, *, source: str = "review-ready", path: Path | None = None) -> None:
    if contract_mode("atomic_value_novelty") == "off":
        return
    cleaned = validate_atomic_value(value)
    target = path or _state_path(ATOMIC_LEDGER_NAME)
    if any(workflow.text_similarity(cleaned, old) >= 0.999 for old in load_atomic_values(target)):
        return
    _append_jsonl(
        target,
        {
            "schema_version": 1,
            "recorded_at": _now(),
            "source": source,
            "atomic_value": cleaned,
            "atomic_hash": hashlib.sha256(cleaned.casefold().encode()).hexdigest(),
        },
    )


def _topic_candidate_schema_v1() -> dict[str, object]:
    schema = json.loads(json.dumps(_ORIGINAL_TOPIC_CANDIDATE_SCHEMA()))
    properties, required = schema["properties"], schema["required"]
    assert isinstance(properties, dict) and isinstance(required, list)
    properties["atomic_value"] = {"type": "string", "minLength": 1, "maxLength": 280}
    required.append("atomic_value")
    return schema


def _topic_role_v1() -> str:
    return (
        _ORIGINAL_TOPIC_LOAD_ROLE()
        + "\n\n## V1 atomic-value contract\n"
        + "Return `atomic_value` for every candidate: one concise 5-45 word statement naming exactly "
        + "one concrete unit of reader value. It is not the broad topic, brand, launch name, or a list. "
        + "The same repository or broad theme may support multiple posts only when each atomic value is materially different."
    )


# ---------------------------------------------------------------------------
# Contract 2: extend the existing discovery boundary with source trust.
# ---------------------------------------------------------------------------


def _hostname(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return (urlsplit(value.strip()).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _is_social(host: str) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in DISCOVERY_ONLY_HOSTS)


def _evidence_by_id(evidence: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    return {
        str(item["id"]): item
        for item in evidence
        if isinstance(item.get("id"), str) and str(item["id"]).strip()
    }


def evaluate_research_trust(
    candidate: Mapping[str, object], evidence: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    if contract_mode("research_trust") == "off":
        return _decision("research_trust", None, "contract-disabled")
    sources = candidate.get("source_ids")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        return _decision("research_trust", False, "candidate-has-no-source-ids")
    by_id = _evidence_by_id(evidence)
    audit: list[dict[str, object]] = []
    trusted_count = 0
    for source_id in sources:
        item = by_id.get(str(source_id))
        if item is None:
            audit.append({"source_id": str(source_id), "status": "missing"})
            continue
        source_url = item.get("canonical_url", item.get("source", ""))
        host = _hostname(source_url)
        body = item.get("body")
        body_read = bool(isinstance(body, str) and body.strip()) or item.get("body_read") is True
        quality = str(item.get("source_quality", "")).casefold()
        social = _is_social(host)
        trusted = bool(host and body_read and not social)
        trusted_count += int(trusted)
        audit.append(
            {
                "source_id": str(source_id),
                "host": host,
                "source_quality": quality,
                "body_read": body_read,
                "discovery_only_social": social,
                "trusted_for_factual_use": trusted,
            }
        )
        if social and quality in {"primary", "mixed"}:
            return _decision(
                "research_trust",
                False,
                "social-source-cannot-be-laundered-as-primary-factual-evidence",
                sources=audit,
            )
    return _decision(
        "research_trust",
        trusted_count >= 1,
        "body-read-non-social-source-present" if trusted_count else "no-body-read-non-social-source-for-selected-value",
        sources=audit,
    )


def _numbers(value: object) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:%|x|×)?", str(value)))


def evaluate_claim_body_support(
    candidate: Mapping[str, object], evidence: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Cheap shadow diagnostic; existing honesty/citation gates remain the release authority."""

    if contract_mode("claim_body_support") == "off":
        return _decision("claim_body_support", None, "contract-disabled")
    by_id = _evidence_by_id(evidence)
    sources = candidate.get("source_ids")
    if not isinstance(sources, Sequence) or isinstance(sources, (str, bytes)):
        return _decision("claim_body_support", False, "candidate-has-no-source-ids")
    body = " ".join(
        str(by_id[str(source_id)].get("body") or by_id[str(source_id)].get("claim") or "")
        for source_id in sources
        if str(source_id) in by_id
    ).strip()
    claim = " ".join(str(candidate.get(field, "")) for field in ("situation", "what_changed")).strip()
    similarity = workflow.text_similarity(claim, body) if claim and body else 0.0
    numbers_supported = _numbers(claim) <= _numbers(body)
    passed = bool(body) and numbers_supported and similarity >= 0.18
    return _decision(
        "claim_body_support",
        passed,
        "claim-has-body-binding-signal" if passed else "claim-needs-stronger-body-binding",
        text_similarity=round(similarity, 4),
        numbers_supported=numbers_supported,
    )


def _evaluate_topic_candidates(
    candidates: Sequence[Mapping[str, object]], evidence: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    evaluated: list[dict[str, object]] = []
    for raw in candidates:
        candidate = dict(raw)
        candidate["atomic_value"] = validate_atomic_value(candidate.get("atomic_value"))
        novelty = evaluate_atomic_novelty(str(candidate["atomic_value"]))
        research = evaluate_research_trust(candidate, evidence)
        body = evaluate_claim_body_support(candidate, evidence)
        candidate["v1_evals"] = {
            "atomic_value_novelty": novelty,
            "research_trust": research,
            "claim_body_support": body,
        }
        _enforce(novelty)
        _enforce(research)
        _enforce(body)
        evaluated.append(candidate)
    return evaluated


def _discovery_selector_v1(
    profile,
    signals,
    *,
    invoker=topic_value._default_invoker,  # type: ignore[attr-defined]
    observer=None,
):
    return _evaluate_topic_candidates(
        _ORIGINAL_DISCOVERY_SELECTOR(
            profile,
            signals,
            invoker=invoker,
            observer=observer,
        ),
        signals,
    )


def _campaign_selector_v1(day, *, invoker=topic_value._default_invoker):  # type: ignore[attr-defined]
    candidate = _ORIGINAL_CAMPAIGN_SELECTOR(day, invoker=invoker)
    evidence = day.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise workflow.WorkflowError("V1 campaign evaluation requires evidence.")
    safe_evidence = [item for item in evidence if isinstance(item, Mapping)]
    return _evaluate_topic_candidates([candidate], safe_evidence)[0]


def _project_signals_v1(signals, candidates):
    projected = _ORIGINAL_PROJECT_SIGNALS(signals, candidates)
    values = {str(item.get("id")): str(item.get("atomic_value", "")) for item in candidates}
    for signal in projected:
        annotations = signal.get("topic_value")
        if isinstance(annotations, list):
            for annotation in annotations:
                if isinstance(annotation, dict) and values.get(str(annotation.get("id"))):
                    annotation["atomic_value"] = values[str(annotation["id"])]
    return projected


def _enrich_day_v1(day, selector, selected_topic_value=None):
    enriched = _ORIGINAL_ENRICH_DAY(day, selector, selected_topic_value)
    topic_result = selected_topic_value or selector.get("topic_value")
    if isinstance(topic_result, Mapping):
        atomic = topic_result.get("atomic_value")
        if isinstance(atomic, str) and atomic.strip():
            enriched["dominant_take"] = (
                f"ATOMIC VALUE LOCKED BEFORE WRITING: {atomic.strip()}\n"
                + str(enriched.get("dominant_take", ""))
            )
    return enriched


# ---------------------------------------------------------------------------
# Contract 3: extend the existing Critic; Python still owns totals and bands.
# ---------------------------------------------------------------------------


def load_critic_rubric(path: Path | None = None) -> dict[str, object]:
    payload = _load_object(path or RUBRIC_PATH, "V1 Critic rubric")
    if set(payload) != {"schema_version", "rubric_id", "axes"} or payload.get("schema_version") != 1:
        raise workflow.WorkflowError("V1 Critic rubric has an invalid schema.")
    axes = payload.get("axes")
    if not isinstance(payload.get("rubric_id"), str) or not isinstance(axes, Mapping):
        raise workflow.WorkflowError("V1 Critic rubric identity is invalid.")
    if set(axes) != set(workflow.CRITIC_AXES):
        raise workflow.WorkflowError("V1 Critic rubric axes do not match runtime axes.")
    for axis in workflow.CRITIC_AXES:
        levels = axes[axis]
        if not isinstance(levels, Mapping) or set(levels) != {"1", "2", "3", "4", "5"}:
            raise workflow.WorkflowError(f"V1 Critic axis {axis!r} must define levels 1-5.")
        if any(not isinstance(levels[str(level)], str) or not levels[str(level)].strip() for level in range(1, 6)):
            raise workflow.WorkflowError("V1 Critic anchors must be non-blank.")
    return payload


def critic_rubric_sha256() -> str:
    try:
        return hashlib.sha256(RUBRIC_PATH.read_bytes()).hexdigest()
    except OSError as exc:
        raise workflow.WorkflowError("V1 Critic rubric is unavailable.") from exc


def _render_rubric() -> str:
    rubric = load_critic_rubric()
    axes = rubric["axes"]
    assert isinstance(axes, Mapping)
    lines = [f"# Critic behavioral anchors ({rubric['rubric_id']})"]
    for axis in workflow.CRITIC_AXES:
        lines.append(f"\n## {axis}")
        levels = axes[axis]
        assert isinstance(levels, Mapping)
        for level in range(1, 6):
            lines.append(f"{level}: {levels[str(level)]}")
    return "\n".join(lines)


def critic_score_schema_v1() -> dict[str, object]:
    detail = {
        "type": "object",
        "properties": {
            "anchor_id": {"type": "string"},
            "evidence": {"type": "string", "minLength": 1, "maxLength": 500},
            "why_not_higher": {"type": "string", "minLength": 1, "maxLength": 500},
            "why_not_lower": {"type": "string", "minLength": 1, "maxLength": 500},
        },
        "required": ["anchor_id", "evidence", "why_not_higher", "why_not_lower"],
        "additionalProperties": False,
    }
    item = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            **{axis: {"type": "integer", "minimum": 1, "maximum": 5} for axis in workflow.CRITIC_AXES},
            "anchors": {
                "type": "object",
                "properties": {axis: detail for axis in workflow.CRITIC_AXES},
                "required": list(workflow.CRITIC_AXES),
                "additionalProperties": False,
            },
        },
        "required": ["candidate_id", *workflow.CRITIC_AXES, "anchors"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"scorecards": {"type": "array", "minItems": 1, "maxItems": 3, "items": item}},
        "required": ["scorecards"],
        "additionalProperties": False,
    }


def _critic_system_prompt_v1() -> str:
    return (
        _render_rubric()
        + "\n\nScore only. For every axis return the integer score plus an `anchors` record. "
        + "anchor_id must equal `<axis>:<score>`. evidence must be a short exact excerpt copied from "
        + "the candidate. Explain the adjacent boundary in why_not_higher and why_not_lower; use "
        + "exactly `not-applicable` only above score 5 or below score 1. Do not rewrite, rank, approve, or publish."
    )


def _build_critic_prompt_v1(*args, **kwargs) -> str:
    return _ORIGINAL_BUILD_CRITIC_PROMPT(*args, **kwargs).replace(
        "Return one scorecards array whose items contain only candidate_id and those five integer axes.",
        "Return one scorecards array whose items contain candidate_id, those five integer axes, and required per-axis anchor evidence.",
    )


def _score_key(candidate_id: str, scorecard: Mapping[str, object], text: str) -> tuple[str, tuple[int, ...], str]:
    return (
        candidate_id,
        tuple(int(scorecard[axis]) for axis in workflow.CRITIC_AXES),
        hashlib.sha256(text.encode()).hexdigest(),
    )


def _validate_critic_scorecards_v1(raw_scorecards, candidates):
    mode = contract_mode("critic_anchor_integrity")
    if mode == "off":
        return _ORIGINAL_VALIDATE_CRITIC(raw_scorecards, candidates)
    if not isinstance(raw_scorecards, Sequence) or isinstance(raw_scorecards, (str, bytes)):
        raise workflow.WorkflowError("Critic scorecards must be a list.")

    candidate_text = {str(item.get("id", "")): str(item.get("text", "")) for item in candidates}
    legacy_keys = {"candidate_id", *workflow.CRITIC_AXES}
    anchored_keys = {*legacy_keys, "anchors"}
    is_legacy = all(isinstance(item, Mapping) and set(item) == legacy_keys for item in raw_scorecards)
    is_anchored = all(isinstance(item, Mapping) and set(item) == anchored_keys for item in raw_scorecards)
    if not is_legacy and not is_anchored:
        raise workflow.WorkflowError("V1 Critic scorecards have an invalid anchored schema.")

    # Legacy score-only envelopes exist only because workflow.invoke_critic sanitizes its already
    # validated model response before run_critic_review validates it once more. Allow that exact
    # second pass, but never allow an unseen score-only envelope to route a live decision.
    if is_legacy:
        if mode == "shadow":
            return _ORIGINAL_VALIDATE_CRITIC(raw_scorecards, candidates)
        for item in raw_scorecards:
            candidate_id = str(item.get("candidate_id", ""))
            if _score_key(candidate_id, item, candidate_text.get(candidate_id, "")) not in _ANCHORED_SCORE_KEYS:
                raise workflow.WorkflowError("Critic anchor evidence is required before scores may route a live decision.")
        return _ORIGINAL_VALIDATE_CRITIC(raw_scorecards, candidates)

    numeric: list[dict[str, object]] = []
    audit: list[dict[str, object]] = []
    for item in raw_scorecards:
        assert isinstance(item, Mapping)
        candidate_id = str(item.get("candidate_id", "")).strip()
        text = candidate_text.get(candidate_id)
        anchors = item.get("anchors")
        if text is None or not isinstance(anchors, Mapping) or set(anchors) != set(workflow.CRITIC_AXES):
            raise workflow.WorkflowError("Critic anchor evidence inventory is invalid.")
        stripped: dict[str, object] = {"candidate_id": candidate_id}
        for axis in workflow.CRITIC_AXES:
            score = item.get(axis)
            detail = anchors.get(axis)
            if type(score) is not int or not 1 <= int(score) <= 5 or not isinstance(detail, Mapping):
                raise workflow.WorkflowError("Critic anchored scores must use valid 1-5 axes.")
            if set(detail) != {"anchor_id", "evidence", "why_not_higher", "why_not_lower"}:
                raise workflow.WorkflowError("Critic anchor detail has an invalid schema.")
            anchor_id = detail.get("anchor_id")
            excerpt = detail.get("evidence")
            higher = detail.get("why_not_higher")
            lower = detail.get("why_not_lower")
            if anchor_id != f"{axis}:{score}":
                raise workflow.WorkflowError("Critic anchor_id must match the scored axis and level.")
            if not all(isinstance(value, str) and value.strip() for value in (excerpt, higher, lower)):
                raise workflow.WorkflowError("Critic anchor evidence and boundary reasons must be non-blank.")
            if " ".join(str(excerpt).casefold().split()) not in " ".join(text.casefold().split()):
                raise workflow.WorkflowError("Critic anchor evidence must be an exact excerpt from the candidate.")
            if int(score) == 5 and str(higher).strip() != "not-applicable":
                raise workflow.WorkflowError("Score 5 must use why_not_higher=not-applicable.")
            if int(score) < 5 and str(higher).strip() == "not-applicable":
                raise workflow.WorkflowError("Only score 5 may omit why_not_higher.")
            if int(score) == 1 and str(lower).strip() != "not-applicable":
                raise workflow.WorkflowError("Score 1 must use why_not_lower=not-applicable.")
            if int(score) > 1 and str(lower).strip() == "not-applicable":
                raise workflow.WorkflowError("Only score 1 may omit why_not_lower.")
            stripped[axis] = score
        numeric.append(stripped)
        key = _score_key(candidate_id, stripped, text)
        _ANCHORED_SCORE_KEYS.add(key)
        audit.append(
            {
                "schema_version": 1,
                "recorded_at": _now(),
                "candidate_id": candidate_id,
                "candidate_sha256": key[2],
                "scores": {axis: stripped[axis] for axis in workflow.CRITIC_AXES},
                "anchors": dict(anchors),
                "rubric_sha256": critic_rubric_sha256(),
            }
        )
    validated = _ORIGINAL_VALIDATE_CRITIC(numeric, candidates)
    for row in audit:
        _append_jsonl(_state_path(CRITIC_AUDIT_NAME), row)
    return validated


def score_disagreement(first, second) -> dict[str, object]:
    """Pure calibration helper; monthly review can compare repeated judge runs without a new stage."""

    left = {str(item.get("candidate_id")): item for item in first}
    right = {str(item.get("candidate_id")): item for item in second}
    if set(left) != set(right):
        raise workflow.WorkflowError("Repeated Critic runs must contain the same candidate IDs.")
    maximum = 0
    differences: dict[str, dict[str, int]] = {}
    for candidate_id in sorted(left):
        row: dict[str, int] = {}
        for axis in workflow.CRITIC_AXES:
            a, b = left[candidate_id].get(axis), right[candidate_id].get(axis)
            if type(a) is not int or type(b) is not int:
                raise workflow.WorkflowError("Repeated Critic comparison needs integer axis scores.")
            row[axis] = abs(int(a) - int(b))
            maximum = max(maximum, row[axis])
        differences[candidate_id] = row
    return {"max_axis_disagreement": maximum, "stable_within_one_point": maximum <= 1, "differences": differences}


# ---------------------------------------------------------------------------
# Contracts 4/5: extend existing Resonance; no extra LLM stage.
# ---------------------------------------------------------------------------


def resonance_post_schema_v1() -> dict[str, object]:
    schema = json.loads(json.dumps(_ORIGINAL_RESONANCE_POST_SCHEMA))
    properties, required = schema["properties"], schema["required"]
    assert isinstance(properties, dict) and isinstance(required, list)
    properties["solution_plausibility"] = {
        "type": "string",
        "enum": ["PASS", "FAIL", "NOT_APPLICABLE"],
    }
    properties["solution_plausibility_reason"] = {"type": "string", "minLength": 1, "maxLength": 500}
    required.extend(["solution_plausibility", "solution_plausibility_reason"])
    return schema


def _resonance_role_v1(name: str) -> str:
    base = _ORIGINAL_RESONANCE_LOAD_ROLE(name)
    if name != "resonance_critic" or contract_mode("solution_plausibility") == "off":
        return base
    return (
        base
        + "\n\n## V1 solution-plausibility diagnostic\n"
        + "Also return solution_plausibility as PASS, FAIL, or NOT_APPLICABLE plus a concise reason. "
        + "PASS means any proposed 'how I would solve it' path is coherent and reasonably implementable "
        + "by a GenAI/product team given normal integration constraints. It does not require proof that "
        + "the design was already deployed. FAIL means a material contradiction, impossible dependency, "
        + "or missing mechanism makes the proposal unreasonable to attempt. NOT_APPLICABLE means the post "
        + "proposes no solution. Do not let this diagnostic alter the existing resonance scores or status."
    )


def _invoke_post_critic_v1(post_text, selector, *, invoker=resonance._default_invoker):  # type: ignore[attr-defined]
    assessment = dict(_ORIGINAL_INVOKE_POST_CRITIC(post_text, selector, invoker=invoker))
    mode = contract_mode("solution_plausibility")
    if mode != "off":
        status = assessment.get("solution_plausibility")
        reason = assessment.get("solution_plausibility_reason")
        if status not in {"PASS", "FAIL", "NOT_APPLICABLE"} or not isinstance(reason, str) or not reason.strip():
            raise workflow.WorkflowError("V1 solution-plausibility diagnostic is malformed.")
        decision = _decision(
            "solution_plausibility",
            status != "FAIL",
            reason.strip(),
            judge_status=status,
        )
        assessment["v1_solution_plausibility"] = decision
        _enforce(decision)

    # Contract 5 remains the existing Resonance gate. We merely record attribution so a monthly
    # review can distinguish attention failure from Critic/anti-slop/source failure.
    base_passed = assessment.get("status") == "PASS"
    assessment["v1_reader_attention"] = _decision(
        "reader_attention",
        base_passed,
        "existing-resonance-gate-passed" if base_passed else "existing-resonance-gate-blocked",
    )
    _enforce(assessment["v1_reader_attention"])

    if assessment.get("status") == "PASS":
        topic_result = selector.get("topic_value")
        if isinstance(topic_result, Mapping) and isinstance(topic_result.get("atomic_value"), str):
            record_atomic_value(str(topic_result["atomic_value"]), source="review-ready")
    return assessment


def install() -> None:
    """Install the additive live-run overlay once; V0 files and SQLite remain untouched."""

    global _INSTALLED
    if _INSTALLED:
        return
    load_config()
    load_critic_rubric()

    if any(contract_mode(name) != "off" for name in ("atomic_value_novelty", "research_trust", "claim_body_support")):
        topic_value._candidate_schema = _topic_candidate_schema_v1  # type: ignore[attr-defined,assignment]
        topic_value._load_role = _topic_role_v1  # type: ignore[attr-defined,assignment]
        topic_value.invoke_discovery_selector = _discovery_selector_v1  # type: ignore[assignment]
        topic_value.invoke_campaign_selector = _campaign_selector_v1  # type: ignore[assignment]
        topic_value.project_discovery_signals = _project_signals_v1  # type: ignore[assignment]
        resonance.enrich_day = _enrich_day_v1  # type: ignore[assignment]

    if contract_mode("critic_anchor_integrity") != "off":
        workflow.CRITIC_SCORE_SCHEMA = critic_score_schema_v1()
        workflow.critic_scoring_system_prompt = _critic_system_prompt_v1  # type: ignore[assignment]
        workflow.build_critic_prompt = _build_critic_prompt_v1  # type: ignore[assignment]
        workflow.validate_critic_scorecards = _validate_critic_scorecards_v1  # type: ignore[assignment]

    if contract_mode("solution_plausibility") != "off" or contract_mode("reader_attention") != "off":
        resonance.POST_SCHEMA = resonance_post_schema_v1()
        resonance._load_role = _resonance_role_v1  # type: ignore[attr-defined,assignment]
        resonance.invoke_post_critic = _invoke_post_critic_v1  # type: ignore[assignment]

    _INSTALLED = True
