"""Persist the best safe draft when a later V1 quality check stops the run."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

from . import acceptance_policy, anti_slop, daily_cli, v1_completion, workflow


OUTPUT_ENV = "LINKEDIN_OS_BEST_EFFORT_OUTPUT"
BLOCKING_GATES = ("honesty", "citation", "proof", "privacy", "relevance")


def output_path() -> Path:
    configured = os.environ.get(OUTPUT_ENV)
    if configured:
        return daily_cli._under_private(Path(configured))
    return daily_cli._under_private(
        workflow.DEFAULT_PRIVATE_DATA
        / "draft-runs"
        / v1_completion.current_run_id()
        / "best-effort-post.md"
    )


def blocking_failures(candidate: object) -> list[str]:
    """Return every hard gate that prevents a best-effort handoff."""

    gates = getattr(candidate, "gates", {})
    if not isinstance(gates, Mapping):
        return [name for name in BLOCKING_GATES if name != "privacy"]
    if acceptance_policy.hard_candidate_gates_pass(
        gates,
        passes_required_gates=bool(
            getattr(candidate, "passes_required_gates", False)
        ),
        reason_codes=getattr(candidate, "gate_reasons", ()),
        allow_factual_wording_advisory=True,
    ):
        return []
    failures = [
        name
        for name in BLOCKING_GATES
        if name != "privacy" and str(gates.get(name, "NOT_EVALUATED")) not in {"PASS", "NOT_REQUIRED"}
    ]
    if getattr(candidate, "passes_required_gates", False) is not True:
        for name, status in gates.items():
            if str(status) == "FAIL" and str(name) not in failures:
                failures.append(str(name))
    return failures


def _run_decisions(artifact_sha256: str) -> list[dict[str, object]]:
    path = v1_completion.STATE_ROOT / v1_completion.DECISION_LEDGER_NAME
    try:
        rows = v1_completion._read_jsonl(path)
        run_id = v1_completion.current_run_id()
    except workflow.WorkflowError:
        return []
    return [
        dict(row)
        for row in rows
        if row.get("run_id") == run_id
        and row.get("artifact_sha256") in {"", artifact_sha256}
    ]


def _shortfalls(
    candidate: object,
    attempt: object,
    decisions: Sequence[Mapping[str, object]],
    failure_reason: str,
) -> list[str]:
    shortfalls: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(bar: str, detail: str) -> None:
        if bar not in seen:
            shortfalls.append((bar, detail))
            seen.add(bar)

    total = int(getattr(candidate, "effective_total", 0))
    if total < acceptance_policy.ACCEPTABLE_QUALITY_FLOOR:
        add(
            "critic_total",
            f"observed {total}/25; required at least "
            f"{acceptance_policy.ACCEPTABLE_QUALITY_FLOOR}/25; shortfall "
            f"{acceptance_policy.ACCEPTABLE_QUALITY_FLOOR - total}",
        )

    axes = getattr(candidate, "axes", {})
    if isinstance(axes, Mapping):
        for axis, detail in acceptance_policy.axis_shortfalls(axes).items():
            add(
                axis,
                f"observed {detail['observed']}/5; required at least "
                f"{detail['required']}/5; shortfall {detail['shortfall']}",
            )

    findings = anti_slop.audit(str(getattr(candidate, "text", "")))
    if findings:
        codes = ", ".join(sorted({finding.code for finding in findings}))
        add("anti_slop", f"{len(findings)} finding(s); required 0 ({codes})")

    review_status = getattr(attempt, "review_status", None)
    if review_status not in {None, "READY_FOR_HUMAN_REVIEW"}:
        add("package_review_status", f"observed {review_status}; required READY_FOR_HUMAN_REVIEW")
    recommendation = getattr(attempt, "recommendation", None)
    candidate_id = str(getattr(candidate, "candidate_id", ""))
    if recommendation not in {None, candidate_id}:
        add("package_recommendation", f"observed {recommendation}; required {candidate_id}")

    for row in decisions:
        if str(row.get("status")) not in {"FAIL", "BLOCKED"}:
            continue
        contract = str(row.get("contract", "unnamed_check"))
        reason = str(row.get("reason", "no shortfall reason recorded"))
        add(contract, reason)

    if not shortfalls:
        add("workflow_completion", failure_reason)
    return [f"- `{bar}` — {detail}" for bar, detail in shortfalls]


def render(
    candidate: object,
    attempt: object,
    *,
    cycle: int,
    failure_reason: str,
) -> str:
    failures = blocking_failures(candidate)
    if failures:
        raise workflow.WorkflowError(
            "Best-effort output is blocked by hard gate(s): " + ", ".join(failures)
        )

    text = str(getattr(candidate, "text", "")).strip()
    if not text:
        raise workflow.WorkflowError("Best-effort output has no candidate text.")
    artifact = v1_completion._sha256_text(text)  # type: ignore[attr-defined]
    decisions = _run_decisions(artifact)
    gates = getattr(candidate, "gates", {})
    passed = [
        f"- `{name}` — {status}"
        for name, status in gates.items()
        if str(status) in {"PASS", "NOT_REQUIRED"}
    ] if isinstance(gates, Mapping) else []
    passed.append("- `privacy` — PASS; private path enforced and file mode is 0o600")
    total = int(getattr(candidate, "effective_total", 0))
    if total >= acceptance_policy.ACCEPTABLE_QUALITY_FLOOR:
        passed.append(
            f"- `critic_total` — PASS; {total}/25 meets the "
            f"{acceptance_policy.ACCEPTABLE_QUALITY_FLOOR}/25 floor"
        )
    axes = getattr(candidate, "axes", {})
    if isinstance(axes, Mapping):
        for axis, required in acceptance_policy.AXIS_FLOORS.items():
            value = int(axes.get(axis, 0))
            if value >= required:
                passed.append(
                    f"- `{axis}` — PASS; {value}/5 meets the {required}/5 floor"
                )
    if not anti_slop.audit(text):
        passed.append("- `anti_slop` — PASS; 0 findings")
    review_status = getattr(attempt, "review_status", None)
    if review_status == "READY_FOR_HUMAN_REVIEW":
        passed.append("- `package_review_status` — PASS; READY_FOR_HUMAN_REVIEW")
    recommendation = getattr(attempt, "recommendation", None)
    if recommendation == str(getattr(candidate, "candidate_id", "")):
        passed.append(f"- `package_recommendation` — PASS; {recommendation}")
    passed_contracts = {
        str(row.get("contract")): str(row.get("reason", "passed"))
        for row in decisions
        if str(row.get("status")) == "PASS"
    }
    passed.extend(
        f"- `{contract}` — PASS; {reason}"
        for contract, reason in sorted(passed_contracts.items())
    )
    shortfalls = _shortfalls(candidate, attempt, decisions, failure_reason)
    candidate_id = str(getattr(candidate, "candidate_id", "unknown"))
    score = total

    return (
        "# BEST_EFFORT — NOT READY_FOR_HUMAN_REVIEW\n\n"
        "> This is the safest retained candidate from a failed run. Publishing remains disabled.\n\n"
        f"Candidate: `{candidate_id}`  \n"
        f"Cycle: `{cycle}`  \n"
        f"Critic score: `{score}/25`  \n"
        f"Run failure: {failure_reason}\n\n"
        "## Candidate text\n\n"
        f"{text}\n\n"
        "## Passed gates and checks\n\n"
        + "\n".join(passed)
        + "\n\n## Missed bars\n\n"
        + "\n".join(shortfalls)
        + "\n"
    )


def write(
    candidate: object,
    attempt: object,
    *,
    cycle: int,
    failure_reason: str,
) -> Path:
    payload = render(
        candidate,
        attempt,
        cycle=cycle,
        failure_reason=failure_reason,
    )
    candidate_id = str(getattr(candidate, "candidate_id", "unknown"))
    artifact = v1_completion._sha256_text(  # type: ignore[attr-defined]
        str(getattr(candidate, "text", ""))
    )

    def record_privacy(status: str, reason: str) -> None:
        try:
            v1_completion.record_decision(
                {
                    "contract": "gate_privacy",
                    "mode": "enforce",
                    "status": status,
                    "reason": reason,
                },
                stage="best-effort-handoff",
                subject_id=candidate_id,
                artifact_sha256=artifact,
            )
        except workflow.WorkflowError:
            # Observability must not replace the original storage result.
            pass

    try:
        target = output_path()
        written = daily_cli.write_private_text(target, payload)
    except (OSError, workflow.WorkflowError):
        record_privacy("FAIL", "private-path-or-owner-only-write-failed")
        raise
    record_privacy("PASS", "private-path-and-mode-0o600-enforced")
    return written
