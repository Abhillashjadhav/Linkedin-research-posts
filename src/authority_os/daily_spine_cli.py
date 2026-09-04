"""Conversation-first daily discovery with advisory narrative-spine routing."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Sequence

from . import daily_cli as base
from . import (
    __version__,
    acceptance_policy,
    campaign,
    eval_dashboard_html,
    momentum,
    storage,
    topic_value,
    v1_completion,
    workflow,
)
from .spine_feedback import CONTENT_SPINES


CARD_KEYS = frozenset((*base.CARD_KEYS, "recommended_spine", "spine_fit_reason"))
MAX_SPINE_FIT_REASON_CHARS = 320
MIN_AUTHORITY_FIT_FALLBACK = 20
MIN_COMBINED_INVENTORY_SCORE = 40
CANDIDATE_INVENTORY = base.OUTPUT_ROOT / "candidate-inventory.json"
EVIDENCE_TIMEOUT_SECONDS = 180
EVIDENCE_CACHE_NAME = "evidence-research.json"
ADMITTED_SCOPE_NAME = "admitted-topics.json"
MIN_VERIFIED_EVIDENCE = 1
MAX_VERIFIED_EVIDENCE = 7
EVAL_CONTRACTS = (
    ("research_trust", "Topic Value", "research trust"),
    ("atomic_value_novelty", "Topic Value", "atomic-value novelty"),
    ("critic_anchor_integrity", "Critic", "anchor integrity"),
    ("critic_reproducibility", "Critic", "score reproducibility"),
    ("critic_total", "Post quality", "Critic total"),
    ("hook_strength", "Post quality", "hook strength"),
    ("middle_escalation", "Post quality", "middle escalation"),
    ("earned_closer", "Post quality", "earned closer"),
    ("specificity_and_source_quality", "Post quality", "specificity and source quality"),
    ("voice_fidelity", "Post quality", "voice fidelity"),
    ("anti_slop", "Post quality", "anti-AI-slop"),
    ("candidate_acceptance", "Post quality", "candidate acceptance"),
    ("solution_plausibility", "Resonance", "solution plausibility"),
    ("reader_attention", "Resonance", "reader attention"),
)
POST_QUALITY_CONTRACTS = frozenset(
    {
        "critic_total",
        "hook_strength",
        "middle_escalation",
        "earned_closer",
        "specificity_and_source_quality",
        "voice_fidelity",
        "anti_slop",
        "candidate_acceptance",
        "solution_plausibility",
        "reader_attention",
    }
)
DISCOVERY_STAGES = (
    ("conversation_discovery", "Conversation discovery"),
    ("topic_admission", "Topic admission"),
    ("evidence_verification", "Evidence verification"),
    ("topic_value", "Topic Value"),
    ("thesis_search", "Thesis search"),
    ("drafting", "High-bar drafting"),
    ("final_evals", "Final evals"),
)
# Stage boundaries report every ordinary exception, then re-raise it unchanged.
# KeyboardInterrupt/SystemExit remain outside this boundary.
STAGE_EXCEPTIONS = (Exception,)
OBSERVABILITY_CONTRACT = "decision-trace-v1"
OBSERVABILITY_STATUS = frozenset(
    {"PASS", "FAIL", "BLOCKED", "NOT_EVALUATED", "RUNNING", "REJECTED", "UNAVAILABLE"}
)


@dataclass(frozen=True, slots=True)
class DraftingRun:
    returncode: int
    reason: str
    log_path: str
    captured_tail: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvidenceResolution:
    items: tuple[dict[str, object], ...]
    route: str
    attempts: int
    scope_fingerprint: str


@dataclass(frozen=True, slots=True)
class DiscoveryResume:
    source_folder: Path
    as_of: str
    top_five: tuple[dict[str, object], ...]
    eligible: tuple[dict[str, object], ...]
    route: str
    surface_scouts: tuple[dict[str, object], ...]


def run_drafting_child(
    command: Sequence[str],
    *,
    cwd: Path,
    folder: Path,
    env: Mapping[str, str] | None = None,
) -> DraftingRun:
    """Stream one child to the operator while retaining its complete private log."""

    chunks: list[str] = []
    returncode = 127
    try:
        with subprocess.Popen(
            list(command),
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=dict(env) if env is not None else None,
        ) as process:
            if process.stdout is None:
                raise workflow.WorkflowError("Drafting child output pipe was unavailable.")
            for line in process.stdout:
                print(line, end="", flush=True)
                chunks.append(line)
            returncode = process.wait()
    except OSError as exc:
        line = f"ERROR: drafting child could not start: {exc}\n"
        print(line, end="", flush=True)
        chunks.append(line)

    captured = "".join(chunks)
    log = base.write_private_text(folder / "drafting.log", captured)
    lines = captured.splitlines()
    reason = next(
        (line.strip() for line in reversed(lines) if line.strip().startswith("ERROR:")),
        next((line.strip() for line in reversed(lines) if line.strip()), "no child output was captured"),
    )
    return DraftingRun(
        returncode=returncode,
        reason=reason,
        log_path=log.relative_to(workflow.REPO_ROOT).as_posix(),
        captured_tail=tuple(lines[-20:]),
    )


def record_drafting_stage(
    dashboard: dict[str, object],
    result: DraftingRun,
    *,
    post_evaluated: bool,
) -> None:
    details = {
        "return_code": result.returncode,
        "log_path": result.log_path,
        "captured_tail": list(result.captured_tail),
    }
    dashboard["drafting"] = {
        "log_path": result.log_path,
        "captured_tail": list(result.captured_tail),
    }
    if result.returncode == 0 or post_evaluated:
        mark_run_stage(
            dashboard,
            "drafting",
            "PASS",
            "draft candidates were generated and reached evaluation",
            **details,
        )
        return
    mark_run_stage(
        dashboard,
        "drafting",
        "FAIL",
        f"high-bar drafting exited {result.returncode}: {result.reason}",
        expected="drafting exits 0 after producing candidates and reaching evaluation",
        observed=f"exit={result.returncode}; last_error={result.reason}",
        **details,
    )


def execution_identity() -> dict[str, object]:
    """Describe the exact checkout executing the run without failing the workflow."""

    def git_value(*arguments: str) -> str:
        try:
            completed = subprocess.run(
                ["git", *arguments],
                cwd=workflow.REPO_ROOT,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired):
            return "unavailable"
        value = completed.stdout.strip()
        return value if completed.returncode == 0 and value else "unavailable"

    commit = os.environ.get("GITHUB_SHA", "").strip() or git_value("rev-parse", "HEAD")
    branch = git_value("branch", "--show-current")
    dirty_output = git_value("status", "--porcelain", "--untracked-files=no")
    return {
        "commit": commit,
        "short_commit": commit[:12] if commit != "unavailable" else commit,
        "branch": branch,
        "dirty": dirty_output not in {"", "unavailable"},
        "observability_contract": OBSERVABILITY_CONTRACT,
    }


def record_run_decision(
    dashboard: dict[str, object],
    *,
    stage: str,
    decision: str,
    status: str,
    expected: object,
    observed: object,
    reason: str,
    subject_id: str = "",
    artifact: str = "",
    details: Mapping[str, object] | None = None,
) -> None:
    """Append one complete, dashboard-safe explanation of a pipeline decision."""

    if status not in OBSERVABILITY_STATUS:
        raise workflow.WorkflowError(f"Decision trace has invalid status {status!r}.")
    decisions = dashboard.get("decisions")
    if not isinstance(decisions, list):
        raise workflow.WorkflowError("Run dashboard has an invalid decision trace.")
    decisions.append(
        {
            "sequence": len(decisions) + 1,
            "stage": stage,
            "decision": decision,
            "status": status,
            "expected": str(expected),
            "observed": str(observed),
            "reason": reason,
            "subject_id": subject_id,
            "artifact": artifact,
            "details": dict(details or {}),
        }
    )


def new_run_dashboard(run_id: str = "") -> dict[str, object]:
    return {
        "schema_version": 2,
        "run_id": run_id,
        "outcome": "RUNNING",
        "stopped_at": None,
        "execution": execution_identity(),
        "evaluator_versions": evaluator_versions(),
        "surface_scouts": [],
        "decisions": [],
        "checks": [
            {
                "stage": stage,
                "label": label,
                "status": "NOT_EVALUATED",
                "reason": "stage was not reached",
                "details": {},
            }
            for stage, label in DISCOVERY_STAGES
        ],
    }


def evaluator_versions() -> dict[str, object]:
    models = campaign.StageModels.preferred()
    model_rows = {
        name: getattr(models, name).trace()
        for name in ("writer", "narrative_editor", "critic", "artisanal_editor")
    }
    scout = getattr(momentum, "MODEL", None)
    if hasattr(scout, "trace"):
        model_rows["surface_scout"] = scout.trace()
    rubrics: dict[str, str] = {}
    for name in ("critic-rubric-v2.json", "eval-v1.json", "eval-v1-calibration.json"):
        path = workflow.REPO_ROOT / "config" / name
        try:
            rubrics[name] = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        except OSError:
            rubrics[name] = "unavailable"
    return {
        "linkedin_os": __version__,
        "models": model_rows,
        "rubrics": rubrics,
        "acceptance": {
            "contract_version": acceptance_policy.ACCEPTANCE_CONTRACT_VERSION,
            "floor": acceptance_policy.ACCEPTABLE_QUALITY_FLOOR,
            "quality_target": acceptance_policy.QUALITY_TARGET,
            "axis_floors": dict(acceptance_policy.AXIS_FLOORS),
        },
    }


def _recent_run_baseline(folder: Path, limit: int = 5) -> list[dict[str, object]]:
    candidates = [
        *base.OUTPUT_ROOT.glob("*/*/run-dashboard.json"),
        *(workflow.DEFAULT_PRIVATE_DATA / "draft-runs").glob("*/run-dashboard.json"),
    ]
    safe: list[tuple[float, Path]] = []
    for path in candidates:
        try:
            if path.parent.resolve() == folder.resolve() or path.is_symlink():
                continue
            safe.append((path.stat().st_mtime, path))
        except OSError:
            continue
    baseline: list[dict[str, object]] = []
    for _modified, path in sorted(safe, reverse=True)[:limit]:
        try:
            payload = base._private_json(path, "Prior run dashboard")
        except workflow.WorkflowError:
            continue
        checks = payload.get("checks")
        passed = (
            sum(1 for item in checks if isinstance(item, Mapping) and item.get("status") == "PASS")
            if isinstance(checks, list)
            else 0
        )
        baseline.append(
            {
                "run_id": str(payload.get("run_id", path.parent.name)),
                "outcome": str(payload.get("outcome", "UNKNOWN")),
                "stopped_at": payload.get("stopped_at"),
                "passed_stages": passed,
            }
        )
    return baseline


def surface_diagnostics(folder: Path) -> list[dict[str, object]]:
    diagnostics: list[dict[str, object]] = []
    for path in sorted(folder.glob("surface-*.json")):
        try:
            payload = base._private_json(path, "Surface Scout trace")
        except workflow.WorkflowError:
            continue
        status = str(payload.get("status", "UNAVAILABLE"))
        caveat = str(payload.get("caveat", "No reason recorded."))
        signals = payload.get("signals")
        count = len(signals) if isinstance(signals, list) else 0
        normal = caveat.casefold()
        reason_code = (
            "evidence-returned" if status == "OBSERVED"
            else "no-current-signal" if status == "NO_SIGNAL"
            else "timeout" if "timed out" in normal or "timeout" in normal
            else "invalid-response" if "schema" in normal or "invalid" in normal
            else "surface-unavailable"
        )
        diagnostics.append(
            {
                "surface": str(payload.get("surface", path.stem.removeprefix("surface-"))),
                "label": str(payload.get("label", path.stem)),
                "status": status,
                "reason_code": reason_code,
                "reason": caveat,
                "signal_count": count,
            }
        )
    return diagnostics


def _dashboard_stage(
    dashboard: Mapping[str, object], stage: str
) -> Mapping[str, object]:
    checks = dashboard.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)):
        raise workflow.WorkflowError("Resume dashboard has an invalid stage list.")
    for item in checks:
        if isinstance(item, Mapping) and item.get("stage") == stage:
            return item
    raise workflow.WorkflowError(f"Resume dashboard does not contain {stage!r}.")


def _mapping_sha256(value: Mapping[str, object]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def load_discovery_resume(
    source: Path,
    *,
    days: int,
    requested_topic: str | None,
    profile: Mapping[str, object],
) -> DiscoveryResume:
    """Restore the successful discovery boundary without running its scouts again."""

    folder = base._under_private(source)
    dashboard = base._private_json(folder / "run-dashboard.json", "Resume dashboard")
    momentum_payload = base._private_json(folder / "momentum.json", "Resume momentum")
    if not isinstance(dashboard, Mapping) or dashboard.get("schema_version") != 2:
        raise workflow.WorkflowError("Resume dashboard has an unsupported schema.")
    if not isinstance(momentum_payload, Mapping) or momentum_payload.get("schema_version") != 1:
        raise workflow.WorkflowError("Resume momentum has an unsupported schema.")
    if momentum_payload.get("days") != days:
        raise workflow.WorkflowError("Resume run must use the same discovery window.")
    prior_topic = momentum_payload.get("topic")
    if prior_topic != requested_topic:
        raise workflow.WorkflowError("Resume run must use the same requested topic.")
    as_of = momentum_payload.get("created_at")
    if not isinstance(as_of, str):
        raise workflow.WorkflowError("Resume momentum is missing its timestamp.")
    workflow.parse_published_at(as_of)

    conversation = _dashboard_stage(dashboard, "conversation_discovery")
    admission = _dashboard_stage(dashboard, "topic_admission")
    evidence = _dashboard_stage(dashboard, "evidence_verification")
    if conversation.get("status") != "PASS" or admission.get("status") != "PASS":
        raise workflow.WorkflowError(
            "Resume requires completed conversation discovery and topic admission."
        )
    if evidence.get("status") != "FAIL":
        raise workflow.WorkflowError(
            "Resume source must have stopped at evidence verification."
        )
    for downstream in ("topic_value", "thesis_search", "drafting", "final_evals"):
        if _dashboard_stage(dashboard, downstream).get("status") != "NOT_EVALUATED":
            raise workflow.WorkflowError(
                "Resume source continued beyond evidence verification."
            )

    candidates = momentum_payload.get("candidates")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise workflow.WorkflowError("Resume momentum candidates are invalid.")
    top_five = [dict(item) for item in candidates if isinstance(item, Mapping)]

    details = admission.get("details")
    if not isinstance(details, Mapping):
        raise workflow.WorkflowError("Resume topic admission details are unavailable.")
    admitted_topics = details.get("admitted_topics")
    route = details.get("route")
    if (
        not isinstance(admitted_topics, Sequence)
        or isinstance(admitted_topics, (str, bytes))
        or not admitted_topics
        or not isinstance(route, str)
        or not route
    ):
        raise workflow.WorkflowError("Resume topic admission scope is invalid.")
    if route not in {
        "momentum-qualified",
        "rolling seven-day inventory",
        "authority-fit fallback",
    }:
        raise workflow.WorkflowError("Resume topic admission route is invalid.")

    scope_path = folder / ADMITTED_SCOPE_NAME
    recorded_scope_fingerprint: object = None
    if scope_path.is_symlink():
        raise workflow.WorkflowError("Resume admitted topic scope must not be a symlink.")
    if scope_path.exists():
        if not scope_path.is_file():
            raise workflow.WorkflowError("Resume admitted topic scope is not a file.")
        scope_payload = base._private_json(scope_path, "Admitted topic scope")
        if (
            not isinstance(scope_payload, Mapping)
            or scope_payload.get("schema_version") != 1
            or scope_payload.get("created_at") != as_of
            or scope_payload.get("days") != days
            or scope_payload.get("topic") != requested_topic
            or scope_payload.get("route") != route
        ):
            raise workflow.WorkflowError("Resume admitted topic scope is inconsistent.")
        profile_digest = scope_payload.get("profile_sha256")
        if (
            not isinstance(profile_digest, str)
            or profile_digest != _mapping_sha256(profile)
        ):
            raise workflow.WorkflowError("Resume authority profile has changed.")
        recorded_scope_fingerprint = scope_payload.get("scope_fingerprint")
        if not isinstance(recorded_scope_fingerprint, str):
            raise workflow.WorkflowError("Resume admitted topic fingerprint is missing.")
        scoped = scope_payload.get("candidates")
        if not isinstance(scoped, Sequence) or isinstance(scoped, (str, bytes)):
            raise workflow.WorkflowError("Resume admitted topic candidates are invalid.")
        pool = [dict(item) for item in scoped if isinstance(item, Mapping)]
    elif route == "rolling seven-day inventory":
        if not CANDIDATE_INVENTORY.is_file() or CANDIDATE_INVENTORY.is_symlink():
            raise workflow.WorkflowError(
                "Legacy rolling-inventory resume needs its original candidate inventory."
            )
        inventory_payload = base._private_json(
            CANDIDATE_INVENTORY, "Candidate inventory"
        )
        if (
            not isinstance(inventory_payload, Mapping)
            or inventory_payload.get("schema_version") != 1
            or inventory_payload.get("updated_at") != as_of
            or inventory_payload.get("window_days") != days
        ):
            raise workflow.WorkflowError(
                "Legacy candidate inventory no longer matches the failed run."
            )
        inventory = inventory_payload.get("candidates")
        if not isinstance(inventory, Sequence) or isinstance(inventory, (str, bytes)):
            raise workflow.WorkflowError("Legacy candidate inventory is invalid.")
        pool = [dict(item) for item in inventory if isinstance(item, Mapping)]
    else:
        pool = list(top_five)
    by_topic = {
        " ".join(str(item.get("topic", "")).casefold().split()): item
        for item in pool
        if isinstance(item.get("topic"), str)
    }
    if len(by_topic) != len(pool):
        raise workflow.WorkflowError("Resume topic scope contains duplicate topic names.")
    eligible: list[dict[str, object]] = []
    for topic in admitted_topics:
        key = " ".join(str(topic).casefold().split())
        candidate = by_topic.get(key)
        if candidate is None:
            raise workflow.WorkflowError(
                f"Resume scope is missing admitted topic {str(topic)!r}."
            )
        urls = candidate.get("representative_urls")
        if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes)) or not urls:
            raise workflow.WorkflowError("Resume topic has no representative URLs.")
        eligible.append(dict(candidate))

    if (
        recorded_scope_fingerprint is not None
        and recorded_scope_fingerprint
        != evidence_scope_fingerprint(eligible, requested_topic=requested_topic)
    ):
        raise workflow.WorkflowError("Resume admitted topic fingerprint has changed.")

    surfaces = dashboard.get("surface_scouts")
    surface_rows = (
        tuple(dict(item) for item in surfaces if isinstance(item, Mapping))
        if isinstance(surfaces, Sequence) and not isinstance(surfaces, (str, bytes))
        else ()
    )
    return DiscoveryResume(
        source_folder=folder,
        as_of=as_of,
        top_five=tuple(top_five),
        eligible=tuple(eligible),
        route=route,
        surface_scouts=surface_rows,
    )


def record_surface_decisions(
    dashboard: dict[str, object],
    diagnostics: Sequence[Mapping[str, object]],
) -> None:
    for item in diagnostics:
        status = str(item.get("status", "UNAVAILABLE"))
        record_run_decision(
            dashboard,
            stage="conversation_discovery",
            decision="surface scout returned usable evidence",
            status="PASS" if status == "OBSERVED" else "UNAVAILABLE",
            expected="OBSERVED with at least one defensible public signal",
            observed=f"status={status}; signals={item.get('signal_count', 0)}",
            reason=str(item.get("reason", "No scout reason was recorded.")),
            subject_id=str(item.get("surface", "unknown-surface")),
            details=item,
        )


def record_momentum_decisions(
    dashboard: dict[str, object],
    candidates: Sequence[Mapping[str, object]],
) -> None:
    for item in candidates:
        total = item.get("total")
        observed_axes = int(item.get("observed_axes", 0))
        passes = (
            type(total) is int
            and int(total) >= momentum.MIN_AUTHORITY_MOMENTUM
            and observed_axes >= momentum.MIN_OBSERVED_AXES
        )
        record_run_decision(
            dashboard,
            stage="conversation_discovery",
            decision="conversation-momentum qualification",
            status="PASS" if passes else "REJECTED",
            expected=(
                f"total >= {momentum.MIN_AUTHORITY_MOMENTUM} and "
                f"observed_axes >= {momentum.MIN_OBSERVED_AXES}"
            ),
            observed=f"total={total}; observed_axes={observed_axes}",
            reason=(
                "candidate cleared the conversation-momentum floor"
                if passes
                else "candidate missed the conversation-momentum floor"
            ),
            subject_id=str(item.get("id", item.get("topic", "unknown-topic"))),
            details={
                "topic": str(item.get("topic", "")),
                "total": total,
                "observed_axes": observed_axes,
                "authority_fit": item.get("authority_fit"),
            },
        )


def record_topic_admission_decisions(
    dashboard: dict[str, object],
    candidates: Sequence[Mapping[str, object]],
    admitted: Sequence[Mapping[str, object]],
    route: str,
) -> None:
    admitted_topics = {str(item.get("topic", "")) for item in admitted}
    for item in candidates:
        topic = str(item.get("topic", ""))
        selected = topic in admitted_topics
        record_run_decision(
            dashboard,
            stage="topic_admission",
            decision="topic admitted to evidence verification",
            status="PASS" if selected else "REJECTED",
            expected=(
                "momentum-qualified, retained-inventory-qualified, or "
                f"authority_fit >= {MIN_AUTHORITY_FIT_FALLBACK} with "
                f"observed_axes >= {momentum.MIN_OBSERVED_AXES}"
            ),
            observed=(
                f"selected={selected}; route={route}; momentum_total={item.get('total')}; "
                f"observed_axes={item.get('observed_axes')}; authority_fit={item.get('authority_fit')}"
            ),
            reason=(
                f"admitted through {route}"
                if selected
                else f"not selected by the {route} route"
            ),
            subject_id=str(item.get("id", topic or "unknown-topic")),
        )


def record_evidence_decisions(
    dashboard: dict[str, object],
    signals: Sequence[Mapping[str, object]],
) -> None:
    for item in signals:
        record_run_decision(
            dashboard,
            stage="evidence_verification",
            decision="signal admitted as body-verified evidence",
            status="PASS",
            expected="valid timestamp, inspectable source body, canonical URL, and allowed source quality",
            observed=(
                f"source_quality={item.get('source_quality')}; "
                f"published_month={workflow.display_publication_month(item.get('published_at'))}; "
                f"date_precision={item.get('publication_date_precision', 'exact')}; "
                f"url={item.get('canonical_url')}"
            ),
            reason="signal passed research-item validation and projection",
            subject_id=str(item.get("id", "unknown-signal")),
        )


def record_topic_value_decisions(
    dashboard: dict[str, object],
    folder: Path,
    observation_stage: str,
    candidates: Sequence[Mapping[str, object]],
) -> Path:
    if observation_stage not in {"pre-gate", "post-gate"}:
        raise workflow.WorkflowError(
            f"Topic Value observation stage {observation_stage!r} is invalid."
        )
    path = folder / f"topic-value-evaluations-{observation_stage}.json"
    path = base.write_private_json(
        path,
        {
            "schema_version": 2,
            "observation_stage": observation_stage,
            "thresholds": {
                "reader_relevance": 4,
                "reader_value": 4,
                "gravity": 2,
                "evidence_strength": 3,
                "authority_fit": 3,
                "minimum_total": topic_value.TOPIC_VALUE_MIN_TOTAL,
                "required_booleans": [
                    "brand_strip_pass",
                    "feed_value_possible",
                    "supports_authority_goal",
                ],
            },
            "candidates": list(candidates),
        },
    )
    relative = path.relative_to(workflow.REPO_ROOT).as_posix()
    expected = (
        "reader_relevance>=4; reader_value>=4; gravity>=2; evidence_strength>=3; "
        f"authority_fit>=3; total>={topic_value.TOPIC_VALUE_MIN_TOTAL}; "
        "brand_strip/feed_value/authority_goal=true"
    )
    for item in candidates:
        scores = item.get("scores")
        observed_scores = dict(scores) if isinstance(scores, Mapping) else {}
        v1_evals = item.get("v1_evals")
        safe_v1_evals = dict(v1_evals) if isinstance(v1_evals, Mapping) else {}
        enforced_failures = [
            decision
            for decision in safe_v1_evals.values()
            if isinstance(decision, Mapping)
            and decision.get("mode") == "enforce"
            and decision.get("status") == "FAIL"
        ]
        status = (
            "PASS"
            if item.get("status") == "PASS" and not enforced_failures
            else "REJECTED"
        )
        reason = str(item.get("diagnosis", "No Topic Value diagnosis was recorded."))
        if enforced_failures:
            reason = "; ".join(
                f"{decision.get('contract')}: {decision.get('reason')}"
                for decision in enforced_failures
            )
        record_run_decision(
            dashboard,
            stage="topic_value",
            decision=f"candidate snapshot ({observation_stage})",
            status=status,
            expected=expected,
            observed=(
                f"scores={observed_scores}; total={item.get('total')}; "
                f"brand_strip={item.get('brand_strip_pass')}; "
                f"feed_value={item.get('feed_value_possible')}; "
                f"authority_goal={item.get('supports_authority_goal')}; "
                f"v1_evals={safe_v1_evals}"
            ),
            reason=reason,
            subject_id=str(item.get("id", "unknown-topic-value-candidate")),
            artifact=relative,
            details={
                "observation_stage": observation_stage,
                "scores": observed_scores,
                "total": item.get("total"),
                "normalization_warnings": item.get("normalization_warnings", []),
                "v1_evals": safe_v1_evals,
            },
        )
    return path


@dataclass(slots=True)
class TopicValueDashboardObserver:
    """Persist Topic Value snapshots without participating in selection."""

    dashboard: dict[str, object]
    folder: Path

    def __call__(
        self,
        stage: str,
        candidates: Sequence[Mapping[str, object]],
    ) -> None:
        record_topic_value_decisions(
            self.dashboard,
            self.folder,
            stage,
            candidates,
        )

    def record_observability_failure(self, stage: str, exc: Exception) -> None:
        record_run_decision(
            self.dashboard,
            stage="topic_value",
            decision="observability_failure",
            status="UNAVAILABLE",
            expected=f"{stage} Topic Value snapshot is recorded without affecting selection",
            observed=f"{type(exc).__name__}: {exc}",
            reason=str(exc),
            subject_id=stage,
        )


def record_thesis_decisions(
    dashboard: dict[str, object],
    trace_path: Path,
) -> None:
    if not trace_path.exists():
        return
    payload = base._private_json(trace_path, "Thesis evaluation trace")
    if not isinstance(payload, Mapping):
        return
    cycles = payload.get("cycles")
    if not isinstance(cycles, Sequence) or isinstance(cycles, (str, bytes)):
        return
    relative = trace_path.relative_to(workflow.REPO_ROOT).as_posix()
    for cycle in cycles:
        if not isinstance(cycle, Mapping):
            continue
        candidates = cycle.get("candidates")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
            continue
        for item in candidates:
            if not isinstance(item, Mapping):
                continue
            scores = item.get("scores")
            score_map = dict(scores) if isinstance(scores, Mapping) else {}
            qualifies = item.get("qualifies") is True
            reasons = item.get("rejection_reasons")
            reason_values = (
                [str(value) for value in reasons]
                if isinstance(reasons, Sequence) and not isinstance(reasons, (str, bytes))
                else []
            )
            record_run_decision(
                dashboard,
                stage="thesis_search",
                decision="thesis clears authority bar",
                status="PASS" if qualifies else "REJECTED",
                expected=(
                    f"total >= {base.MIN_TOTAL}/25 and "
                    f"simplicity >= {base.MIN_SIMPLICITY}/5"
                ),
                observed=(
                    f"cycle={cycle.get('cycle')}; total={item.get('total')}/25; "
                    f"simplicity={score_map.get('simplicity')}/5; axes={score_map}"
                ),
                reason=(
                    "cleared every thesis threshold"
                    if qualifies
                    else "; ".join(reason_values) or "thesis did not qualify"
                ),
                subject_id=str(item.get("id", "unknown-thesis")),
                artifact=relative,
            )


def mark_run_stage(
    dashboard: dict[str, object],
    stage: str,
    status: str,
    reason: str,
    **details: object,
) -> None:
    checks = dashboard.get("checks")
    if not isinstance(checks, list):
        raise workflow.WorkflowError("Run dashboard has an invalid check inventory.")
    for check in checks:
        if isinstance(check, dict) and check.get("stage") == stage:
            check["status"] = status
            check["reason"] = reason
            check["details"] = details
            if status == "FAIL":
                dashboard["outcome"] = "FAIL"
                if dashboard.get("stopped_at") is None:
                    dashboard["stopped_at"] = stage
            record_run_decision(
                dashboard,
                stage=stage,
                decision=f"{check.get('label', stage)} stage outcome",
                status=status,
                expected=details.get("expected", "stage completes without a blocking error"),
                observed=details.get("observed", reason),
                reason=reason,
                artifact=str(
                    details.get("evaluation_artifact")
                    or details.get("log_path")
                    or ""
                ),
                details=details,
            )
            return
    raise workflow.WorkflowError(f"Run dashboard does not recognise stage {stage!r}.")


def persist_run_dashboard(
    folder: Path,
    dashboard: dict[str, object],
    *,
    outcome: str | None = None,
) -> Path:
    if outcome is not None:
        dashboard["outcome"] = outcome
    dashboard["baseline"] = _recent_run_baseline(folder)
    path = base.write_private_json(folder / "run-dashboard.json", dashboard)
    print("Run dashboard:")
    execution = dashboard.get("execution")
    if isinstance(execution, Mapping):
        print(
            "  Execution: "
            f"branch={execution.get('branch')}; commit={execution.get('short_commit')}; "
            f"observability={execution.get('observability_contract')}"
        )
    for check in dashboard["checks"]:  # type: ignore[index]
        print(
            f"  {check['label']}: {check['status']} ({check['reason']})"  # type: ignore[index]
        )
    stopped_at = dashboard.get("stopped_at")
    if stopped_at:
        blocker = next(
            (
                item
                for item in dashboard["checks"]  # type: ignore[index]
                if isinstance(item, Mapping) and item.get("stage") == stopped_at
            ),
            None,
        )
        if isinstance(blocker, Mapping):
            print(
                f"  FIRST BLOCKER: {blocker.get('label')} — {blocker.get('reason')}"
            )
    print(f"Run dashboard stored: {path.relative_to(workflow.REPO_ROOT)}.")
    return path


def render_eval_dashboard(
    rows: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    latest: dict[str, Mapping[str, object]] = {}
    acceptance_by_artifact: dict[str, Mapping[str, object]] = {}
    best_post_artifact = ""
    best_post_score = -1
    for row in rows:
        contract = str(row.get("contract", ""))
        if contract:
            latest[contract] = row
        if contract == "candidate_acceptance":
            artifact = str(row.get("artifact_sha256", ""))
            if artifact:
                acceptance_by_artifact[artifact] = row
        evidence = row.get("evidence")
        score = evidence.get("score") if isinstance(evidence, Mapping) else None
        if contract == "critic_total" and type(score) is int and int(score) > best_post_score:
            best_post_score = int(score)
            best_post_artifact = str(row.get("artifact_sha256", ""))
    checks: list[dict[str, object]] = []
    decisions: list[dict[str, object]] = []
    for sequence, row in enumerate(rows, start=1):
        evidence = row.get("evidence")
        evidence_map = dict(evidence) if isinstance(evidence, Mapping) else {}
        threshold = evidence_map.get("threshold")
        score = evidence_map.get("score", evidence_map.get("effective_total"))
        expected = (
            f"score >= {threshold} under the locked contract"
            if threshold is not None
            else "contract returns PASS under the locked policy"
        )
        observed = (
            f"score={score}; evidence={evidence_map}"
            if score is not None
            else f"reason={row.get('reason', 'not recorded')}; evidence={evidence_map}"
        )
        decisions.append(
            {
                "sequence": sequence,
                "stage": str(row.get("stage", "evaluation")),
                "decision": str(row.get("contract", "unknown contract")),
                "status": str(row.get("status", "NOT_EVALUATED")),
                "expected": expected,
                "observed": observed,
                "reason": str(row.get("reason", "No reason was recorded.")),
                "subject_id": str(row.get("subject_id", "")),
                "artifact": str(row.get("artifact_sha256", "")),
                "details": evidence_map,
            }
        )
    scorecards: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("contract", "")) != "critic_total":
            continue
        evidence = row.get("evidence")
        if not isinstance(evidence, Mapping):
            continue
        axes = evidence.get("axes")
        if not isinstance(axes, Mapping):
            continue
        artifact = str(row.get("artifact_sha256", ""))
        failure_codes = (
            list(evidence.get("failure_codes", []))
            if isinstance(evidence.get("failure_codes"), list)
            else []
        )
        acceptance = acceptance_by_artifact.get(artifact)
        if acceptance is not None and str(acceptance.get("status")) != "PASS":
            acceptance_evidence = acceptance.get("evidence")
            acceptance_codes = (
                acceptance_evidence.get("failure_codes", [])
                if isinstance(acceptance_evidence, Mapping)
                else []
            )
            if isinstance(acceptance_codes, list):
                failure_codes.extend(
                    str(value) for value in acceptance_codes if str(value) not in failure_codes
                )
        scorecards.append(
            {
                "cycle": int(evidence.get("cycle", 0)),
                "candidate_id": str(row.get("subject_id", "")),
                "status": str(row.get("status", "NOT_EVALUATED")),
                "total": int(evidence.get("score", 0)),
                "threshold": int(evidence.get("threshold", 18)),
                "axes": {axis: int(axes.get(axis, 0)) for axis in workflow.CRITIC_AXES},
                "failure_codes": failure_codes,
                "failed_gates": dict(evidence.get("gates", {})) if isinstance(evidence.get("gates"), Mapping) else {},
                "artifact_sha256": artifact,
            }
        )
    print("Eval dashboard:")
    for contract, stage, label in EVAL_CONTRACTS:
        row = latest.get(contract)
        if contract in POST_QUALITY_CONTRACTS and best_post_artifact:
            matching = [
                item for item in rows
                if str(item.get("contract", "")) == contract
                and str(item.get("artifact_sha256", "")) == best_post_artifact
            ]
            if matching:
                row = matching[-1]
        status = str(row.get("status", "NOT_EVALUATED")) if row else "NOT_EVALUATED"
        reason = str(row.get("reason", "stage was not reached")) if row else "stage was not reached"
        checks.append(
            {
                "stage": stage,
                "contract": contract,
                "label": label,
                "category": "post_quality" if contract in POST_QUALITY_CONTRACTS else "pipeline",
                "status": status,
                "reason": reason,
                "subject_id": str(row.get("subject_id", "")) if row else "",
                "evidence": dict(row.get("evidence", {})) if row and isinstance(row.get("evidence"), Mapping) else {},
            }
        )
        print(f"  {stage} | {label}: {status} ({reason})")
    scorecards.sort(key=lambda item: (int(item["cycle"]), str(item["candidate_id"])))
    return {
        "schema_version": 3,
        "checks": checks,
        "critic_scorecards": scorecards,
        "decisions": decisions,
    }


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def update_candidate_inventory(
    candidates: Sequence[Mapping[str, object]],
    *,
    as_of: str,
    days: int,
    path: Path = CANDIDATE_INVENTORY,
) -> tuple[Path, list[dict[str, object]]]:
    """Retain qualified unused topic candidates in a rolling private inventory."""

    target = base._under_private(path)
    now = _parse_timestamp(as_of)
    cutoff = now - timedelta(days=days)
    existing: list[dict[str, object]] = []
    if target.exists():
        raw = base._private_json(target, "Candidate inventory")
        if not isinstance(raw, Mapping) or not isinstance(raw.get("candidates"), list):
            raise workflow.WorkflowError("Candidate inventory has an invalid schema.")
        for item in raw["candidates"]:
            if not isinstance(item, Mapping) or not isinstance(item.get("last_seen_at"), str):
                raise workflow.WorkflowError("Candidate inventory entry is malformed.")
            if _parse_timestamp(str(item["last_seen_at"])) >= cutoff:
                existing.append(dict(item))

    by_topic = {
        " ".join(str(item["topic"]).casefold().split()): item
        for item in existing
        if isinstance(item.get("topic"), str)
    }
    for candidate in candidates:
        momentum_total = candidate.get("total")
        authority = candidate.get("authority_fit")
        authority_total = (
            authority.get("total") if isinstance(authority, Mapping) else None
        )
        if type(momentum_total) is not int or type(authority_total) is not int:
            continue
        combined = int(momentum_total) + int(authority_total)
        if combined < MIN_COMBINED_INVENTORY_SCORE:
            continue
        topic = str(candidate["topic"]).strip()
        key = " ".join(topic.casefold().split())
        prior = by_topic.get(key)
        first_seen = (
            str(prior["first_seen_at"])
            if prior is not None and isinstance(prior.get("first_seen_at"), str)
            else as_of
        )
        by_topic[key] = {
            "topic": topic,
            "why_now": str(candidate["why_now"]),
            "first_seen_at": first_seen,
            "last_seen_at": as_of,
            "expires_at": (now + timedelta(days=days)).isoformat().replace("+00:00", "Z"),
            "momentum_total": int(momentum_total),
            "authority_fit_total": int(authority_total),
            "combined_total": combined,
            "representative_urls": list(candidate.get("representative_urls", [])),
            "status": "AVAILABLE",
        }
    retained = sorted(
        by_topic.values(),
        key=lambda item: (-int(item["combined_total"]), str(item["topic"]).casefold()),
    )
    payload = {
        "schema_version": 1,
        "window_days": days,
        "qualification": (
            f"momentum_total + authority_fit_total >= {MIN_COMBINED_INVENTORY_SCORE}/50"
        ),
        "updated_at": as_of,
        "candidates": retained,
    }
    base.legacy_cli._ensure_owner_only_directory(target.parent)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        offset = 0
        while offset < len(data):
            written = os.write(descriptor, data[offset:])
            if written < 1:
                raise workflow.WorkflowError("Candidate inventory was not written completely.")
            offset += written
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
    finally:
        os.close(descriptor)
    os.replace(temporary, target)
    return target, retained


def select_topic_scope(
    top_five: Sequence[Mapping[str, object]],
    inventory: Sequence[Mapping[str, object]] = (),
) -> tuple[list[dict[str, object]], str]:
    momentum_eligible = [
        dict(item) for item in top_five if item.get("momentum_eligible") is True
    ]
    if momentum_eligible:
        return momentum_eligible, "momentum-qualified"
    retained = [
        dict(item)
        for item in inventory
        if item.get("status") == "AVAILABLE"
        and type(item.get("combined_total")) is int
        and int(item["combined_total"]) >= MIN_COMBINED_INVENTORY_SCORE
    ]
    if retained:
        return retained, "rolling seven-day inventory"
    authority_eligible = [
        dict(item)
        for item in top_five
        if isinstance(item.get("authority_fit"), Mapping)
        and int(item["authority_fit"].get("total", 0)) >= MIN_AUTHORITY_FIT_FALLBACK
        and int(item.get("observed_axes", 0)) >= momentum.MIN_OBSERVED_AXES
    ]
    return authority_eligible, "authority-fit fallback"


def _schema(kind: str) -> dict[str, object]:
    if kind != "cards":
        return base._schema(kind)
    props = {key: {"type": "string"} for key in CARD_KEYS - {"signal_ids"}}
    props["recommended_spine"] = {
        "type": "string",
        "enum": list(CONTENT_SPINES),
    }
    props["signal_ids"] = {
        "type": "array",
        "minItems": 1,
        "maxItems": 2,
        "items": {"type": "string"},
    }
    card = {
        "type": "object",
        "properties": props,
        "required": sorted(CARD_KEYS),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "items": card,
            }
        },
        "required": ["cards"],
        "additionalProperties": False,
    }


def persist_browser_dashboard(
    folder: Path,
    run_dashboard: dict[str, object],
    decision_rows: Sequence[Mapping[str, object]],
) -> tuple[Path, Path]:
    """Persist the machine-readable evals and open their zero-install UI."""

    dashboard = render_eval_dashboard(decision_rows)
    dashboard["run_id"] = run_dashboard.get("run_id", "")
    dashboard_path = base.write_private_json(
        folder / "eval-dashboard.json",
        dashboard,
    )
    browser_dashboard = eval_dashboard_html.write_dashboard(
        folder,
        run_dashboard,
        dashboard,
    )
    opened = eval_dashboard_html.open_dashboard(browser_dashboard)
    print(
        f"Eval dashboard stored: "
        f"{dashboard_path.relative_to(workflow.REPO_ROOT)}."
    )
    print(
        f"Eval dashboard UI: {browser_dashboard.as_uri()}"
        + (" (opened in your browser)." if opened else ".")
    )
    return dashboard_path, browser_dashboard


def validate_cards(
    raw: object,
    signals: Sequence[Mapping[str, object]],
    profile: Mapping[str, object],
) -> list[dict[str, object]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)) or len(raw) != 3:
        raise workflow.WorkflowError("Thesis generator must return exactly three cards.")
    base_cards: list[dict[str, object]] = []
    routing: dict[str, tuple[str, str]] = {}
    for raw_card in raw:
        if not isinstance(raw_card, Mapping) or set(raw_card) != CARD_KEYS:
            raise workflow.WorkflowError("Thesis card has an invalid schema.")
        thesis_id = raw_card.get("id")
        spine = raw_card.get("recommended_spine")
        reason = raw_card.get("spine_fit_reason")
        if not isinstance(thesis_id, str):
            raise workflow.WorkflowError("Thesis card has an invalid ID.")
        if spine not in CONTENT_SPINES:
            raise workflow.WorkflowError("Thesis recommended_spine is unsupported.")
        if (
            not isinstance(reason, str)
            or not reason.strip()
            or reason != reason.strip()
            or len(reason) > MAX_SPINE_FIT_REASON_CHARS
        ):
            raise workflow.WorkflowError("Thesis spine_fit_reason is invalid.")
        if thesis_id in routing:
            raise workflow.WorkflowError("Thesis IDs must be distinct.")
        routing[thesis_id] = (str(spine), reason)
        base_cards.append({key: raw_card[key] for key in base.CARD_KEYS})
    validated = base.validate_cards(base_cards, signals, profile)
    return [
        {
            **card,
            "recommended_spine": routing[str(card["id"])][0],
            "spine_fit_reason": routing[str(card["id"])][1],
        }
        for card in validated
    ]


def generate_cards(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    feedback: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    retry = (
        "\nUNTRUSTED_PREVIOUS_SCORES\n"
        f"{json.dumps(feedback, indent=2, sort_keys=True)}\n"
        "END_UNTRUSTED_PREVIOUS_SCORES\nCreate genuinely different theses."
        if feedback
        else ""
    )
    prompt = f"""Create exactly three one-idea authority thesis cards from the Topic-Value-selected signals. Each supplied signal may contain topic_value annotations naming the selected situation, reader-value route, gravity, reader payoff, and the authority contribution available to this author. Preserve that selected reader value; do not replace it with a generic AI-news thesis. Turn the situation into original product judgment, name a concrete reader problem, state what a team should do differently, connect honestly to one supplied proof ID, and include a non-technical summary of no more than 25 words. Prefer the broadest audience-relevant formulation that preserves the evidence: omit incidental precision or map an instance to its true parent category, but never add severity, prevalence, causality, scope, materiality, or certainty. For each card, include conversation_surface: one concise statement naming the exact assumption, trade-off, counterexample, implementation experience, or unresolved evidence a credible practitioner could challenge or extend. Also include recommended_spine using exactly one of {', '.join(CONTENT_SPINES)}, plus spine_fit_reason explaining why the evidence and conversation surface fit that spine. The spine is advisory only; do not force a template or choose by weekday. The topic field must express the underlying evidence-supported atomic idea in a concise audience-relevant phrase. Do not draft a post or browse. Avoid recent_theses and avoid_topics. Use thesis-1 through thesis-3 exactly once.
