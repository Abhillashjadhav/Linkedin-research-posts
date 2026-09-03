
## Three-way calibration (current)

`calibration-set.json` holds 30 published posts: the top 15 and bottom 15 by
lift, in a fixed shuffled order, each with the text and its outcome label.

Three label sets get compared, not two:

| Pair | Question |
|---|---|
| outcome vs owner | does his taste predict what actually happened |
| outcome vs judge | does the Critic predict what actually happened |
| owner vs judge | is the Critic a stand-in for him |

`three_way.run()` returns Cohen's kappa, a Wilson interval, and separate
false-positive and false-negative rates for each pair, plus per-axis MAE where
both sides supplied 1-5 scores. It also names the calibration target: tune the
Critic to the owner only if his labels track outcomes at least as well as the
judge's do.

Kappa rather than raw agreement, because agreement flatters a lopsided set — a
judge that passes everything scores 50% here and knows nothing.

```bash
python3 run_critic.py

# Run 1 is the pre-declared primary result. Run 2 is an independent model
# sample used only for test-retest stability.
python3 -c "
import json, three_way
outcome = {x['item_id']: x['label'] for x in json.load(open('calibration-set.json'))}
owner, owner_scores = three_way.load_labels('owner-labels.jsonl')
judge, judge_scores = three_way.load_labels('judge-labels.run1.jsonl')
print(json.dumps(three_way.run(outcome, owner, judge,
      owner_scores=owner_scores, judge_scores=judge_scores), indent=2))"
```

The runner also writes `judge-labels.run2.jsonl` and a combined 60-row
`judge-labels.jsonl`. Do not load the combined file into `three_way.load_labels`:
that function intentionally supports single-run files, so duplicate item IDs
would otherwise use the last row.

Before every invocation, the runner audits the final assembled system and task
prompt. It prints the number of calibration posts found and requires exactly
one: the item under test. It also blocks on any `counter-anchor` marker or a
sealed outcome field paired with a calibration value. A failed check records
the item as `BLOCKED`; it never calls the model.

The repository has no genuinely out-of-sample published-post corpus. For this
calibration only, the runner therefore overrides the live post anchors with the
outcome-free rules in `data/voice/voice-guide.md`. This removes the direct
answer leak but makes voice fidelity less grounded than it is in production.
The original strategic brief and source bundle are also unavailable, so the
runner supplies a minimal valid authority brief, one context-only evidence row,
one angle and one matching claim ID. Because the live prompt says to evaluate
specificity only against supplied evidence, this is a pre-registered downward
bias on `specificity_and_source_quality`; report an excluding-specificity
variant beside the headline result.

The live judge is the score-only section of `.claude/agents/critic.md`, not
either JSON rubric file. Every result row records the SHA-256 of that file.
All binary gates, including proof, are `NOT_EVALUATED`: the score-only contract
does not run them. Classification reads the `band` returned by
`validate_critic_scorecards()`; it does not duplicate live thresholds.

Owner labels come from the blind scoring workbook: five axes at 1-5 plus a
would-publish answer. The outcome column is withheld while scoring, because a
score made while looking at the result is not an independent judgement.
