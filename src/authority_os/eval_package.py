"""Re-evaluate a frozen approval package without drafting or revision."""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

from . import acceptance_policy, anti_slop, package as approval_package
from . import performance, storage, workflow


_BRIEF_PATTERN = re.compile(
    r"\A# Strategy brief\n\n"
    r"- Package ID: `(?P<package_id>[^`\n]+)`\n"
    r"- Topic: `(?P<topic_slug>[^`\n]+)`\n"
    r"- Strategic goal: `(?P<goal>[^`\n]+)`\n"
    r"- Output format: `(?P<output_format>[^`\n]+)`\n"
    r"- Weekly slot: `(?P<weekly_slot>[^`\n]+)`\n"
    r"- Narrative route: `(?P<narrative_route>[^`\n]+)`\n"
    r"- Strategy provenance: `(?P<strategy_origin>[^`\n]+)`\n"
    r"- Evidence limitations: `(?P<limitations>[^`\n]+)`\n\n"
    r"## Goal purpose\n\n(?P<goal_purpose>(?:    [^\n]*\n)+)\n"
    r"## Target reader\n\n(?P<target_reader>(?:    [^\n]*\n)+)\n"
    r"## Reader problem\n\n(?P<reader_problem>(?:    [^\n]*\n)+)\n"
    r"## Core hypothesis\n\n(?P<core_hypothesis>(?:    [^\n]*\n)+)\n"
    r"## Product decision\n\n(?P<product_decision>(?:    [^\n]*\n)+)\n"
    r"## Authority statement\n\n(?P<authority_statement>(?:    [^\n]*\n)+)\n"
    r"## Why now\n\n(?P<why_now>(?:    [^\n]*\n)+)\n"
    r"## Dominant take\n\n(?P<dominant_take>(?:    [^\n]*\n)+)\n"
    r"## Missing angle\n\n(?P<missing_angle>(?:    [^\n]*(?:\n|\Z))+?)\Z"
)

_CANDIDATE_SECTION = re.compile(
    r"\A## Candidate (?P<number>[1-3]): `(?P<id>[^`\n]+)`\n\n"
    r"Angle:\n\n(?P<angle>(?:    [^\n]*\n)+)\n"
    r"Claim IDs: `(?P<claim_ids>[^`\n]+)`\n\n"
    r"Text:\n\n(?P<text>(?:    [^\n]*(?:\n|\Z))+?)\Z"
)


def _literal_text(value: str, *, label: str) -> str:
    lines = value.splitlines()
    if not lines or any(not line.startswith("    ") for line in lines):
        raise workflow.WorkflowError(f"Frozen package {label} is malformed.")
    result = "\n".join(line[4:] for line in lines).strip()
    if not result:
        raise workflow.WorkflowError(f"Frozen package {label} must not be blank.")
    return result


def _parse_candidates(markdown: str) -> list[dict[str, object]]:
    prefix = "# Final candidate set\n\n"
    if not markdown.startswith(prefix):
        raise workflow.WorkflowError("Frozen package candidates.md header is invalid.")
    body = markdown[len(prefix) :].rstrip("\n")
    sections = re.split(r"\n\n(?=## Candidate [1-3]: `)", body)
    if len(sections) != 3:
        raise workflow.WorkflowError(
            "Frozen package candidates.md must contain exactly three candidate sections."
        )
    candidates: list[dict[str, object]] = []
    for expected, section in enumerate(sections, start=1):
        match = _CANDIDATE_SECTION.fullmatch(section)
        if match is None or int(match.group("number")) != expected:
            raise workflow.WorkflowError(
                "Frozen package candidates.md does not match the exact package format."
            )
        claim_ids = [value.strip() for value in match.group("claim_ids").split(",")]
        if any(not value for value in claim_ids):
            raise workflow.WorkflowError("Frozen package contains an invalid claim ID list.")
        candidates.append(
            {
                "id": match.group("id"),
                "angle": _literal_text(match.group("angle"), label="candidate angle"),
                "text": _literal_text(match.group("text"), label="candidate text"),
                "claim_ids": claim_ids,
            }
        )
    return candidates


