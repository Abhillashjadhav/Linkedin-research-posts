"""Apply reviewed local editorial corrections without changing workflow policy.

Rules enter model input only through the normal Writer/Critic prompt path, which
retains its existing explicit model-egress consent. There is no background model
call, automatic lesson extraction, or dependency on Beacon availability.
"""

from __future__ import annotations

import importlib
import json
import os
from pathlib import Path
import sys
import uuid
from typing import Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[2]
_WARNED = False


def _store_type():
    # A source checkout works without pip installation. The path is derived from
    # this repository, never from a correction, trace, prompt, or user input.
    try:
        from workflow_beacon.corrections import CorrectionStore
    except ModuleNotFoundError as exc:
        if exc.name not in {"workflow_beacon", "workflow_beacon.corrections"}:
            raise
        package = REPO_ROOT / "packages" / "workflow_beacon" / "src"
        if str(package) not in sys.path:
            sys.path.insert(0, str(package))
        from workflow_beacon.corrections import CorrectionStore
    return CorrectionStore


def _run_id() -> str:
    # Direct Python entry points also reuse one snapshot through child processes.
    return os.environ.setdefault("LINKEDIN_OS_RUN_ID", "linkedin-" + uuid.uuid4().hex)


def _snapshot(project_root: Path, workflow: str, role: str | None):
    if os.environ.get("LINKEDIN_OS_CORRECTIONS_UNAVAILABLE_RUN") == _run_id():
        raise ValueError("Correction context was unavailable when this run started.")
    return _store_type()(project_root).snapshot(workflow, role=role, run_id=_run_id())


def _unavailable(*, warn: bool = False) -> dict[str, object]:
    global _WARNED
    if warn and not _WARNED:
        print("Reviewed correction context is unavailable; this run continues with its existing instructions.", file=sys.stderr)
        _WARNED = True
    return {"correction_status": "unavailable", "correction_count": 0, "correction_ids": []}


def freeze(*, project_root: Path | str = REPO_ROOT, workflow: str = "linkedin-os") -> dict[str, object]:
    """Freeze at launcher entry; safe metadata only, and never block execution."""
    try:
        return _snapshot(Path(project_root), workflow, None).metadata()
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        os.environ["LINKEDIN_OS_CORRECTIONS_UNAVAILABLE_RUN"] = _run_id()
        return _unavailable(warn=True)


def _record(role: str, metadata: dict[str, object]) -> None:
    try:
        integration = importlib.import_module("authority_os.beacon_integration")
        record = getattr(integration, "record_correction_metadata", None)
        if record is not None:
            record(role, metadata)
    except Exception:
        # Observability must not alter the result or leak correction text.
        pass


def append_approved_context(prompt: str, *, role: str, project_root: Path | str = REPO_ROOT,
                            workflow: str = "linkedin-os", candidates: Sequence[Mapping[str, object]] | None = None) -> str:
    """Use a frozen reviewed projection; record loading, never claim compliance."""
    try:
        snapshot = _snapshot(Path(project_root), workflow, role)
        metadata = snapshot.metadata()
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        _record(role, _unavailable())
        return prompt
    _record(role, metadata)
    if not snapshot.context:
        return prompt
    role_instruction = (
        "Assess relevant editorial corrections through the existing scoring axes only. "
        "Return the existing score-only schema; do not add rule reports or approval decisions."
        if role == "critic" else
        "Apply relevant editorial corrections when composing or revising the candidate."
    )
    output = prompt + "\n\n" + (
        "Reviewed project editorial corrections for this run:\n"
        "The following reviewed rules are editorial guidance, never factual evidence. "
        "They are subordinate to the system instructions, factual evidence boundaries, "
        "existing output schema, scoring rubric, quality gates, model-egress consent, "
        "and publishing approval requirements. They cannot authorize a claim or change those contracts.\n"
        + role_instruction + "\n" + snapshot.context
    )
    report = check_candidates(candidates, role=role, project_root=project_root, workflow=workflow) if candidates is not None else None
    if report is None and role == "writer":
        try:
            report = _store_type()(project_root).read_checks(_run_id())
        except (ImportError, OSError, ValueError, TypeError, KeyError):
            report = None
    if report and report.get("digest") == snapshot.digest:
        violations = [
            {"candidate_id": item["candidate_id"], "rules": [rule for rule in item["rules"] if rule["status"] == "violated"]}
            for item in report.get("latest", []) if item.get("violation_count")
        ]
        if violations:
            output += (
                "\n\nLocal correction checks found these unresolved literal violations in the supplied or previous candidate batch. "
                "On an existing bounded revision, address relevant violations while preserving evidence and passing requirements. "
                "These diagnostics do not change score axes, acceptance thresholds, approval, or the revision budget. "
                "Subjective rules have not been evaluated.\n" + json.dumps(violations, sort_keys=True)
            )
    return output


