"""Three-way calibration: outcome, owner, judge.

Calibrating the Critic against outcomes alone leaves the owner out, and
calibrating it against the owner alone assumes his taste predicts results. That
assumption has never been tested, so this measures all three edges of the
triangle and lets the numbers decide which target the Critic should be tuned to.

    outcome vs owner   does his taste predict what actually happened
    outcome vs judge   does the Critic predict what actually happened
    owner  vs judge    is the Critic a stand-in for him

Cohen's kappa is used rather than raw agreement because agreement flatters a
lopsided set: a judge that says PASS to everything scores 50% here and knows
nothing. Kappa removes the agreement that chance alone would produce.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

AXES = ("hook_strength", "middle_escalation", "specificity_and_source_quality",
        "voice_fidelity", "earned_closer")
LABELS = ("GOOD", "BAD")


@dataclass(frozen=True, slots=True)
class Agreement:
    pair: str
    n: int
    observed: float
    expected_by_chance: float
    kappa: float
    false_positive_rate: float
    false_negative_rate: float
    interval_95: tuple[float, float]
    verdict: str


def _wilson(hits: int, n: int) -> tuple[float, float]:
    """Wilson interval. Normal approximation breaks down at n=30."""
    if n == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    p = hits / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def _verdict(kappa: float) -> str:
    if kappa >= 0.8:
        return "strong"
    if kappa >= 0.6:
        return "usable as a release gate"
    if kappa >= 0.4:
        return "directional only, not a gate"
    return "no better than chance"


def compare(pair: str, left: Sequence[str], right: Sequence[str]) -> Agreement:
    """Left is treated as the reference when naming false positives."""
    if len(left) != len(right):
        raise ValueError(f"{pair}: label counts differ ({len(left)} vs {len(right)})")
    n = len(left)
    if n == 0:
        raise ValueError(f"{pair}: no overlapping items to compare")
    for series, name in ((left, "left"), (right, "right")):
        unknown = sorted(set(series) - set(LABELS))
        if unknown:
            raise ValueError(f"{pair}: {name} has labels outside GOOD/BAD: {unknown}")

    hits = sum(1 for i in range(n) if left[i] == right[i])
    observed = hits / n
    left_good = sum(1 for v in left if v == "GOOD") / n
    right_good = sum(1 for v in right if v == "GOOD") / n
    expected = left_good * right_good + (1 - left_good) * (1 - right_good)
    kappa = 0.0 if expected >= 1 else (observed - expected) / (1 - expected)

    actual_bad = sum(1 for v in left if v == "BAD")
    actual_good = n - actual_bad
    false_positives = sum(1 for i in range(n) if left[i] == "BAD" and right[i] == "GOOD")
    false_negatives = sum(1 for i in range(n) if left[i] == "GOOD" and right[i] == "BAD")
    return Agreement(
        pair=pair, n=n, observed=round(observed, 3),
        expected_by_chance=round(expected, 3), kappa=round(kappa, 3),
        false_positive_rate=round(false_positives / actual_bad, 3) if actual_bad else 0.0,
        false_negative_rate=round(false_negatives / actual_good, 3) if actual_good else 0.0,
        interval_95=tuple(round(v, 3) for v in _wilson(hits, n)),
        verdict=_verdict(kappa),
    )


def score_mae(left: Mapping[str, Mapping[str, int]],
              right: Mapping[str, Mapping[str, int]]) -> dict[str, float]:
    """Per-axis mean absolute error over the items both sides scored."""
    out: dict[str, float] = {}
    shared = sorted(set(left) & set(right))
    for axis in AXES:
        gaps = [abs(left[i][axis] - right[i][axis]) for i in shared
                if axis in left[i] and axis in right[i]]
        if gaps:
            out[axis] = round(sum(gaps) / len(gaps), 3)
    if out:
        out["overall"] = round(sum(out.values()) / len(out), 3)
    return out


def run(outcome: Mapping[str, str],
        owner: Mapping[str, str],
        judge: Mapping[str, str],
        *,
        owner_scores: Mapping[str, Mapping[str, int]] | None = None,
        judge_scores: Mapping[str, Mapping[str, int]] | None = None) -> dict[str, object]:
    """Compare the three label sets over the items all three cover."""
    shared = sorted(set(outcome) & set(owner) & set(judge))
    if not shared:
        return {"status": "BLOCKED", "reason": "no item is labelled by all three sources",
                "agreements": [], "score_mae": {}}
    pick = lambda src: [src[i] for i in shared]
    agreements = [
        compare("outcome_vs_owner", pick(outcome), pick(owner)),
        compare("outcome_vs_judge", pick(outcome), pick(judge)),
        compare("owner_vs_judge", pick(owner), pick(judge)),
    ]
    by_pair = {a.pair: a for a in agreements}
    owner_k = by_pair["outcome_vs_owner"].kappa
    judge_k = by_pair["outcome_vs_judge"].kappa
    if owner_k >= 0.6 and owner_k >= judge_k:
        target, why = "owner", "his labels predict outcomes at least as well as the judge, so tuning to him is faster and loses nothing"
    elif judge_k >= 0.6:
        target, why = "outcome", "the judge already tracks outcomes better than his stated taste does"
    else:
        target, why = "outcome", "neither predicts outcomes yet; outcomes are the only anchor that cannot drift"
    return {
        "status": "PASS",
        "items": len(shared),
        "agreements": [asdict(a) for a in agreements],
        "score_mae": (score_mae(owner_scores, judge_scores)
                      if owner_scores and judge_scores else {}),
        "calibration_target": target,
        "target_reason": why,
        "limitations": [
            f"{len(shared)} items is enough for a direction, not a guarantee; read the interval, not the point estimate.",
            "Labels come from lift, which is conversion at a given reach. A judge calibrated on it predicts conversion, never distribution.",
            "The middle band was excluded by design, so these are the clear cases and agreement will read higher than on live drafts.",
        ],
    }


def load_labels(path: Path) -> tuple[dict[str, str], dict[str, dict[str, int]]]:
    """Read a JSONL of {item_id, label, scores{...}} into labels and scores."""
    labels: dict[str, str] = {}
    scores: dict[str, dict[str, int]] = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        item = str(row["item_id"])
        labels[item] = str(row["label"])
        if isinstance(row.get("scores"), Mapping):
            scores[item] = {a: int(v) for a, v in row["scores"].items() if a in AXES}
    return labels, scores
