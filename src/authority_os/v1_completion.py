"""Finish the reversible V1 eval loop without adding another product stage.

This module is installed after :mod:`authority_os.v1_gates` on live commands. It adds
provenance and calibration around the existing V1 contracts:

* review-ready atomic values are bound to the exact final post hash, but novelty history
  advances only after a confirmed manual-publication performance write succeeds;
* one private decision ledger gives every V1 contract a stage and artifact identity;
* one extra Critic call per live command is sampled in shadow to measure score stability;
* the existing weekly-review command records a V1 calibration snapshot for later monthly
  product review without changing the rubric automatically.

V0 SQLite, CLI commands, release thresholds, and model providers are unchanged.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Mapping, Sequence

from . import campaign, learning, performance, resonance, storage, v1_gates, workflow

STATE_ROOT = v1_gates.STATE_ROOT
CALIBRATION_CONFIG_PATH = workflow.REPO_ROOT / "config" / "eval-v1-calibration.json"
PUBLISHED_ATOMIC_LEDGER_NAME = "published-atomic-values.jsonl"
ATOMIC_BINDINGS_LEDGER_NAME = "review-ready-atomic-bindings.jsonl"
DECISION_LEDGER_NAME = "decisions.jsonl"
CALIBRATION_LEDGER_NAME = "calibration-snapshots.jsonl"
MAX_LEDGER_BYTES = 5_000_000
RUN_ID_ENV = "LINKEDIN_OS_RUN_ID"
RUN_ID_PATTERN = re.compile(r"[A-Za-z0-9._:@+-]{1,160}")

_INSTALLED = False
_REPRO_SAMPLED = {"legacy": False, "campaign": False}
_PROCESS_RUN_ID = ""

# These are captured when this module is imported. The live launcher imports us only after
# v1_gates.install(), so the captured Topic Value/Critic/Resonance functions already include
# the first V1 layer.
_BASE_TOPIC_EVALUATOR = v1_gates._evaluate_topic_candidates  # type: ignore[attr-defined]
_BASE_VALIDATE_CRITIC = workflow.validate_critic_scorecards
_BASE_POST_CRITIC = resonance.invoke_post_critic
_BASE_WORKFLOW_INVOKE_CRITIC = workflow.invoke_critic
_BASE_CAMPAIGN_INVOKER = campaign.default_stage_invoker
_BASE_RECORD_PERFORMANCE_MANY = storage.record_performance_many
_BASE_WRITE_WEEKLY_REVIEW = learning.write_weekly_review


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def begin_run(run_id: str | None = None) -> str:
    """Create and expose one opaque identity for an end-to-end V1 run."""

    global _PROCESS_RUN_ID
    value = run_id or (
        "linkedin-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(6)
    )
    if RUN_ID_PATTERN.fullmatch(value) is None:
        raise workflow.WorkflowError("V1 run ID must be a bounded public-safe label.")
    _PROCESS_RUN_ID = value
    os.environ[RUN_ID_ENV] = value
    return value


def current_run_id() -> str:
    """Return the process run ID, inheriting it across the draft subprocess."""

    global _PROCESS_RUN_ID
    if _PROCESS_RUN_ID:
        return _PROCESS_RUN_ID
    inherited = os.environ.get(RUN_ID_ENV, "")
    if inherited:
        if RUN_ID_PATTERN.fullmatch(inherited) is None:
            raise workflow.WorkflowError("Inherited V1 run ID is invalid.")
        _PROCESS_RUN_ID = inherited
        return inherited
    return begin_run()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _safe_token(value: object, *, maximum: int = 160) -> str:
    cleaned = " ".join(str(value).split())[:maximum]
    return cleaned if cleaned.isprintable() else "<redacted>"


def _state_path(name: str) -> Path:
    return STATE_ROOT / name


def _ensure_state_root() -> None:
    try:
        STATE_ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        metadata = os.lstat(STATE_ROOT)
        if not stat.S_ISDIR(metadata.st_mode) or stat.S_ISLNK(metadata.st_mode):
            raise workflow.WorkflowError("V1 calibration state directory is unsafe.")
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise workflow.WorkflowError("V1 calibration state directory is not owner-controlled.")
        os.chmod(STATE_ROOT, 0o700)
    except workflow.WorkflowError:
        raise
    except OSError as exc:
        raise workflow.WorkflowError("V1 calibration state directory is unavailable.") from exc


def _append_jsonl(path: Path, row: Mapping[str, object]) -> None:
    _ensure_state_root()
    if path.parent != STATE_ROOT:
        raise workflow.WorkflowError("V1 calibration state path escaped its private root.")
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise workflow.WorkflowError("V1 calibration ledger must be a regular file.")
        if hasattr(os, "geteuid") and metadata.st_uid != os.geteuid():
            raise workflow.WorkflowError("V1 calibration ledger is not owner-controlled.")
        os.fchmod(descriptor, 0o600)
        payload = (
            json.dumps(dict(row), sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        view = memoryview(payload)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short ledger write")
            view = view[written:]
        os.fsync(descriptor)
    except workflow.WorkflowError:
        raise
    except OSError as exc:
        raise workflow.WorkflowError("V1 calibration ledger could not be written safely.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise workflow.WorkflowError("V1 calibration ledger is unavailable.") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or metadata.st_size > MAX_LEDGER_BYTES
        or (hasattr(os, "geteuid") and metadata.st_uid != os.geteuid())
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise workflow.WorkflowError("V1 calibration ledger is unsafe.")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(path, flags)
        held = os.fstat(descriptor)
        if held.st_size != metadata.st_size:
            raise workflow.WorkflowError("V1 calibration ledger changed while opening.")
        chunks: list[bytes] = []
        remaining = int(held.st_size)
        while remaining:
            chunk = os.read(descriptor, min(65_536, remaining))
            if not chunk:
                raise workflow.WorkflowError("V1 calibration ledger could not be read completely.")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            raise workflow.WorkflowError("V1 calibration ledger changed while reading.")
        raw = b"".join(chunks).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise workflow.WorkflowError("V1 calibration ledger must be UTF-8 JSONL.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    rows: list[dict[str, object]] = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise workflow.WorkflowError(
                f"V1 calibration ledger line {line_number} is invalid JSON."
            ) from exc
        if not isinstance(item, dict):
            raise workflow.WorkflowError("V1 calibration ledger rows must be objects.")
        rows.append(item)
    return rows


def load_calibration_config(path: Path | None = None) -> dict[str, object]:
    try:
        payload = json.loads((path or CALIBRATION_CONFIG_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError("V1 calibration config is unavailable or invalid.") from exc
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "critic_reproducibility"}:
        raise workflow.WorkflowError("V1 calibration config has an invalid schema.")
    settings = payload.get("critic_reproducibility")
    if (
        payload.get("schema_version") != 1
        or not isinstance(settings, dict)
        or set(settings) != {"mode", "sample", "max_axis_delta"}
        or settings.get("mode") not in {"off", "shadow"}
        or settings.get("sample") != "once-per-command"
        or type(settings.get("max_axis_delta")) is not int
        or not 0 <= int(settings["max_axis_delta"]) <= 4
    ):
        raise workflow.WorkflowError("V1 Critic reproducibility policy is invalid.")
    return payload


def _decision_row(
    decision: Mapping[str, object],
    *,
    stage: str,
    subject_id: str = "",
    artifact_sha256: str = "",
) -> dict[str, object]:
    contract = _safe_token(decision.get("contract"), maximum=80)
    status = str(decision.get("status", "NOT_EVALUATED"))
    mode = str(decision.get("mode", "shadow"))
    if status not in {"PASS", "FAIL", "NOT_EVALUATED", "BLOCKED"}:
        status = "BLOCKED"
    if mode not in {"off", "shadow", "enforce"}:
        mode = "shadow"
    evidence: dict[str, object] = {}
    for key in (
        "threshold",
        "max_similarity",
        "text_similarity",
        "numbers_supported",
        "judge_status",
        "max_axis_disagreement",
        "stable_within_one_point",
        "compared_values",
        "score",
        "effective_total",
        "band",
        "hook_cap_applied",
        "finding_count",
        "observed_status",
    ):
        value = decision.get(key)
        if isinstance(value, (str, int, float, bool)) or value is None:
            evidence[key] = value
    axes = decision.get("axes")
    if isinstance(axes, Mapping):
        cleaned_axes = {
            str(key): int(value)
            for key, value in axes.items()
            if str(key) in workflow.CRITIC_AXES
            and type(value) is int
            and 1 <= int(value) <= 5
        }
        if cleaned_axes:
            evidence["axes"] = cleaned_axes
    cycle = decision.get("cycle")
    if type(cycle) is int and int(cycle) > 0:
        evidence["cycle"] = int(cycle)
    failure_codes = decision.get("failure_codes")
    if isinstance(failure_codes, Sequence) and not isinstance(failure_codes, (str, bytes)):
        evidence["failure_codes"] = [
            _safe_token(value, maximum=180) for value in failure_codes
        ][:20]
    gates = decision.get("gates")
    if isinstance(gates, Mapping):
        evidence["gates"] = {
            _safe_token(key, maximum=80): _safe_token(value, maximum=80)
            for key, value in gates.items()
        }
    return {
        "schema_version": 2,
        "run_id": current_run_id(),
        "recorded_at": _now(),
        "contract": contract,
        "stage": _safe_token(stage, maximum=80),
        "mode": mode,
        "status": status,
        "reason": _safe_token(decision.get("reason"), maximum=300),
        "subject_id": _safe_token(subject_id, maximum=160),
        "artifact_sha256": artifact_sha256 if re.fullmatch(r"[0-9a-f]{64}", artifact_sha256) else "",
        "evidence": evidence,
    }


def record_decision(
    decision: Mapping[str, object],
    *,
    stage: str,
    subject_id: str = "",
    artifact_sha256: str = "",
) -> None:
    _append_jsonl(
        _state_path(DECISION_LEDGER_NAME),
        _decision_row(
            decision,
            stage=stage,
            subject_id=subject_id,
            artifact_sha256=artifact_sha256,
        ),
    )


# ---------------------------------------------------------------------------
# Atomic value: review-ready binding first, published novelty history second.
# ---------------------------------------------------------------------------


def load_published_atomic_records(path: Path | None = None) -> list[dict[str, object]]:
    rows = _read_jsonl(path or _state_path(PUBLISHED_ATOMIC_LEDGER_NAME))
    validated: list[dict[str, object]] = []
    for row in rows:
        expected = {
            "schema_version",
            "recorded_at",
            "package_id",
            "candidate_id",
            "atomic_value",
            "atomic_hash",
            "artifact_sha256",
            "topic_value_id",
            "source_ids",
        }
        if set(row) != expected or row.get("schema_version") != 1:
            raise workflow.WorkflowError("Published atomic-value ledger has an invalid row schema.")
        atomic = v1_gates.validate_atomic_value(row.get("atomic_value"))
        if row.get("atomic_hash") != hashlib.sha256(atomic.casefold().encode()).hexdigest():
            raise workflow.WorkflowError("Published atomic-value ledger integrity check failed.")
        if re.fullmatch(r"[0-9a-f]{64}", str(row.get("artifact_sha256", ""))) is None:
            raise workflow.WorkflowError("Published atomic-value artifact hash is invalid.")
        source_ids = row.get("source_ids")
        if not isinstance(source_ids, list) or any(not isinstance(item, str) or not item for item in source_ids):
            raise workflow.WorkflowError("Published atomic-value source IDs are invalid.")
        validated.append(dict(row))
    return validated


def load_published_atomic_values(path: Path | None = None) -> list[str]:
    return [str(row["atomic_value"]) for row in load_published_atomic_records(path)]


def _binding_rows(path: Path | None = None) -> list[dict[str, object]]:
    rows = _read_jsonl(path or _state_path(ATOMIC_BINDINGS_LEDGER_NAME))
    for row in rows:
        expected = {
            "schema_version",
            "recorded_at",
            "artifact_sha256",
            "atomic_value",
            "atomic_hash",
            "topic_value_id",
            "source_ids",
        }
        if set(row) != expected or row.get("schema_version") != 1:
            raise workflow.WorkflowError("Review-ready atomic binding has an invalid schema.")
        atomic = v1_gates.validate_atomic_value(row.get("atomic_value"))
        if row.get("atomic_hash") != hashlib.sha256(atomic.casefold().encode()).hexdigest():
            raise workflow.WorkflowError("Review-ready atomic binding integrity check failed.")
        if re.fullmatch(r"[0-9a-f]{64}", str(row.get("artifact_sha256", ""))) is None:
            raise workflow.WorkflowError("Review-ready atomic binding artifact hash is invalid.")
    return rows


def record_review_ready_binding(post_text: str, topic_result: Mapping[str, object]) -> None:
    if topic_result.get("status") != "PASS":
        return
    atomic = topic_result.get("atomic_value")
    if not isinstance(atomic, str) or not atomic.strip():
        return
    cleaned = v1_gates.validate_atomic_value(atomic)
    artifact = _sha256_text(post_text)
    source_ids = topic_result.get("source_ids", [])
    if not isinstance(source_ids, Sequence) or isinstance(source_ids, (str, bytes)):
        source_ids = []
    row = {
        "schema_version": 1,
        "recorded_at": _now(),
        "artifact_sha256": artifact,
        "atomic_value": cleaned,
        "atomic_hash": hashlib.sha256(cleaned.casefold().encode()).hexdigest(),
        "topic_value_id": _safe_token(topic_result.get("id"), maximum=80),
        "source_ids": [str(item) for item in source_ids if isinstance(item, str) and item],
    }
    for existing in _binding_rows():
        if (
            existing.get("artifact_sha256") == row["artifact_sha256"]
            and existing.get("atomic_hash") == row["atomic_hash"]
        ):
            return
    _append_jsonl(_state_path(ATOMIC_BINDINGS_LEDGER_NAME), row)


def promote_binding(
    artifact_sha256: str,
    *,
    package_id: str,
    candidate_id: str,
) -> bool:
    matches = [
        row for row in _binding_rows() if row.get("artifact_sha256") == artifact_sha256
    ]
    atomic_hashes = {str(row.get("atomic_hash")) for row in matches}
    if len(atomic_hashes) != 1 or not matches:
        return False
    binding = matches[-1]
    for existing in load_published_atomic_records():
        if existing.get("package_id") == package_id and existing.get("candidate_id") == candidate_id:
            return True
    row = {
        "schema_version": 1,
        "recorded_at": _now(),
        "package_id": package_id,
        "candidate_id": candidate_id,
        "atomic_value": binding["atomic_value"],
        "atomic_hash": binding["atomic_hash"],
        "artifact_sha256": artifact_sha256,
        "topic_value_id": binding["topic_value_id"],
        "source_ids": list(binding["source_ids"]),
    }
    _append_jsonl(_state_path(PUBLISHED_ATOMIC_LEDGER_NAME), row)
    return True


def _candidate_artifact_sha256(package_id: str, candidate_id: str) -> str:
    manifest, evaluation, documents = performance._load_package_documents(  # type: ignore[attr-defined]
        package_id,
        include_learning_documents=True,
    )
    validated = performance._validate_package_context(  # type: ignore[attr-defined]
        package_id,
        candidate_id,
        manifest=manifest,
        evaluation=evaluation,
    )
    candidates, _route = performance._validate_learning_snapshot(  # type: ignore[attr-defined]
        manifest=manifest,
        evaluation=evaluation,
        validated=validated,
        documents=documents,
    )
    selected = candidates.get(candidate_id)
    if not isinstance(selected, tuple) or len(selected) != 2:
        raise workflow.WorkflowError("Published candidate could not be linked to its V1 atomic value.")
    return _sha256_text(str(selected[1]))


def _promote_published_records(records: object) -> None:
    if not isinstance(records, Sequence) or isinstance(records, (str, bytes)):
        return
    seen: set[tuple[str, str]] = set()
    for record in records:
        if not isinstance(record, Mapping):
            continue
        package_id = record.get("package_id")
        candidate_id = record.get("candidate_id")
        if not isinstance(package_id, str) or not isinstance(candidate_id, str):
            continue
        key = (package_id, candidate_id)
        if key in seen:
            continue
        seen.add(key)
        try:
            artifact = _candidate_artifact_sha256(package_id, candidate_id)
            promoted = promote_binding(
                artifact,
                package_id=package_id,
                candidate_id=candidate_id,
            )
            decision = {
                "contract": "atomic_value_novelty",
                "mode": "enforce",
                "status": "PASS" if promoted else "NOT_EVALUATED",
                "reason": (
                    "manual-publication-promoted-atomic-value"
                    if promoted
                    else "manual-publication-has-no-v1-review-ready-binding"
                ),
            }
            record_decision(
                decision,
                stage="manual-publication",
                subject_id=f"{package_id}:{candidate_id}",
                artifact_sha256=artifact,
            )
        except workflow.WorkflowError:
            # Performance has already committed successfully. A diagnostic sidecar must never
            # turn that successful durable write into an apparent failure.
            continue


def _record_performance_many_v1(*args, **kwargs):
    result = _BASE_RECORD_PERFORMANCE_MANY(*args, **kwargs)
    records = args[1] if len(args) > 1 else kwargs.get("records")
    _promote_published_records(records)
    return result


# ---------------------------------------------------------------------------
# Consolidated attribution for Topic Value, Critic, and Resonance.
# ---------------------------------------------------------------------------


def _topic_evaluator_v1(candidates, evidence):
    evaluated = _BASE_TOPIC_EVALUATOR(candidates, evidence)
    for candidate in evaluated:
        if not isinstance(candidate, Mapping):
            continue
        subject = str(candidate.get("id", ""))
        evaluations = candidate.get("v1_evals")
        if not isinstance(evaluations, Mapping):
            continue
        for name in ("atomic_value_novelty", "research_trust", "claim_body_support"):
            decision = evaluations.get(name)
            if isinstance(decision, Mapping):
                record_decision(decision, stage="topic-value", subject_id=subject)
    return evaluated


def _critic_validator_v1(raw_scorecards, candidates):
    anchored = bool(
        isinstance(raw_scorecards, Sequence)
        and not isinstance(raw_scorecards, (str, bytes))
        and raw_scorecards
        and all(isinstance(item, Mapping) and "anchors" in item for item in raw_scorecards)
    )
    try:
        validated = _BASE_VALIDATE_CRITIC(raw_scorecards, candidates)
    except workflow.WorkflowError:
        if anchored:
            for item in raw_scorecards:
                if isinstance(item, Mapping):
                    record_decision(
                        {
                            "contract": "critic_anchor_integrity",
                            "mode": v1_gates.contract_mode("critic_anchor_integrity"),
                            "status": "FAIL",
                            "reason": "anchored-scorecard-rejected-by-validator",
                        },
                        stage="critic",
                        subject_id=str(item.get("candidate_id", "")),
                    )
        raise
    text_by_id = {
        str(item.get("id", "")): str(item.get("text", ""))
        for item in candidates
        if isinstance(item, Mapping)
    }
    for item in validated:
        candidate_id = str(item.get("candidate_id", ""))
        text = text_by_id.get(candidate_id, "")
        record_decision(
            {
                "contract": "critic_total",
                "mode": "shadow",
                "status": "PASS",
                "reason": "critic-scorecard-recorded-diagnostic",
                "score": item.get("effective_total"),
                "effective_total": item.get("effective_total"),
                "band": item.get("band"),
                "hook_cap_applied": item.get("hook_cap_applied"),
                "axes": {axis: item.get(axis) for axis in workflow.CRITIC_AXES},
            },
            stage="critic",
            subject_id=candidate_id,
            artifact_sha256=_sha256_text(text) if text else "",
        )
    if anchored:
        for item in validated:
            candidate_id = str(item.get("candidate_id", ""))
            text = text_by_id.get(candidate_id, "")
            record_decision(
                {
                    "contract": "critic_anchor_integrity",
                    "mode": v1_gates.contract_mode("critic_anchor_integrity"),
                    "status": "PASS",
                    "reason": "behavioral-anchor-evidence-validated",
                },
                stage="critic",
                subject_id=candidate_id,
                artifact_sha256=_sha256_text(text) if text else "",
            )
    return validated


def _post_critic_v1(post_text, selector, *, invoker=resonance._default_invoker):  # type: ignore[attr-defined]
    assessment = dict(_BASE_POST_CRITIC(post_text, selector, invoker=invoker))
    artifact = _sha256_text(post_text)
    for key in ("v1_solution_plausibility", "v1_reader_attention"):
        decision = assessment.get(key)
        if isinstance(decision, Mapping):
            record_decision(
                decision,
                stage="resonance-post",
                artifact_sha256=artifact,
            )
    if assessment.get("status") == "PASS":
        topic_result = selector.get("topic_value")
        if isinstance(topic_result, Mapping):
            record_review_ready_binding(post_text, topic_result)
    return assessment


# ---------------------------------------------------------------------------
# Critic reproducibility: one shadow duplicate per live command, never a gate.
# ---------------------------------------------------------------------------


def _repro_settings() -> Mapping[str, object]:
    settings = load_calibration_config()["critic_reproducibility"]
    assert isinstance(settings, Mapping)
    return settings


def _record_reproducibility(first: object, second: object, *, runtime: str) -> None:
    settings = _repro_settings()
    if settings.get("mode") == "off":
        return
    try:
        if (
            not isinstance(first, Sequence)
            or isinstance(first, (str, bytes))
            or not first
        ):
            raise workflow.WorkflowError("First Critic reproducibility sample is malformed.")
        if (
            not isinstance(second, Sequence)
            or isinstance(second, (str, bytes))
            or not second
        ):
            raise workflow.WorkflowError("Second Critic reproducibility sample is malformed.")
        result = v1_gates.score_disagreement(first, second)
        limit = int(settings["max_axis_delta"])
        maximum = int(result["max_axis_disagreement"])
        decision = {
            "contract": "critic_reproducibility",
            "mode": "shadow",
            "status": "PASS" if maximum <= limit else "FAIL",
            "reason": (
                "repeated-critic-within-calibration-band"
                if maximum <= limit
                else "repeated-critic-exceeded-calibration-band"
            ),
            "max_axis_disagreement": maximum,
            "stable_within_one_point": maximum <= 1,
        }
    except workflow.WorkflowError:
        decision = {
            "contract": "critic_reproducibility",
            "mode": "shadow",
            "status": "BLOCKED",
            "reason": "repeated-critic-sample-could-not-be-compared",
        }
    record_decision(decision, stage=f"critic-reproducibility-{runtime}")


def _workflow_invoke_critic_v1(*args, **kwargs):
    first = _BASE_WORKFLOW_INVOKE_CRITIC(*args, **kwargs)
    settings = _repro_settings()
    if settings.get("mode") != "off" and not _REPRO_SAMPLED["legacy"]:
        _REPRO_SAMPLED["legacy"] = True
        try:
            second = _BASE_WORKFLOW_INVOKE_CRITIC(*args, **kwargs)
        except workflow.WorkflowError:
            _record_reproducibility([], [], runtime="legacy-error")
        else:
            _record_reproducibility(first, second, runtime="legacy")
    return first


def _campaign_invoker_v1(stage, config, role_prompt, task_prompt, schema):
    first = _BASE_CAMPAIGN_INVOKER(stage, config, role_prompt, task_prompt, schema)
    settings = _repro_settings()
    if (
        stage == "critic"
        and settings.get("mode") != "off"
        and not _REPRO_SAMPLED["campaign"]
    ):
        _REPRO_SAMPLED["campaign"] = True
        try:
            second = _BASE_CAMPAIGN_INVOKER(stage, config, role_prompt, task_prompt, schema)
            left = first.get("scorecards") if isinstance(first, Mapping) else None
            right = second.get("scorecards") if isinstance(second, Mapping) else None
            _record_reproducibility(left, right, runtime="campaign")
        except workflow.WorkflowError:
            record_decision(
                {
                    "contract": "critic_reproducibility",
                    "mode": "shadow",
                    "status": "BLOCKED",
                    "reason": "second-critic-sample-failed",
                },
                stage="critic-reproducibility-campaign",
            )
    return first


# ---------------------------------------------------------------------------
# Calibration snapshot: reuse weekly-review inputs; never mutate the rubric.
# ---------------------------------------------------------------------------


def build_calibration_snapshot(
    rows: Sequence[Mapping[str, object]],
    *,
    as_of: str,
) -> dict[str, object]:
    decisions = _read_jsonl(_state_path(DECISION_LEDGER_NAME))
    counts: dict[str, dict[str, int]] = {}
    for row in decisions:
        contract = str(row.get("contract", "unknown"))
        status = str(row.get("status", "NOT_EVALUATED"))
        contract_counts = counts.setdefault(
            contract,
            {"PASS": 0, "FAIL": 0, "BLOCKED": 0, "NOT_EVALUATED": 0},
        )
        if status not in contract_counts:
            status = "NOT_EVALUATED"
        contract_counts[status] += 1

    organic_72h = [
        row
        for row in rows
        if isinstance(row, Mapping)
        and row.get("channel") == "organic"
        and row.get("checkpoint") == "72h"
    ]
    metric_medians: dict[str, float] = {}
    for metric in storage.PERFORMANCE_METRICS:
        values = [
            int(row[metric])
            for row in organic_72h
            if type(row.get(metric)) is int
        ]
        if values:
            metric_medians[metric] = float(median(values))

    package_ids = {
        str(row.get("package_id"))
        for row in organic_72h
        if isinstance(row.get("package_id"), str)
    }
    published = load_published_atomic_records()
    linked_atomic = sum(1 for item in published if str(item.get("package_id")) in package_ids)
    return {
        "schema_version": 1,
        "recorded_at": _now(),
        "as_of": as_of,
        "contract_decisions": counts,
        "decision_events": len(decisions),
        "review_ready_atomic_bindings": len(_binding_rows()),
        "published_atomic_values": len(published),
        "organic_72h_posts": len(organic_72h),
        "published_atomic_values_linked_to_72h": linked_atomic,
        "organic_72h_metric_medians": metric_medians,
        "rubric_mutated": False,
        "human_product_review_required": True,
    }


def _write_weekly_review_v1(rows, *, as_of, candidate_contexts):
    generated = _BASE_WRITE_WEEKLY_REVIEW(
        rows,
        as_of=as_of,
        candidate_contexts=candidate_contexts,
    )
    safe_rows = [row for row in rows if isinstance(row, Mapping)]
    snapshot = build_calibration_snapshot(safe_rows, as_of=as_of)
    _append_jsonl(_state_path(CALIBRATION_LEDGER_NAME), snapshot)
    if isinstance(generated, dict):
        generated = dict(generated)
        generated["v1_calibration"] = {
            "status": "recorded",
            "decision_events": snapshot["decision_events"],
            "published_atomic_values": snapshot["published_atomic_values"],
            "organic_72h_posts": snapshot["organic_72h_posts"],
        }
    return generated


def install() -> None:
    """Install V1 completion hooks after v1_gates.install()."""

    global _INSTALLED
    if _INSTALLED:
        return
    load_calibration_config()

    # The first V1 implementation recorded review-ready values directly in novelty history.
    # From this layer onward, novelty means *published* history. The old private file is left
    # untouched for reversibility/audit but is no longer consulted by live novelty checks.
    v1_gates.load_atomic_values = load_published_atomic_values  # type: ignore[assignment]
    v1_gates.record_atomic_value = lambda *args, **kwargs: None  # type: ignore[assignment]

    v1_gates._evaluate_topic_candidates = _topic_evaluator_v1  # type: ignore[attr-defined,assignment]
    workflow.validate_critic_scorecards = _critic_validator_v1  # type: ignore[assignment]
    resonance.invoke_post_critic = _post_critic_v1  # type: ignore[assignment]
    workflow.invoke_critic = _workflow_invoke_critic_v1  # type: ignore[assignment]
    campaign.default_stage_invoker = _campaign_invoker_v1  # type: ignore[assignment]
    storage.record_performance_many = _record_performance_many_v1  # type: ignore[assignment]
    learning.write_weekly_review = _write_weekly_review_v1  # type: ignore[assignment]

    _INSTALLED = True