def _parse_brief(
    markdown: str,
    *,
    manifest: Mapping[str, object],
    strategy_inputs: Mapping[str, str],
) -> dict[str, object]:
    match = _BRIEF_PATTERN.fullmatch(markdown)
    if match is None:
        raise workflow.WorkflowError(
            "Frozen package brief.md does not match the exact package format."
        )
    values = match.groupdict()
    expected_metadata = {
        "package_id": str(manifest["package_id"]),
        "topic_slug": str(manifest["topic_slug"]),
        "goal": str(manifest["goal"]),
        "output_format": str(manifest["output_format"] or "not-selected"),
        "weekly_slot": str(manifest["weekly_slot"] or "not-selected"),
        "narrative_route": " -> ".join(
            workflow.GOAL_ROUTES[str(manifest["goal"])]["narrative_route"]  # type: ignore[index]
        ),
        "strategy_origin": "explicit-input",
    }
    if any(values[name] != expected for name, expected in expected_metadata.items()):
        raise workflow.WorkflowError(
            "Frozen package manifest and strategy brief metadata do not match."
        )
    literal_fields = {
        name: _literal_text(values[name], label=name.replace("_", " "))
        for name in (
            "goal_purpose",
            "target_reader",
            "reader_problem",
            "core_hypothesis",
            "product_decision",
            "authority_statement",
            "why_now",
            "dominant_take",
            "missing_angle",
        )
    }
    for name in workflow.STRATEGY_INPUT_FIELDS:
        if literal_fields[name] != strategy_inputs[name]:
            raise workflow.WorkflowError(
                f"Frozen package brief does not match strategy input {name!r}."
            )
    route = workflow.GOAL_ROUTES[str(manifest["goal"])]
    if literal_fields["goal_purpose"] != route["purpose"]:
        raise workflow.WorkflowError(
            "Frozen package goal purpose does not match the current route contract."
        )
    return {
        "topic_slug": manifest["topic_slug"],
        "goal": manifest["goal"],
        "goal_purpose": literal_fields["goal_purpose"],
        "narrative_route": list(route["narrative_route"]),
        "output_format": manifest["output_format"],
        "weekly_slot": manifest["weekly_slot"],
        **{name: literal_fields[name] for name in workflow.STRATEGY_INPUT_FIELDS},
        "strategy_input_origin": "explicit-input",
        "analysis": {
            "why_now": literal_fields["why_now"],
            "dominant_take": literal_fields["dominant_take"],
            "missing_angle": literal_fields["missing_angle"],
        },
    }


def _repo_local_package_path(raw_path: Path | str) -> Path:
    supplied = Path(raw_path).expanduser()
    if ".." in supplied.parts:
        raise workflow.WorkflowError("Package paths cannot contain parent traversal.")
    root = workflow.REPO_ROOT.absolute()
    absolute = supplied.absolute() if supplied.is_absolute() else (root / supplied).absolute()
    try:
        relative = absolute.relative_to(root)
    except ValueError as exc:
        raise workflow.WorkflowError("Eval package must be a repository-local folder.") from exc
    current = root
    for component in relative.parts:
        current = current / component
        try:
            if current.is_symlink():
                raise workflow.WorkflowError("Eval package paths cannot contain symlinks.")
        except OSError as exc:
            raise workflow.WorkflowError("Eval package path is unavailable or unsafe.") from exc
    return absolute


def _read_package_documents(raw_path: Path | str) -> tuple[Path, dict[str, str]]:
    package_path = _repo_local_package_path(raw_path)
    directory_fd = -1
    opened: dict[str, tuple[int, os.stat_result]] = {}
    documents: dict[str, str] = {}
    expected_files = set(approval_package.PACKAGE_FILES.values())
    try:
        directory_fd = performance._open_directory(package_path)  # type: ignore[attr-defined]
        before = os.fstat(directory_fd)
        if set(os.listdir(directory_fd)) != expected_files:
            raise workflow.WorkflowError(
                "Eval package is incomplete or has an invalid file inventory."
            )
        for filename in sorted(expected_files):
            opened[filename] = performance._open_regular_file(  # type: ignore[attr-defined]
                filename,
                directory_fd=directory_fd,
                maximum_bytes=performance.MAX_PACKAGE_FILE_BYTES,
            )
        for filename in sorted(expected_files):
            descriptor, metadata = opened[filename]
            documents[filename] = performance._read_open_regular_file(  # type: ignore[attr-defined]
                descriptor, metadata
            )
        if set(os.listdir(directory_fd)) != expected_files:
            raise workflow.WorkflowError("Eval package changed while it was being read.")
        if performance._metadata_token(os.fstat(directory_fd)) != performance._metadata_token(before):  # type: ignore[attr-defined]
            raise workflow.WorkflowError("Eval package changed while it was being read.")
        if any(
            performance._metadata_token(os.fstat(descriptor))  # type: ignore[attr-defined]
            != performance._metadata_token(metadata)  # type: ignore[attr-defined]
            for descriptor, metadata in opened.values()
        ):
            raise workflow.WorkflowError("Eval package changed while it was being read.")
    finally:
        for descriptor, _metadata in opened.values():
            os.close(descriptor)
        if directory_fd >= 0:
            os.close(directory_fd)
    return package_path, documents