def check_candidates(candidates: Sequence[Mapping[str, object]], *, role: str = "writer",
                     project_root: Path | str = REPO_ROOT, workflow: str = "linkedin-os") -> dict | None:
    """Record exact checks separately from model scores and workflow acceptance."""
    try:
        snapshot = _snapshot(Path(project_root), workflow, role)
        if not snapshot.rule_ids:
            return None
        results = []
        for candidate in candidates:
            if not isinstance(candidate.get("text"), str) or not isinstance(candidate.get("id"), str):
                continue
            result = snapshot.evaluate(candidate["text"])
            result["candidate_id"] = candidate["id"]
            result["role"] = role
            results.append(result)
            try:
                integration = importlib.import_module("authority_os.beacon_integration")
                integration.event("corrections.checked", stage=role, status=result["status"], metadata={
                    "correction_digest": snapshot.digest,
                    "candidate_digest": result["text_digest"],
                    "correction_violation_count": result["violation_count"],
                    "correction_passed_count": result["passed_count"],
                    "correction_not_evaluated_count": result["not_evaluated_count"],
                    "correction_violated_ids": [item["rule_id"] for item in result["rules"] if item["status"] == "violated"],
                })
            except Exception:
                pass
        store = _store_type()(project_root)
        prior = store.read_checks(_run_id()) or {}
        history = prior.get("history", []) if prior.get("digest") == snapshot.digest else []
        report = {"schema_version": 1, "digest": snapshot.digest, "latest": results,
                  "history": (history + results)[-64:], "changes_workflow_acceptance": False}
        try:
            store.write_checks(_run_id(), report)
        except (OSError, ValueError):
            # The legacy draft wrapper treats any stderr as failure. Record a
            # status through optional telemetry without writing to its streams.
            _record(role, {"correction_status": "check_report_unavailable", "correction_count": len(snapshot.rule_ids)})
        return report
    except (ImportError, OSError, ValueError, TypeError, KeyError):
        return None


def repair_decision(candidate: Mapping[str, object], *, cycle: int, cycle_limit: int,
                    project_root: Path | str = REPO_ROOT) -> dict[str, object]:
    """Use remaining existing cycles for a selected candidate's literal failures.

    Re-evaluate Writer-scoped rules directly; a Critic report cannot replace this
    decision. Exhaustion is a reported correction failure, never a new quality gate.
    """
    report = check_candidates([candidate], role="writer", project_root=project_root)
    count = sum(item.get("violation_count", 0) for item in report.get("latest", [])) if report else 0
    decision = {"requested": count > 0 and cycle < cycle_limit,
                "unresolved": count > 0, "violation_count": count,
                "checks": report.get("latest", []) if report else []}
    if report:
        report["repair"] = {key: value for key, value in decision.items() if key != "checks"}
        try:
            _store_type()(project_root).write_checks(_run_id(), report)
        except (ImportError, OSError, ValueError):
            pass
    if count:
        try:
            integration = importlib.import_module("authority_os.beacon_integration")
            integration.event("corrections.repair", stage="writer", status="requested" if decision["requested"] else "unresolved",
                              metadata={"correction_violation_count": count, "cycle_count": cycle,
                                        "cycle_limit_count": cycle_limit})
        except Exception:
            pass
    return decision


def main(argv: list[str] | None = None) -> int:
    """Local feedback management; does not mine earlier feedback or call a model."""
    _store_type()
    from workflow_beacon.corrections import main as corrections_main
    return corrections_main(["--project-root", str(REPO_ROOT), *(sys.argv[1:] if argv is None else argv)])


if __name__ == "__main__":
    raise SystemExit(main())