UNTRUSTED_PROFILE
{json.dumps(dict(profile), indent=2, sort_keys=True)}
END_UNTRUSTED_PROFILE
UNTRUSTED_TOPIC_VALUE_SIGNALS
{json.dumps(list(signals), indent=2, sort_keys=True)}
END_UNTRUSTED_TOPIC_VALUE_SIGNALS{retry}"""
    result = base.invoke_structured(
        config=base.THESIS_MODEL,
        role_prompt=base._role("thesis"),
        task_prompt=prompt,
        schema=_schema("cards"),
        timeout=420,
        web_search=False,
        stage_label="Thesis generator",
    )
    return validate_cards(result.get("cards"), signals, profile)


def search_theses(
    profile: Mapping[str, object],
    signals: Sequence[Mapping[str, object]],
    *,
    trace_path: Path | None = None,
) -> list[dict[str, object]]:
    feedback: Mapping[str, object] | None = None
    rejected: set[str] = set()
    cycle_traces: list[dict[str, object]] = []
    best_so_far: dict[str, object] | None = None
    for cycle in range(1, base.MAX_CYCLES + 1):
        cards = generate_cards(profile, signals, feedback)
        if any(base._normal(card["thesis"]) in rejected for card in cards):
            raise workflow.WorkflowError("Thesis generator reused a rejected thesis.")
        scores = {
            str(score["thesis_id"]): score
            for score in base.score_cards(cards, profile, signals)
        }
        combined = [
            {
                **card,
                "scores": {
                    axis: int(scores[str(card["id"])][axis])
                    for axis in base.AXES
                },
                "total": int(scores[str(card["id"])]["total"]),
            }
            for card in cards
        ]
        combined.sort(
            key=lambda card: (
                -int(card["total"]),
                -int(card["scores"]["distinctiveness"]),  # type: ignore[index]
                str(card["id"]),
            )
        )
        qualifying = [
            card
            for card in combined
            if int(card["total"]) >= base.MIN_TOTAL
            and int(card["scores"]["simplicity"]) >= base.MIN_SIMPLICITY  # type: ignore[index]
        ]
        evaluated: list[dict[str, object]] = []
        for card in combined:
            reasons: list[str] = []
            if int(card["total"]) < base.MIN_TOTAL:
                reasons.append(
                    f"total {card['total']}/25 is below {base.MIN_TOTAL}/25"
                )
            simplicity = int(card["scores"]["simplicity"])  # type: ignore[index]
            if simplicity < base.MIN_SIMPLICITY:
                reasons.append(
                    f"simplicity {simplicity}/5 is below {base.MIN_SIMPLICITY}/5"
                )
            evaluated.append(
                {
                    **card,
                    "qualifies": not reasons,
                    "rejection_reasons": reasons,
                }
            )
        cycle_traces.append({"cycle": cycle, "candidates": evaluated})
        if best_so_far is None or (
            int(evaluated[0]["total"]),
            int(evaluated[0]["scores"]["distinctiveness"]),  # type: ignore[index]
            int(evaluated[0]["scores"]["simplicity"]),  # type: ignore[index]
        ) > (
            int(best_so_far["total"]),
            int(best_so_far["scores"]["distinctiveness"]),  # type: ignore[index]
            int(best_so_far["scores"]["simplicity"]),  # type: ignore[index]
        ):
            best_so_far = dict(evaluated[0])
        print(f"Thesis evaluation cycle {cycle}:")
        for card in evaluated:
            result = "PASS" if card["qualifies"] else "FAIL"
            reason = (
                "cleared every thesis threshold"
                if card["qualifies"]
                else "; ".join(card["rejection_reasons"])  # type: ignore[arg-type]
            )
            print(
                f"  {card['id']}: {card['total']}/25; "
                f"simplicity={card['scores']['simplicity']}/5; {result} ({reason})"  # type: ignore[index]
            )
            print(
                "    axes="
                + ", ".join(
                    f"{axis}:{card['scores'][axis]}"  # type: ignore[index]
                    for axis in base.AXES
                )
            )
        if qualifying:
            if trace_path is not None:
                base.write_private_json(
                    trace_path,
                    {
                        "schema_version": 1,
                        "outcome": "PASS",
                        "thresholds": {
                            "minimum_total": base.MIN_TOTAL,
                            "minimum_simplicity": base.MIN_SIMPLICITY,
                        },
                        "cycles": cycle_traces,
                        "best_overall": best_so_far,
                        "qualifying_ids": [str(card["id"]) for card in qualifying],
                    },
                )
            print(
                f"Thesis search: retained {len(qualifying)} qualifying candidate(s) "
                f"from cycle {cycle}; weaker parallel candidates were not allowed "
                "to discard the leader."
            )
            return qualifying
        rejected.update(base._normal(card["thesis"]) for card in cards)
        feedback = {
            "cycle": cycle,
            "required_total": base.MIN_TOTAL,
            "required_simplicity": base.MIN_SIMPLICITY,
            "rejected": [
                {
                    "id": card["id"],
                    "thesis": card["thesis"],
                    "conversation_surface": card["conversation_surface"],
                    "scores": card["scores"],
                    "total": card["total"],
                }
                for card in combined
            ],
        }
    if trace_path is not None:
        base.write_private_json(
            trace_path,
            {
                "schema_version": 1,
                "outcome": "FAIL",
                "thresholds": {
                    "minimum_total": base.MIN_TOTAL,
                    "minimum_simplicity": base.MIN_SIMPLICITY,
                },
                "cycles": cycle_traces,
                "best_overall": best_so_far,
                "qualifying_ids": [],
            },
        )
        print(
            f"Thesis evaluation stored: "
            f"{trace_path.relative_to(workflow.REPO_ROOT)}."
        )
    if best_so_far is not None:
        print(
            f"Best thesis across all cycles: {best_so_far['id']} at "
            f"{best_so_far['total']}/25; "
            f"simplicity={best_so_far['scores']['simplicity']}/5; "  # type: ignore[index]
            f"reasons={'; '.join(best_so_far['rejection_reasons'])}."  # type: ignore[arg-type]
        )
    raise workflow.WorkflowError(
        "No thesis cleared the authority bar after the bounded search. "
        "Improve the audience, proof inventory or signals."
    )


def evidence_scope_fingerprint(
    candidates: Sequence[Mapping[str, object]],
    *,
    requested_topic: str | None = None,
) -> str:
    """Bind reusable evidence to the exact admitted topic scope."""

    scope: list[dict[str, object]] = []
    for candidate in candidates:
        topic = candidate.get("topic")
        urls = candidate.get("representative_urls", [])
        if not isinstance(topic, str) or not topic.strip():
            raise workflow.WorkflowError("Admitted evidence scope needs a topic.")
        if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes)):
            raise workflow.WorkflowError("Admitted evidence scope URLs are invalid.")
        canonical_urls: list[str] = []
        for value in urls:
            try:
                canonical_urls.append(workflow.canonicalise_url(str(value)))
            except ValueError as exc:
                raise workflow.WorkflowError(
                    "Admitted evidence scope contains an invalid public URL."
                ) from exc
        scope.append(
            {
                "topic": " ".join(topic.casefold().split()),
                "representative_urls": sorted(set(canonical_urls)),
            }
        )
    if not scope:
        raise workflow.WorkflowError("Evidence verification needs an admitted topic scope.")
    encoded = json.dumps(
        {
            "requested_topic": (
                " ".join(requested_topic.casefold().split())
                if isinstance(requested_topic, str) and requested_topic.strip()
                else None
            ),
            "admitted_scope": sorted(
                scope,
                key=lambda item: (str(item["topic"]), item["representative_urls"]),
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_body_verified_evidence(
    raw_items: Sequence[Mapping[str, object]],
    *,
    days: int,
    as_of: str,
    fetched_at: str | None = None,
    require_stored_hash: bool = False,
) -> list[dict[str, object]]:
    try:
        prepared = workflow.prepare_research_items(raw_items, fetched_at=fetched_at)
        window_end = workflow.parse_published_at(as_of)
    except (TypeError, ValueError) as exc:
        raise workflow.WorkflowError("Evidence Scout returned invalid research records.") from exc
    window_start = window_end - timedelta(days=days)
    seen_urls: set[str] = set()
    seen_hashes: set[str] = set()
    for raw, item in zip(raw_items, prepared, strict=True):
        body = item.get("body")
        if not isinstance(body, str) or not body.strip():
            raise workflow.WorkflowError("Evidence verification requires a non-blank source body.")
        earliest, latest, precision = workflow.source_publication_bounds(
            str(item["published_at"])
        )
        if latest < window_start or earliest > window_end:
            raise workflow.WorkflowError(
                "Evidence verification found a source outside the requested time window."
            )
        item["publication_date_precision"] = precision
        item["publication_date_uncertain"] = precision == "month"
        canonical_url = str(item["canonical_url"])
        content_hash = str(item["content_hash"])
        if require_stored_hash and raw.get("content_hash") != content_hash:
            raise workflow.WorkflowError(
                "Verified evidence cache content hash no longer matches its source body."
            )
        if canonical_url in seen_urls or content_hash in seen_hashes:
            raise workflow.WorkflowError("Evidence verification requires distinct source bodies.")
        seen_urls.add(canonical_url)
        seen_hashes.add(content_hash)
    if not MIN_VERIFIED_EVIDENCE <= len(prepared) <= MAX_VERIFIED_EVIDENCE:
        raise workflow.WorkflowError(
            f"Discovery needs {MIN_VERIFIED_EVIDENCE} to {MAX_VERIFIED_EVIDENCE} "
            "body-verified signals."
        )
    return prepared


def _invoke_signal_scout(
    topic: str | None,
    days: int,
    as_of: str,
    admitted_candidates: Sequence[Mapping[str, object]],
    *,
    timeout: int = EVIDENCE_TIMEOUT_SECONDS,
    target_count: int = 3,
    stage_label: str = "Evidence Scout",
) -> list[dict[str, object]]:
    scope_lines: list[str] = []
    lead_urls: dict[str, set[str]] = {}
    for index, candidate in enumerate(admitted_candidates, start=1):
        candidate_topic = str(candidate.get("topic", "")).strip()
        raw_urls = candidate.get("representative_urls", [])
        if not isinstance(raw_urls, Sequence) or isinstance(raw_urls, (str, bytes)):
            raise workflow.WorkflowError("Evidence lead URLs are invalid.")
        urls: list[str] = []
        for value in raw_urls:
            try:
                urls.append(workflow.canonicalise_url(str(value)))
            except ValueError as exc:
                raise workflow.WorkflowError("Evidence lead URL is invalid.") from exc
        if not candidate_topic or not urls:
            raise workflow.WorkflowError("Evidence verification needs topic-and-URL leads.")
        lead_id = f"lead-{index}"
        lead_urls[lead_id] = set(urls)
        scope_lines.append(f"[{lead_id}] {candidate_topic}: {', '.join(urls)}")
    ranked_scope = "\n- ".join(scope_lines)
    prompt = f"""Find {target_count} defensible GenAI product signals published during the {days} days ending {as_of}.