def _manifest(document: str, package_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(document)
    except json.JSONDecodeError as exc:
        raise workflow.WorkflowError("Eval package manifest is invalid JSON.") from exc
    if not isinstance(payload, Mapping) or set(payload) != performance._MANIFEST_FIELDS:  # type: ignore[attr-defined]
        raise workflow.WorkflowError("Eval package manifest schema is invalid.")
    manifest = dict(payload)
    if (
        manifest.get("schema_version") != approval_package.PACKAGE_SCHEMA_VERSION
        or manifest.get("mode") != "live"
        or manifest.get("files") != dict(approval_package.PACKAGE_FILES)
        or manifest.get("human_approval_status") != "NOT_APPROVED"
        or manifest.get("publishing_status") != "DISABLED"
    ):
        raise workflow.WorkflowError("Eval package must be a supported frozen live package.")
    package_id = manifest.get("package_id")
    expected_id = f"{package_path.parent.name}-{package_path.name}"
    if package_id != expected_id:
        raise workflow.WorkflowError("Eval package ID does not match its folder path.")
    if manifest.get("goal") not in workflow.STRATEGIC_GOALS:
        raise workflow.WorkflowError("Eval package strategic goal is invalid.")
    topic_slug = manifest.get("topic_slug")
    if not isinstance(topic_slug, str) or workflow.slugify(topic_slug) != topic_slug:
        raise workflow.WorkflowError("Eval package topic slug is invalid.")
    return manifest


def _load_context(args: object) -> dict[str, object]:
    package_path, documents = _read_package_documents(getattr(args, "package"))
    manifest = _manifest(documents["manifest.json"], package_path)
    strategy_inputs = workflow.load_strategy_inputs_file(getattr(args, "strategy_input"))
    evidence_manifest = workflow.load_evidence_manifest_file(
        getattr(args, "evidence_manifest")
    )
    database = Path(getattr(args, "db"))
    if not database.is_file():
        raise workflow.WorkflowError("Eval package needs an existing private research ledger.")
    source_urls = evidence_manifest["source_urls"]
    if not isinstance(source_urls, list):
        raise workflow.WorkflowError("Evidence manifest source URLs are invalid.")
    items = storage.list_research_items_by_urls(
        database, source_urls, evidence_origin="private-import"
    )
    returned = {str(item["canonical_url"]) for item in items}
    missing = [str(url) for url in source_urls if str(url) not in returned]
    if missing:
        raise workflow.WorkflowError(
            "Selected source URL is missing from the private ledger: "
            + ", ".join(missing)
            + "."
        )
    evidence = workflow.build_drafting_evidence(
        items, topic_slug=str(manifest["topic_slug"]), include_all=True
    )
    for item in evidence:
        source = str(item["source"])
        parts = urlsplit(source)
        public_source = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
        if f"## `{item['id']}`" not in documents["sources.md"] or f"    {public_source}" not in documents["sources.md"]:
            raise workflow.WorkflowError(
                "Frozen package source index does not match the evidence manifest."
            )
    brief = _parse_brief(
        documents["brief.md"], manifest=manifest, strategy_inputs=strategy_inputs
    )
    proof = None
    proof_manifest = getattr(args, "proof_manifest", None)
    if proof_manifest is not None:
        proof = workflow.load_proof_manifest(proof_manifest)
    elif manifest["goal"] == "opportunity":
        raise workflow.WorkflowError(
            "Opportunity package evaluation requires its original --proof-manifest."
        )
    candidates = workflow.validate_draft_candidates(
        _parse_candidates(documents["candidates.md"]),
        brief=brief,
        evidence=evidence,
        proof=proof,
    )
    requested = getattr(args, "candidate", None)
    if requested is not None and requested not in {item["id"] for item in candidates}:
        raise workflow.WorkflowError(f"Candidate {requested!r} is not in the frozen package.")
    selected_candidates = (
        candidates
        if requested is None
        else [item for item in candidates if item["id"] == requested]
    )
    return {
        "package_path": package_path,
        "manifest": manifest,
        "brief": brief,
        "evidence": evidence,
        "proof": proof,
        "all_candidates": candidates,
        "selected_candidates": selected_candidates,
    }


def _rubric_identity() -> dict[str, str]:
    # Validate the same live rubric loader used by invoke_critic, then bind the dashboard
    # to the exact bytes that were active for this run.
    workflow.critic_scoring_system_prompt()
    try:
        raw = workflow.CRITIC_RUBRIC_PATH.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError("Current Critic rubric is unavailable.") from exc
    try:
        display_path = workflow.CRITIC_RUBRIC_PATH.relative_to(
            workflow.REPO_ROOT
        ).as_posix()
    except ValueError:
        # Tests may replace the loader's path with an external fixture. Do not expose
        # host paths in provenance records; the byte hash remains the identity.
        display_path = f"<external>/{workflow.CRITIC_RUBRIC_PATH.name}"
    return {
        "path": display_path,
        "rubric_id": str(payload.get("rubric_id", "unknown")),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _acceptance_identity() -> dict[str, object]:
    path = workflow.REPO_ROOT / "config" / "linkedin-post-contract-v1.json"
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise workflow.WorkflowError("Approved LinkedIn post contract is unavailable.") from exc
    if not isinstance(payload, Mapping):
        raise workflow.WorkflowError("Approved LinkedIn post contract is malformed.")
    metadata = payload.get("metadata")
    critic = payload.get("critic")
    repair = payload.get("repair")
    if (
        not isinstance(metadata, Mapping)
        or not isinstance(critic, Mapping)
        or not isinstance(repair, Mapping)
    ):
        raise workflow.WorkflowError("Approved LinkedIn post contract is malformed.")
    if metadata.get("status") != "APPROVED":
        raise workflow.WorkflowError("LinkedIn post contract is not approved.")
    if (
        critic.get("minimum_total") != acceptance_policy.ACCEPTABLE_QUALITY_FLOOR
        or critic.get("axis_floors") != dict(acceptance_policy.AXIS_FLOORS)
        or critic.get("axis_order") != list(workflow.CRITIC_AXES)
        or repair.get("maximum_quality_cycles") != 4
    ):
        raise workflow.WorkflowError(
            "Approved LinkedIn post contract does not match the runtime Critic acceptance policy."
        )
    return {
        "path": path.relative_to(workflow.REPO_ROOT).as_posix(),
        "contract_id": str(metadata.get("contract_id", "unknown")),
        "version": str(metadata.get("version", "unknown")),
        "status": "APPROVED",
        "minimum_total": acceptance_policy.ACCEPTABLE_QUALITY_FLOOR,
        "axis_floors": dict(acceptance_policy.AXIS_FLOORS),
        "maximum_quality_cycles": repair.get("maximum_quality_cycles"),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _persist_dashboards(
    *,
    package_path: Path,
    manifest: Mapping[str, object],
    rubric: Mapping[str, str],
    acceptance_contract: Mapping[str, object],
    results: Sequence[Mapping[str, object]],
    repair_history: Sequence[Mapping[str, object]] = (),
) -> tuple[Path, Path, Path, bool]:
    run_id = (
        "eval-package-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + secrets.token_hex(6)
    )
    folder = workflow.DEFAULT_PRIVATE_DATA / "draft-runs" / run_id
    from . import __main__ as legacy_cli
    from . import daily_cli

    legacy_cli._ensure_owner_only_directory(folder)  # type: ignore[attr-defined]
    candidate_artifacts: dict[str, str] = {}
    for item in results:
        candidate = item.get("candidate")
        if not isinstance(candidate, Mapping):
            continue
        candidate_id = str(candidate.get("id", "candidate"))
        candidate_path = daily_cli.write_private_text(
            folder / f"evaluated-{candidate_id}.md",
            str(candidate.get("text", "")).strip() + "\n",
        )
        candidate_artifacts[candidate_id] = candidate_path.relative_to(
            workflow.REPO_ROOT
        ).as_posix()
    accepted = [str(item["candidate_id"]) for item in results if item["acceptance"]["status"] == "PASS"]  # type: ignore[index]
    checks = [
        {
            "stage": "final_evals",
            "category": "post_quality",
            "contract": "candidate_acceptance",
            "label": f"Candidate {item['candidate_id']} acceptance",
            "status": item["acceptance"]["status"],  # type: ignore[index]
            "mode": "diagnostic",
            "reason": (
                (
                    "candidate cleared writing scores; advisory: "
                    + ", ".join(
                        str(value)
                        for value in item["acceptance"].get(  # type: ignore[index]
                            "advisory_warnings", []
                        )
                    )
                )
                if (
                    item["acceptance"]["status"] == "PASS"  # type: ignore[index]
                    and item["acceptance"].get("advisory_warnings")  # type: ignore[index]
                )
                else "candidate cleared writing scores"
                if item["acceptance"]["status"] == "PASS"  # type: ignore[index]
                else (
                    ", ".join(
                        str(value) for value in item["acceptance"]["reasons"]  # type: ignore[index]
                    )
                ).rstrip(" |")
            ),
        }
        for item in results
    ]
    if repair_history:
        critic_scorecards = [
            {
                "cycle": item["iteration"],
                "candidate_id": item["candidate_id"],
                "axes": {
                    axis: item["scorecard"][axis]  # type: ignore[index]
                    for axis in workflow.CRITIC_AXES
                },
                "total": item["scorecard"]["effective_total"],  # type: ignore[index]
                "threshold": acceptance_policy.ACCEPTABLE_QUALITY_FLOOR,
                "status": (
                    item["acceptance"]["status"]  # type: ignore[index]
                    if item["accepted_as_next_seed"]
                    else "REJECTED"
                ),
                "failure_codes": list(item["acceptance"]["reasons"])  # type: ignore[index]
                + (list(item["editorial_decision_reasons"]) if not item["accepted_as_next_seed"] else []),
                "advisory_codes": list(item["acceptance"].get("advisory_warnings", [])),  # type: ignore[index]
            }
            for item in repair_history
        ]
    else:
        critic_scorecards = [
            {
                "cycle": 1,
                "candidate_id": item["candidate_id"],
                "axes": {
                    axis: item["scorecard"][axis]  # type: ignore[index]
                    for axis in workflow.CRITIC_AXES
                },
                "total": item["scorecard"]["effective_total"],  # type: ignore[index]
                "threshold": acceptance_policy.ACCEPTABLE_QUALITY_FLOOR,
                "status": item["acceptance"]["status"],  # type: ignore[index]
                "failure_codes": list(item["acceptance"]["reasons"]),  # type: ignore[index]
                "advisory_codes": list(
                    item["acceptance"].get("advisory_warnings", [])  # type: ignore[index]
                ),
            }
            for item in results
        ]
    eval_dashboard = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "eval-package",
        "package_id": manifest["package_id"],
        "package_path": package_path.relative_to(workflow.REPO_ROOT).as_posix(),
        "rubric": dict(rubric),
        "acceptance_contract": dict(acceptance_contract),
        "results": list(results),
        "repair_history": list(repair_history),
        "candidate_artifacts": candidate_artifacts,
        "accepted_candidate_ids": accepted,
        "checks": checks,
        "critic_scorecards": critic_scorecards,
    }
    run_dashboard = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "eval-package",
        "outcome": "PASS" if accepted else "COMPLETED_WITH_WARNINGS",
        "package_id": manifest["package_id"],
        "evaluated_candidate_ids": [str(item["candidate_id"]) for item in results],
        "accepted_candidate_ids": accepted,
        "writer_invoked": False,
        "revision_invoked": bool(len(repair_history) > 1),
        "editor_invocation_count": max(0, len(repair_history) - 1),
        "discovery_invoked": False,
        "thesis_selection_invoked": False,
        "rubric_sha256": rubric["sha256"],
        "acceptance_contract_sha256": acceptance_contract["sha256"],
        "repair_history": list(repair_history),
        "candidate_artifacts": candidate_artifacts,
        "checks": [
            {
                "stage": "final_evals",
                "label": "Frozen-package final evals",
                "status": "PASS" if accepted else "FAIL",
                "mode": "diagnostic",
                "reason": (
                    f"{len(accepted)} selected candidate(s) passed"
                    if accepted
                    else "best draft delivered; writing scores remain below target"
                ),
                "details": {},
            }
        ],
        "surface_scouts": [],
        "decisions": [],
        "evaluator_versions": {
            "rubrics": {
                str(rubric["path"]): rubric["sha256"],
                str(acceptance_contract["path"]): acceptance_contract["sha256"],
            }
        },
    }
    eval_path = daily_cli.write_private_json(folder / "eval-dashboard.json", eval_dashboard)
    run_path = daily_cli.write_private_json(folder / "run-dashboard.json", run_dashboard)
    from . import eval_dashboard_html

    html_path = eval_dashboard_html.write_dashboard(folder, run_dashboard, eval_dashboard)
    opened = eval_dashboard_html.open_dashboard(html_path)
    return eval_path, run_path, html_path, opened


def _evaluate_candidates(
    candidates: Sequence[Mapping[str, object]],
    *,
    all_candidates: Sequence[Mapping[str, object]],
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    proof: workflow.LoadedProof | None,
    score_provider: Callable[..., Sequence[Mapping[str, object]]],
    allow_factual_wording_advisory: bool = False,
) -> list[dict[str, object]]:
    raw_scores = score_provider(
        candidates,
        brief,
        evidence,
        allow_model_egress=True,
        proof=proof,
    )
    scorecards = workflow.validate_critic_scorecards(raw_scores, candidates)
    ranked = workflow.rank_critic_scorecards(scorecards)
    gate_results = workflow.evaluate_candidate_set_gates(
        all_candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,
    )
    gates_by_id = {str(item["candidate_id"]): item for item in gate_results}
    candidates_by_id = {str(item["id"]): item for item in all_candidates}
    results: list[dict[str, object]] = []
    for scorecard in ranked:
        candidate_id = str(scorecard["candidate_id"])
        candidate = candidates_by_id[candidate_id]
        gate = gates_by_id[candidate_id]
        findings = anti_slop.audit(str(candidate["text"]))
        raw_gates = gate["gates"]
        hard_gates_pass = acceptance_policy.hard_candidate_gates_pass(
            raw_gates,  # type: ignore[arg-type]
            passes_required_gates=bool(gate["passes_required_gates"]),
            allow_factual_wording_advisory=allow_factual_wording_advisory,
        )
        advisories = [
            f"{name}:{raw.get('status')}:{','.join(raw.get('reason_codes', []))}"
            for name, raw in raw_gates.items()
            if raw.get("status") not in {"PASS", "NOT_REQUIRED"}
        ] + [f"anti-slop:{finding.code}:{finding.excerpt}" for finding in findings]
        decision = acceptance_policy.acceptance_decision(
            scorecard,
            hard_gates_pass=hard_gates_pass,
            additional_checks_pass=not findings,
        )
        decision["advisory_warnings"] = advisories
        results.append(
            {
                "candidate_id": candidate_id,
                "candidate": dict(candidate),
                "scorecard": dict(scorecard),
                "gates": gate,
                "factual_support_diagnostics": (
                    workflow.candidate_factual_support_diagnostics(
                        candidate, evidence, proof=proof
                    )
                ),
                "anti_slop_findings": [
                    {"code": finding.code, "excerpt": finding.excerpt}
                    for finding in findings
                ],
                "acceptance": decision,
            }
        )
    return results


def _failed_gate_details(result: Mapping[str, object]) -> dict[str, object]:
    raw_gate_result = result.get("gates")
    if not isinstance(raw_gate_result, Mapping):
        raise workflow.WorkflowError("Progressive editor gate result is malformed.")
    raw_gates = raw_gate_result.get("gates")
    if not isinstance(raw_gates, Mapping):
        raise workflow.WorkflowError("Progressive editor gate map is malformed.")
    return {
        str(name): dict(gate)
        for name, gate in raw_gates.items()
        if isinstance(gate, Mapping)
        and str(gate.get("status")) not in {"PASS", "NOT_REQUIRED"}
    }


def _repair_feedback(iteration: int, result: Mapping[str, object]) -> dict[str, object]:
    scorecard = result.get("scorecard")
    acceptance = result.get("acceptance")
    if not isinstance(scorecard, Mapping) or not isinstance(acceptance, Mapping):
        raise workflow.WorkflowError("Progressive editor score result is malformed.")
    passing_axes = {
        axis: int(scorecard[axis])
        for axis, floor in acceptance_policy.AXIS_FLOORS.items()
        if int(scorecard[axis]) >= floor
    }
    feedback: dict[str, object] = {
        "next_scored_iteration": iteration,
        "same_candidate_required": True,
        "current_scores": {
            axis: int(scorecard[axis]) for axis in workflow.CRITIC_AXES
        },
        "current_total": int(scorecard["effective_total"]),
        "required_total": acceptance_policy.ACCEPTABLE_QUALITY_FLOOR,
        "total_shortfall": max(
            0,
            acceptance_policy.ACCEPTABLE_QUALITY_FLOOR
            - int(scorecard["effective_total"]),
        ),
        "axis_shortfalls": dict(acceptance.get("axis_shortfalls", {})),
        "passing_axes_to_preserve": passing_axes,
        "failed_gates": _failed_gate_details(result),
        "factual_support_diagnostics": list(
            result.get("factual_support_diagnostics", [])  # type: ignore[arg-type]
        ),
        "anti_slop_findings": list(
            result.get("anti_slop_findings", [])  # type: ignore[arg-type]
        ),
        "editor_contract": (
            "Edit only the named failures. Keep the candidate ID, angle, claim IDs, "
            "selected thesis, evidence boundary, and passing material. Do not invent facts, "
            "experience, emotion, sources, scale, causality, or impact. The next revision is "
            "eligible to become the new seed only if its overall total does not regress. Hook "
            "and voice remain final acceptance targets, not iteration vetoes. Editorial findings are "
            "advisory feedback, never reasons to discard score progress. Individual "
            "axis scores may trade off inside the overall total."
        ),
    }
    voice_score = int(scorecard["voice_fidelity"])
    if voice_score < acceptance_policy.AXIS_FLOORS["voice_fidelity"]:
        voice_rubric = workflow._load_canonical_voice_fidelity_rubric()
        feedback["voice_repair_standard"] = {
            "current_score": voice_score,
            "required_score": acceptance_policy.AXIS_FLOORS["voice_fidelity"],
            "level_3": voice_rubric["3"],
            "level_4": voice_rubric["4"],
            "level_5": voice_rubric["5"],
            "short_emphasis_rule": voice_rubric["short_emphasis_rule"],
            "optional_human_devices_rule": voice_rubric[
                "optional_human_devices_rule"
            ],
            "calibration_examples": voice_rubric["calibration_examples"],
        }
    return feedback


def _finding_keys(raw: object) -> set[tuple[str, str]]:
    if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
        return set()
    return {
        (str(item.get("code", "")), str(item.get("excerpt", "")))
        for item in raw
        if isinstance(item, Mapping)
    }


def _monotonic_edit_decision(
    previous: Mapping[str, object], proposed: Mapping[str, object]
) -> tuple[bool, list[str]]:
    previous_score = previous.get("scorecard")
    proposed_score = proposed.get("scorecard")
    if not isinstance(previous_score, Mapping) or not isinstance(proposed_score, Mapping):
        raise workflow.WorkflowError("Progressive editor score comparison is malformed.")
    regressions: list[str] = []
    previous_total = int(previous_score["effective_total"])
    proposed_total = int(proposed_score["effective_total"])
    if proposed_total < previous_total:
        regressions.append(f"total-regressed-{previous_total}-to-{proposed_total}")

    previous_gate_result = previous.get("gates")
    proposed_gate_result = proposed.get("gates")
    if not isinstance(previous_gate_result, Mapping) or not isinstance(
        proposed_gate_result, Mapping
    ):
        raise workflow.WorkflowError("Progressive editor gate comparison is malformed.")
    previous_gates = previous_gate_result.get("gates")
    proposed_gates = proposed_gate_result.get("gates")
    if not isinstance(previous_gates, Mapping) or not isinstance(proposed_gates, Mapping):
        raise workflow.WorkflowError("Progressive editor gate comparison is incomplete.")
    previous_slop = _finding_keys(previous.get("anti_slop_findings"))
    proposed_slop = _finding_keys(proposed.get("anti_slop_findings"))
    if regressions:
        return False, regressions

    previous_failed = len(_failed_gate_details(previous))
    proposed_failed = len(_failed_gate_details(proposed))
    previous_factual = len(
        _finding_keys(previous.get("factual_support_diagnostics"))
    )
    proposed_factual = len(
        _finding_keys(proposed.get("factual_support_diagnostics"))
    )
    previous_shortfalls = acceptance_policy.axis_shortfalls(previous_score)
    proposed_shortfalls = acceptance_policy.axis_shortfalls(proposed_score)
    improved = (
        (
            previous.get("acceptance", {}).get("status") != "PASS"  # type: ignore[union-attr]
            and proposed.get("acceptance", {}).get("status") == "PASS"  # type: ignore[union-attr]
        )
        or
        proposed_total > previous_total
        or sum(item["shortfall"] for item in proposed_shortfalls.values())
        < sum(item["shortfall"] for item in previous_shortfalls.values())
        or proposed_failed < previous_failed
        or len(proposed_slop) < len(previous_slop)
        or proposed_factual < previous_factual
    )
    return improved, [] if improved else ["no-measurable-improvement"]


def _replace_candidate(
    candidates: Sequence[Mapping[str, object]],
    revised: Mapping[str, object],
    *,
    original: Mapping[str, object],
    brief: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
    proof: workflow.LoadedProof | None,
) -> list[dict[str, object]]:
    if (
        revised.get("id") != original.get("id")
        or revised.get("angle") != original.get("angle")
        or revised.get("claim_ids") != original.get("claim_ids")
    ):
        raise workflow.WorkflowError(
            "Progressive editor must preserve candidate ID, angle, and claim IDs exactly."
        )
    replaced = [
        dict(revised) if item.get("id") == original.get("id") else dict(item)
        for item in candidates
    ]
    return workflow.validate_draft_candidates(
        replaced, brief=brief, evidence=evidence, proof=proof
    )


def _history_entry(
    iteration: int,
    result: Mapping[str, object],
    *,
    accepted_as_seed: bool,
    decision_reasons: Sequence[str],
) -> dict[str, object]:
    return {
        "iteration": iteration,
        "candidate_id": result["candidate_id"],
        "scorecard": dict(result["scorecard"]),  # type: ignore[arg-type]
        "acceptance": dict(result["acceptance"]),  # type: ignore[arg-type]
        "failed_gates": _failed_gate_details(result),
        "factual_support_diagnostics": list(
            result.get("factual_support_diagnostics", [])  # type: ignore[arg-type]
        ),
        "anti_slop_findings": list(
            result.get("anti_slop_findings", [])  # type: ignore[arg-type]
        ),
        "accepted_as_next_seed": accepted_as_seed,
        "editorial_decision_reasons": list(decision_reasons),
    }


def command(
    args: object,
    *,
    persist: Callable[..., tuple[Path, Path, Path, bool]] = _persist_dashboards,
    score_provider: Callable[..., Sequence[Mapping[str, object]]] | None = None,
    editor: Callable[..., Mapping[str, object]] | None = None,
) -> int:
    """Evaluate frozen candidates, optionally editing one candidate monotonically."""

    if not bool(getattr(args, "allow_model_egress", False)):
        raise workflow.WorkflowError(
            "Eval package requires --allow-model-egress before frozen content reaches the Critic."
        )
    repair_requested = bool(getattr(args, "repair", False))
    if repair_requested and getattr(args, "candidate", None) is None:
        raise workflow.WorkflowError("Progressive repair requires one explicit --candidate.")
    context = _load_context(args)
    candidates = context["selected_candidates"]
    brief = context["brief"]
    evidence = context["evidence"]
    all_candidates = context["all_candidates"]
    proof = context["proof"]
    if (
        not isinstance(candidates, list)
        or not isinstance(all_candidates, list)
        or not isinstance(brief, Mapping)
        or not isinstance(evidence, list)
    ):
        raise workflow.WorkflowError("Eval package context is malformed.")
    rubric = _rubric_identity()
    acceptance_contract = _acceptance_identity()
    scorer = workflow.invoke_critic if score_provider is None else score_provider
    results = _evaluate_candidates(
        candidates,
        all_candidates=all_candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,  # type: ignore[arg-type]
        score_provider=scorer,
    )
    repair_history: list[dict[str, object]] = []

    if repair_requested:
        if len(results) != 1 or len(candidates) != 1:
            raise workflow.WorkflowError("Progressive repair requires exactly one candidate.")
        current_result = results[0]
        current_candidate = dict(candidates[0])
        current_all_candidates = [dict(candidate) for candidate in all_candidates]
        repair_history.append(
            _history_entry(
                1,
                current_result,
                accepted_as_seed=True,
                decision_reasons=["frozen-baseline"],
            )
        )
        raw_limit = acceptance_contract.get("maximum_quality_cycles")
        if type(raw_limit) is not int or raw_limit != 4:
            raise workflow.WorkflowError(
                "Approved contract must define exactly four progressive scored iterations."
            )
        edit = workflow.invoke_writer_revision if editor is None else editor
        for iteration in range(2, raw_limit + 1):
            factual_findings = current_result.get("factual_support_diagnostics") or any(
                "unsupported-factual-marker" in gate.get("reason_codes", [])
                for gate in _failed_gate_details(current_result).values()
            )
            if current_result["acceptance"]["status"] == "PASS" and (  # type: ignore[index]
                iteration > 2 or not factual_findings
            ):
                break
            feedback = _repair_feedback(iteration, current_result)
            revised = edit(
                current_candidate,
                brief,
                evidence,
                scorecard=current_result["scorecard"],
                allow_model_egress=True,
                proof=proof,
                repair_feedback=feedback,
            )
            if not isinstance(revised, Mapping):
                raise workflow.WorkflowError("Progressive editor returned a malformed candidate.")
            proposed_all_candidates = _replace_candidate(
                current_all_candidates,
                revised,
                original=current_candidate,
                brief=brief,
                evidence=evidence,
                proof=proof,  # type: ignore[arg-type]
            )
            proposed_candidate = next(
                candidate
                for candidate in proposed_all_candidates
                if candidate["id"] == current_candidate["id"]
            )
            proposed_result = _evaluate_candidates(
                [proposed_candidate],
                all_candidates=proposed_all_candidates,
                brief=brief,
                evidence=evidence,
                proof=proof,  # type: ignore[arg-type]
                score_provider=scorer,
                # Findings stay advisory before and after the bounded edit.
                allow_factual_wording_advisory=True,
            )[0]
            accepted_as_seed, reasons = _monotonic_edit_decision(
                current_result, proposed_result
            )
            repair_history.append(
                _history_entry(
                    iteration,
                    proposed_result,
                    accepted_as_seed=accepted_as_seed,
                    decision_reasons=(
                        ["monotonic-improvement"] if accepted_as_seed else reasons
                    ),
                )
            )
            if accepted_as_seed:
                current_candidate = dict(proposed_candidate)
                current_all_candidates = proposed_all_candidates
                current_result = proposed_result
        results = [current_result]

    eval_path, run_path, html_path, opened = persist(
        package_path=context["package_path"],  # type: ignore[arg-type]
        manifest=context["manifest"],  # type: ignore[arg-type]
        rubric=rubric,
        acceptance_contract=acceptance_contract,
        results=results,
        repair_history=repair_history,
    )
    if repair_history:
        for item in repair_history:
            scorecard = item["scorecard"]
            print(
                f"Progressive iteration {item['iteration']}/4: "
                f"score={scorecard['effective_total']}/25; "  # type: ignore[index]
                + ",".join(
                    f"{axis}={scorecard[axis]}/5"  # type: ignore[index]
                    for axis in workflow.CRITIC_AXES
                )
                + f"; accepted_as_next_seed={'yes' if item['accepted_as_next_seed'] else 'no'}; "
                + "reasons="
                + ",".join(str(value) for value in item["editorial_decision_reasons"])
                + "."
            )
    for result in results:
        scorecard = result["scorecard"]
        if not isinstance(scorecard, Mapping):
            raise workflow.WorkflowError("Eval scorecard is malformed.")
        axes = ",".join(f"{axis}={scorecard[axis]}" for axis in workflow.CRITIC_AXES)
        print(
            f"Eval score: id={result['candidate_id']}; {axes}; "
            f"raw_total={scorecard['raw_total']}; effective_total={scorecard['effective_total']}; "
            f"acceptance={result['acceptance']['status']}."  # type: ignore[index]
        )
        artifact = eval_path.parent / f"evaluated-{result['candidate_id']}.md"
        if artifact.is_file():
            print(f"Evaluated candidate: {artifact.relative_to(workflow.REPO_ROOT)}.")
    print("Eval ranking: " + ",".join(str(item["candidate_id"]) for item in results) + ".")
    print(f"Active Critic rubric: {rubric['rubric_id']} ({rubric['sha256'][:12]}).")
    print(
        "Active acceptance contract: "
        f"{acceptance_contract['version']} ({str(acceptance_contract['sha256'])[:12]})."
    )
    print(f"Eval dashboard stored: {eval_path.relative_to(workflow.REPO_ROOT)}.")
    print(f"Run dashboard stored: {run_path.relative_to(workflow.REPO_ROOT)}.")
    print(
        f"Eval dashboard UI: {html_path.as_uri()}"
        + (" (opened in your browser)." if opened else ".")
    )
    if repair_requested:
        print(
            "Discovery, research, thesis selection, and the original Writer were not run; "
            f"the bounded editor was invoked {max(0, len(repair_history) - 1)} time(s)."
        )
    else:
        print("Frozen candidates were not drafted, revised, selected as a thesis, or published.")
    print("No LinkedIn publishing action was taken.")
    if not any(item["acceptance"]["status"] == "PASS" for item in results):  # type: ignore[index]
        print("Completed with warnings: best draft delivered; writing scores remain below target.")
    return 0
