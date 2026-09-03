#!/usr/bin/env python3
"""Blind, two-sample Critic calibration over the 30 published posts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT / "src"))

from authority_os import campaign, model_runtime, workflow  # noqa: E402


CALIBRATION_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = CALIBRATION_DIR / "calibration-set.json"
DEFAULT_RUN1_OUTPUT = CALIBRATION_DIR / "judge-labels.run1.jsonl"
DEFAULT_RUN2_OUTPUT = CALIBRATION_DIR / "judge-labels.run2.jsonl"
DEFAULT_COMBINED_OUTPUT = CALIBRATION_DIR / "judge-labels.jsonl"
CALIBRATION_VOICE_PATH = REPO_ROOT / "data" / "voice" / "voice-guide.md"
CRITIC_RUBRIC_PATH = REPO_ROOT / ".claude" / "agents" / "critic.md"
FORBIDDEN_OUTCOME_FIELDS = frozenset(
    {"label", "lift", "impressions", "engagements", "rank_by_lift"}
)
JUDGE_ID = "critic-v1"
PRIMARY_RUN = 1
GOOD_BANDS = frozenset({"advance-to-gates", "one-light-revision"})


class PromptLeakError(ValueError):
    """The assembled judge prompt contains sealed calibration information."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _all_mapping_keys(value: object) -> set[str]:
    keys: set[str] = set()
    if isinstance(value, Mapping):
        for key, nested in value.items():
            keys.add(str(key))
            keys.update(_all_mapping_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.update(_all_mapping_keys(nested))
    return keys


def _blind_item(item: Mapping[str, object]) -> dict[str, str]:
    """Project away every sealed outcome field before prompt construction."""

    item_id = item.get("item_id")
    text = item.get("text")
    if not isinstance(item_id, str) or not item_id.strip():
        raise ValueError("Calibration item needs a non-blank item_id.")
    if not isinstance(text, str) or not text.strip():
        raise ValueError(f"Calibration item {item_id!r} needs non-blank text.")
    blind = {"item_id": item_id.strip(), "text": text.strip()}
    assert FORBIDDEN_OUTCOME_FIELDS.isdisjoint(_all_mapping_keys(blind))
    assert set(blind) == {"item_id", "text"}
    return blind


def _calibration_voice_guidance() -> dict[str, str]:
    """Use only outcome-free rules; the in-repo post examples overlap the set."""

    text = CALIBRATION_VOICE_PATH.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError("Calibration voice rules are empty.")
    return {
        "provenance": "measured-performance-anchors",
        "calibration_safe_voice_rules": text,
    }


def _stand_in_inputs(
    blind: Mapping[str, str],
) -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    """Supply the minimum valid contract inputs absent from the published set."""

    item_id = blind["item_id"]
    candidate = {
        "id": item_id,
        "angle": "published-post-calibration",
        "text": blind["text"],
        "claim_ids": ["calibration-context"],
    }
    brief = {
        "goal": "authority",
        "topic_slug": "published-linkedin-post",
        "goal_purpose": "Evaluate a previously published LinkedIn post.",
        "narrative_route": ["published post", "reader value"],
        "target_reader": "Senior product leaders and AI product managers.",
        "reader_problem": "Decide whether a published post deserves to advance.",
        "core_hypothesis": "The supplied post can be scored on the recovered Critic rubric.",
        "product_decision": "Use the Critic score only as the calibration prediction.",
        "authority_statement": "The author communicates practical product judgement.",
        "strategy_input_origin": "calibration-stand-in",
        "analysis": {
            "why_now": "The Critic is being measured against sealed published outcomes.",
            "dominant_take": "The published post text is the only original input supplied.",
            "missing_angle": "The original strategic brief and source bundle are unavailable.",
        },
    }
    evidence = [
        {
            "id": "calibration-context",
            "title": "Blind published-post calibration context",
            "claim": (
                "This item is a previously published LinkedIn post. Its original research "
                "evidence and strategic brief are not included in the calibration set."
            ),
            "source": (
                "https://github.com/Abhillashjadhav/Linkedin-research-posts/"
                "blob/main/evals/linkedin-os/calibration/calibration-set.json"
            ),
            "source_quality": "primary",
            "body_read": True,
        }
    ]
    prompt_inputs = {"candidate": candidate, "brief": brief, "evidence": evidence}
    assert FORBIDDEN_OUTCOME_FIELDS.isdisjoint(_all_mapping_keys(prompt_inputs))
    return candidate, brief, evidence


def _metadata_value_patterns(item: Mapping[str, object]) -> list[re.Pattern[str]]:
    """Match a sealed field paired with its value, not coincidental numbers."""

    patterns: list[re.Pattern[str]] = []
    for field in FORBIDDEN_OUTCOME_FIELDS:
        if field not in item:
            continue
        rendered = re.escape(str(item[field]))
        patterns.append(
            re.compile(
                rf"(?i)(?:\"{re.escape(field)}\"|\b{re.escape(field)}\b)"
                rf"\s*(?::|=|-)?\s*[\"']?{rendered}(?:[\"']|\b)"
            )
        )
    return patterns


def _audit_prompt(
    assembled_prompt: str,
    *,
    current: Mapping[str, object],
    calibration_items: Sequence[Mapping[str, object]],
) -> dict[str, object]:
    """Fail closed unless only the item under test appears in the final prompt."""

    current_id = str(current["item_id"])
    current_text = str(current["text"]).strip()
    current_needle = json.dumps(current_text)[1:-1]
    matches = [
        str(item["item_id"])
        for item in calibration_items
        if isinstance(item.get("text"), str)
        and str(item["text"]).strip()
        and json.dumps(str(item["text"]).strip())[1:-1] in assembled_prompt
    ]
    if matches != [current_id]:
        raise PromptLeakError(
            "assembled prompt calibration-post count is "
            f"{len(matches)} (expected 1: {current_id}); found={matches}"
        )
    current_occurrences = assembled_prompt.count(current_needle)
    if current_occurrences != 1:
        raise PromptLeakError(
            f"current calibration post occurs {current_occurrences} times (expected 1)"
        )
    if "counter-anchor" in assembled_prompt.casefold():
        raise PromptLeakError("assembled prompt contains counter-anchor outcome metadata")
    leaked_pairs: list[str] = []
    for item in calibration_items:
        for field in FORBIDDEN_OUTCOME_FIELDS:
            if field not in item:
                continue
            if any(
                pattern.search(assembled_prompt)
                for pattern in _metadata_value_patterns({field: item[field]})
            ):
                leaked_pairs.append(f"{item.get('item_id', '?')}:{field}")
    if leaked_pairs:
        raise PromptLeakError(
            "assembled prompt contains sealed field/value pairs: "
            + ", ".join(sorted(set(leaked_pairs)))
        )
    return {
        "calibration_posts_found": len(matches),
        "calibration_post_ids_found": matches,
        "current_post_occurrences": current_occurrences,
        "sealed_field_value_pairs_found": 0,
        "counter_anchor_found": False,
    }


def _unavailable_gates() -> dict[str, str]:
    return {
        "honesty": "NOT_EVALUATED",
        "citation": "NOT_EVALUATED",
        "proof": "NOT_EVALUATED",
        "relevance": "NOT_EVALUATED",
        "authority_conversion": "NOT_EVALUATED",
    }


def score_item(
    item: Mapping[str, object],
    *,
    calibration_items: Sequence[Mapping[str, object]],
    run: int,
    timeout: int,
) -> dict[str, object]:
    blind = _blind_item(item)
    item_id = blind["item_id"]
    try:
        candidate, brief, evidence = _stand_in_inputs(blind)
        role_prompt = workflow.critic_scoring_system_prompt()
        voice_guidance = _calibration_voice_guidance()
        task_prompt = workflow.build_critic_prompt(
            candidates=[candidate],
            brief=brief,
            evidence=evidence,
            voice_guidance=voice_guidance,
            proof=None,
        )
        assembled_prompt = f"{role_prompt}\n\n{task_prompt}"
        audit = _audit_prompt(
            assembled_prompt,
            current=item,
            calibration_items=calibration_items,
        )
        print(
            "Prompt leak check: "
            f"item={item_id} calibration_posts_found={audit['calibration_posts_found']} "
            "sealed_field_value_pairs_found=0 counter_anchor_found=false",
            flush=True,
        )
        result = model_runtime.invoke_structured(
            config=campaign.StageModels.preferred().critic,
            role_prompt=role_prompt,
            task_prompt=task_prompt,
            schema=workflow.CRITIC_SCORE_SCHEMA,
            timeout=timeout,
            web_search=False,
            stage_label=f"Calibration Critic {item_id} run {run}",
        )
        raw = result.get("scorecards")
        validated = workflow.validate_critic_scorecards(raw, [candidate])  # type: ignore[arg-type]
        if len(validated) != 1:
            raise workflow.WorkflowError("Critic did not return exactly one scorecard.")
        scorecard = validated[0]
        band = str(scorecard["band"])
        if band not in GOOD_BANDS | {"below-critic-bar"}:
            raise workflow.WorkflowError(f"Critic returned unknown band {band!r}.")
        label = "GOOD" if band in GOOD_BANDS else "BAD"
        verdict = {
            "advance-to-gates": "READY FOR HUMAN APPROVAL",
            "one-light-revision": "REVISE",
            "below-critic-bar": "DROP",
        }[band]
        return {
            "item_id": item_id,
            "judge_id": JUDGE_ID,
            "run": run,
            "primary": run == PRIMARY_RUN,
            "status": "PASS",
            "label": label,
            "band": band,
            "total": int(scorecard["effective_total"]),
            "effective_total": int(scorecard["effective_total"]),
            "raw_total": int(scorecard["raw_total"]),
            "hook_cap_applied": bool(scorecard["hook_cap_applied"]),
            "scores": {axis: int(scorecard[axis]) for axis in workflow.CRITIC_AXES},
            "gates": _unavailable_gates(),
            "verdict": verdict,
            "critic_rubric_sha256": _sha256(CRITIC_RUBRIC_PATH),
            "calibration_voice_sha256": _sha256(CALIBRATION_VOICE_PATH),
            "prompt_leak_check": audit,
        }
    except Exception as exc:  # Every failed judge attempt must remain visible.
        return {
            "item_id": item_id,
            "judge_id": JUDGE_ID,
            "run": run,
            "primary": run == PRIMARY_RUN,
            "status": "BLOCKED",
            "label": "BLOCKED",
            "reason": str(exc) or exc.__class__.__name__,
            "critic_rubric_sha256": (
                _sha256(CRITIC_RUBRIC_PATH) if CRITIC_RUBRIC_PATH.exists() else None
            ),
        }


def load_calibration(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or len(payload) != 30:
        raise ValueError("Calibration set must contain exactly 30 items.")
    ids: list[str] = []
    for item in payload:
        if not isinstance(item, Mapping):
            raise ValueError("Calibration set rows must be objects.")
        blind = _blind_item(item)
        ids.append(blind["item_id"])
    if len(ids) != len(set(ids)):
        raise ValueError("Calibration item IDs must be unique.")
    return [dict(item) for item in payload]


def _open_output(path: Path):  # type: ignore[no-untyped-def]
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w", encoding="utf-8")
    os.chmod(path, 0o600)
    return handle


def run(
    input_path: Path,
    run1_path: Path,
    run2_path: Path,
    combined_path: Path,
    *,
    timeout: int,
) -> int:
    items = load_calibration(input_path)
    orders = ((PRIMARY_RUN, items), (2, list(reversed(items))))
    rows: list[dict[str, object]] = []
    print("Calibration protocol: run 1 is primary; run 2 is an independent test-retest sample.")
    with (
        _open_output(run1_path) as run1_handle,
        _open_output(run2_path) as run2_handle,
        _open_output(combined_path) as combined_handle,
    ):
        per_run_handles = {1: run1_handle, 2: run2_handle}
        for run_number, ordered in orders:
            for index, item in enumerate(ordered, start=1):
                item_id = str(item["item_id"])
                print(f"Critic run {run_number}/2: {index}/30 {item_id}", flush=True)
                row = score_item(
                    item,
                    calibration_items=items,
                    run=run_number,
                    timeout=timeout,
                )
                rows.append(row)
                line = json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                per_run_handles[run_number].write(line)
                per_run_handles[run_number].flush()
                os.fsync(per_run_handles[run_number].fileno())
                combined_handle.write(line)
                combined_handle.flush()
                os.fsync(combined_handle.fileno())
    blocked = [row for row in rows if row.get("status") == "BLOCKED"]
    print(f"Run 1 labels: {run1_path}")
    print(f"Run 2 labels: {run2_path}")
    print(f"Combined 60-row record: {combined_path}")
    print(f"BLOCKED: {len(blocked)}")
    if blocked:
        print(
            "Blocked item IDs: "
            + ", ".join(f"{row['item_id']}/run-{row['run']}" for row in blocked)
        )
        return 2
    if len(rows) != 60:
        return 1
    return 0


def parser() -> argparse.ArgumentParser:
    out = argparse.ArgumentParser(description=__doc__)
    out.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    out.add_argument("--run1-output", type=Path, default=DEFAULT_RUN1_OUTPUT)
    out.add_argument("--run2-output", type=Path, default=DEFAULT_RUN2_OUTPUT)
    out.add_argument("--output", type=Path, default=DEFAULT_COMBINED_OUTPUT)
    out.add_argument("--timeout", type=int, default=300)
    return out


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.timeout < 1:
        raise SystemExit("--timeout must be positive")
    try:
        return run(
            args.input,
            args.run1_output,
            args.run2_output,
            args.output,
            timeout=args.timeout,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