Scope: {topic or 'agentic AI, evaluations, reliability, enterprise AI and AI product management'}.
Discovery is already complete. Start from the supplied topic-and-URL leads below; do not search for or rank new topics. Read the linked bodies. When a supplied social or aggregation URL cannot support the factual claim, find only the primary or reputable source needed to verify that same claim:
- {ranked_scope}
For every returned item, copy the supplied lead_id and the exact supplied lead_url that nominated the claim. The item's url may be the stronger primary source used to verify it. Prefer official engineering/research blogs, documentation, papers, repositories, government and standards sources. Collect enough body evidence for a later selector to answer: what concretely changed, who in the target audience would care, what capability/decision/utility the reader receives, how consequential it is, and what inspectable evidence supports it. Return concise evidence summaries, not copied prose, topic rankings, theses, or post drafts. Public social pages may nominate a claim, but factual evidence must come from the normal primary/reputable source rules. Never access authenticated LinkedIn/X pages, email, private data, local files, credentials or authenticated services."""
    schema = json.loads(json.dumps(base._schema("research")))
    item_schema = schema["properties"]["items"]["items"]
    item_schema["properties"]["lead_id"] = {
        "type": "string",
        "enum": sorted(lead_urls),
    }
    item_schema["properties"]["lead_url"] = {
        "type": "string",
        "enum": sorted({url for values in lead_urls.values() for url in values}),
    }
    item_schema["required"].extend(["lead_id", "lead_url"])
    result = base.invoke_structured(
        config=base.SCOUT_MODEL,
        role_prompt=base._role("scout"),
        task_prompt=prompt,
        schema=schema,
        timeout=timeout,
        web_search=True,
        stage_label=stage_label,
    )
    items = result.get("items")
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise workflow.WorkflowError("Scout must return an items list.")
    bound: list[dict[str, object]] = []
    bindings: list[tuple[str, str]] = []
    for item in items:
        if not isinstance(item, Mapping):
            raise workflow.WorkflowError("Evidence Scout item is invalid.")
        lead_id = item.get("lead_id")
        lead_url = item.get("lead_url")
        if (
            not isinstance(lead_id, str)
            or not isinstance(lead_url, str)
            or lead_id not in lead_urls
        ):
            raise workflow.WorkflowError("Evidence Scout item has no admitted lead identity.")
        try:
            canonical_lead_url = workflow.canonicalise_url(lead_url)
        except ValueError as exc:
            raise workflow.WorkflowError("Evidence Scout lead URL is invalid.") from exc
        if canonical_lead_url not in lead_urls[lead_id]:
            raise workflow.WorkflowError(
                "Evidence Scout item does not match its admitted topic-and-URL lead."
            )
        cleaned = dict(item)
        cleaned.pop("lead_id", None)
        cleaned.pop("lead_url", None)
        bound.append(cleaned)
        bindings.append((lead_id, canonical_lead_url))
    prepared = _validate_body_verified_evidence(bound, days=days, as_of=as_of)
    for item, (lead_id, lead_url) in zip(prepared, bindings, strict=True):
        item["admitted_lead_id"] = lead_id
        item["admitted_lead_url"] = lead_url
    return prepared


