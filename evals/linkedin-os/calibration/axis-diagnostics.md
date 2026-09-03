# Critic rank and axis diagnostics

> Every threshold, axis subset, and apparent winner below was fitted on the same 30 items. These results are overfitted and cannot promote an axis or threshold without held-out confirmation.

## Rank check

Critic effective total vs lift: Spearman rho `-0.068128`, two-sided p `0.720558`.

Owner total vs lift: Spearman rho `0.426152`, two-sided p `0.018866`.

| Critic measure | Spearman rho | p-value |
|---|---:|---:|
| `hook_strength` | -0.076831 | 0.686553 |
| `middle_escalation` | -0.229961 | 0.221521 |
| `specificity_and_source_quality` | 0.260357 | 0.164669 |
| `voice_fidelity` | -0.041801 | 0.826399 |
| `earned_closer` | -0.112201 | 0.554985 |

Top-5: **2 of 5** are known top-15 posts; precision `0.400`.

Selected IDs: CAL-09, CAL-23, CAL-24, CAL-29, CAL-30

Top-10: **4 of 10** are known top-15 posts; precision `0.400`.

Selected IDs: CAL-09, CAL-23, CAL-24, CAL-29, CAL-30, CAL-02, CAL-08, CAL-21, CAL-27, CAL-04

Tie rule: descending effective_total, then fixed calibration-set order.

## Single axes

| Axis | Best fitted kappa | Threshold(s) | GOOD mean | BAD mean | Gap | Owner MAE |
|---|---:|---:|---:|---:|---:|---:|
| `hook_strength` | 0.067 | 5 | 4.200 | 4.333 | -0.133 | 0.900 |
| `middle_escalation` | 0.133 | 3 | 4.200 | 4.467 | -0.267 | 0.900 |
| `specificity_and_source_quality` | 0.067 | 2, 3 | 2.533 | 2.400 | +0.133 | 1.200 |
| `voice_fidelity` | 0.000 | 1, 2, 3 | 4.000 | 4.133 | -0.133 | 1.800 |
| `earned_closer` | 0.067 | 2 | 4.267 | 4.533 | -0.267 | 1.200 |

## Axis pairs and triples

| Axes | Best fitted kappa | Threshold(s) | GOOD mean | BAD mean | Gap | Owner MAE |
|---|---:|---:|---:|---:|---:|---:|
| `hook_strength+middle_escalation` | 0.067 | 5, 6 | 8.400 | 8.800 | -0.400 | 1.800 |
| `hook_strength+specificity_and_source_quality` | 0.000 | 2, 3, 4, 5, 6, 7, 8, 9, 10 | 6.733 | 6.733 | +0.000 | 1.100 |
| `hook_strength+voice_fidelity` | 0.067 | 10 | 8.200 | 8.467 | -0.267 | 2.567 |
| `hook_strength+earned_closer` | 0.067 | 4, 5, 10 | 8.467 | 8.867 | -0.400 | 2.033 |
| `middle_escalation+specificity_and_source_quality` | 0.133 | 5 | 6.733 | 6.867 | -0.133 | 1.233 |
| `middle_escalation+voice_fidelity` | 0.067 | 5, 6 | 8.200 | 8.600 | -0.400 | 2.633 |
| `middle_escalation+earned_closer` | 0.067 | 4, 5 | 8.467 | 9.000 | -0.533 | 2.100 |
| `specificity_and_source_quality+voice_fidelity` | 0.067 | 4 | 6.533 | 6.533 | +0.000 | 1.267 |
| `specificity_and_source_quality+earned_closer` | 0.067 | 4, 5 | 6.800 | 6.933 | -0.133 | 1.000 |
| `voice_fidelity+earned_closer` | 0.000 | 2, 3, 4, 5, 6, 7 | 8.267 | 8.667 | -0.400 | 2.733 |
| `hook_strength+middle_escalation+specificity_and_source_quality` | 0.133 | 8 | 10.933 | 11.200 | -0.267 | 1.667 |
| `hook_strength+middle_escalation+voice_fidelity` | 0.067 | 8, 9 | 12.400 | 12.933 | -0.533 | 3.400 |
| `hook_strength+middle_escalation+earned_closer` | 0.067 | 6, 7, 8 | 12.667 | 13.333 | -0.667 | 2.933 |
| `hook_strength+specificity_and_source_quality+voice_fidelity` | 0.067 | 12 | 10.733 | 10.867 | -0.133 | 2.100 |
| `hook_strength+specificity_and_source_quality+earned_closer` | 0.067 | 6, 7 | 11.000 | 11.267 | -0.267 | 1.633 |
| `hook_strength+voice_fidelity+earned_closer` | 0.067 | 7, 15 | 12.467 | 13.000 | -0.533 | 3.500 |
| `middle_escalation+specificity_and_source_quality+voice_fidelity` | 0.067 | 6, 7, 8, 9 | 10.733 | 11.000 | -0.267 | 2.033 |
| `middle_escalation+specificity_and_source_quality+earned_closer` | 0.133 | 7 | 11.000 | 11.400 | -0.400 | 1.633 |
| `middle_escalation+voice_fidelity+earned_closer` | 0.067 | 7, 8 | 12.467 | 13.133 | -0.667 | 3.633 |
| `specificity_and_source_quality+voice_fidelity+earned_closer` | 0.067 | 7, 8 | 10.800 | 11.067 | -0.267 | 2.133 |

## Composite comparison

All five axes: best fitted kappa `0.067` at threshold(s) 11, 12, 13, 14.

Excluding `earned_closer`: best fitted kappa `0.133` at threshold(s) 10.

Dropping `earned_closer` changes the best fitted kappa by `+0.066`.

Any tested single, pair, or triple beats all five: `true`.
