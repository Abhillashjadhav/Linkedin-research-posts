"""Read a completed native dashboard; never rerun, repair, or transmit a product."""

from __future__ import annotations

import json
import math
import os
import stat
from collections.abc import Mapping
from pathlib import Path

from . import workflow
from .monitoring_export import _digest, build_normalized_export, source_fact

MAX_DASHBOARD_BYTES = 5 * 1024 * 1024


def _read_dashboard(folder: Path, name: str) -> dict[str, object]:
    root = workflow.DEFAULT_PRIVATE_DATA.absolute()
    target = folder.absolute() / name
    try:
        relative = target.relative_to(root)
    except ValueError:
        raise workflow.WorkflowError("Select a dashboard under data/private.") from None
    if ".." in relative.parts:
        raise workflow.WorkflowError("Dashboard traversal is not allowed.")
    # Descriptor-relative traversal prevents symlink replacement races.
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    descriptor = os.open(root, flags | os.O_DIRECTORY)
    try:
        for part in relative.parts[:-1]:
            child = os.open(part, flags | os.O_DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        leaf = os.open(relative.name, flags, dir_fd=descriptor)
        try:
            meta = os.fstat(leaf)
            if not stat.S_ISREG(meta.st_mode) or meta.st_size > MAX_DASHBOARD_BYTES:
                raise workflow.WorkflowError(
                    "Dashboard must be a bounded regular file."
                )
            if meta.st_uid != os.getuid() or stat.S_IMODE(meta.st_mode) & 0o077:
                raise workflow.WorkflowError("Dashboard must be owner-only.")
            with os.fdopen(leaf, "rb", closefd=False) as handle:
                payload = json.loads(handle.read(MAX_DASHBOARD_BYTES + 1))
        finally:
            os.close(leaf)
    finally:
        os.close(descriptor)
    if not isinstance(payload, dict):
        raise workflow.WorkflowError("Dashboard must be a JSON object.")
    return payload


def export_completed_dashboard(
    context: Mapping[str, str], folder: Path
) -> dict[str, object]:
    run = _read_dashboard(folder, "run-dashboard.json")
    evaluation = _read_dashboard(folder, "eval-dashboard.json")
    if run.get("outcome") not in {"PASS", "FAIL", "BLOCKED", "COMPLETED_WITH_WARNINGS"}:
        raise workflow.WorkflowError(
            "This run is not complete; leave the active run untouched."
        )
    if run.get("run_id") != context["run_id"] or evaluation.get("run_id") != run.get(
        "run_id"
    ):
        raise workflow.WorkflowError(
            "Context and both dashboards must identify the same run."
        )
    saved_contract = evaluation.get("acceptance_contract")
    saved_contract = saved_contract if isinstance(saved_contract, dict) else {}
    axis_floors = saved_contract.get("axis_floors")
    axis_floors = axis_floors if isinstance(axis_floors, dict) else {}
    rows: list[dict[str, object]] = []
    for check in evaluation.get("checks", []):
        if not isinstance(check, dict):
            raise workflow.WorkflowError("Invalid dashboard check.")
        if check.get("contract") == "candidate_acceptance" and not check.get(
            "subject_id"
        ):
            continue
        rows.append(
            dict(check, run_id=context["run_id"], recorded_at=context["observed_at"])
        )
    for score in evaluation.get("critic_scorecards", []):
        if not isinstance(score, dict):
            raise workflow.WorkflowError("Invalid scorecard.")
        # Selection/acceptance describes the whole attempt, not each score.
        # Preserve it separately so a rejected revision cannot relabel good axes.
        rows.append(
            {
                "run_id": context["run_id"],
                "recorded_at": context["observed_at"],
                "contract": "critic_candidate_status",
                "status": score.get("status", "NOT_EVALUATED"),
                "subject_id": score.get("candidate_id", "unknown"),
                "mode": "diagnostic",
                "evidence": {
                    "cycle": score.get("cycle", 0),
                    "reason_codes": list(score.get("failure_codes") or [])
                    + list(score.get("advisory_codes") or []),
                },
            }
        )
        values = {"critic_total": score.get("total"), **dict(score.get("axes") or {})}
        for name, value in values.items():
            threshold = (
                score.get("threshold", saved_contract.get("minimum_total"))
                if name == "critic_total"
                else axis_floors.get(name)
            )
            measured = (
                type(value) in {int, float}
                and math.isfinite(value)
                and type(threshold) in {int, float}
                and math.isfinite(threshold)
            )
            status = (
                "NOT_EVALUATED"
                if not measured
                else "PASS"
                if value >= threshold
                else "FAIL"
            )
            rows.append(
                {
                    "run_id": context["run_id"],
                    "recorded_at": context["observed_at"],
                    "contract": name,
                    "status": status,
                    "subject_id": score.get("candidate_id", "unknown"),
                    "mode": "diagnostic",
                    "evidence": {
                        "score": value,
                        "cycle": score.get("cycle", 0),
                        "threshold": threshold,
                    },
                }
            )
    # Candidate-specific gate outcomes are carried independently, never promoted
    # to a run-level seven-stage check or used to change native acceptance.
    for result in evaluation.get("results", []):
        if not isinstance(result, dict):
            continue
        acceptance = result.get("acceptance")
        if isinstance(acceptance, dict):
            rows.append(
                {
                    "run_id": context["run_id"],
                    "recorded_at": context["observed_at"],
                    "contract": "candidate_acceptance",
                    "status": acceptance.get("status", "NOT_EVALUATED"),
                    "subject_id": result.get("candidate_id", "unknown"),
                    "mode": "diagnostic",
                    "evidence": {
                        "observed_status": acceptance.get("status", "NOT_EVALUATED"),
                        "reason_codes": list(acceptance.get("reasons") or [])
                        + list(acceptance.get("advisory_warnings") or []),
                    },
                }
            )
        gate_envelope = result.get("gates")
        gates = gate_envelope.get("gates") if isinstance(gate_envelope, dict) else None
        if not isinstance(gates, dict):
            continue
        for name, gate in gates.items():
            if isinstance(gate, dict) and "status" in gate:
                rows.append(
                    {
                        "run_id": context["run_id"],
                        "recorded_at": context["observed_at"],
                        "contract": "gate_" + name,
                        "status": gate["status"],
                        "subject_id": result.get("candidate_id", "unknown"),
                        "mode": "diagnostic",
                        "evidence": {
                            "observed_status": gate["status"],
                            "reason_codes": gate.get("reason_codes", []),
                        },
                    }
                )
    rows.append(
        {
            "run_id": context["run_id"],
            "recorded_at": context["observed_at"],
            "contract": "draft_delivery",
            "status": "PASS"
            if run["outcome"] in {"PASS", "COMPLETED_WITH_WARNINGS"}
            else run["outcome"],
            "mode": "diagnostic",
            "evidence": {"observed_status": run["outcome"]},
        }
    )
    exported = build_normalized_export(context, rows)
    snapshot = _digest(
        json.dumps([run, evaluation], sort_keys=True, separators=(",", ":")).encode()
    )
    exported["source_facts"].append(
        {
            "contract": "dashboard_snapshot",
            "subject_id": "completed-run",
            "cycle": 0,
            "recorded_status": "PASS",
            "observed_status": "PASS",
            "mode": "diagnostic",
            "value": None,
            "reason_codes": [],
            "evidence_refs": [
                {"uri": "urn:linkedin-os:dashboard:" + snapshot[7:], "sha256": snapshot}
            ],
        }
    )
    native_version = _digest(
        json.dumps(
            [
                evaluation.get("rubric"),
                evaluation.get("acceptance_contract"),
                context["rubric_version"],
                context["evaluator_version"],
            ],
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )
    final_results = evaluation.get("results", [])
    for result in final_results if isinstance(final_results, list) else []:
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("scorecard"), dict)
            or not isinstance(result.get("acceptance"), dict)
        ):
            continue
        score = result["scorecard"]
        acceptance = result["acceptance"]
        subject = str(result.get("candidate_id", "unknown"))
        candidate_case = dict(exported["cases"][0]["case"])
        candidate_case["case_id"] = (
            "candidate-"
            + _digest((str(candidate_case["case_id"]) + ":" + subject).encode())[7:31]
        )
        candidate_case["display_name"] = "LinkedIn evaluated candidate"
        candidate_case["segment"] = "linkedin-candidate"
        checks = []
        acceptance_status = acceptance.get("status")
        measured = [
            (
                "candidate-acceptance",
                1
                if acceptance_status == "PASS"
                else 0
                if acceptance_status == "FAIL"
                else None,
                1,
            ),
            (
                "critic-total",
                score.get("effective_total"),
                saved_contract.get("minimum_total"),
            ),
        ]
        for axis in workflow.CRITIC_AXES:
            measured.append(
                (
                    axis.replace("_", "-"),
                    score.get(axis),
                    axis_floors.get(axis),
                )
            )
        for name, value, threshold in measured:
            numeric = type(value) in {int, float} and math.isfinite(value)
            threshold_known = type(threshold) in {int, float} and math.isfinite(
                threshold
            )
            threshold = threshold if threshold_known else None
            status = (
                "NOT_EVALUATED"
                if not numeric or not threshold_known
                else "FAIL"
                if threshold is not None and value < threshold
                else "PASS"
            )
            digest = _digest(
                json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
            )
            checks.append(
                {
                    "definition_id": name,
                    "suite_version": native_version,
                    "status": status,
                    "current_value": value if numeric else None,
                    "expected_value": threshold,
                    "recorded_threshold": {"value": threshold},
                    "reason_code": "NATIVE_CANDIDATE_CHECK"
                    if threshold_known
                    else "NATIVE_SAVED_THRESHOLD_UNAVAILABLE",
                    "evidence_refs": [
                        {
                            "uri": "urn:linkedin-os:candidate:" + digest[7:],
                            "sha256": digest,
                        }
                    ],
                }
            )
        exported["cases"].append(
            {
                "case_type": "linkedin-candidate",
                "case": candidate_case,
                "checks": checks,
            }
        )
    # Preserve individual recorded execution decisions as evidence. Their presence
    # does not certify all possible tool failure modes.
    decisions = run.get("decisions", [])
    for decision in decisions if isinstance(decisions, list) else []:
        if isinstance(decision, dict):
            exported["source_facts"].append(
                source_fact(
                    {
                        "contract": "execution_"
                        + str(decision.get("stage", "unknown")),
                        "status": decision.get("status", "NOT_EVALUATED"),
                        "subject_id": decision.get("subject_id", "run"),
                        "mode": "enforce",
                        "evidence": {"cycle": decision.get("sequence", 0)},
                    }
                )
            )
    return exported
