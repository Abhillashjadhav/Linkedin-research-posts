#!/usr/bin/env python3
"""Instrument one isolated Authority OS draft run for private V0/V1 comparison."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
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
    parser.add_argument("draft_args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    draft_args = list(args.draft_args)
    if draft_args and draft_args[0] == "--":
        draft_args = draft_args[1:]
    if not draft_args or draft_args[0] != "draft":
        raise SystemExit("comparison capture requires Authority OS draft arguments")

    quality_optimizer = None
    if args.label == "v1":
        from authority_os import v1_gates
        v1_gates.install()
        from authority_os import v1_completion
        v1_completion.install()
        from authority_os import topic_value_id_contract
        topic_value_id_contract.install()
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
        _secure_write(Path(args.diagnostics).expanduser().resolve(), {
            "schema_version": 1,
            "label": args.label,
            "exit_code": exit_code,
            "cycles": cycles,
        })


if __name__ == "__main__":
    raise SystemExit(main())