def _timed_out(exc: Exception) -> bool:
    return "timed out" in str(exc).casefold()


def _cached_evidence_for_scope(
    *,
    scope_fingerprint: str,
    days: int,
    as_of: str,
    current_folder: Path,
    db_path: Path,
) -> list[dict[str, object]]:
    candidates: list[tuple[float, Path, str]] = []
    paths = (
        (workflow.DEFAULT_PRIVATE_DATA.rglob(EVIDENCE_CACHE_NAME), "snapshot"),
        (workflow.DEFAULT_PRIVATE_DATA.rglob("theses.json"), "legacy-theses"),
    )
    for collection, kind in paths:
        for path in collection:
            try:
                if path.parent.resolve() == current_folder.resolve() or path.is_symlink():
                    continue
                candidates.append((path.stat().st_mtime, path, kind))
            except OSError:
                continue
    for _modified, path, kind in sorted(candidates, reverse=True):
        try:
            payload = base._private_json(
                path,
                "Verified evidence cache" if kind == "snapshot" else "Prior thesis evidence",
            )
        except workflow.WorkflowError:
            continue
        if not isinstance(payload, Mapping) or payload.get("schema_version") != 1:
            continue
        if kind == "snapshot":
            if (
                payload.get("scope_fingerprint") != scope_fingerprint
                or payload.get("origin") != "body-verified-private-web"
            ):
                continue
            raw_items = payload.get("items")
        else:
            previous_scope = payload.get("conversation_momentum")
            if not isinstance(previous_scope, Sequence) or isinstance(
                previous_scope, (str, bytes)
            ):
                continue
            try:
                previous_fingerprint = evidence_scope_fingerprint(
                    [dict(item) for item in previous_scope if isinstance(item, Mapping)],
                    requested_topic=(
                        str(payload["topic"])
                        if isinstance(payload.get("topic"), str)
                        else None
                    ),
                )
            except workflow.WorkflowError:
                continue
            if previous_fingerprint != scope_fingerprint:
                continue
            raw_items = payload.get("raw_signals")
        fetched_at = payload.get("created_at")
        if (
            not isinstance(raw_items, Sequence)
            or isinstance(raw_items, (str, bytes))
            or not isinstance(fetched_at, str)
            or any(not isinstance(item, Mapping) for item in raw_items)
        ):
            continue
        raw_records = [dict(item) for item in raw_items]
        try:
            prepared = _validate_body_verified_evidence(
                raw_records,
                days=days,
                as_of=as_of,
                fetched_at=fetched_at,
                require_stored_hash=kind == "snapshot",
            )
            if kind == "snapshot":
                for raw, item in zip(raw_records, prepared, strict=True):
                    fetched_at_value = raw.get("fetched_at")
                    if not isinstance(fetched_at_value, str):
                        raise workflow.WorkflowError(
                            "Verified evidence cache is missing fetch provenance."
                        )
                    workflow.parse_published_at(fetched_at_value)
                    item["fetched_at"] = fetched_at_value
                    if isinstance(raw.get("admitted_lead_id"), str) and isinstance(
                        raw.get("admitted_lead_url"), str
                    ):
                        item["admitted_lead_id"] = raw["admitted_lead_id"]
                        item["admitted_lead_url"] = raw["admitted_lead_url"]
        except workflow.WorkflowError:
            continue
        if kind == "legacy-theses":
            if not db_path.is_file() or db_path.is_symlink():
                continue
            identities = [
                {
                    "canonical_url": item["canonical_url"],
                    "content_hash": item["content_hash"],
                }
                for item in prepared
            ]
            try:
                stored = storage.list_research_items_by_identity(db_path, identities)
            except (OSError, ValueError, workflow.WorkflowError):
                continue
            if len(stored) != len(prepared):
                continue
        return prepared
    return []


