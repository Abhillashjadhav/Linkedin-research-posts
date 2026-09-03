
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
python3 -c "
import json, three_way
outcome = {x['item_id']: x['label'] for x in json.load(open('calibration-set.json'))}
owner, owner_scores = three_way.load_labels('owner-labels.jsonl')
judge, judge_scores = three_way.load_labels('judge-labels.jsonl')
print(json.dumps(three_way.run(outcome, owner, judge,
      owner_scores=owner_scores, judge_scores=judge_scores), indent=2))"
```

Owner labels come from the blind scoring workbook: five axes at 1-5 plus a
would-publish answer. The outcome column is withheld while scoring, because a
score made while looking at the result is not an independent judgement.
