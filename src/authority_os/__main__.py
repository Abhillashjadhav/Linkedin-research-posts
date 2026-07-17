"""One fixed CLI entry point for LinkedIn Authority OS."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import stat
import sys
from pathlib import Path

from . import (
    __version__,
    learning,
    package as approval_package,
    performance,
    privacy,
    storage,
    workflow,
)


def _path(value: str) -> Path:
    return Path(value).expanduser().resolve()


def _unresolved_path(value: str) -> Path:
    """Keep symlink information available for private proof validation."""

    return Path(value).expanduser()


def _nonblank(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise argparse.ArgumentTypeError("value must not be blank")
    return cleaned


def _metric(value: str) -> int:
    try:
        return performance.parse_metric(value, field="value")
    except workflow.WorkflowError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--db", type=_unresolved_path, default=workflow.DEFAULT_DB, help=argparse.SUPPRESS
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin-os",
        description="Prepare LinkedIn research and drafts for manual human approval.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="Create ignored local runtime directories.")
    _add_common(init)

    doctor = subparsers.add_parser("doctor", help="Check local setup without printing secrets.")
    _add_common(doctor)

    subparsers.add_parser(
        "privacy-check",
        help="Scan tracked and prospective public files without reading ignored private data.",
    )

    draft = subparsers.add_parser(
        "draft",
        help="Generate, Critic-score, and locally gate three drafts.",
    )
    draft.add_argument(
        "--topic", type=_nonblank, help="Optional topic substituted into the fixture."
    )
    draft.add_argument(
        "--goal",
        choices=workflow.STRATEGIC_GOALS,
        help="Strategic outcome; independent from the output format.",
    )
    draft.add_argument(
        "--format",
        dest="output_format",
        choices=workflow.OUTPUT_FORMATS,
        help="Optional output format; never inferred from the strategic goal.",
    )
    draft.add_argument(
        "--week-slot",
        type=int,
        help="Use the default four-post weekly mix, or guarded optional slot 5.",
    )
    draft.add_argument(
        "--strong-current-signal",
        action="store_true",
        help="Confirm that optional slot 5 has a strong current incident or launch.",
    )
    draft.add_argument(
        "--strategy-input",
        type=_path,
        help="Private JSON object containing the five explicit strategy fields.",
    )
    draft.add_argument(
        "--allow-model-egress",
        action="store_true",
        help=(
            "Explicitly allow selected evidence, strategy, and any public proof claim or "
            "attestation text to leave this machine for the configured Claude service."
        ),
    )
    draft.add_argument(
        "--proof-manifest",
        type=_unresolved_path,
        help=(
            "Private proof manifest under data/private (required for Opportunity and "
            "optional otherwise); its local artifact path and contents never leave this "
            "machine."
        ),
    )
    draft.add_argument("--dry-run", action="store_true", help="Use the offline safe fixture.")
    draft.add_argument(
        "--package",
        action="store_true",
        help="Write an ignored local package for explicit human review.",
    )
    _add_common(draft)

    research = subparsers.add_parser("research", help="Import or validate research signals.")
    research.add_argument(
        "--topic", type=_nonblank, help="Optional topic substituted into the fixture."
    )
    research.add_argument("--input", type=_path, help="Private JSON or JSONL research import.")
    research.add_argument(
        "--recent-posts",
        type=_path,
        help="Private JSON list of recent post text used only for stale-topic comparison.",
    )
    research.add_argument("--dry-run", action="store_true", help="Use the offline safe fixture.")
    _add_common(research)

    performance_parser = subparsers.add_parser(
        "record-performance",
        help="Record a manually published candidate's paid or organic checkpoint.",
    )
    performance_parser.add_argument(
        "--csv",
        type=_unresolved_path,
        help="Owner-only exact-schema CSV batch under data/private.",
    )
    performance_parser.add_argument(
        "--package-id",
        type=_nonblank,
        help="Committed live package ID printed by draft --package.",
    )
    performance_parser.add_argument(
        "--candidate",
        type=_nonblank,
        help="Eligible candidate that a human actually published.",
    )
    performance_parser.add_argument(
        "--manually-published-at",
        help="Whole-second timezone-aware timestamp of the external manual publication.",
    )
    performance_parser.add_argument(
        "--checkpoint", choices=storage.PERFORMANCE_CHECKPOINTS
    )
    performance_parser.add_argument("--channel", choices=storage.PERFORMANCE_CHANNELS)
    performance_parser.add_argument(
        "--observed-at", help="Whole-second timezone-aware timestamp of the metric snapshot."
    )
    for metric in storage.PERFORMANCE_METRICS:
        performance_parser.add_argument(
            f"--{metric.replace('_', '-')}",
            type=_metric,
            default=None,
        )
    performance_parser.add_argument(
        "--confirm-manual-publication",
        action="store_true",
        help="Assert that publication already happened outside this runtime.",
    )
    performance_parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing checkpoint with an equal-or-newer complete snapshot.",
    )
    _add_common(performance_parser)

    weekly = subparsers.add_parser(
        "weekly-review",
        help="Build a private observation-only learning report from trusted checkpoints.",
    )
    weekly.add_argument(
        "--as-of",
        type=_nonblank,
        help="Optional whole-second timezone-aware boundary for a reproducible review.",
    )
    _add_common(weekly)
    return parser


def _private_directory_plan(path: Path) -> tuple[Path, tuple[str, ...]]:
    if path.is_absolute():
        anchor = Path(path.anchor)
        components = path.parts[1:]
        # Resolve only the exact root-owned aliases exposed by macOS. Arbitrary
        # symlinks remain invalid path components.
        if components and components[0] in {"tmp", "var"}:
            alias = Path(path.anchor) / components[0]
            try:
                metadata = os.lstat(alias)
                target = os.readlink(alias)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISLNK(metadata.st_mode)
                    and metadata.st_uid == 0
                    and target == f"private/{components[0]}"
                ):
                    components = ("private", components[0], *components[1:])
    else:
        anchor = Path(".")
        components = path.parts
    cleaned = tuple(part for part in components if part not in {"", "."})
    if not cleaned or any(part == ".." for part in cleaned):
        raise workflow.WorkflowError(
            "A private runtime directory is unavailable or unsafe."
        )
    return anchor, cleaned


def _directory_identity(metadata: os.stat_result) -> tuple[int, ...]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_uid,
    )


def _safe_directory_component(metadata: os.stat_result) -> bool:
    permissions = stat.S_IMODE(metadata.st_mode)
    return (
        stat.S_ISDIR(metadata.st_mode)
        and metadata.st_uid in {0, os.geteuid()}
        and (permissions & 0o022 == 0 or permissions & stat.S_ISVTX != 0)
    )


def _ensure_owner_only_directory(path: Path) -> None:
    if not all(
        (
            getattr(os, "O_DIRECTORY", 0),
            getattr(os, "O_NOFOLLOW", 0),
            hasattr(os, "geteuid"),
            hasattr(os, "fchmod"),
            os.open in getattr(os, "supports_dir_fd", ()),
            os.mkdir in getattr(os, "supports_dir_fd", ()),
            os.stat in getattr(os, "supports_dir_fd", ()),
            os.stat in getattr(os, "supports_follow_symlinks", ()),
        )
    ):
        raise workflow.WorkflowError("Secure private directory operations are unavailable.")
    descriptors: list[int] = []
    identities: list[tuple[int, ...]] = []
    edges: list[tuple[int, str, tuple[int, ...]]] = []
    try:
        anchor, components = _private_directory_plan(path)
        descriptor = os.open(
            anchor,
            os.O_RDONLY
            | os.O_DIRECTORY
            | os.O_NOFOLLOW
            | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if not _safe_directory_component(metadata):
            raise workflow.WorkflowError(
                "A private runtime directory is unavailable or unsafe."
            )
        descriptors.append(descriptor)
        identities.append(_directory_identity(metadata))
        for index, component in enumerate(components):
            parent_descriptor = descriptors[-1]
            created = False
            try:
                descriptor = os.open(
                    component,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent_descriptor,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(component, 0o700, dir_fd=parent_descriptor)
                    created = True
                except FileExistsError:
                    pass
                descriptor = os.open(
                    component,
                    os.O_RDONLY
                    | os.O_DIRECTORY
                    | os.O_NOFOLLOW
                    | getattr(os, "O_CLOEXEC", 0),
                    dir_fd=parent_descriptor,
                )
            descriptors.append(descriptor)
            metadata = os.fstat(descriptor)
            is_final = index == len(components) - 1
            if is_final:
                if (
                    not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                ):
                    raise workflow.WorkflowError(
                        "A private runtime directory is unavailable or unsafe."
                    )
                os.fchmod(descriptor, 0o700)
                metadata = os.fstat(descriptor)
            elif not _safe_directory_component(metadata):
                raise workflow.WorkflowError(
                    "A private runtime directory is unavailable or unsafe."
                )
            if created and metadata.st_uid != os.geteuid():
                raise workflow.WorkflowError(
                    "A private runtime directory is unavailable or unsafe."
                )
            identity = _directory_identity(metadata)
            current = os.stat(
                component,
                dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
            if _directory_identity(current) != identity:
                raise workflow.WorkflowError(
                    "A private runtime directory is unavailable or unsafe."
                )
            identities.append(identity)
            edges.append((parent_descriptor, component, identity))

        if (
            _directory_identity(os.stat(anchor, follow_symlinks=False))
            != identities[0]
            or any(
                _directory_identity(os.fstat(opened)) != expected
                for opened, expected in zip(descriptors, identities, strict=True)
            )
            or any(
                _directory_identity(
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                )
                != expected
                for parent, name, expected in edges
            )
        ):
            raise workflow.WorkflowError(
                "A private runtime directory is unavailable or unsafe."
            )
    except OSError as exc:
        raise workflow.WorkflowError(
            "A private runtime directory is unavailable or unsafe."
        ) from exc
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def initialise_paths(db_path: Path) -> None:
    _ensure_owner_only_directory(workflow.DEFAULT_OUTPUTS)
    _ensure_owner_only_directory(workflow.DEFAULT_PRIVATE_DATA)
    storage.initialise(db_path)


def command_init(args: argparse.Namespace) -> int:
    initialise_paths(args.db)
    print(f"Initialised private Authority OS database: {args.db}")
    print("Publishing remains disabled.")
    return 0


def command_privacy_check(_args: argparse.Namespace) -> int:
    findings = privacy.scan_repository(workflow.REPO_ROOT)
    if findings:
        for finding in findings:
            print(f"PRIVACY FAIL: {finding}", file=sys.stderr)
        return 1
    print(
        "Privacy check passed: ignored private data was not read; no tracked secret, "
        "schedule, database, browser, or LinkedIn write surface was found."
    )
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    secure_posix = bool(
        all(
            (
                getattr(os, "O_DIRECTORY", 0),
                getattr(os, "O_NOFOLLOW", 0),
                getattr(os, "O_NONBLOCK", 0),
                hasattr(os, "geteuid"),
                hasattr(os, "fchmod"),
            )
        )
    )
    checks: list[tuple[str, bool, str]] = [
        ("Python 3.11+", sys.version_info >= (3, 11), sys.version.split()[0]),
        ("secure POSIX filesystem", secure_posix, "available" if secure_posix else "unavailable"),
    ]
    entrypoint = workflow.REPO_ROOT / "bin/linkedin-os"
    try:
        metadata = entrypoint.lstat()
        entrypoint_ok = stat.S_ISREG(metadata.st_mode) and os.access(entrypoint, os.X_OK)
    except OSError:
        entrypoint_ok = False
    checks.append(("single CLI entry point", entrypoint_ok, "executable" if entrypoint_ok else "unavailable"))
    for relative in (
        "data/voice/voice-guide.md",
        "data/voice/abhillash-best-posts.md",
        "data/samples/dry-run.json",
        "data/samples/proof-fixture.json",
        "data/samples/synthetic-proof.md",
    ):
        path = workflow.REPO_ROOT / relative
        try:
            metadata = path.lstat()
            present = stat.S_ISREG(metadata.st_mode) and metadata.st_size > 0
        except OSError:
            present = False
        checks.append((relative, present, "present" if present else "unavailable"))
    try:
        privacy_findings = privacy.scan_repository(workflow.REPO_ROOT)
        privacy_ok = not privacy_findings
        ignores_ok = not any(
            finding.startswith(".gitignore:") for finding in privacy_findings
        )
    except (ValueError, OSError):
        privacy_ok = False
        ignores_ok = False
    checks.append(
        (
            "privacy ignore rules",
            ignores_ok,
            "configured" if ignores_ok else "unavailable",
        )
    )
    try:
        storage.inspect_database_health(args.db)
        database_ok = True
    except (ValueError, sqlite3.Error, OSError):
        database_ok = False
    checks.append(
        (
            "private research and performance ledger",
            database_ok,
            "ready" if database_ok else "run init",
        )
    )
    checks.append(
        (
            "repository privacy scan",
            privacy_ok,
            "passed" if privacy_ok else "run privacy-check",
        )
    )
    checks.append(("optional Claude CLI", shutil.which("claude") is not None, "optional"))

    forbidden_actions = {
        "publish",
        "schedule",
        "approve",
        "message",
        "comment",
        "post",
        "send",
    }
    no_external_action = all(
        forbidden_actions.isdisjoint(command.split("-")) for command in COMMANDS
    )
    checks.append(
        (
            "LinkedIn publishing command",
            no_external_action,
            "absent" if no_external_action else "unsafe",
        )
    )

    failures: list[str] = []
    for name, passed, detail in checks:
        label = "OK" if passed else ("WARN" if name == "optional Claude CLI" else "FAIL")
        print(f"[{label}] {name}: {detail}")
        if not passed and name != "optional Claude CLI":
            failures.append(name)
    print("[OK] credential handling: values were not inspected or printed")
    return 1 if failures else 0


def command_draft(args: argparse.Namespace) -> int:
    strategy_input = getattr(args, "strategy_input", None)
    allow_model_egress = bool(getattr(args, "allow_model_egress", False))
    proof_manifest = getattr(args, "proof_manifest", None)
    fixture: dict[str, object] | None = None
    if args.dry_run:
        if strategy_input or allow_model_egress or proof_manifest:
            raise workflow.WorkflowError(
                "Fixture drafting does not accept strategy files, proof files, or model-egress consent."
            )
        fixture = workflow.load_fixture(topic=args.topic)
        items = workflow.prepare_research_items(fixture["research_items"])
        analysis_items, _combined = workflow.deduplicate_analysis_items(items, ())
        package_created_at = workflow.parse_published_at(str(fixture["as_of"]))
        analysis = workflow.analyse_research(
            analysis_items,
            topic=args.topic,
            as_of=package_created_at,
        )
        strategy_inputs = fixture.get("strategy_inputs")
        strategy_input_origin = "synthetic-fixture"
    else:
        package_created_at = None
        if not strategy_input:
            raise workflow.WorkflowError(
                "Live drafting requires --strategy-input with explicit reader and decision fields."
            )
        if not allow_model_egress:
            raise workflow.WorkflowError(
                "Live drafting requires --allow-model-egress before private text reaches the Writer."
            )
        if not args.db.is_file():
            raise workflow.WorkflowError(
                "Live drafting needs an existing private research ledger; run research first."
            )
        storage.initialise(args.db)
        strategy_inputs = workflow.load_strategy_inputs_file(strategy_input)
        # Apply the bounded query after boundary-safe topic matching, rather than
        # hiding an older match behind 200 unrelated newer rows or materialising
        # an unbounded ledger in memory.
        items = storage.list_research_items(
            args.db,
            topic_terms=(
                workflow.topic_prefilter_terms(args.topic) if args.topic else None
            ),
            evidence_origins=("private-import",),
        )
        if not items:
            raise workflow.WorkflowError(
                "Live drafting needs explicitly imported private research evidence; "
                "fixture and unverified rows are ineligible, so nothing was invented."
            )
        analysis = workflow.analyse_research(items, topic=args.topic)
        strategy_input_origin = "explicit-input"

    selected = analysis["pass_2"]["selected"]
    brief = workflow.build_strategy_brief(
        selected,
        strategy_inputs=strategy_inputs,
        strategy_input_origin=strategy_input_origin,
        goal=args.goal,
        output_format=args.output_format,
        week_slot=args.week_slot,
        strong_current_signal=args.strong_current_signal,
    )
    evidence = workflow.build_drafting_evidence(
        items,
        topic_slug=str(brief["topic_slug"]),
    )
    proof: workflow.LoadedProof | None = None
    if fixture is not None and brief["goal"] == "opportunity":
        proof = workflow.load_proof_manifest(
            workflow.DEFAULT_FIXTURE_PROOF,
            fixture_mode=True,
        )
    elif fixture is None and brief["goal"] == "opportunity":
        if proof_manifest is None:
            raise workflow.WorkflowError(
                "Live Opportunity drafting requires --proof-manifest before model egress."
            )
        proof = workflow.load_proof_manifest(proof_manifest)
    elif fixture is None and proof_manifest is not None:
        proof = workflow.load_proof_manifest(proof_manifest)
    if fixture is not None:
        candidate_sets = fixture.get("draft_candidates")
        if not isinstance(candidate_sets, dict):
            raise workflow.WorkflowError("Fixture needs goal-specific draft candidates.")
        raw_candidates = candidate_sets.get(str(brief["goal"]))
        if not isinstance(raw_candidates, list):
            raise workflow.WorkflowError(
                f"Fixture needs three {brief['goal']} draft candidates."
            )
        candidates = workflow.validate_draft_candidates(
            raw_candidates,
            brief=brief,
            evidence=evidence,
            proof=proof,
        )
        print(
            f"Fixture envelope validated: topic={fixture['topic']}; "
            f"research_items={len(fixture['research_items'])}."
        )
    else:
        candidates = workflow.invoke_writer(
            brief=brief,
            evidence=evidence,
            allow_model_egress=allow_model_egress,
            proof=proof,
        )
        print(
            f"Stored evidence selected for Writer: topic={brief['topic_slug']}; "
            f"sources={len(evidence)}."
        )
    if fixture is not None:
        fixture_scorecards = fixture.get("critic_scorecards")
        if not isinstance(fixture_scorecards, dict):
            raise workflow.WorkflowError("Fixture needs goal-specific Critic scorecards.")
        fixture_review = fixture_scorecards.get(str(brief["goal"]))
        if not isinstance(fixture_review, dict):
            raise workflow.WorkflowError(
                f"Fixture needs {brief['goal']} Critic scorecards."
            )
        initial_scores = fixture_review.get("initial")
        if not isinstance(initial_scores, list):
            raise workflow.WorkflowError("Fixture needs initial Critic scorecards.")
        revision_fixture = fixture_review.get("revision")
        score_responses: list[object] = [initial_scores]
        if isinstance(revision_fixture, dict):
            score_responses.append([revision_fixture.get("scorecard")])

        def score_provider(
            _candidates: object,
        ) -> list[dict[str, object]]:
            if not score_responses:
                raise workflow.WorkflowError("Fixture Critic was invoked too many times.")
            response = score_responses.pop(0)
            if not isinstance(response, list) or not all(
                isinstance(item, dict) for item in response
            ):
                raise workflow.WorkflowError("Fixture Critic scorecards are malformed.")
            return response

        def revision_provider(
            _candidate: object, _scorecard: object
        ) -> dict[str, object]:
            if not isinstance(revision_fixture, dict) or not isinstance(
                revision_fixture.get("candidate"), dict
            ):
                raise workflow.WorkflowError(
                    "Fixture needs a candidate for the one-revision band."
                )
            return dict(revision_fixture["candidate"])

    else:

        def score_provider(
            candidates_to_score: object,
        ) -> list[dict[str, object]]:
            if not isinstance(candidates_to_score, list):
                raise workflow.WorkflowError("Critic candidates must be a list.")
            return workflow.invoke_critic(
                candidates_to_score,
                brief,
                evidence,
                allow_model_egress=allow_model_egress,
                proof=proof,
            )

        def revision_provider(
            candidate_to_revise: object, scorecard: object
        ) -> dict[str, object]:
            if not isinstance(candidate_to_revise, dict) or not isinstance(
                scorecard, dict
            ):
                raise workflow.WorkflowError("Writer revision inputs are malformed.")
            return workflow.invoke_writer_revision(
                candidate_to_revise,
                brief,
                evidence,
                scorecard=scorecard,
                allow_model_egress=allow_model_egress,
                proof=proof,
            )

    review = workflow.run_critic_review(
        candidates,
        brief,
        evidence,
        score_provider,
        revision_provider,
        proof=proof,
    )
    candidates = review["candidates"]
    gate_results = workflow.evaluate_candidate_set_gates(
        candidates,
        brief=brief,
        evidence=evidence,
        proof=proof,
    )
    output_format = brief["output_format"] or "not-selected"
    route = " -> ".join(brief["narrative_route"])
    print(
        f"Strategy brief: goal={brief['goal']}; format={output_format}; "
        f"weekly_slot={brief['weekly_slot'] or 'not-selected'}; topic={brief['topic_slug']}."
    )
    print(f"Purpose: {brief['goal_purpose']} Route: {route}.")
    print(
        f"Reader: {brief['target_reader']} Problem: {brief['reader_problem']}"
    )
    print(f"Core hypothesis: {brief['core_hypothesis']}")
    print(f"Product decision: {brief['product_decision']}")
    print(f"Authority statement: {brief['authority_statement']}")
    print(f"Strategy input origin: {brief['strategy_input_origin']}")
    evidence_status = brief["evidence_status"]
    stale_status = (
        "not-evaluated"
        if evidence_status["stale"] is None
        else "yes"
        if evidence_status["stale"]
        else "no"
    )
    limitations = ",".join(evidence_status["limitations"]) or "none"
    print(
        "Evidence status: "
        f"source_quality={'sufficient' if evidence_status['source_quality_sufficient'] else 'insufficient'}; "
        f"body={'sufficient' if evidence_status['body_read_sufficient'] else 'insufficient'}; "
        f"recency={'sufficient' if evidence_status['recency_sufficient'] else 'insufficient'}; "
        f"stale={stale_status}; primary_sources={evidence_status['primary_source_count']}; "
        f"limitations={limitations}."
    )
    if brief["proof_required"]:
        print("Opportunity route: a validated local proof manifest was supplied; its path is private.")
    for index, candidate in enumerate(candidates, start=1):
        claim_ids = ",".join(candidate["claim_ids"])
        print(
            f"Candidate {index}: id={candidate['id']}; angle={candidate['angle']}; "
            f"claim_ids={claim_ids}."
        )
        print(candidate["text"])
    for scorecard in review["scorecards"]:
        axis_scores = ",".join(
            f"{axis}={scorecard[axis]}" for axis in workflow.CRITIC_AXES
        )
        print(
            f"Critic score: id={scorecard['candidate_id']}; {axis_scores}; "
            f"raw_total={scorecard['raw_total']}; "
            f"effective_total={scorecard['effective_total']}; "
            f"band={scorecard['band']}."
        )
    print(f"Critic ranking: {','.join(review['ranking'])}.")
    print(
        f"Score leader: {review['score_leader_id']}; "
        f"revision_count={review['revision_count']}."
    )
    for result in gate_results:
        gate_summary = ",".join(
            f"{name}={result['gates'][name]['status']}"
            for name in workflow.GATE_ORDER
        )
        reasons = ",".join(
            reason
            for name in workflow.GATE_ORDER
            for reason in result["gates"][name]["reason_codes"]
        )
        print(
            f"Gate result: id={result['candidate_id']}; {gate_summary}; "
            f"passes_required_gates={'yes' if result['passes_required_gates'] else 'no'}; "
            f"manual_fact_verification_required=yes; reasons={reasons}."
        )
    if not bool(getattr(args, "package", False)):
        print("Three draft candidates scored and gated. No winner was selected.")
        print(
            "A gate pass is not approval, recommendation, scheduling, or permission to publish."
        )
        print("No approval package was generated. No LinkedIn action was taken.")
        return 0
    generated = approval_package.write_human_approval_package(
        brief=brief,
        evidence=evidence,
        review=review,
        proof=proof,
        mode="fixture" if fixture is not None else "live",
        created_at=package_created_at,
    )
    manifest = generated["manifest"]
    package_path = generated["path"]
    if not isinstance(manifest, dict) or not isinstance(package_path, Path):
        raise workflow.WorkflowError("Approval package returned an invalid result.")
    try:
        display_path = package_path.relative_to(workflow.REPO_ROOT).as_posix()
    except ValueError as exc:
        raise workflow.WorkflowError(
            "Approval package path escaped the local repository."
        ) from exc
    print("Three final draft candidates were scored, gated, and packaged for human review.")
    print(
        "A gate pass alone is not approval, recommendation, scheduling, or permission to publish."
    )
    print(f"Content package: {display_path}")
    if manifest["mode"] == "live" and manifest["review_status"] == "READY_FOR_HUMAN_REVIEW":
        print(f"Performance package ID: {manifest['package_id']}")
    else:
        print("Performance recording: unavailable for this review-only or blocked package.")
    recommended_id = manifest["recommended_candidate_id"]
    if recommended_id is None and manifest["mode"] == "fixture":
        print("Recommendation: none; synthetic fixture output is review-only.")
    elif recommended_id is None:
        print("Recommendation: none; the package is blocked.")
    else:
        print(f"Recommended candidate for human review: {recommended_id}")
    print(f"Review status: {manifest['review_status']}.")
    print("Human approval status: NOT_APPROVED; manual fact verification required.")
    print("Publishing status: DISABLED. No LinkedIn action was taken.")
    return 0


def command_record_performance(args: argparse.Namespace) -> int:
    if not bool(args.confirm_manual_publication):
        raise workflow.WorkflowError(
            "Performance recording requires --confirm-manual-publication after a human publishes externally."
        )
    direct_fields = (
        "package_id",
        "candidate",
        "manually_published_at",
        "checkpoint",
        "channel",
        "observed_at",
        *storage.PERFORMANCE_METRICS,
    )
    recorded_at = workflow.now_iso()
    if args.csv is not None:
        if any(getattr(args, field, None) is not None for field in direct_fields):
            raise workflow.WorkflowError(
                "Use either --csv or direct performance fields, not both."
            )
        records = performance.load_csv_records(
            args.csv,
            recorded_at=recorded_at,
        )
    else:
        required = {
            "--package-id": args.package_id,
            "--candidate": args.candidate,
            "--manually-published-at": args.manually_published_at,
            "--checkpoint": args.checkpoint,
            "--channel": args.channel,
            "--observed-at": args.observed_at,
        }
        if any(value is None for value in required.values()):
            raise workflow.WorkflowError(
                "Direct performance recording requires --package-id, --candidate, "
                "--manually-published-at, --checkpoint, --channel, and --observed-at."
            )
        if args.replace and any(
            getattr(args, metric) is None for metric in storage.PERFORMANCE_METRICS
        ):
            raise workflow.WorkflowError(
                "--replace requires every performance metric for a complete correction."
            )
        context = performance.load_package_context(args.package_id, args.candidate)
        records = [
            performance.prepare_record(
                context,
                published_at=args.manually_published_at,
                checkpoint=args.checkpoint,
                channel=args.channel,
                observed_at=args.observed_at,
                metrics={
                    metric: (
                        getattr(args, metric)
                        if getattr(args, metric) is not None
                        else 0
                    )
                    for metric in storage.PERFORMANCE_METRICS
                },
                recorded_at=recorded_at,
            )
        ]
    initialise_paths(args.db)
    counts = storage.record_performance_many(
        args.db,
        records,
        replace=bool(args.replace),
    )
    print(
        "Performance checkpoints: "
        f"inserted={counts['inserted']}; replaced={counts['replaced']}; "
        f"unchanged={counts['unchanged']}."
    )
    print("Publishing remains disabled. No LinkedIn action was taken.")
    return 0


def command_weekly_review(args: argparse.Namespace) -> int:
    try:
        rows = storage.list_performance_readonly(args.db)
    except ValueError as exc:
        raise workflow.WorkflowError(
            "Weekly review needs a current private ledger; run init first."
        ) from exc
    as_of = args.as_of or workflow.now_iso()
    candidate_contexts: dict[tuple[str, str], dict[str, object]] = {}
    for package_id, candidate_id, fingerprint in (
        learning.winning_candidate_context_requests(rows, as_of=as_of)
    ):
        key = (package_id, candidate_id)
        try:
            candidate_contexts[key] = performance.load_package_learning_context(
                package_id,
                candidate_id,
                expected_fingerprint=fingerprint,
            )
        except workflow.WorkflowError:
            # Performance evidence remains usable when its private package is
            # unavailable, changed, or outside the bounded learning contract;
            # the report records an explicit context gap.
            continue
    generated = learning.write_weekly_review(
        rows,
        as_of=as_of,
        candidate_contexts=candidate_contexts,
    )
    report = generated.get("report")
    report_path = generated.get("path")
    if not isinstance(report, dict) or not isinstance(report_path, Path):
        raise workflow.WorkflowError("Weekly review returned an invalid result.")
    try:
        relative = report_path.relative_to(workflow.REPO_ROOT).as_posix()
    except ValueError as exc:
        raise workflow.WorkflowError(
            "Weekly review path escaped the private repository boundary."
        ) from exc
    basis = report.get("basis")
    calibration = report.get("rubric_calibration")
    safety = report.get("safety")
    if not all(isinstance(value, dict) for value in (basis, calibration, safety)):
        raise workflow.WorkflowError("Weekly review returned an invalid result.")
    recommendations = calibration.get("recommendations")  # type: ignore[union-attr]
    if not isinstance(recommendations, list):
        raise workflow.WorkflowError("Weekly review returned an invalid result.")
    print(f"Private weekly review: {relative}")
    print(
        "Learning evidence: "
        f"organic_72h={basis['canonical_posts']}; "  # type: ignore[index]
        f"late_72h_excluded={basis['late_organic_72h_observations_excluded']}; "  # type: ignore[index]
        f"organic_7d_followup={basis['organic_7d_followups']}; "  # type: ignore[index]
        f"paid_descriptive={basis['paid_descriptive_observations']}; "  # type: ignore[index]
        f"package_contexts={len(candidate_contexts)}."
    )
    print(
        f"Rubric review suggestions: {len(recommendations)}; rubric_mutated=no."
    )
    print("Publishing status: DISABLED. No LinkedIn action was taken.")
    return 0


def command_research(args: argparse.Namespace) -> int:
    if args.dry_run and args.input:
        raise workflow.WorkflowError("Choose either --dry-run or --input, not both.")
    if args.dry_run:
        fixture = workflow.load_fixture(topic=args.topic)
        items = workflow.prepare_research_items(fixture["research_items"])
        analysis_as_of = workflow.parse_published_at(str(fixture["as_of"]))
        mode = "fixture"
    elif args.input:
        items = workflow.load_research_file(args.input)
        analysis_as_of = None
        mode = "private import"
    else:
        raise workflow.WorkflowError(
            "Live research is not available yet; use --dry-run or --input."
        )
    recent_posts = (
        workflow.load_recent_posts_file(args.recent_posts) if args.recent_posts else None
    )
    initialise_paths(args.db)
    existing = (
        []
        if args.dry_run
        else storage.list_research_items(
            args.db, evidence_origins=("private-import",)
        )
    )
    # Analyse the current invocation's representation when it collides with a
    # stored URL/hash. Persistence still applies its own durable deduplication.
    current_unique, prospective = workflow.deduplicate_analysis_items(items, existing)
    analysis_candidates = current_unique if args.dry_run else prospective
    analysis: dict[str, object] | None = None
    if analysis_candidates:
        analysis = workflow.analyse_research(
            analysis_candidates,
            topic=args.topic,
            recent_posts=recent_posts,
            as_of=analysis_as_of,
        )

    inserted, duplicates = storage.insert_research_items(
        args.db,
        items,
        evidence_origin=("synthetic-fixture" if args.dry_run else "private-import"),
    )
    print(f"Research mode: {mode}; inserted={inserted}; duplicates={duplicates}.")
    if analysis:
        selected = analysis["pass_2"]["selected"]
        print(analysis["broad_discovery_note"])
        stale_status = (
            "not-evaluated"
            if selected["stale"] is None
            else "yes"
            if selected["stale"]
            else "no"
        )
        print(
            f"Selected cluster: {selected['slug']}; "
            f"source_quality={'sufficient' if selected['source_quality_sufficient'] else 'insufficient'}; "
            f"recency={'sufficient' if selected['recency_sufficient'] else 'insufficient'}; "
            f"stale={stale_status}."
        )
    else:
        print("No defensible research items were supplied; nothing was invented.")
    return 0


COMMANDS = {
    "init": command_init,
    "doctor": command_doctor,
    "privacy-check": command_privacy_check,
    "draft": command_draft,
    "research": command_research,
    "record-performance": command_record_performance,
    "weekly-review": command_weekly_review,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return COMMANDS[args.command](args)
    except sqlite3.Error:
        print("ERROR: private research database is unavailable or corrupt.", file=sys.stderr)
        return 2
    except (workflow.WorkflowError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
