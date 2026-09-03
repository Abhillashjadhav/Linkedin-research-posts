"""Explicit, redacted export from the private V1 decision ledger.

This module never sends network traffic. It writes one owner-only normalized
monitoring artifact whose fields are limited to opaque IDs, status/value facts,
version labels, and digests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

from . import v1_completion, workflow

CONTRACTS = {
    "research_trust": "research-trust",
    "claim_body_support": "claim-body-support",
    "atomic_value_novelty": "atomic-value-novelty",
    "critic_anchor_integrity": "critic-anchor-integrity",
    "critic_reproducibility": "critic-reproducibility",
    "solution_plausibility": "solution-plausibility",
    "reader_attention": "reader-attention",
}
CASE_TYPE = "linkedin-run"
CONTEXT_FIELDS = {
    "run_id",
    "comparison_run_id",
    "observed_at",
    "product_version",
    "use_case_version",
    "deployment_id",
    "model_provider",
    "model_name",
    "model_snapshot",
    "prompt_version",
    "config_version",
    "toolset_version",
    "evaluator_version",
    "rubric_version",
    "golden_dataset_version",
    "production_cohort",
    "since",
    "through",
}


def _digest(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _file_digest(path: Path) -> str:
    try:
        return _digest(path.read_bytes())
    except FileNotFoundError:
        return _digest(b"")


def _ledger_digest(path: Path) -> str:
    rows = v1_completion._read_jsonl(path)
    return _digest(json.dumps(rows, sort_keys=True, separators=(",", ":")).encode())


def _timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise workflow.WorkflowError(f"Monitoring context {field} must be text.")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise workflow.WorkflowError(
            f"Monitoring context {field} must be an ISO timestamp."
        ) from exc
    if parsed.tzinfo is None:
        raise workflow.WorkflowError(f"Monitoring context {field} must include a timezone.")
    return parsed.astimezone(timezone.utc)


def load_context(path: Path) -> dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError("Monitoring context is unavailable or invalid.") from exc
    if not isinstance(payload, dict) or set(payload) != CONTEXT_FIELDS:
        raise workflow.WorkflowError("Monitoring context has an invalid schema.")
    if not all(isinstance(value, str) and value.strip() for value in payload.values()):
        raise workflow.WorkflowError("Monitoring context values must be non-empty text.")
    for key, value in payload.items():
        if key in {"observed_at", "since", "through"}:
            continue
        if len(value) > 160 or not re.fullmatch(r"[A-Za-z0-9._:@+-]+", value):
            raise workflow.WorkflowError(
                f"Monitoring context {key} must be a bounded public-safe label."
            )
    _timestamp(payload["observed_at"], field="observed_at")
    since = _timestamp(payload["since"], field="since")
    through = _timestamp(payload["through"], field="through")
    if through < since:
        raise workflow.WorkflowError("Monitoring context through must not precede since.")
    return {str(key): str(value) for key, value in payload.items()}


def _reason_code(value: object) -> str:
    code = re.sub(r"[^A-Z0-9]+", "_", str(value).upper()).strip("_")
    return code[:120] or "NO_REASON_RECORDED"


def build_normalized_export(
    context: Mapping[str, str], rows: list[dict[str, object]]
) -> dict[str, object]:
    since = _timestamp(context["since"], field="since")
    through = _timestamp(context["through"], field="through")
    selected: list[dict[str, object]] = []
    legacy_rows = 0
    for row in rows:
        recorded_at = _timestamp(row.get("recorded_at"), field="ledger recorded_at")
        if not since <= recorded_at <= through:
            continue
        if "run_id" not in row:
            legacy_rows += 1
            continue
        if row.get("run_id") == context["run_id"]:
            selected.append(row)
    if not selected:
        suffix = " Legacy rows in the window have no run ID." if legacy_rows else ""
        raise workflow.WorkflowError(
            f"No V1 decisions match run ID {context['run_id']!r} in the export window.{suffix}"
        )

    latest: dict[str, dict[str, object]] = {}
    for row in selected:
        contract = str(row.get("contract", ""))
        if contract in CONTRACTS:
            latest[contract] = row
    if not latest:
        raise workflow.WorkflowError("The selected run contains no supported V1 contracts.")

    checks: list[dict[str, object]] = []
    for contract, definition_id in CONTRACTS.items():
        row = latest.get(contract)
        if row is None:
            checks.append(
                {
                    "definition_id": definition_id,
                    "status": "NOT_EVALUATED",
                    "current_value": None,
                    "expected_value": 1.0,
                    "reason_code": "STAGE_NOT_REACHED",
                    "evidence_refs": [],
                }
            )
            continue
        status = str(row.get("status", "BLOCKED"))
        if status not in {"PASS", "FAIL", "BLOCKED", "NOT_EVALUATED"}:
            status = "BLOCKED"
        canonical = json.dumps(row, sort_keys=True, separators=(",", ":")).encode()
        checks.append(
            {
                "definition_id": definition_id,
                "status": status,
                "current_value": 1.0 if status == "PASS" else 0.0 if status == "FAIL" else None,
                "expected_value": 1.0,
                "reason_code": _reason_code(row.get("reason")),
                "evidence_refs": [
                    {
                        "uri": f"urn:linkedin-os:decision:{_digest(canonical)[7:]}",
                        "sha256": _digest(canonical),
                    }
                ],
            }
        )
    identity = {
        "run_id": context["run_id"],
        "product_version": context["product_version"],
        "use_case_version": context["use_case_version"],
    }
    fingerprint = _digest(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    )
    cases = [
        {
            "case_type": CASE_TYPE,
            "case": {
                "case_id": f"linkedin-{fingerprint[7:31]}",
                "display_name": "LinkedIn V1 end-to-end run",
                "use_case_id": "linkedin-authority-post",
                "segment": CASE_TYPE,
                "input_fingerprint": fingerprint,
            },
            "checks": checks,
        }
    ]

    selected_bytes = json.dumps(selected, sort_keys=True, separators=(",", ":")).encode()
    return {
        "format_version": "normalized-eval-run/0.1",
        "run_id": context["run_id"],
        "observed_at": _timestamp(context["observed_at"], field="observed_at").isoformat(),
        "product_version": context["product_version"],
        "comparison": {"run_id": context["comparison_run_id"], "label": "Last approved good run", "sha256": None},
        "change_manifest": {
            "use_case_version": context["use_case_version"],
            "deployment_id": context["deployment_id"],
            "model": {"provider": context["model_provider"], "name": context["model_name"], "snapshot": context["model_snapshot"]},
            "prompt_version": context["prompt_version"],
            "config_version": context["config_version"],
            "toolset_version": context["toolset_version"],
            "evaluator_version": context["evaluator_version"],
            "rubric_version": context["rubric_version"],
            "golden_dataset_version": context["golden_dataset_version"],
            "production_cohort": context["production_cohort"],
        },
        "provenance": {
            "contract_digest": _file_digest(workflow.REPO_ROOT / "config/eval-v1.json"),
            "config_digest": _file_digest(workflow.REPO_ROOT / "config/eval-v1-calibration.json"),
            "production_data_digest": _digest(selected_bytes),
            "golden_dataset_digest": _ledger_digest(v1_completion.STATE_ROOT / v1_completion.PUBLISHED_ATOMIC_LEDGER_NAME),
            "prompt_digest": _file_digest(workflow.REPO_ROOT / "config/critic-rubric-v1.json"),
            "toolset_digest": _file_digest(workflow.REPO_ROOT / "bin/linkedin-os"),
        },
        "cases": cases,
    }


def _write_private(path: Path, payload: Mapping[str, object]) -> None:
    root = v1_completion.STATE_ROOT.resolve()
    target = path.resolve()
    if target.parent != root:
        raise workflow.WorkflowError("Monitoring export must stay in the private V1 state root.")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = -1
    try:
        descriptor = os.open(target, flags, 0o600)
        data = (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
        written = 0
        while written < len(data):
            count = os.write(descriptor, data[written:])
            if count == 0:
                raise workflow.WorkflowError("Monitoring export write did not make progress.")
            written += count
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o600)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise workflow.WorkflowError("Monitoring export is not a regular file.")
    except FileExistsError as exc:
        raise workflow.WorkflowError("Monitoring export already exists; choose a new run ID.") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="linkedin-os export-monitoring")
    parser.add_argument("--context", type=Path, required=True)
    parser.add_argument("--allow-monitoring-export", action="store_true")
    args = parser.parse_args(argv)
    if not args.allow_monitoring_export:
        raise workflow.WorkflowError("Monitoring export requires explicit consent.")
    context = load_context(args.context)
    rows = v1_completion._read_jsonl(
        v1_completion.STATE_ROOT / v1_completion.DECISION_LEDGER_NAME
    )
    payload = build_normalized_export(context, rows)
    output = v1_completion.STATE_ROOT / f"monitoring-{context['run_id']}.normalized.json"
    _write_private(output, payload)
    print(f"Redacted monitoring export: {output.relative_to(workflow.REPO_ROOT)}")
    print("Network transmission: DISABLED. No private content or local path was exported.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
