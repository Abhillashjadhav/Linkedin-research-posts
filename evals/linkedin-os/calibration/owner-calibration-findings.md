# Owner calibration: what his 30 blind scores say

Source: `owner-labels.jsonl`, generated from the blind scoring workbook. Thirty
published posts, top-15 and bottom-15 by lift, scored on five axes 1-5 plus a
would-publish yes/no, with the outcome column sealed during scoring.

## The binary answer does not predict outcomes

    outcome vs owner (would_publish)
      n                 30
      raw agreement     0.567
      kappa             0.133      95% CI [0.392, 0.726] on agreement
      false positives   0.667      he would have published 10 of the 15 flops
      false negatives   0.200      he would have killed 3 of the 15 winners
      verdict           no better than chance

Read that as: the yes/no call is not a usable label source. Tuning a judge to
reproduce it would reproduce a coin flip.

## The graded scores do carry signal

Mean score by outcome class:

    axis                              GOOD   BAD    gap
    hook_strength                     3.80   3.47  +0.33
    middle_escalation                 3.80   3.60  +0.20
    specificity_and_source_quality    4.00   3.33  +0.67
    voice_fidelity                    2.87   2.07  +0.80
    earned_closer                     3.33   3.73  -0.40
    TOTAL /25                        17.80  16.20  +1.60

`earned_closer` runs backwards: posts that flopped scored *higher* on it. This
is the second independent confirmation that the closer axis is inverted, and it
is why the axis is a diagnostic in rubric v2 rather than a gate.

Best single threshold on the total:

    total /25 >= 16                   kappa 0.333
    total excluding closer /20 >= 14  kappa 0.533

Dropping one of five axes lifts kappa by 0.20. Two axes on their own match that:

    specificity_and_source_quality >= 4   kappa 0.533
    voice_fidelity >= 3                   kappa 0.533
    earned_closer  (any threshold)        kappa 0.000

## What this means for the Critic

`three_way.run()` picks the calibration target in code: owner only if his labels
track outcomes at least as well as the judge's. At kappa 0.133 they do not, so
unless the Critic scores below that, the target is **outcome**, not owner. His
scores stay in the loop as a second opinion and as the source of the voice
floor; they do not become the answer key.

Still missing: the judge's own labels on these same 30 items. Until the Critic
is run against `calibration-set.json`, only one edge of the triangle is measured.

## Limits

Thirty items is a direction, not a guarantee. The middle band was excluded by
design, so these are the clear cases and agreement will read higher here than on
live drafts. Labels come from lift, which is conversion at a given reach, so a
judge calibrated on it predicts conversion and never distribution.