def _database_evidence_for_scope(
    *,
    admitted_candidates: Sequence[Mapping[str, object]],
    days: int,
    as_of: str,
    db_path: Path,
) -> list[dict[str, object]]:
    """Reuse exact admitted URLs whose verified bodies already exist privately."""

    if not db_path.is_file() or db_path.is_symlink():
        return []
    admitted_urls: set[str] = set()
    for candidate in admitted_candidates:
        urls = candidate.get("representative_urls", [])
        if not isinstance(urls, Sequence) or isinstance(urls, (str, bytes)):
            continue
        for value in urls:
            try:
                admitted_urls.add(workflow.canonicalise_url(str(value)))
            except ValueError:
                continue
    if not admitted_urls:
        return []
    try:
        stored = storage.list_research_items_by_urls(
            db_path,
            sorted(admitted_urls),
            evidence_origin="private-import",
        )
    except (OSError, ValueError, workflow.WorkflowError):
        return []
    exact = stored[:MAX_VERIFIED_EVIDENCE]
    if len(exact) < MIN_VERIFIED_EVIDENCE:
        return []
    try:
        prepared = _validate_body_verified_evidence(
            exact,
            days=days,
            as_of=as_of,
            require_stored_hash=True,
        )
        for raw, item in zip(exact, prepared, strict=True):
            fetched_at = raw.get("fetched_at")
            if not isinstance(fetched_at, str):
                return []
            workflow.parse_published_at(fetched_at)
            item["fetched_at"] = fetched_at
        return prepared
    except workflow.WorkflowError:
        return []


