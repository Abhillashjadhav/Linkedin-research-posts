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
    if not isinstance(metadata, Mapping) or not isinstance(critic, Mapping):
        raise workflow.WorkflowError("Approved LinkedIn post contract is malformed.")
    if metadata.get("status") != "APPROVED":
        raise workflow.WorkflowError("LinkedIn post contract is not approved.")
    if (
        critic.get("minimum_total") != acceptance_policy.ACCEPTABLE_QUALITY_FLOOR
        or critic.get("axis_floors") != dict(acceptance_policy.AXIS_FLOORS)
        or critic.get("axis_order") != list(workflow.CRITIC_AXES)
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
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def _persist_dashboards(
    *,
    package_path: Path,
    manifest: Mapping[str, object],
    rubric: Mapping[str, str],
    acceptance_contract: Mapping[str, object],
    results: Sequence[Mapping[str, object]],
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
    accepted = [str(item["candidate_id"]) for item in results if item["acceptance"]["status"] == "PASS"]  # type: ignore[index]
    checks = [
        {
            "stage": "final_evals",
            "category": "post_quality",
            "contract": "candidate_acceptance",
            "label": f"Candidate {item['candidate_id']} acceptance",
            "status": item["acceptance"]["status"],  # type: ignore[index]
            "reason": (
                "candidate cleared Critic, hard gates, and anti-slop"
                if item["acceptance"]["status"] == "PASS"  # type: ignore[index]
                else ", ".join(str(value) for value in item["acceptance"]["reasons"])  # type: ignore[index]
            ),
        }
        for item in results
    ]
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
        "accepted_candidate_ids": accepted,
        "checks": checks,
        "critic_scorecards": critic_scorecards,
    }
    run_dashboard = {
        "schema_version": 1,
        "run_id": run_id,
        "command": "eval-package",
        "outcome": "PASS" if accepted else "FAIL",
        "package_id": manifest["package_id"],
        "evaluated_candidate_ids": [str(item["candidate_id"]) for item in results],
        "accepted_candidate_ids": accepted,
        "writer_invoked": False,
        "revision_invoked": False,
        "discovery_invoked": False,
        "thesis_selection_invoked": False,
        "rubric_sha256": rubric["sha256"],
        "acceptance_contract_sha256": acceptance_contract["sha256"],
        "checks": [
            {
                "stage": "final_evals",
                "label": "Frozen-package final evals",
                "status": "PASS" if accepted else "FAIL",
                "reason": (
                    f"{len(accepted)} selected candidate(s) passed"
                    if accepted
                    else "no selected candidate passed"
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


def command(
    args: object,
    *,
    persist: Callable[..., tuple[Path, Path, Path, bool]] = _persist_dashboards,
) -> int:
    """Run Critic plus deterministic final evaluation on immutable candidates."""

    if not bool(getattr(args, "allow_model_egress", False)):
        raise workflow.WorkflowError(
            "Eval package requires --allow-model-egress before frozen content reaches the Critic."
        )
    context = _load_context(args)
    candidates = context["selected_candidates"]
    brief = context["brief"]
    evidence = context["evidence"]
    if not isinstance(candidates, list) or not isinstance(brief, Mapping) or not isinstance(evidence, list):
        raise workflow.WorkflowError("Eval package context is malformed.")
    rubric = _rubric_identity()
    acceptance_contract = _acceptance_identity()
    raw_scores = workflow.invoke_critic(
        candidates,
        brief,
        evidence,
        allow_model_egress=True,
        proof=context["proof"],  # type: ignore[arg-type]
    )
    scorecards = workflow.validate_critic_scorecards(raw_scores, candidates)
    ranked = workflow.rank_critic_scorecards(scorecards)
    all_candidates = context["all_candidates"]
    if not isinstance(all_candidates, list):
        raise workflow.WorkflowError("Eval package candidates are malformed.")
    gate_results = workflow.evaluate_candidate_set_gates(
        all_candidates,
        brief=brief,
        evidence=evidence,
        proof=context["proof"],  # type: ignore[arg-type]
    )
    gates_by_id = {str(item["candidate_id"]): item for item in gate_results}
    candidates_by_id = {str(item["id"]): item for item in all_candidates}
    results: list[dict[str, object]] = []
    for scorecard in ranked:
        candidate_id = str(scorecard["candidate_id"])
        gate = gates_by_id[candidate_id]
        findings = anti_slop.audit(str(candidates_by_id[candidate_id]["text"]))
        hard_gates_pass = (
            gate["passes_required_gates"] is True
            and acceptance_policy.hard_candidate_gates_pass(gate["gates"])  # type: ignore[arg-type]
        )
        decision = acceptance_policy.acceptance_decision(
            scorecard,
            hard_gates_pass=hard_gates_pass,
            additional_checks_pass=not findings,
        )
        results.append(
            {
                "candidate_id": candidate_id,
                "scorecard": dict(scorecard),
                "gates": gate,
                "anti_slop_findings": [
                    {"code": finding.code, "excerpt": finding.excerpt}
                    for finding in findings
                ],
                "acceptance": decision,
            }
        )
    eval_path, run_path, html_path, opened = persist(
        package_path=context["package_path"],  # type: ignore[arg-type]
        manifest=context["manifest"],  # type: ignore[arg-type]
        rubric=rubric,
        acceptance_contract=acceptance_contract,
        results=results,
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
    print("Frozen candidates were not drafted, revised, selected as a thesis, or published.")
    return 0 if any(item["acceptance"]["status"] == "PASS" for item in results) else 1  # type: ignore[index]
