#!/usr/bin/env python3
"""Pre-registered analysis for the blind 30-post Critic calibration."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import asdict
from pathlib import Path

CALIBRATION_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(CALIBRATION_DIR))

import three_way  # noqa: E402


PRIMARY_RUN = 1
RETEST_RUN = 2
LIVE_THRESHOLD = 24
VARIANT_PROPORTIONAL_THRESHOLD = 19
FULL_SCORE_MAXIMUM = 25
VARIANT_SCORE_MAXIMUM = 20
EXPECTED_ITEMS = 30
LABELS = frozenset({"GOOD", "BAD"})
AXES = tuple(three_way.AXES)
VARIANTS = {
    "excluding_earned_closer": "earned_closer",
    "excluding_specificity_and_source_quality": "specificity_and_source_quality",
}

DEFAULT_CALIBRATION = CALIBRATION_DIR / "calibration-set.json"
DEFAULT_OWNER = CALIBRATION_DIR / "owner-labels.jsonl"
DEFAULT_RUN1 = CALIBRATION_DIR / "judge-labels.run1.jsonl"
DEFAULT_RUN2 = CALIBRATION_DIR / "judge-labels.run2.jsonl"
DEFAULT_RESULTS = CALIBRATION_DIR / "three-way-results.json"
DEFAULT_FINDINGS = CALIBRATION_DIR / "judge-calibration-findings.md"
COMBINED_JUDGE_NAME = "judge-labels.jsonl"


class AnalysisBlocked(RuntimeError):
    """Required calibration evidence is missing or contains BLOCKED rows."""


class AnalysisFailure(RuntimeError):
    """Calibration evidence exists but violates the pre-registered contract."""


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AnalysisBlocked(f"required input is missing: {path}") from exc
    except OSError as exc:
        raise AnalysisBlocked(f"required input is unreadable: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisFailure(f"invalid JSON in {path}") from exc


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise AnalysisBlocked(f"required input is missing: {path}") from exc
    except OSError as exc:
        raise AnalysisBlocked(f"required input is unreadable: {path}") from exc
    rows: list[dict[str, object]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AnalysisFailure(f"invalid JSONL at {path}:{number}") from exc
        if not isinstance(row, Mapping):
            raise AnalysisFailure(f"JSONL row is not an object at {path}:{number}")
        rows.append(dict(row))
    return rows


def _reject_combined_path(path: Path) -> None:
    if path.name == COMBINED_JUDGE_NAME:
        raise AnalysisFailure(
            "combined judge-labels.jsonl cannot be used as a run input"
        )


def _blocked_rows(rows: Sequence[Mapping[str, object]]) -> list[str]:
    blocked: list[str] = []
    for row in rows:
        if row.get("status") == "BLOCKED" or row.get("label") == "BLOCKED":
            blocked.append(
                f"{row.get('item_id', '?')}/run-{row.get('run', '?')}"
            )
    return blocked


def _validate_no_blocked(
    run1_rows: Sequence[Mapping[str, object]],
    run2_rows: Sequence[Mapping[str, object]],
) -> None:
    blocked = _blocked_rows([*run1_rows, *run2_rows])
    if blocked:
        raise AnalysisBlocked(
            f"judge input contains {len(blocked)} BLOCKED row(s): "
            + ", ".join(blocked)
        )


def _outcome_labels(path: Path) -> dict[str, str]:
    payload = _read_json(path)
    if not isinstance(payload, list) or len(payload) != EXPECTED_ITEMS:
        raise AnalysisFailure("calibration-set.json must contain exactly 30 rows")
    labels: dict[str, str] = {}
    for row in payload:
        if not isinstance(row, Mapping):
            raise AnalysisFailure("calibration rows must be objects")
        item_id = row.get("item_id")
        label = row.get("label")
        if not isinstance(item_id, str) or not item_id.strip() or label not in LABELS:
            raise AnalysisFailure("calibration rows need unique item_id and GOOD/BAD label")
        if item_id in labels:
            raise AnalysisFailure(f"duplicate calibration item_id: {item_id}")
        labels[item_id] = str(label)
    return labels


def _score_map(row: Mapping[str, object], *, source: str) -> dict[str, int]:
    raw = row.get("scores")
    if not isinstance(raw, Mapping):
        raise AnalysisFailure(f"{source} row needs scores")
    scores: dict[str, int] = {}
    for axis in AXES:
        value = raw.get(axis)
        if type(value) is not int or not 1 <= int(value) <= 5:
            raise AnalysisFailure(f"{source} axis {axis} must be an integer from 1 to 5")
        scores[axis] = int(value)
    return scores


def _owner_maps(
    rows: Sequence[Mapping[str, object]],
) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    if len(rows) != EXPECTED_ITEMS:
        raise AnalysisFailure("owner-labels.jsonl must contain exactly 30 rows")
    labels: dict[str, str] = {}
    scores: dict[str, dict[str, int]] = {}
    for row in rows:
        item_id = row.get("item_id")
        label = row.get("label")
        if not isinstance(item_id, str) or not item_id.strip() or label not in LABELS:
            raise AnalysisFailure("owner rows need unique item_id and GOOD/BAD label")
        if item_id in labels:
            raise AnalysisFailure(f"duplicate owner item_id: {item_id}")
        labels[item_id] = str(label)
        scores[item_id] = _score_map(row, source="owner")
    return labels, scores


def _judge_maps(
    rows: Sequence[Mapping[str, object]],
    *,
    expected_run: int,
) -> tuple[dict[str, str], dict[str, dict[str, int]], dict[str, int]]:
    if len(rows) != EXPECTED_ITEMS:
        raise AnalysisFailure(
            f"judge run {expected_run} must contain exactly 30 rows"
        )
    labels: dict[str, str] = {}
    scores: dict[str, dict[str, int]] = {}
    effective_totals: dict[str, int] = {}
    for row in rows:
        item_id = row.get("item_id")
        label = row.get("label")
        run = row.get("run")
        primary = row.get("primary")
        status = row.get("status")
        if run != expected_run:
            raise AnalysisFailure(
                f"judge run {expected_run} contains row for run {run}"
            )
        if primary is not (expected_run == PRIMARY_RUN):
            raise AnalysisFailure(
                f"judge run {expected_run} has an invalid primary declaration"
            )
        if status != "PASS":
            raise AnalysisFailure(
                f"judge run {expected_run} contains non-PASS row {item_id}"
            )
        if not isinstance(item_id, str) or not item_id.strip() or label not in LABELS:
            raise AnalysisFailure("judge rows need unique item_id and GOOD/BAD label")
        if item_id in labels:
            raise AnalysisFailure(
                f"duplicate judge item_id in run {expected_run}: {item_id}"
            )
        total = row.get("effective_total")
        if type(total) is not int or not 1 <= int(total) <= FULL_SCORE_MAXIMUM:
            raise AnalysisFailure(
                f"judge row {item_id} needs effective_total from 1 to 25"
            )
        labels[item_id] = str(label)
        scores[item_id] = _score_map(row, source=f"judge run {expected_run}")
        effective_totals[item_id] = int(total)
    return labels, scores, effective_totals


def _require_same_ids(reference: Mapping[str, object], **sources: Mapping[str, object]) -> None:
    expected = set(reference)
    for name, source in sources.items():
        missing = sorted(expected - set(source))
        extra = sorted(set(source) - expected)
        if missing or extra:
            raise AnalysisFailure(
                f"{name} item IDs differ; missing={missing}, extra={extra}"
            )


def _agreement_at_threshold(
    outcome: Mapping[str, str],
    totals: Mapping[str, int],
    threshold: int,
    *,
    pair: str,
) -> dict[str, object]:
    ids = sorted(outcome)
    predictions = ["GOOD" if totals[item_id] >= threshold else "BAD" for item_id in ids]
    result = three_way.compare(pair, [outcome[item_id] for item_id in ids], predictions)
    return asdict(result)


def _sweep(
    outcome: Mapping[str, str],
    totals: Mapping[str, int],
    *,
    maximum: int,
    pair_prefix: str,
) -> dict[str, object]:
    results = {
        threshold: _agreement_at_threshold(
            outcome,
            totals,
            threshold,
            pair=f"{pair_prefix}_threshold_{threshold}",
        )
        for threshold in range(1, maximum + 1)
    }
    maximum_kappa = max(float(result["kappa"]) for result in results.values())
    maximising = [
        threshold
        for threshold, result in results.items()
        if float(result["kappa"]) == maximum_kappa
    ]
    return {
        "maximum_kappa": maximum_kappa,
        "maximising_thresholds": maximising,
        "all_thresholds": {str(key): value for key, value in results.items()},
    }


def _test_retest(
    run1_labels: Mapping[str, str],
    run1_scores: Mapping[str, Mapping[str, int]],
    run2_labels: Mapping[str, str],
    run2_scores: Mapping[str, Mapping[str, int]],
) -> dict[str, object]:
    ids = sorted(run1_labels)
    differences = {
        axis: round(
            sum(abs(run1_scores[item_id][axis] - run2_scores[item_id][axis]) for item_id in ids)
            / len(ids),
            3,
        )
        for axis in AXES
    }
    flipped = [
        item_id for item_id in ids if run1_labels[item_id] != run2_labels[item_id]
    ]
    return {
        "per_axis_mean_absolute_difference": differences,
        "label_flip_count": len(flipped),
        "label_flip_rate": round(len(flipped) / len(ids), 3),
        "flipped_item_ids": flipped,
    }


def _closer_inversion(
    outcome: Mapping[str, str],
    judge_scores: Mapping[str, Mapping[str, int]],
) -> dict[str, object]:
    means: dict[str, float] = {}
    for label in ("GOOD", "BAD"):
        values = [
            judge_scores[item_id]["earned_closer"]
            for item_id, outcome_label in outcome.items()
            if outcome_label == label
        ]
        means[label] = round(sum(values) / len(values), 3)
    return {
        "critic_mean_outcome_good": means["GOOD"],
        "critic_mean_outcome_bad": means["BAD"],
        "owner_mean_outcome_good": 3.33,
        "owner_mean_outcome_bad": 3.73,
        "critic_runs_backwards": means["BAD"] > means["GOOD"],
    }


def _variant_results(
    outcome: Mapping[str, str],
    judge_scores: Mapping[str, Mapping[str, int]],
) -> dict[str, object]:
    output: dict[str, object] = {}
    for name, excluded_axis in VARIANTS.items():
        totals = {
            item_id: sum(
                value for axis, value in scores.items() if axis != excluded_axis
            )
            for item_id, scores in judge_scores.items()
        }
        sweep = _sweep(
            outcome,
            totals,
            maximum=VARIANT_SCORE_MAXIMUM,
            pair_prefix=name,
        )
        output[name] = {
            "excluded_axis": excluded_axis,
            "sum_rule": "raw sum of the remaining four axes; no hook cap",
            "score_maximum": VARIANT_SCORE_MAXIMUM,
            "proportional_live_threshold": VARIANT_PROPORTIONAL_THRESHOLD,
            "at_proportional_live_threshold": _agreement_at_threshold(
                outcome,
                totals,
                VARIANT_PROPORTIONAL_THRESHOLD,
                pair=f"{name}_proportional_threshold_19",
            ),
            "maximum_kappa": sweep["maximum_kappa"],
            "maximising_thresholds": sweep["maximising_thresholds"],
            "overfitted_to_n_30": True,
        }
    return output


def _agreement_map(result: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    agreements = result.get("agreements")
    if not isinstance(agreements, list):
        raise AnalysisFailure("three_way.run returned no agreements")
    output: dict[str, Mapping[str, object]] = {}
    for agreement in agreements:
        if not isinstance(agreement, Mapping):
            raise AnalysisFailure("three_way.run returned malformed agreement")
        output[str(agreement.get("pair"))] = agreement
    return output


def _judge_gate_statement(kappa: float) -> str:
    if kappa > 0.6:
        return "usable as a release gate under the stated policy"
    if kappa < 0.4:
        return "not usable as a release gate at any threshold under the stated policy"
    return "directional only; not established as a release gate"


def _owner_reproduction_statement(kappa: float) -> str:
    if kappa >= 0.6:
        return "The Critic substantially reproduces the owner's binary judgement."
    if kappa < 0.4:
        return "The Critic does not reproduce the owner's binary judgement."
    return "The Critic only partially reproduces the owner's binary judgement."


def _render_findings(result: Mapping[str, object]) -> str:
    agreements = _agreement_map(result)
    primary = agreements["outcome_vs_judge"]
    owner_judge = agreements["owner_vs_judge"]
    owner_outcome = agreements["outcome_vs_owner"]
    winners = result["winner_false_negatives"]
    retest = result["test_retest"]
    closer = result["closer_inversion"]
    threshold = result["effective_total_threshold_sweep"]
    variants = result["variants"]
    mae = result["score_mae"]
    largest = result["largest_owner_judge_mae_axes"]

    def interval(row: Mapping[str, object]) -> str:
        low, high = row["interval_95"]  # type: ignore[misc]
        return f"[{low:.3f}, {high:.3f}]"

    lines = [
        "# Critic calibration findings",
        "",
        "## Operational result first",
        "",
        (
            f"The primary Critic would drop **{winners['count']} of 15 known "
            f"winners** ({winners['rate']:.3f})."
        ),
        "",
        "Dropped winner item IDs: "
        + (", ".join(winners["item_ids"]) if winners["item_ids"] else "none"),
        "",
        "## Three-way agreement",
        "",
        "| Pair | Kappa | Wilson 95% interval* | False-positive rate | False-negative rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for pair, row in (
        ("outcome vs judge", primary),
        ("owner vs judge", owner_judge),
        ("outcome vs owner", owner_outcome),
    ):
        lines.append(
            f"| {pair} | {row['kappa']:.3f} | {interval(row)} | "
            f"{row['false_positive_rate']:.3f} | {row['false_negative_rate']:.3f} |"
        )
    lines.extend(
        [
            "",
            "*The Wilson interval is for observed agreement, matching `three_way.py`.",
            "",
            f"Outcome-vs-judge verdict: {_judge_gate_statement(float(primary['kappa']))}.",
            "",
            _owner_reproduction_statement(float(owner_judge["kappa"])),
            "",
            "## Owner-vs-judge axis error",
            "",
        ]
    )
    for axis in AXES:
        lines.append(f"- `{axis}` MAE: {mae[axis]:.3f}")
    lines.extend(
        [
            "",
            "Largest disagreement axis: " + ", ".join(f"`{axis}`" for axis in largest),
            "",
            "## Test-retest stability",
            "",
        ]
    )
    for axis in AXES:
        value = retest["per_axis_mean_absolute_difference"][axis]
        lines.append(f"- `{axis}` mean absolute difference: {value:.3f}")
    lines.extend(
        [
            "",
            f"Label flips: **{retest['label_flip_count']} of 30** "
            f"({retest['label_flip_rate']:.3f}).",
            "",
            "Flipped item IDs: "
            + (", ".join(retest["flipped_item_ids"]) if retest["flipped_item_ids"] else "none"),
            "",
            "Run 1 is the primary result. Run 2 is used only for test-retest stability.",
            "",
            "## Closer inversion",
            "",
            f"Critic mean `earned_closer`, outcome-GOOD: {closer['critic_mean_outcome_good']:.3f}",
            "",
            f"Critic mean `earned_closer`, outcome-BAD: {closer['critic_mean_outcome_bad']:.3f}",
            "",
            "Owner reference: 3.330 for outcome-GOOD and 3.730 for outcome-BAD.",
            "",
            (
                "The Critic also runs backwards, so this result is consistent with an axis-level inversion."
                if closer["critic_runs_backwards"]
                else "The Critic does not reproduce the owner's closer inversion."
            ),
            "",
            "## Effective-total threshold sweep",
            "",
            f"Live threshold 24 kappa: {threshold['at_live_threshold']['kappa']:.3f}",
            "",
            f"Maximum kappa: {threshold['maximum_kappa']:.3f}",
            "",
            "Kappa-maximising threshold(s): "
            + ", ".join(str(value) for value in threshold["maximising_thresholds"]),
            "",
            "The maximising threshold is exploratory and overfitted to this 30-item set.",
            "",
            "## Four-axis variants",
            "",
            "Each variant uses the raw sum of the remaining four axes with no hook cap. "
            "The proportional live threshold is 19/20. Both readouts are labelled "
            "overfitted to this 30-item set.",
            "",
        ]
    )
    for name in VARIANTS:
        row = variants[name]
        lines.extend(
            [
                f"### {name}",
                "",
                f"Kappa at 19/20: {row['at_proportional_live_threshold']['kappa']:.3f}",
                "",
                f"Maximum kappa: {row['maximum_kappa']:.3f}",
                "",
                "Kappa-maximising threshold(s): "
                + ", ".join(str(value) for value in row["maximising_thresholds"]),
                "",
            ]
        )
    lines.extend(
        [
            "## Calibration target",
            "",
            f"`{result['calibration_target']}`",
            "",
            str(result["target_reason"]),
            "",
            "## Limits",
            "",
            "- Thirty items is a direction, not a guarantee. Read the interval, not only the point estimate.",
            "- The middle band was excluded by design, so agreement will read higher here than on live drafts.",
            "- Labels come from lift, which is conversion at a given reach. This predicts conversion, never distribution.",
            "- Voice fidelity used the outcome-free voice guide, not the production anchors.",
            "- Specificity has a known downward bias because the original evidence was unavailable and a stand-in was supplied.",
            "",
        ]
    )
    return "\n".join(lines)


def analyze(
    calibration_path: Path,
    owner_path: Path,
    run1_path: Path,
    run2_path: Path,
    results_path: Path,
    findings_path: Path,
) -> dict[str, object]:
    _reject_combined_path(run1_path)
    _reject_combined_path(run2_path)

    run1_rows = _read_jsonl(run1_path)
    run2_rows = _read_jsonl(run2_path)
    _validate_no_blocked(run1_rows, run2_rows)

    outcome = _outcome_labels(calibration_path)
    owner, owner_scores = _owner_maps(_read_jsonl(owner_path))
    run1, run1_scores, run1_totals = _judge_maps(
        run1_rows, expected_run=PRIMARY_RUN
    )
    run2, run2_scores, _ = _judge_maps(run2_rows, expected_run=RETEST_RUN)
    _require_same_ids(
        outcome,
        owner=owner,
        run1=run1,
        run2=run2,
    )

    primary_result = three_way.run(
        outcome,
        owner,
        run1,
        owner_scores=owner_scores,
        judge_scores=run1_scores,
    )
    if primary_result.get("status") != "PASS" or primary_result.get("items") != 30:
        raise AnalysisFailure("primary three-way comparison did not return PASS for 30 items")

    score_mae = primary_result.get("score_mae")
    if not isinstance(score_mae, Mapping) or any(axis not in score_mae for axis in AXES):
        raise AnalysisFailure("primary comparison did not return complete per-axis MAE")
    largest_value = max(float(score_mae[axis]) for axis in AXES)
    largest_axes = [axis for axis in AXES if float(score_mae[axis]) == largest_value]

    live = _agreement_at_threshold(
        outcome,
        run1_totals,
        LIVE_THRESHOLD,
        pair="outcome_vs_judge_live_threshold_24",
    )
    threshold_sweep = _sweep(
        outcome,
        run1_totals,
        maximum=FULL_SCORE_MAXIMUM,
        pair_prefix="outcome_vs_judge_effective_total",
    )
    winners_dropped = sorted(
        item_id
        for item_id, label in outcome.items()
        if label == "GOOD" and run1[item_id] == "BAD"
    )

    result = {
        **primary_result,
        "analysis_protocol": {
            "primary_run": PRIMARY_RUN,
            "retest_run": RETEST_RUN,
            "run2_averaged_or_substituted": False,
            "combined_judge_file_loaded": False,
            "live_threshold": LIVE_THRESHOLD,
            "variant_rule": (
                "raw sum of remaining four axes, no hook cap; sweep thresholds 1-20 "
                "and report proportional threshold 19"
            ),
        },
        "largest_owner_judge_mae_axes": largest_axes,
        "largest_owner_judge_mae": largest_value,
        "test_retest": _test_retest(run1, run1_scores, run2, run2_scores),
        "closer_inversion": _closer_inversion(outcome, run1_scores),
        "effective_total_threshold_sweep": {
            "live_threshold": LIVE_THRESHOLD,
            "at_live_threshold": live,
            "maximum_kappa": threshold_sweep["maximum_kappa"],
            "maximising_thresholds": threshold_sweep["maximising_thresholds"],
            "maximum_is_overfitted_to_n_30": True,
        },
        "variants": _variant_results(outcome, run1_scores),
        "winner_false_negatives": {
            "known_winners": 15,
            "count": len(winners_dropped),
            "rate": round(len(winners_dropped) / 15, 3),
            "item_ids": winners_dropped,
        },
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    findings_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    findings_path.write_text(_render_findings(result), encoding="utf-8")
    return result


def parser() -> argparse.ArgumentParser:
    output = argparse.ArgumentParser(description=__doc__)
    output.add_argument("--calibration", type=Path, default=DEFAULT_CALIBRATION)
    output.add_argument("--owner", type=Path, default=DEFAULT_OWNER)
    output.add_argument("--run1", type=Path, default=DEFAULT_RUN1)
    output.add_argument("--run2", type=Path, default=DEFAULT_RUN2)
    output.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    output.add_argument("--findings", type=Path, default=DEFAULT_FINDINGS)
    return output


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        result = analyze(
            args.calibration,
            args.owner,
            args.run1,
            args.run2,
            args.results,
            args.findings,
        )
    except AnalysisBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2
    except (AnalysisFailure, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        f"Calibration analysis: {result['status']} "
        f"({result['items']} primary items)."
    )
    print(f"Results: {args.results}")
    print(f"Findings: {args.findings}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