def resolve_signal_evidence(
    topic: str | None,
    days: int,
    as_of: str,
    admitted_candidates: Sequence[Mapping[str, object]],
    *,
    folder: Path,
    db_path: Path,
    attempt_trace: list[dict[str, object]] | None = None,
) -> EvidenceResolution:
    trace = attempt_trace if attempt_trace is not None else []
    fingerprint = evidence_scope_fingerprint(
        admitted_candidates,
        requested_topic=topic,
    )
    cached = _cached_evidence_for_scope(
        scope_fingerprint=fingerprint,
        days=days,
        as_of=as_of,
        current_folder=folder,
        db_path=db_path,
    )
    if cached:
        trace.append(
            {
                "route": "verified-cache",
                "status": "PASS",
                "signal_count": len(cached),
                "live_call_started": False,
            }
        )
        print(
            f"Evidence Scout: reusing {len(cached)} exact-scope body-verified "
            "signal(s); no live evidence search was started.",
            flush=True,
        )
        return EvidenceResolution(tuple(cached), "verified-cache", 0, fingerprint)
    trace.append(
        {
            "route": "verified-cache",
            "status": "MISS",
            "signal_count": 0,
            "live_call_started": False,
        }
    )
    stored = _database_evidence_for_scope(
        admitted_candidates=admitted_candidates,
        days=days,
        as_of=as_of,
        db_path=db_path,
    )
    if stored:
        trace.append(
            {
                "route": "verified-database",
                "status": "PASS",
                "signal_count": len(stored),
                "live_call_started": False,
            }
        )
        print(
            f"Evidence Scout: reusing {len(stored)} body-verified signal(s) by "
            "exact admitted URL; no live evidence search was started.",
            flush=True,
        )
        return EvidenceResolution(tuple(stored), "verified-database", 0, fingerprint)
    trace.append(
        {
            "route": "verified-database",
            "status": "MISS",
            "signal_count": 0,
            "live_call_started": False,
        }
    )
    started = time.monotonic()
    try:
        items = _invoke_signal_scout(
            topic,
            days,
            as_of,
            admitted_candidates,
            timeout=EVIDENCE_TIMEOUT_SECONDS,
            target_count=3,
            stage_label="Evidence Scout targeted verification",
        )
        trace.append(
            {
                "route": "live-targeted",
                "status": "PASS",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "timeout_seconds": EVIDENCE_TIMEOUT_SECONDS,
                "target_count": 3,
                "signal_count": len(items),
                "model": base.SCOUT_MODEL.trace(),
                "live_call_started": True,
            }
        )
        return EvidenceResolution(tuple(items), "live-targeted", 1, fingerprint)
    except workflow.WorkflowError as exc:
        trace.append(
            {
                "route": "live-targeted",
                "status": "TIMEOUT" if _timed_out(exc) else "FAIL",
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "timeout_seconds": EVIDENCE_TIMEOUT_SECONDS,
                "target_count": 3,
                "signal_count": 0,
                "model": base.SCOUT_MODEL.trace(),
                "reason": str(exc),
                "live_call_started": True,
            }
        )
        if not _timed_out(exc):
            raise
    raise workflow.WorkflowError(
        "Targeted Evidence Scout timed out after one bounded attempt. Discovery "
        "artifacts were preserved; resume this run without repeating discovery."
    )


