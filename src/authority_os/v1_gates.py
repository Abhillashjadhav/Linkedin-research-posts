"""Reversible V1 evaluation contracts layered on top of the working V0 runtime.

V1 deliberately extends existing Topic Value, Critic, and Resonance boundaries instead of
adding parallel evaluator services. Runtime state lives under ignored ``data/private`` and
never changes the V0 SQLite schema. ``install()`` is idempotent and is called only by the live
CLI wrapper; the documented dry-run remains a V0 compatibility path.
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

# Social/community surfaces are useful discovery inputs, but they cannot become factual
# evidence merely because the model labels them primary or mixed.
DISCOVERY_ONLY_HOSTS = frozenset(
    {
        "x.com",
        "twitter.com",
        "linkedin.com",
        "reddit.com",
        "news.ycombinator.com",
        "youtube.com",
        "youtu.be",
        "threads.net",
        "facebook.com",
        "instagram.com",
    }
)

_STOPWORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "are",
        "because",
        "been",
        "before",
        "being",
        "but",
        "can",
        "could",
        "does",
        "for",
        "from",
        "have",
        "into",
        "its",
        "more",
        "not",
        "now",
        "only",
        "our",
        "that",
        "the",
        "their",
        "then",
        "there",
        "these",
        "this",
        "those",
        "through",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)

_INSTALLED = False
_ANCHORED_SCORE_KEYS: set[tuple[str, tuple[int, ...], str]] = set()

_ORIGINAL_TOPIC_CANDIDATE_SCHEMA = topic_value._candidate_schema  # type: ignore[attr-defined]
_ORIGINAL_TOPIC_LOAD_ROLE = topic_value._load_role  # type: ignore[attr-defined]
_ORIGINAL_DISCOVERY_SELECTOR = topic_value.invoke_discovery_selector
_ORIGINAL_CAMPAIGN_SELECTOR = topic_value.invoke_campaign_selector
_ORIGINAL_PROJECT_DISCOVERY_SIGNALS = topic_value.project_discovery_signals
_ORIGINAL_VALIDATE_CRITIC = workflow.validate_critic_scorecards
_ORIGINAL_CRITIC_SYSTEM_PROMPT = workflow.critic_scoring_system_prompt
_ORIGINAL_BUILD_CRITIC_PROMPT = workflow.build_critic_prompt
_ORIGINAL_RESONANCE_LOAD_ROLE = resonance._load_role  # type: ignore[attr-defined]
_ORIGINAL_RESONANCE_POST_SCHEMA = json.loads(json.dumps(resonance.POST_SCHEMA))
_ORIGINAL_INVOKE_POST_CRITIC = resonance.invoke_post_critic


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json(path: Path, label: str) -> Mapping[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError(f"{label} is unavailable or invalid JSON.") from exc
    if not isinstance(payload, Mapping):
        raise workflow.WorkflowError(f"{label} must contain one JSON object.")
    return payload


def load_config(path: Path | None = None) -> dict[str, object]:
    """Load the exact repo-owned V1 switchboard."""

    payload = dict(_json(path or CONFIG_PATH, "V1 eval config"))
    if set(payload) != {"schema_version", "contracts"} or payload.get("schema_version") != 1:
        raise workflow.WorkflowError("V1 eval config must use schema_version 1 and contracts only.")
    contracts = payload.get("contracts")
    if not isinstance(contracts, Mapping) or set(contracts) != set(CONTRACTS):
        raise workflow.WorkflowError("V1 eval config has an unexpected contract inventory.")
    cleaned: dict[str, object] = {}
    for name in CONTRACTS:
        raw = contracts[name]
        if not isinstance(raw, Mapping):
            raise workflow.WorkflowError(f"V1 contract {name!r} must be an object.")
        allowed = {"mode", "threshold"} if name == "atomic_value_novelty" else {"mode"}
        if set(raw) != allowed:
            raise workflow.WorkflowError(f"V1 contract {name!r} has an invalid config schema.")
        mode = raw.get("mode")
        if mode not in MODES:
            raise workflow.WorkflowError(f"V1 contract {name!r} has an invalid mode.")
        item: dict[str, object] = {"mode": mode}
        if name == "atomic_value_novelty":
            threshold = raw.get("threshold")
            if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < float(threshold) <= 1:
                raise workflow.WorkflowError("Atomic-value novelty threshold must be in (0, 1].")
            item["threshold"] = float(threshold)
        cleaned[name] = item
    return {"schema_version": 1, "contracts": cleaned}


def contract_mode(name: str) -> str:
    config = load_config()
    contracts = config["contracts"]
    assert isinstance(contracts, Mapping)
    item = contracts.get(name)
    if not isinstance(item, Mapping) or item.get("mode") not in MODES:
        raise workflow.WorkflowError(f"Unknown V1 contract {name!r}.")
    return str(item["mode"])


def _decision(name: str, passed: bool | None, reason: str, **details: object) -> dict[str, object]:
    mode = contract_mode(name)
    status = "NOT_EVALUATED" if mode == "off" or passed is None else "PASS" if passed else "FAIL"
    return {"contract": name, "mode": mode, "status": status, "reason": reason, **details}


def _enforce(decision: Mapping[str, object]) -> None:
    if decision.get("mode") == "enforce" and decision.get("status") == "FAIL":
        raise workflow.WorkflowError(
            f"V1 contract {decision.get('contract')} failed: {decision.get('reason')}"
        )


def _state_path(name: str) -> Path:
    return STATE_ROOT / name


def _ensure_private_state_dir() -> None:
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(STATE_ROOT, 0o700)
    except OSError as exc:
        raise workflow.WorkflowError("V1 private eval state directory is unavailable.") from exc


def _append_jsonl(path: Path, payload: Mapping[str, object]) -> None:
    _ensure_private_state_dir()
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        try:
            os.fchmod(descriptor, 0o600)
            encoded = (json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            os.write(descriptor, encoded)
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
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise workflow.WorkflowError(f"V1 eval ledger line {index} is invalid JSON.") from exc
        if not isinstance(item, dict):
            raise workflow.WorkflowError(f"V1 eval ledger line {index} must be an object.")
        rows.append(item)
    return rows


def _atomic_words(value: str) -> int:
    return len(re.findall(r"[A-Za-z0-9][A-Za-z0-9'’-]*", value))


def validate_atomic_value(value: object) -> str:
    if not isinstance(value, str):
        raise workflow.WorkflowError("Topic Value atomic_value must be text.")
    cleaned = " ".join(value.split())
    if (
        not cleaned
        or len(cleaned) > 280
        or not 5 <= _atomic_words(cleaned) <= 45
        or "\n" in value
        or cleaned.startswith(("-", "*", "•"))
    ):
        raise workflow.WorkflowError(
            "Topic Value atomic_value must be one concise 5-45 word unit of reader value."
        )
    return cleaned


def load_atomic_values(path: Path | None = None) -> list[str]:
    rows = _read_jsonl(path or _state_path(ATOMIC_LEDGER_NAME))
    values: list[str] = []
    for index, row in enumerate(rows, start=1):
        if set(row) != {"schema_version", "recorded_at", "source", "atomic_value", "atomic_hash"}:
            raise workflow.WorkflowError(f"Atomic-value ledger row {index} has an invalid schema.")
        if row.get("schema_version") != 1:
            raise workflow.WorkflowError("Atomic-value ledger schema is unsupported.")
        value = validate_atomic_value(row.get("atomic_value"))
        expected = hashlib.sha256(value.casefold().encode("utf-8")).hexdigest()
        if row.get("atomic_hash") != expected:
            raise workflow.WorkflowError("Atomic-value ledger integrity check failed.")
        values.append(value)
    return values


def evaluate_atomic_novelty(value: str, *, path: Path | None = None) -> dict[str, object]:
    mode = contract_mode("atomic_value_novelty")
    if mode == "off":
        return _decision("atomic_value_novelty", None, "contract-disabled", compared_values=0)
    config = load_config()["contracts"]
    assert isinstance(config, Mapping)
    settings = config["atomic_value_novelty"]
    assert isinstance(settings, Mapping)
    threshold = float(settings["threshold"])
    prior = load_atomic_values(path)
    comparisons = [(workflow.text_similarity(value, previous), previous) for previous in prior]
    maximum, matched = max(comparisons, default=(0.0, ""), key=lambda item: item[0])
    decision = _decision(
        "atomic_value_novelty",
        maximum < threshold,
        "materially-new-atomic-value" if maximum < threshold else "atomic-value-too-similar-to-v1-history",
        threshold=threshold,
        max_similarity=round(maximum, 4),
        compared_values=len(prior),
        matched_atomic_value=matched if maximum >= threshold else "",
    )
    return decision


def record_atomic_value(value: str, *, source: str = "resonance-pass", path: Path | None = None) -> None:
    if contract_mode("atomic_value_novelty") == "off":
        return
    cleaned = validate_atomic_value(value)
    target = path or _state_path(ATOMIC_LEDGER_NAME)
    prior = load_atomic_values(target)
    if any(workflow.text_similarity(cleaned, previous) >= 0.999 for previous in prior):
        return
    _append_jsonl(
        target,
        {
            "schema_version": 1,
            "recorded_at": _now(),
            "source": source,
            "atomic_value": cleaned,
            "atomic_hash": hashlib.sha256(cleaned.casefold().encode("utf-8")).hexdigest(),
        },
    )


def _host(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        return (urlsplit(value.strip()).hostname or "").casefold().removeprefix("www.")
    except ValueError:
        return ""


def _social_host(host: str) -> bool:
    return any(host == domain or host.endswith("." + domain) for domain in DISCOVERY_ONLY_HOSTS)


def _evidence_map(evidence: Sequence[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
    result: dict[str, Mapping[str, object]] = {}
    for item in evidence:
        identifier = item.get("id")
        if isinstance(identifier, str) and identifier.strip():
            result[identifier.strip()] = item
    return result


def evaluate_research_trust(
    candidate: Mapping[str, object], evidence: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    if contract_mode("research_trust") == "off":
        return _decision("research_trust", None, "contract-disabled")
    by_id = _evidence_map(evidence)
    source_ids = candidate.get("source_ids")
    if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)):
        return _decision("research_trust", False, "candidate-has-no-source-ids")
    inspected: list[dict[str, object]] = []
    credible = 0
    for source_id in source_ids:
        item = by_id.get(str(source_id))
        if item is None:
            inspected.append({"source_id": str(source_id), "status": "missing"})
            continue
        url = item.get("canonical_url", item.get("source", ""))
        host = _host(url)
        body = item.get("body")
        body_read = bool(isinstance(body, str) and body.strip()) or item.get("body_read") is True
        quality = str(item.get("source_quality", "")).casefold()
        social = _social_host(host)
        trusted = bool(host and body_read and not social)
        if trusted:
            credible += 1
        inspected.append(
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
                sources=inspected,
            )
    return _decision(
        "research_trust",
        credible >= 1,
        "body-read-non-social-source-present" if credible else "no-body-read-non-social-source-for-selected-value",
        sources=inspected,
    )


def _content_tokens(value: object) -> set[str]:
    tokens = set(re.findall(r"[A-Za-z0-9][A-Za-z0-9._/-]*", str(value).casefold()))
    return {token for token in tokens if len(token) >= 3 and token not in _STOPWORDS}


def _numbers(value: object) -> set[str]:
    return set(re.findall(r"(?<![A-Za-z])\d+(?:[.,]\d+)*(?:%|x|×)?", str(value)))


def evaluate_claim_body_support(
    candidate: Mapping[str, object], evidence: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    if contract_mode("claim_body_support") == "off":
        return _decision("claim_body_support", None, "contract-disabled")
    by_id = _evidence_map(evidence)
    source_ids = candidate.get("source_ids")
    if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)):
        return _decision("claim_body_support", False, "candidate-has-no-source-ids")
    supporting_text = " ".join(
        str(by_id[str(source_id)].get("body", by_id[str(source_id)].get("claim", "")))
        for source_id in source_ids
        if str(source_id) in by_id
    )
    claim = " ".join(
        str(candidate.get(field, "")) for field in ("situation", "what_changed")
    ).strip()
    claim_tokens = _content_tokens(claim)
    evidence_tokens = _content_tokens(supporting_text)
    overlap = len(claim_tokens & evidence_tokens) / len(claim_tokens) if claim_tokens else 0.0
    numbers_supported = _numbers(claim) <= _numbers(supporting_text)
    # This is intentionally a shadow-friendly lexical diagnostic, not a semantic truth oracle.
    passed = bool(supporting_text.strip()) and numbers_supported and (not claim_tokens or overlap >= 0.25)
    return _decision(
        "claim_body_support",
        passed,
        "lexical-and-numeric-support-observed" if passed else "selected-claim-needs-stronger-body-binding",
        lexical_overlap=round(overlap, 4),
        numbers_supported=numbers_supported,
    )


def _topic_candidate_schema_v1() -> dict[str, object]:
    schema = json.loads(json.dumps(_ORIGINAL_TOPIC_CANDIDATE_SCHEMA()))
    properties = schema["properties"]
    required = schema["required"]
    assert isinstance(properties, dict) and isinstance(required, list)
    properties["atomic_value"] = {"type": "string", "minLength": 1, "maxLength": 280}
    if "atomic_value" not in required:
        required.append("atomic_value")
    return schema


def _topic_role_v1() -> str:
    base = _ORIGINAL_TOPIC_LOAD_ROLE()
    return (
        f"{base}\n\n"
        "## V1 atomic-value contract\n"
        "Every candidate must include `atomic_value`: one concise 5-45 word statement naming exactly "
        "one concrete unit of value the reader gains from this situation. It is not the broad topic, "
        "company name, launch name, or a list of takeaways. The same repository or broad theme may "
        "support many posts only when each candidate contributes a materially different atomic value."
    )


def _evaluate_topic_candidates(
    candidates: Sequence[Mapping[str, object]], evidence: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    evaluated: list[dict[str, object]] = []
    for raw in candidates:
        candidate = dict(raw)
        atomic = validate_atomic_value(candidate.get("atomic_value"))
        candidate["atomic_value"] = atomic
        novelty = evaluate_atomic_novelty(atomic)
        research = evaluate_research_trust(candidate, evidence)
        body_support = evaluate_claim_body_support(candidate, evidence)
        candidate["v1_evals"] = {
            "atomic_value_novelty": novelty,
            "research_trust": research,
            "claim_body_support": body_support,
        }
        _enforce(novelty)
        _enforce(research)
        _enforce(body_support)
        evaluated.append(candidate)
    return evaluated


def _discovery_selector_v1(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    *,
    invoker=topic_value._default_invoker,  # type: ignore[attr-defined]
) -> list[dict[str, object]]:
    candidates = _ORIGINAL_DISCOVERY_SELECTOR(profile, signals, invoker=invoker)
    return _evaluate_topic_candidates(candidates, signals)


def _campaign_selector_v1(
    day: Mapping[str, object],
    *,
    invoker=topic_value._default_invoker,  # type: ignore[attr-defined]
) -> dict[str, object]:
    candidate = _ORIGINAL_CAMPAIGN_SELECTOR(day, invoker=invoker)
    evidence = day.get("evidence")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise workflow.WorkflowError("V1 campaign evaluation requires evidence.")
    return _evaluate_topic_candidates([candidate], [item for item in evidence if isinstance(item, Mapping)])[0]


def _project_discovery_signals_v1(
    signals: Sequence[Mapping[str, object]], candidates: Sequence[Mapping[str, object]]
) -> list[dict[str, object]]:
    projected = _ORIGINAL_PROJECT_DISCOVERY_SIGNALS(signals, candidates)
    atomic_by_id = {str(candidate.get("id")): str(candidate.get("atomic_value", "")) for candidate in candidates}
    for signal in projected:
        annotations = signal.get("topic_value")
        if not isinstance(annotations, list):
            continue
        for annotation in annotations:
            if isinstance(annotation, dict):
                atomic = atomic_by_id.get(str(annotation.get("id")), "")
                if atomic:
                    annotation["atomic_value"] = atomic
    return projected


def load_critic_rubric(path: Path | None = None) -> dict[str, object]:
    payload = dict(_json(path or RUBRIC_PATH, "V1 Critic rubric"))
    if set(payload) != {"schema_version", "rubric_id", "axes"} or payload.get("schema_version") != 1:
        raise workflow.WorkflowError("V1 Critic rubric has an invalid top-level schema.")
    rubric_id = payload.get("rubric_id")
    axes = payload.get("axes")
    if not isinstance(rubric_id, str) or not rubric_id.strip() or not isinstance(axes, Mapping):
        raise workflow.WorkflowError("V1 Critic rubric identity is invalid.")
    if set(axes) != set(workflow.CRITIC_AXES):
        raise workflow.WorkflowError("V1 Critic rubric axes do not match the runtime Critic axes.")
    cleaned_axes: dict[str, dict[str, str]] = {}
    expected_levels = {str(level) for level in range(1, 6)}
    for axis in workflow.CRITIC_AXES:
        raw_levels = axes[axis]
        if not isinstance(raw_levels, Mapping) or set(raw_levels) != expected_levels:
            raise workflow.WorkflowError(f"V1 Critic axis {axis!r} must define levels 1 through 5.")
        levels: dict[str, str] = {}
        for level in range(1, 6):
            text = raw_levels[str(level)]
            if not isinstance(text, str) or not text.strip():
                raise workflow.WorkflowError("V1 Critic anchor text must be non-blank.")
            levels[str(level)] = text.strip()
        cleaned_axes[axis] = levels
    return {"schema_version": 1, "rubric_id": rubric_id.strip(), "axes": cleaned_axes}


def critic_rubric_sha256() -> str:
    try:
        data = RUBRIC_PATH.read_bytes()
    except OSError as exc:
        raise workflow.WorkflowError("V1 Critic rubric is unavailable.") from exc
    return hashlib.sha256(data).hexdigest()


def _render_critic_rubric() -> str:
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
    anchor_detail = {
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
    scorecard = {
        "type": "object",
        "properties": {
            "candidate_id": {"type": "string"},
            **{
                axis: {"type": "integer", "minimum": 1, "maximum": 5}
                for axis in workflow.CRITIC_AXES
            },
            "anchors": {
                "type": "object",
                "properties": {axis: anchor_detail for axis in workflow.CRITIC_AXES},
                "required": list(workflow.CRITIC_AXES),
                "additionalProperties": False,
            },
        },
        "required": ["candidate_id", *workflow.CRITIC_AXES, "anchors"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "scorecards": {"type": "array", "minItems": 1, "maxItems": 3, "items": scorecard}
        },
        "required": ["scorecards"],
        "additionalProperties": False,
    }


def _critic_system_prompt_v1() -> str:
    return (
        f"{_render_critic_rubric()}\n\n"
        "Score only. Return one scorecard for every supplied candidate. For each of the five axes, "
        "return the integer score plus an `anchors` record. `anchor_id` must be exactly `<axis>:<score>`. "
        "`evidence` must copy a short exact excerpt from the candidate that demonstrates why the anchor "
        "applies. `why_not_higher` and `why_not_lower` must explain the adjacent boundary; use exactly "
        "`not-applicable` for why_not_lower at score 1 and why_not_higher at score 5. Do not rewrite, "
        "revise, rank, select, approve, package, publish, or make a downstream decision."
    )


def _build_critic_prompt_v1(*args, **kwargs) -> str:
    base = _ORIGINAL_BUILD_CRITIC_PROMPT(*args, **kwargs)
    base = base.replace(
        "Return one scorecards array whose items contain only candidate_id and those five integer axes.",
        "Return one scorecards array whose items contain candidate_id, those five integer axes, and the required per-axis anchors evidence object.",
    )
    return base


def _candidate_text_by_id(candidates: Sequence[Mapping[str, object]]) -> dict[str, str]:
    return {str(candidate.get("id", "")): str(candidate.get("text", "")) for candidate in candidates}


def _score_key(candidate_id: str, scores: Mapping[str, object], text: str) -> tuple[str, tuple[int, ...], str]:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return (
        candidate_id,
        tuple(int(scores[axis]) for axis in workflow.CRITIC_AXES),
        digest,
    )


def _excerpt_supported(excerpt: str, candidate_text: str) -> bool:
    excerpt_norm = " ".join(excerpt.casefold().split())
    candidate_norm = " ".join(candidate_text.casefold().split())
    return bool(excerpt_norm) and excerpt_norm in candidate_norm


def _validate_critic_scorecards_v1(
    raw_scorecards: Sequence[Mapping[str, object]],
    candidates: Sequence[Mapping[str, object]],
) -> list[dict[str, object]]:
    mode = contract_mode("critic_anchor_integrity")
    if mode == "off":
        return _ORIGINAL_VALIDATE_CRITIC(raw_scorecards, candidates)
    if not isinstance(raw_scorecards, Sequence) or isinstance(raw_scorecards, (str, bytes)):
        raise workflow.WorkflowError("Critic scorecards must be a list.")
    texts = _candidate_text_by_id(candidates)
    anchored_required = {"candidate_id", *workflow.CRITIC_AXES, "anchors"}
    legacy_required = {"candidate_id", *workflow.CRITIC_AXES}
    anchored = all(isinstance(item, Mapping) and set(item) == anchored_required for item in raw_scorecards)
    legacy = all(isinstance(item, Mapping) and set(item) == legacy_required for item in raw_scorecards)
    if not anchored and not legacy:
        raise workflow.WorkflowError("V1 Critic scorecards have an invalid anchored schema.")

    if legacy:
        if mode == "shadow":
            return _ORIGINAL_VALIDATE_CRITIC(raw_scorecards, candidates)
        for item in raw_scorecards:
            candidate_id = str(item.get("candidate_id", ""))
            text = texts.get(candidate_id, "")
            if _score_key(candidate_id, item, text) not in _ANCHORED_SCORE_KEYS:
                raise workflow.WorkflowError("Critic anchor evidence is required before scores may route a live decision.")
        return _ORIGINAL_VALIDATE_CRITIC(raw_scorecards, candidates)

    stripped: list[dict[str, object]] = []
    audit_rows: list[dict[str, object]] = []
    for item in raw_scorecards:
        candidate_id = str(item.get("candidate_id", "")).strip()
        text = texts.get(candidate_id, "")
        anchors = item.get("anchors")
        if candidate_id not in texts or not isinstance(anchors, Mapping) or set(anchors) != set(workflow.CRITIC_AXES):
            raise workflow.WorkflowError("Critic anchor evidence inventory is invalid.")
        clean_scores = {axis: item.get(axis) for axis in workflow.CRITIC_AXES}
        for axis in workflow.CRITIC_AXES:
            score = clean_scores[axis]
            detail = anchors.get(axis)
            if type(score) is not int or not 1 <= int(score) <= 5 or not isinstance(detail, Mapping):
                raise workflow.WorkflowError("Critic anchored scores must use valid 1-5 axes.")
            if set(detail) != {"anchor_id", "evidence", "why_not_higher", "why_not_lower"}:
                raise workflow.WorkflowError("Critic anchor detail has an invalid schema.")
            anchor_id = detail.get("anchor_id")
            evidence = detail.get("evidence")
            higher = detail.get("why_not_higher")
            lower = detail.get("why_not_lower")
            if anchor_id != f"{axis}:{score}":
                raise workflow.WorkflowError("Critic anchor_id must match the scored axis and level.")
            if not all(isinstance(value, str) and value.strip() for value in (evidence, higher, lower)):
                raise workflow.WorkflowError("Critic anchor evidence and boundary reasons must be non-blank.")
            if not _excerpt_supported(str(evidence), text):
                raise workflow.WorkflowError("Critic anchor evidence must be an exact excerpt from the candidate.")
            if int(score) == 5 and str(higher).strip() != "not-applicable":
                raise workflow.WorkflowError("Score 5 must use why_not_higher=not-applicable.")
            if int(score) == 1 and str(lower).strip() != "not-applicable":
                raise workflow.WorkflowError("Score 1 must use why_not_lower=not-applicable.")
            if int(score) < 5 and str(higher).strip() == "not-applicable":
                raise workflow.WorkflowError("Only score 5 may omit the higher-boundary explanation.")
            if int(score) > 1 and str(lower).strip() == "not-applicable":
                raise workflow.WorkflowError("Only score 1 may omit the lower-boundary explanation.")
        stripped_item = {"candidate_id": candidate_id, **clean_scores}
        stripped.append(stripped_item)
        key = _score_key(candidate_id, stripped_item, text)
        _ANCHORED_SCORE_KEYS.add(key)
        audit_rows.append(
            {
                "schema_version": 1,
                "recorded_at": _now(),
                "candidate_id": candidate_id,
                "candidate_sha256": key[2],
                "scores": clean_scores,
                "anchors": dict(anchors),
                "rubric_sha256": critic_rubric_sha256(),
            }
        )
    validated = _ORIGINAL_VALIDATE_CRITIC(stripped, candidates)
    for row in audit_rows:
        _append_jsonl(_state_path(CRITIC_AUDIT_NAME), row)
    return validated


def score_disagreement(
    first: Sequence[Mapping[str, object]], second: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    """Pure helper for monthly repeated-judge calibration; it makes no model call."""

    by_first = {str(item.get("candidate_id")): item for item in first}
    by_second = {str(item.get("candidate_id")): item for item in second}
    if set(by_first) != set(by_second):
        raise workflow.WorkflowError("Repeated Critic runs must contain the same candidate IDs.")
    differences: dict[str, dict[str, int]] = {}
    maximum = 0
    for candidate_id in sorted(by_first):
        axis_diffs: dict[str, int] = {}
        for axis in workflow.CRITIC_AXES:
            left, right = by_first[candidate_id].get(axis), by_second[candidate_id].get(axis)
            if type(left) is not int or type(right) is not int:
                raise workflow.WorkflowError("Repeated Critic comparison needs integer axis scores.")
            diff = abs(int(left) - int(right))
            axis_diffs[axis] = diff
            maximum = max(maximum, diff)
        differences[candidate_id] = axis_diffs
    return {"max_axis_disagreement": maximum, "stable_within_one_point": maximum <= 1, "differences": differences}


def _resonance_role_v1(name: str) -> str:
    base = _ORIGINAL_RESONANCE_LOAD_ROLE(name)
    if name != "resonance_critic" or contract_mode("solution_plausibility") == "off":
        return base
    return (
        f"{base}\n\n"
        "## V1 solution-plausibility diagnostic\n"
        "Also return `solution_plausibility` as PASS, FAIL, or NOT_APPLICABLE and a concise "
        "`solution_plausibility_reason`. PASS means any proposed 'how I would solve it' path is "
        "coherent and reasonably implementable by a GenAI/product team given normal integration "
        "constraints. It does not require proof that the architecture was already deployed. FAIL "
        "means the proposed path contains a material contradiction, impossible dependency, or missing "
        "mechanism that makes it unreasonable to attempt. NOT_APPLICABLE means the post proposes no "
        "solution. This diagnostic must not influence the existing resonance scores or status."
    )


def resonance_post_schema_v1() -> dict[str, object]:
    schema = json.loads(json.dumps(_ORIGINAL_RESONANCE_POST_SCHEMA))
    properties = schema["properties"]
    required = schema["required"]
    assert isinstance(properties, dict) and isinstance(required, list)
    properties["solution_plausibility"] = {
        "type": "string",
        "enum": ["PASS", "FAIL", "NOT_APPLICABLE"],
    }
    properties["solution_plausibility_reason"] = {"type": "string", "minLength": 1, "maxLength": 500}
    for field in ("solution_plausibility", "solution_plausibility_reason"):
        if field not in required:
            required.append(field)
    return schema


def _invoke_post_critic_v1(
    post_text: str,
    selector: Mapping[str, object],
    *,
    invoker=resonance._default_invoker,  # type: ignore[attr-defined]
) -> dict[str, object]:
    assessment = dict(_ORIGINAL_INVOKE_POST_CRITIC(post_text, selector, invoker=invoker))
    base_status = str(assessment.get("status", ""))
    mode = contract_mode("solution_plausibility")
    if mode != "off":
        plausibility = assessment.get("solution_plausibility")
        reason = assessment.get("solution_plausibility_reason")
        if plausibility not in {"PASS", "FAIL", "NOT_APPLICABLE"} or not isinstance(reason, str) or not reason.strip():
            raise workflow.WorkflowError("V1 solution-plausibility diagnostic is malformed.")
        decision = _decision(
            "solution_plausibility",
            plausibility != "FAIL",
            reason.strip(),
            judge_status=plausibility,
        )
        assessment["v1_solution_plausibility"] = decision
        if mode == "enforce" and plausibility == "FAIL":
            assessment["status"] = "BLOCKED"
            assessment["diagnosis"] = "solution-plausibility-failed: " + reason.strip()[:400]
    assessment["v1_reader_attention"] = _decision(
        "reader_attention",
        base_status == "PASS",
        "existing-resonance-gate-passed" if base_status == "PASS" else "existing-resonance-gate-blocked",
    )

    # Record only after a completed post clears the currently enforced public-value gates.
    if assessment.get("status") == "PASS":
        topic_result = selector.get("topic_value")
        if isinstance(topic_result, Mapping) and isinstance(topic_result.get("atomic_value"), str):
            record_atomic_value(str(topic_result["atomic_value"]), source="resonance-pass")
    return assessment


def install() -> None:
    """Install the V1 overlay once without mutating the V0 persistence schema."""

    global _INSTALLED
    if _INSTALLED:
        return
    # Validate all versioned assets before touching runtime functions.
    load_config()
    load_critic_rubric()

    if contract_mode("atomic_value_novelty") != "off" or contract_mode("research_trust") != "off" or contract_mode("claim_body_support") != "off":
        topic_value._candidate_schema = _topic_candidate_schema_v1  # type: ignore[attr-defined,assignment]
        topic_value._load_role = _topic_role_v1  # type: ignore[attr-defined,assignment]
        topic_value.invoke_discovery_selector = _discovery_selector_v1  # type: ignore[assignment]
        topic_value.invoke_campaign_selector = _campaign_selector_v1  # type: ignore[assignment]
        topic_value.project_discovery_signals = _project_discovery_signals_v1  # type: ignore[assignment]

    if contract_mode("critic_anchor_integrity") != "off":
        workflow.CRITIC_SCORE_SCHEMA = critic_score_schema_v1()
        workflow.critic_scoring_system_prompt = _critic_system_prompt_v1  # type: ignore[assignment]
        workflow.build_critic_prompt = _build_critic_prompt_v1  # type: ignore[assignment]
        workflow.validate_critic_scorecards = _validate_critic_scorecards_v1  # type: ignore[assignment]

    if contract_mode("solution_plausibility") != "off":
        resonance.POST_SCHEMA = resonance_post_schema_v1()
        resonance._load_role = _resonance_role_v1  # type: ignore[attr-defined,assignment]
        resonance.invoke_post_critic = _invoke_post_critic_v1  # type: ignore[assignment]

    _INSTALLED = True
