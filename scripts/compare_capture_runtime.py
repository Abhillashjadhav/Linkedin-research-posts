#!/usr/bin/env python3
"""Instrument one isolated Authority OS draft run for private V0/V1 comparison."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType
from typing import Mapping, Sequence


def _candidate(candidate: object) -> dict[str, object]:
    return {
        "candidate_id": str(getattr(candidate, "candidate_id", "")),
        "angle": str(getattr(candidate, "angle", "")),
        "text": str(getattr(candidate, "text", "")),
        "axes": dict(getattr(candidate, "axes", {})),
        "raw_total": int(getattr(candidate, "raw_total", 0)),
        "effective_total": int(getattr(candidate, "effective_total", 0)),
        "band": str(getattr(candidate, "band", "")),
        "gates": dict(getattr(candidate, "gates", {})),
        "passes_required_gates": bool(getattr(candidate, "passes_required_gates", False)),
        "gate_reasons": list(getattr(candidate, "gate_reasons", ())),
    }


def _secure_write(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    path.write_text(json.dumps(dict(payload), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--label", choices=("v0", "v1"), required=True)
    parser.add_argument("--diagnostics", required=True)
    parser.add_argument("--frozen-research", required=True)
    parser.add_argument("--frozen-topic", required=True)
    parser.add_argument("draft_args", nargs=argparse.REMAINDER)
    return parser


_FROZEN_IDENTITY_FIELDS = (
    "canonical_url",
    "title",
    "body",
    "source",
    "author",
    "published_at",
    "source_quality",
    "content_hash",
)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65_536), b""):
                digest.update(chunk)
    except OSError as exc:
        raise SystemExit("frozen comparison research could not be read") from exc
    return digest.hexdigest()


def _record_identity(item: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(str(item.get(field, "")) for field in _FROZEN_IDENTITY_FIELDS)


def _record_digest(item: Mapping[str, object]) -> str:
    payload = dict(zip(_FROZEN_IDENTITY_FIELDS, _record_identity(item), strict=True))
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _install_frozen_evidence_routing(
    *, frozen_research: Path, frozen_topic: str
) -> dict[str, object]:
    """Treat one explicit frozen set as one topic, only in this observer process."""

    from authority_os import storage, workflow

    frozen_path = frozen_research.expanduser().resolve()
    input_sha256 = _file_sha256(frozen_path)
    try:
        frozen_items = workflow.load_research_file(frozen_path)
    except (ValueError, workflow.WorkflowError) as exc:
        raise SystemExit(f"invalid frozen comparison research: {exc}") from exc
    if not frozen_items:
        raise SystemExit("frozen comparison research must contain at least one record")

    expected_identities = {_record_identity(item) for item in frozen_items}
    if len(expected_identities) != len(frozen_items):
        raise SystemExit("frozen comparison research contains duplicate records")
    expected_by_url = {
        str(item["canonical_url"]): {
            "content_hash": str(item["content_hash"]),
            "record_sha256": _record_digest(item),
        }
        for item in frozen_items
    }
    if len(expected_by_url) != len(frozen_items):
        raise SystemExit("frozen comparison research contains duplicate URLs")

    original_list = storage.list_research_items
    original_build_evidence = workflow.build_drafting_evidence
    frozen_slug = workflow.slugify(frozen_topic)
    if not frozen_slug:
        raise SystemExit("frozen comparison topic must be non-blank")

    trace: dict[str, object] = {
        "input_sha256": input_sha256,
        "topic": frozen_topic,
        "topic_slug": frozen_slug,
        "record_count": len(frozen_items),
        "record_hashes": sorted(_record_digest(item) for item in frozen_items),
        "content_hashes": sorted(str(item["content_hash"]) for item in frozen_items),
        "writer_evidence": [],
        "input_unchanged": False,
    }

    def list_frozen_research(
        db_path: Path | str,
        *,
        limit: int = 200,
        topic: str | None = None,
        topic_terms: Sequence[str] | None = None,
        evidence_origins: Sequence[str] | None = None,
    ) -> list[dict[str, object]]:
        is_comparison_draft_read = (
            topic is None
            and topic_terms is not None
            and tuple(evidence_origins or ()) == ("private-import",)
        )
        if not is_comparison_draft_read:
            return original_list(
                db_path,
                limit=limit,
                topic=topic,
                topic_terms=topic_terms,
                evidence_origins=evidence_origins,
            )
        rows = original_list(
            db_path,
            limit=max(limit, len(frozen_items)),
            evidence_origins=("private-import",),
        )
        if {_record_identity(item) for item in rows} != expected_identities:
            raise workflow.WorkflowError(
                "Comparison ledger does not exactly match the frozen research set."
            )
        return rows

    def build_exact_evidence(
        items: Sequence[Mapping[str, object]], *, topic_slug: str, limit: int = 8
    ) -> list[dict[str, object]]:
        if {_record_identity(item) for item in items} != expected_identities:
            raise workflow.WorkflowError(
                "Comparison drafting input does not exactly match the frozen research set."
            )
        if len(frozen_items) > limit:
            raise workflow.WorkflowError(
                "Frozen comparison research exceeds the historical evidence limit."
            )
        evidence = original_build_evidence(items, topic_slug=topic_slug, limit=limit)
        if len(evidence) != len(frozen_items):
            raise workflow.WorkflowError(
                "Comparison evidence projection removed a frozen research record."
            )
        sources = {str(item.get("source", "")) for item in evidence}
        if sources != set(expected_by_url):
            raise workflow.WorkflowError(
                "Comparison evidence projection changed the frozen research set."
            )
        trace["writer_evidence"] = [
            {
                "id": str(item.get("id", "")),
                "canonical_url": str(item.get("source", "")),
                **expected_by_url[str(item.get("source", ""))],
            }
            for item in evidence
        ]
        return evidence

    storage.list_research_items = list_frozen_research  # type: ignore[assignment]
    workflow._theme_for = lambda _title: frozen_slug  # type: ignore[attr-defined,assignment]
    workflow.build_drafting_evidence = build_exact_evidence  # type: ignore[assignment]
    return trace


def _assert_frozen_research_unchanged(path: Path, trace: dict[str, object]) -> None:
    unchanged = _file_sha256(path.expanduser().resolve()) == trace["input_sha256"]
    trace["input_unchanged"] = unchanged
    if not unchanged:
        raise SystemExit("frozen comparison research changed during generation")


def _install_v0_codex_provider() -> ModuleType:
    """Load only the current Codex provider adapter against the frozen V0 package."""

    provider_path = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "authority_os"
        / "single_topic_codex.py"
    )
    module_name = "authority_os._comparison_v0_codex_provider"
    spec = importlib.util.spec_from_file_location(module_name, provider_path)
    if spec is None or spec.loader is None:
        raise SystemExit("V0 Codex provider adapter could not be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(module_name, None)
        raise
    install = getattr(module, "install", None)
    if not callable(install):
        raise SystemExit("V0 Codex provider adapter has no install hook")
    install()
    return module


def _lock_comparison_codex_runtime(*, include_v1_selection: bool) -> None:
    """Pin every comparison model stage to Sol/high with Fast mode disabled."""

    from authority_os import campaign, model_runtime

    def preferred(cls):
        config = model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")
        return campaign.StageModels(
            writer=config,
            narrative_editor=config,
            critic=config,
            artisanal_editor=config,
            comment_writer=config,
            comment_reviewer=config,
            artifact_editor=config,
            visual_qa=config,
        )

    campaign.StageModels.preferred = classmethod(preferred)  # type: ignore[method-assign]
    model_runtime.NON_WEB_TOOL_FEATURES = frozenset(
        {*model_runtime.NON_WEB_TOOL_FEATURES, "fast_mode"}
    )

    if include_v1_selection:
        from authority_os import resonance, topic_value

        def high_config(_runtime: str, _model: str, _reasoning: str):
            return model_runtime.ModelConfig("codex", "gpt-5.6-sol", "high")

        topic_value.ModelConfig = high_config  # type: ignore[assignment]
        resonance.ModelConfig = high_config  # type: ignore[assignment]


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    draft_args = list(args.draft_args)
    if draft_args and draft_args[0] == "--":
        draft_args = draft_args[1:]
    if not draft_args or draft_args[0] != "draft":
        raise SystemExit("comparison capture requires Authority OS draft arguments")

    frozen_research = Path(args.frozen_research)
    frozen_trace = _install_frozen_evidence_routing(
        frozen_research=frozen_research,
        frozen_topic=args.frozen_topic,
    )

    quality_optimizer = None
    if args.label == "v0":
        _install_v0_codex_provider()
    elif args.label == "v1":
        from authority_os import v1_gates
        v1_gates.install()
        from authority_os import v1_completion
        v1_completion.install()
        from authority_os import topic_value_id_contract
        topic_value_id_contract.install()
        from authority_os import v1_length_policy
        v1_length_policy.install()
        from authority_os import single_topic_codex
        single_topic_codex.install()
        from authority_os import human_readability
        human_readability.install()
        from authority_os import critic_anchor_retry
        critic_anchor_retry.install()
        from authority_os import actionable_diagnostics
        actionable_diagnostics.install()
        from authority_os import social_media_gate_policy
        social_media_gate_policy.install()
        from authority_os import v1_runtime_tuning
        v1_runtime_tuning.install()
        from authority_os import quality_optimizer as optimizer
        optimizer.install()
        quality_optimizer = optimizer

    _lock_comparison_codex_runtime(include_v1_selection=args.label == "v1")

    from authority_os import integrated_cli, quality_cli
    if quality_optimizer is not None:
        quality_optimizer.wire_integrated_dispatch(integrated_cli)

    cycles: list[dict[str, object]] = []
    feedback_by_cycle: dict[int, object] = {}
    original_rejection = quality_cli._render_rejection  # type: ignore[attr-defined]
    original_success = quality_cli._render_success  # type: ignore[attr-defined]
    original_feedback = quality_cli._quality_feedback  # type: ignore[attr-defined]

    def record_attempt(attempt: object, *, cycle: int, limit: int, outcome: str, accepted: Sequence[object] = ()) -> None:
        raw_candidates = getattr(attempt, "candidates", ())
        candidates = list(raw_candidates) if isinstance(raw_candidates, Sequence) and not isinstance(raw_candidates, (str, bytes)) else []
        cycles.append({
            "cycle": cycle,
            "limit": limit,
            "outcome": outcome,
            "accepted_candidate_ids": [str(getattr(item, "candidate_id", "")) for item in accepted],
            "candidates": [_candidate(item) for item in candidates],
        })

    def capture_rejection(attempt: object, cycle: int, limit: int) -> None:
        record_attempt(attempt, cycle=cycle, limit=limit, outcome="REJECTED")
        original_rejection(attempt, cycle, limit)

    def capture_success(attempt: object, accepted: Sequence[object], cycle: int, limit: int) -> None:
        record_attempt(attempt, cycle=cycle, limit=limit, outcome="ACCEPTED", accepted=accepted)
        original_success(attempt, accepted, cycle, limit)

    def capture_feedback(attempt: object, cycle: int) -> dict[str, object]:
        result = original_feedback(attempt, cycle)
        feedback_by_cycle[cycle] = dict(result)
        return result

    quality_cli._render_rejection = capture_rejection  # type: ignore[attr-defined,assignment]
    quality_cli._render_success = capture_success  # type: ignore[attr-defined,assignment]
    quality_cli._quality_feedback = capture_feedback  # type: ignore[attr-defined,assignment]

    exit_code = 2
    try:
        exit_code = int(integrated_cli.main(draft_args))
        return exit_code
    finally:
        for row in cycles:
            cycle = row.get("cycle")
            if isinstance(cycle, int) and cycle in feedback_by_cycle:
                row["feedback"] = feedback_by_cycle[cycle]
        _assert_frozen_research_unchanged(frozen_research, frozen_trace)
        _secure_write(Path(args.diagnostics).expanduser().resolve(), {
            "schema_version": 1,
            "label": args.label,
            "exit_code": exit_code,
            "cycles": cycles,
            "frozen_evidence": frozen_trace,
        })


if __name__ == "__main__":
    raise SystemExit(main())
