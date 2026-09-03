# Critic calibration findings

## Operational result first

The primary Critic would drop **11 of 15 known winners** (0.733).

Dropped winner item IDs: CAL-01, CAL-05, CAL-06, CAL-10, CAL-11, CAL-12, CAL-14, CAL-15, CAL-19, CAL-25, CAL-26

## Three-way agreement

| Pair | Kappa | Wilson 95% interval* | False-positive rate | False-negative rate |
|---|---:|---:|---:|---:|
| outcome vs judge | -0.067 | [0.302, 0.639] | 0.333 | 0.733 |
| owner vs judge | -0.067 | [0.219, 0.545] | 0.375 | 0.727 |
| outcome vs owner | 0.133 | [0.392, 0.726] | 0.667 | 0.200 |

*The Wilson interval is for observed agreement, matching `three_way.py`.

Outcome-vs-judge verdict: not usable as a release gate at any threshold under the stated policy.

The Critic does not reproduce the owner's binary judgement.

## Owner-vs-judge axis error

- `hook_strength` MAE: 0.900
- `middle_escalation` MAE: 0.900
- `specificity_and_source_quality` MAE: 1.200
- `voice_fidelity` MAE: 1.800
- `earned_closer` MAE: 1.200

Largest disagreement axis: `voice_fidelity`

## Test-retest stability

- `hook_strength` mean absolute difference: 0.167
- `middle_escalation` mean absolute difference: 0.033
- `specificity_and_source_quality` mean absolute difference: 0.333
- `voice_fidelity` mean absolute difference: 0.333
- `earned_closer` mean absolute difference: 0.167

Label flips: **5 of 30** (0.167).

Flipped item IDs: CAL-03, CAL-13, CAL-24, CAL-27, CAL-29

Run 1 is the primary result. Run 2 is used only for test-retest stability.

## Closer inversion

Critic mean `earned_closer`, outcome-GOOD: 4.267

Critic mean `earned_closer`, outcome-BAD: 4.533

Owner reference: 3.330 for outcome-GOOD and 3.730 for outcome-BAD.

The Critic also runs backwards, so this result is consistent with an axis-level inversion.

## Effective-total threshold sweep

Live threshold 24 kappa: 0.000

Maximum kappa: 0.067

Kappa-maximising threshold(s): 11, 12, 13, 14

The maximising threshold is exploratory and overfitted to this 30-item set.

## Four-axis variants

Each variant uses the raw sum of the remaining four axes with no hook cap. The proportional live threshold is 19/20. Both readouts are labelled overfitted to this 30-item set.

### excluding_earned_closer

Kappa at 19/20: 0.000

Maximum kappa: 0.133

Kappa-maximising threshold(s): 10

### excluding_specificity_and_source_quality

Kappa at 19/20: -0.200

Maximum kappa: 0.067

Kappa-maximising threshold(s): 9, 10

## Calibration target

`outcome`

neither predicts outcomes yet; outcomes are the only anchor that cannot drift

## Limits

- Thirty items is a direction, not a guarantee. Read the interval, not only the point estimate.
- The middle band was excluded by design, so agreement will read higher here than on live drafts.
- Labels come from lift, which is conversion at a given reach. This predicts conversion, never distribution.
- Voice fidelity used the outcome-free voice guide, not the production anchors.
- Specificity has a known downward bias because the original evidence was unavailable and a stand-in was supplied.
