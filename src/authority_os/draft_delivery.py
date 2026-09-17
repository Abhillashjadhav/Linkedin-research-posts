"""Retain evaluated prose alongside the local dashboard, including rejected drafts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path

from . import best_effort, daily_cli, post_styles, v1_completion, workflow


def _folder(folder: Path | None = None) -> Path:
    return daily_cli._under_private(
        folder if folder is not None else best_effort.output_path().parent
    )


def load(folder: Path | None = None) -> dict[str, object]:
    folder = _folder(folder)
    payload = {"schema_version": 1, "results": []}
    for path in sorted(folder.glob("draft-candidates-cycle-*.json")):
        if path.is_symlink():
            raise workflow.WorkflowError("Candidate snapshot must not be a symlink.")
        saved = json.loads(path.read_text(encoding="utf-8"))
        payload["results"].extend(saved["results"])
        payload["post_style"] = saved.get("post_style", "standard")
    selection = folder / "draft-selection.json"
    if selection.exists():
        if selection.is_symlink():
            raise workflow.WorkflowError("Candidate selection must not be a symlink.")
        payload["selection"] = json.loads(selection.read_text(encoding="utf-8"))
        for row in payload["results"]:
            selected = payload["selection"]
            row["shortlisted"] = bool(selected["shortlisted"]
                and row["cycle"] == selected["cycle"]
                and row["text_sha256"] == selected["text_sha256"])
    return payload


def _markdown(payload: dict[str, object]) -> str:
    sections = ["# Saved candidate posts", "All scores belong to the exact text below."]
    for row in payload["results"]:
        selected = " — SHORTLISTED" if row.get("shortlisted") else ""
        sections.append(
            f"## Cycle {row['cycle']} · {row['candidate_id']}{selected}\n\n"
            f"Total: {row['effective_total']}/25 · Hook: "
            f"{row['axes'].get('hook_strength', 'not evaluated')}/5 "
            f"({row['hook_verdict']})\n\n{row['candidate']['text']}"
        )
    return "\n\n".join(sections) + "\n"


def retain(attempt: object, *, cycle: int, post_style: str = "standard") -> None:
    payload = {"schema_version": 1, "run_id": v1_completion.current_run_id(),
               "post_style": post_style}
    rows = []
    for candidate in attempt.candidates:
        axes = dict(candidate.axes)
        rows.append({
            "cycle": cycle,
            "candidate_id": candidate.candidate_id,
            "candidate": {"id": candidate.candidate_id, "angle": candidate.angle,
                          "text": candidate.text},
            "text_sha256": hashlib.sha256(candidate.text.encode("utf-8")).hexdigest(),
            "axes": axes,
            "effective_total": candidate.effective_total,
            "hook_verdict": post_styles.hook_verdict(axes.get("hook_strength")),
            "gates": dict(candidate.gates),
            "advisories": list(candidate.gate_reasons),
            "shortlisted": False,
        })
    payload["results"] = rows
    folder = _folder()
    daily_cli.write_private_json(folder / f"draft-candidates-cycle-{cycle}.json", payload)
    daily_cli.write_private_text(folder / f"candidates-cycle-{cycle}.md", _markdown(payload))


def select(candidate: object, *, cycle: int, shortlisted: bool = True) -> Path:
    payload = load()
    digest = hashlib.sha256(candidate.text.encode("utf-8")).hexdigest()
    for row in payload["results"]:
        row["shortlisted"] = bool(
            shortlisted and row["cycle"] == cycle and row["text_sha256"] == digest
        )
    selection = {
        "candidate_id": candidate.candidate_id, "cycle": cycle,
        "text_sha256": digest, "shortlisted": shortlisted,
    }
    folder = _folder()
    daily_cli.write_private_json(folder / "draft-selection.json", selection)
    daily_cli.write_private_text(folder / "all-candidates.md", _markdown(payload))
    name = "shortlisted-post.md" if shortlisted else "best-available-post.md"
    return daily_cli.write_private_text(folder / name, candidate.text + "\n")


def attach(folder: Path, dashboard: dict[str, object]) -> None:
    """Embed the retained exact versions; hashes in the decision ledger aren't prose."""
    payload = load(folder)
    weekly_path = _folder(folder) / "weekly-plan.json"
    if weekly_path.is_file() and not weekly_path.is_symlink():
        dashboard["weekly_plan"] = json.loads(weekly_path.read_text(encoding="utf-8"))
    if payload["results"]:
        dashboard["results"] = payload["results"]
        dashboard["post_style"] = payload.get("post_style", "standard")
        if isinstance(payload.get("selection"), Mapping):
            dashboard["selection"] = payload["selection"]