def command(args: argparse.Namespace) -> int:
    if not args.allow_web_research:
        raise workflow.WorkflowError("Discovery requires --allow-web-research.")
    if not args.allow_model_egress:
        raise workflow.WorkflowError(
            "Discovery requires --allow-model-egress before the private profile reaches thesis models."
        )
    run_id = v1_completion.begin_run()
    print(f"Run ID: {run_id}")
    ledger_path = (
        v1_completion.STATE_ROOT / v1_completion.DECISION_LEDGER_NAME
    )
    ledger_start = len(v1_completion._read_jsonl(ledger_path))
    profile = base.validate_profile(base._private_json(args.profile, "Authority profile"))
    resume = (
        load_discovery_resume(
            args.resume_from,
            days=args.days,
            requested_topic=args.topic,
            profile=profile,
        )
        if getattr(args, "resume_from", None) is not None
        else None
    )
    as_of = resume.as_of if resume is not None else (
        args.as_of
        or datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    if resume is not None and args.as_of is not None and args.as_of != resume.as_of:
        raise workflow.WorkflowError("Resume run must retain its original --as-of value.")
    workflow.parse_published_at(as_of)

    folder = base._under_private(
        args.output_dir
        or base.OUTPUT_ROOT / as_of[:10] / as_of[11:19].replace(":", "")
    )
    base.legacy_cli._ensure_owner_only_directory(folder)
    if resume is not None and folder.resolve() == resume.source_folder.resolve():
        raise workflow.WorkflowError(
            "Resume output must be different from the preserved source run."
        )
    run_dashboard = new_run_dashboard(run_id)

    try:
        if resume is not None:
            top_five = [dict(item) for item in resume.top_five]
            momentum_candidates = list(top_five)
            ranked = list(top_five)
        else:
            momentum_candidates = momentum.invoke_scout(args.topic, args.days, as_of)
            ranked = momentum.rank_candidates(
                momentum_candidates,
                minimum=momentum.MIN_AUTHORITY_MOMENTUM,
            )
            top_five = ranked[: momentum.MOMENTUM_TOP_K]
            authority_scores = momentum.score_authority_fit(top_five, profile)
            top_five = momentum.attach_authority_fit(top_five, authority_scores)
    except STAGE_EXCEPTIONS as exc:
        run_dashboard["surface_scouts"] = surface_diagnostics(folder)
        record_surface_decisions(run_dashboard, run_dashboard["surface_scouts"])  # type: ignore[arg-type]
        mark_run_stage(
            run_dashboard,
            "conversation_discovery",
            "FAIL",
            str(exc),
            expected="all configured scouts return enough valid evidence to rank candidates",
            observed=f"{type(exc).__name__}: {exc}",
            exception_type=type(exc).__name__,
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    run_dashboard["surface_scouts"] = (
        [dict(item) for item in resume.surface_scouts]
        if resume is not None
        else surface_diagnostics(folder)
    )
    record_surface_decisions(run_dashboard, run_dashboard["surface_scouts"])  # type: ignore[arg-type]
    record_momentum_decisions(run_dashboard, top_five)
    mark_run_stage(
        run_dashboard,
        "conversation_discovery",
        "PASS",
        (
            "conversation candidates and rankings were resumed from the preserved run"
            if resume is not None
            else "conversation candidates were collected and ranked"
        ),
        signal_count=len(momentum_candidates),
        ranked_count=len(ranked),
        resumed_from=(
            resume.source_folder.relative_to(workflow.REPO_ROOT).as_posix()
            if resume is not None
            else None
        ),
        observed_scouts=sum(
            1 for item in run_dashboard["surface_scouts"]  # type: ignore[index]
            if isinstance(item, Mapping) and item.get("status") == "OBSERVED"
        ),
        surface_signals=sum(
            int(item.get("signal_count", 0))
            for item in run_dashboard["surface_scouts"]  # type: ignore[index]
            if isinstance(item, Mapping)
        ),
    )
    if resume is None:
        inventory_path, inventory = update_candidate_inventory(
            top_five,
            as_of=as_of,
            days=args.days,
        )
    else:
        inventory_path, inventory = CANDIDATE_INVENTORY, []

    momentum_package = base.write_private_json(
        folder / "momentum.json",
        {
            "schema_version": 1,
            "created_at": as_of,
            "label": momentum.MOMENTUM_LABEL,
            "topic": args.topic,
            "days": args.days,
            "threshold": momentum.MIN_AUTHORITY_MOMENTUM,
            "ranking_claim_limit": (
                "Public-web proxy only; not an exact X/Twitter popularity ranking."
            ),
            "candidates": top_five,
            "publishing_status": "DISABLED",
            "human_selection_required": True,
            "resumed_from": (
                resume.source_folder.relative_to(workflow.REPO_ROOT).as_posix()
                if resume is not None
                else None
            ),
        },
    )
    if resume is None:
        momentum.print_top(top_five)
    else:
        print(f"Resumed {len(top_five)} previously ranked topic candidate(s).")
    print(
        f"Momentum evidence stored: "
        f"{momentum_package.relative_to(workflow.REPO_ROOT)}."
    )
    if resume is None:
        print(
            f"Rolling candidate inventory: {len(inventory)} qualified unused topic(s) at "
            f"{inventory_path.relative_to(workflow.REPO_ROOT)}."
        )
    else:
        print(
            "Resume: conversation discovery and topic admission were not executed again."
        )

    if resume is None:
        eligible, discovery_route = select_topic_scope(top_five, inventory)
    else:
        eligible = [dict(item) for item in resume.eligible]
        discovery_route = resume.route
    if not eligible:
        record_topic_admission_decisions(
            run_dashboard,
            top_five,
            (),
            discovery_route,
        )
        reason = (
            "No topic cleared either the authority conversation-momentum floor or the "
            "evidence-bounded authority-fit fallback."
        )
        mark_run_stage(run_dashboard, "topic_admission", "FAIL", reason)
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise workflow.WorkflowError(
            f"{reason} No thesis was generated."
        )
    record_topic_admission_decisions(
        run_dashboard,
        eligible if resume is not None else top_five,
        eligible,
        discovery_route,
    )
    mark_run_stage(
        run_dashboard,
        "topic_admission",
        "PASS",
        f"{len(eligible)} topic(s) admitted through {discovery_route}",
        route=discovery_route,
        admitted_topics=[str(item["topic"]) for item in eligible],
        resumed_from=(
            resume.source_folder.relative_to(workflow.REPO_ROOT).as_posix()
            if resume is not None
            else None
        ),
    )
    print(
        f"Discovery route: {discovery_route}; {len(eligible)} topic(s) admitted "
        "to evidence verification."
    )

    base.write_private_json(
        folder / ADMITTED_SCOPE_NAME,
        {
            "schema_version": 1,
            "created_at": as_of,
            "topic": args.topic,
            "days": args.days,
            "route": discovery_route,
            "candidates": eligible,
            "profile_sha256": _mapping_sha256(profile),
            "scope_fingerprint": evidence_scope_fingerprint(
                eligible,
                requested_topic=args.topic,
            ),
            "resumed_from": (
                resume.source_folder.relative_to(workflow.REPO_ROOT).as_posix()
                if resume is not None
                else None
            ),
        },
    )

    db = base._under_private(args.db)
    evidence_attempts: list[dict[str, object]] = []
    try:
        evidence_resolution = resolve_signal_evidence(
            args.topic,
            args.days,
            as_of,
            eligible,
            folder=folder,
            db_path=db,
            attempt_trace=evidence_attempts,
        )
        evidence_attempt_path = base.write_private_json(
            folder / "evidence-attempts.json",
            {
                "schema_version": 1,
                "created_at": as_of,
                "scope_fingerprint": evidence_resolution.scope_fingerprint,
                "attempts": evidence_attempts,
            },
        )
        items = list(evidence_resolution.items)
        raw_signals = base.project_signals(items)
        evidence_snapshot = base.write_private_json(
            folder / EVIDENCE_CACHE_NAME,
            {
                "schema_version": 1,
                "created_at": as_of,
                "window_days": args.days,
                "window_end": as_of,
                "scope_fingerprint": evidence_resolution.scope_fingerprint,
                "admitted_topics": [str(item["topic"]) for item in eligible],
                "origin": "body-verified-private-web",
                "acquisition_route": evidence_resolution.route,
                "live_attempts": evidence_resolution.attempts,
                "items": items,
                "publishing_status": "DISABLED",
            },
        )
        base.legacy_cli.initialise_paths(db)
        inserted, duplicates = storage.insert_research_items(
            db, items, evidence_origin="private-import"
        )
    except STAGE_EXCEPTIONS as exc:
        evidence_attempt_path = base.write_private_json(
            folder / "evidence-attempts.json",
            {
                "schema_version": 1,
                "created_at": as_of,
                "attempts": evidence_attempts,
            },
        )
        mark_run_stage(
            run_dashboard,
            "evidence_verification",
            "FAIL",
            str(exc),
            expected="3-7 research signals pass timestamp, source-body, URL, and source-quality validation",
            observed=f"{type(exc).__name__}: {exc}",
            exception_type=type(exc).__name__,
            attempt_trace=evidence_attempt_path.relative_to(
                workflow.REPO_ROOT
            ).as_posix(),
            attempts=evidence_attempts,
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    record_evidence_decisions(run_dashboard, raw_signals)
    mark_run_stage(
        run_dashboard,
        "evidence_verification",
        "PASS",
        f"{len(raw_signals)} body-verified signal(s) prepared",
        signal_ids=[str(item["id"]) for item in raw_signals],
        acquisition_route=evidence_resolution.route,
        live_attempts=evidence_resolution.attempts,
        evidence_snapshot=evidence_snapshot.relative_to(workflow.REPO_ROOT).as_posix(),
        attempt_trace=evidence_attempt_path.relative_to(workflow.REPO_ROOT).as_posix(),
        database_inserted=inserted,
        database_duplicates=duplicates,
    )

    topic_value_pre_gate_path = folder / "topic-value-evaluations-pre-gate.json"
    topic_value_post_gate_path = folder / "topic-value-evaluations-post-gate.json"
    try:
        topic_value_candidates = topic_value.invoke_discovery_selector(
            profile,
            raw_signals,
            observer=TopicValueDashboardObserver(run_dashboard, folder),
        )
        signals = topic_value.project_discovery_signals(raw_signals, topic_value_candidates)
    except STAGE_EXCEPTIONS as exc:
        gate_decision = getattr(exc, "decision", None)
        structured_gate = (
            dict(gate_decision) if isinstance(gate_decision, Mapping) else {}
        )
        failure_reason = (
            f"{structured_gate.get('contract')}: {structured_gate.get('reason')}"
            if structured_gate
            else str(exc)
        )
        mark_run_stage(
            run_dashboard,
            "topic_value",
            "FAIL",
            failure_reason,
            expected="at least one grounded candidate clears every locked Topic Value rule",
            observed=(
                structured_gate
                if structured_gate
                else f"{type(exc).__name__}: {exc}"
            ),
            exception_type=type(exc).__name__,
            gate_decision=structured_gate,
            evaluation_artifact=next(
                (
                    path.relative_to(workflow.REPO_ROOT).as_posix()
                    for path in (topic_value_post_gate_path, topic_value_pre_gate_path)
                    if path.exists()
                ),
                "",
            ),
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    mark_run_stage(
        run_dashboard,
        "topic_value",
        "PASS",
        f"{len(topic_value_candidates)} situation(s) cleared Topic Value",
        candidates=[
            {
                "id": str(item["id"]),
                "total": int(item["total"]),
                "priority": str(item["priority"]),
            }
            for item in topic_value_candidates
        ],
        evaluation_artifact=next(
            (
                path.relative_to(workflow.REPO_ROOT).as_posix()
                for path in (topic_value_post_gate_path, topic_value_pre_gate_path)
                if path.exists()
            ),
            "",
        ),
    )
    topic_value_package = base.write_private_json(
        folder / "topic-value.json",
        {
            "schema_version": 1,
            "created_at": as_of,
            "target_audience": profile["target_audience"],
            "authority_goal": profile["authority_goal"],
            "candidates": topic_value_candidates,
            "selected_signal_ids": [str(item["id"]) for item in signals],
            "publishing_status": "DISABLED",
            "human_selection_required": True,
        },
    )
    print(
        f"Topic Value evidence stored: "
        f"{topic_value_package.relative_to(workflow.REPO_ROOT)}."
    )
    print(
        f"{len(topic_value_candidates)} situation(s) cleared Topic Value before "
        "thesis generation:"
    )
    for candidate in topic_value_candidates:
        print(
            f"{candidate['id']}: {candidate['reader_value_type']} | "
            f"gravity={candidate['gravity']} | priority={candidate['priority']} | "
            f"score={candidate['total']}/25"
        )
        print(f"Situation: {candidate['situation']}")
        print(f"Reader value: {candidate['reader_value']}")

    thesis_trace_path = folder / "thesis-evaluations.json"
    try:
        theses = search_theses(
            profile,
            signals,
            trace_path=thesis_trace_path,
        )
    except STAGE_EXCEPTIONS as exc:
        record_thesis_decisions(run_dashboard, thesis_trace_path)
        trace_details: dict[str, object] = {}
        if thesis_trace_path.exists():
            trace_details["evaluation_artifact"] = thesis_trace_path.relative_to(
                workflow.REPO_ROOT
            ).as_posix()
        mark_run_stage(
            run_dashboard,
            "thesis_search",
            "FAIL",
            str(exc),
            expected=(
                f"at least one thesis scores >= {base.MIN_TOTAL}/25 with "
                f"simplicity >= {base.MIN_SIMPLICITY}/5"
            ),
            observed=f"{type(exc).__name__}: {exc}",
            exception_type=type(exc).__name__,
            **trace_details,
        )
        persist_run_dashboard(folder, run_dashboard)
        persist_browser_dashboard(
            folder,
            run_dashboard,
            v1_completion._read_jsonl(ledger_path)[ledger_start:],
        )
        raise
    record_thesis_decisions(run_dashboard, thesis_trace_path)
    mark_run_stage(
        run_dashboard,
        "thesis_search",
        "PASS",
        f"{len(theses)} thesis candidate(s) cleared the authority bar",
        qualifying_ids=[str(item["id"]) for item in theses],
        evaluation_artifact=thesis_trace_path.relative_to(workflow.REPO_ROOT).as_posix(),
    )

    package = base.write_private_json(
        folder / "theses.json",
        {
            "schema_version": 1,
            "created_at": as_of,
            "topic": args.topic,
            "days": args.days,
            "momentum_label": momentum.MOMENTUM_LABEL,
            "conversation_momentum": top_five,
            "topic_value_candidates": topic_value_candidates,
            "raw_signals": raw_signals,
            "signals": signals,
            "theses": theses,
            "publishing_status": "DISABLED",
            "human_selection_required": True,
        },
    )
    db_rel = db.relative_to(workflow.REPO_ROOT).as_posix()
    print(
        f"Live research stored: inserted={inserted}; duplicates={duplicates}; "
        f"package={package.relative_to(workflow.REPO_ROOT)}."
    )
    print(f"{len(theses)} thesis candidate(s) cleared the locked authority bar:")
    draft_commands: list[tuple[dict[str, object], list[str], str]] = []
    for card in theses:
        strategy = base.write_private_json(
            folder / f"strategy-{card['id']}.json",
            base.strategy_for(card, profile),
        )
        evidence_manifest = base.write_private_json(
            folder / f"evidence-{card['id']}.json",
            base.evidence_manifest_for(card, signals, items),
        )
        strategy_rel = strategy.relative_to(workflow.REPO_ROOT).as_posix()
        evidence_rel = evidence_manifest.relative_to(workflow.REPO_ROOT).as_posix()
        week_slot = getattr(args, "week_slot", None)
        slot_arg = f" --week-slot {week_slot}" if week_slot is not None else ""
        draft = (
            f"./bin/linkedin-os draft --topic {json.dumps(str(card['topic']))} "
            f"--goal authority --format text{slot_arg} "
            f"--strategy-input {json.dumps(strategy_rel)} "
            f"--evidence-manifest {json.dumps(evidence_rel)} "
            f"--db {json.dumps(db_rel)} --allow-model-egress --package"
        )
        draft_argv = [
            str(workflow.REPO_ROOT / "bin" / "linkedin-os"),
            "draft",
            "--topic",
            str(card["topic"]),
            "--goal",
            "authority",
            "--format",
            "text",
        ]
        if week_slot is not None:
            draft_argv.extend(["--week-slot", str(week_slot)])
        draft_argv.extend([
            "--strategy-input",
            strategy_rel,
            "--evidence-manifest",
            evidence_rel,
            "--db",
            db_rel,
            "--allow-model-egress",
            "--package",
        ])
        draft_commands.append((card, draft_argv, draft))
        print(
            f"{card['id']}: {card['plain_language_summary']} "
            f"[{card['total']}/25; simplicity={card['scores']['simplicity']}/5]"
        )
        print(f"Decision: {card['product_decision']}")
        print(f"Conversation: {card['conversation_surface']}")
        print(
            f"Spine: {card['recommended_spine']} — {card['spine_fit_reason']}"
        )
        print(f"Draft command: {draft}")
    if getattr(args, "generate_post", False):
        selected = draft_commands[0]
        record_run_decision(
            run_dashboard,
            stage="drafting",
            decision="thesis selected for drafting",
            status="PASS",
            expected="highest-ranked thesis that cleared the locked authority bar",
            observed=(
                f"candidate={selected[0]['id']}; total={selected[0]['total']}/25; "
                f"simplicity={selected[0]['scores']['simplicity']}/5"
            ),
            reason="highest qualifying thesis selected deterministically",
            subject_id=str(selected[0]["id"]),
        )
        guidance = workflow.load_voice_guidance()
        anchors = [
            key for key, value in guidance.items()
            if key != "provenance" and isinstance(value, str) and value.strip()
        ]
        print(
            f"Auto-selection: {selected[0]['id']} ({selected[0]['total']}/25), "
            "the highest qualifying thesis."
        )
        print(
            f"Voice stage: LOADED ({len(anchors)} non-blank anchor(s)); "
            "Writer and Critic receive the same guidance."
        )
        run_dashboard["voice_stage"] = {
            "status": "LOADED",
            "anchor_count": len(anchors),
            "provenance": str(guidance.get("provenance", "not-recorded")),
        }
        print("Drafting: starting the high-bar post workflow.", flush=True)
        child_env = os.environ.copy()
        child_env["LINKEDIN_OS_BEST_EFFORT_OUTPUT"] = str(
            folder / "best-effort-post.md"
        )
        completed = run_drafting_child(
            selected[1],
            cwd=workflow.REPO_ROOT,
            folder=folder,
            env=child_env,
        )
        current_rows = v1_completion._read_jsonl(ledger_path)[ledger_start:]
        dashboard = render_eval_dashboard(current_rows)
        dashboard["run_id"] = run_id
        dashboard_path = base.write_private_json(
            folder / "eval-dashboard.json",
            dashboard,
        )
        evaluated_rows = [
            check
            for check in dashboard["checks"]
            if check["status"] != "NOT_EVALUATED"
        ]
        post_evaluated_rows = [
            check
            for check in evaluated_rows
            if check.get("category") == "post_quality"
        ]
        failed_rows = [
            check
            for check in evaluated_rows
            if check["status"] in {"FAIL", "BLOCKED"}
        ]
        record_drafting_stage(
            run_dashboard,
            completed,
            post_evaluated=bool(post_evaluated_rows),
        )
        if failed_rows:
            first_failure = failed_rows[0]
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "FAIL",
                f"{first_failure['label']}: {first_failure['reason']}",
                failed_contracts=[str(check["contract"]) for check in failed_rows],
                failure_reasons=[
                    {
                        "contract": str(check["contract"]),
                        "reason": str(check["reason"]),
                    }
                    for check in failed_rows
                ],
            )
        elif completed.returncode != 0 and post_evaluated_rows:
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "FAIL",
                f"workflow failed after recorded evals passed: {completed.reason}",
                evaluated_contracts=[
                    str(check["contract"]) for check in evaluated_rows
                ],
            )
        elif completed.returncode != 0:
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "FAIL",
                f"draft subprocess stopped before a valid Critic 1-5 scorecard: {completed.reason}",
                return_code=completed.returncode,
            )
        elif completed.returncode == 0:
            mark_run_stage(
                run_dashboard,
                "final_evals",
                "PASS",
                f"{len(evaluated_rows)} evaluated contract(s) cleared",
            )
        print(
            f"Eval dashboard stored: "
            f"{dashboard_path.relative_to(workflow.REPO_ROOT)}."
        )
        persist_run_dashboard(
            folder,
            run_dashboard,
            outcome="PASS" if completed.returncode == 0 else "FAIL",
        )
        browser_dashboard = eval_dashboard_html.write_dashboard(
            folder,
            run_dashboard,
            dashboard,
        )
        opened = eval_dashboard_html.open_dashboard(browser_dashboard)
        print(
            f"Eval dashboard UI: {browser_dashboard.as_uri()}"
            + (" (opened in your browser)." if opened else ".")
        )
        return completed.returncode
    persist_run_dashboard(
        folder,
        run_dashboard,
        outcome="AWAITING_HUMAN_SELECTION",
    )
    persist_browser_dashboard(
        folder,
        run_dashboard,
        v1_completion._read_jsonl(ledger_path)[ledger_start:],
    )
    print("No thesis was selected and no post was generated or published.")
    return 0


def parser() -> argparse.ArgumentParser:
    result = base.parser()
    result.add_argument(
        "--resume-from",
        type=Path,
        help=(
            "Resume a run that stopped at evidence verification without repeating "
            "conversation discovery or topic admission."
        ),
    )
    result.add_argument(
        "--week-slot",
        type=int,
        choices=(2, 3),
        help="Bind the generated authority post to weekly slot 2 or 3; Thursday is slot 3.",
    )
    result.add_argument(
        "--generate-post",
        action="store_true",
        help=(
            "Select the highest-scoring qualifying thesis and continue through the "
            "high-bar drafting workflow."
        ),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        return command(parser().parse_args(argv))
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
