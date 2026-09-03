# LinkedIn Authority OS — eval suite

Runs on `pm-verifier` (from `Abhillashjadhav/AI-PM-essential-skills`). Four layers,
each answering one question you cannot answer today.

| Layer | Question | Command |
|---|---|---|
| 1. Judge calibration | Is the Critic / Topic Value rating *right*? | `calibration/` |
| 2. Gate regression | Did I break a gate while editing code? | `faults/` |
| 3. Pipeline capability | Does every stage run, in order, with attribution? | `suite.json` |
| 4. Outcome correlation | Is 24/25 the right bar? | not built — needs ~30 published posts |

## Layers 2 and 3

```bash
python3 -m pip install --no-deps /path/to/AI-PM-essential-skills/pm-verifier
cd evals/linkedin-os
pm-verifier execute --project . --trials-out trials.executed.jsonl \
  --results-out results.json -- python3 adapter.py
pm-verifier report --results results.json --out report.md
pm-verifier inspect --results results.json --trials trials.executed.jsonl
```

Exit codes: `0=PASS`, `1=FAIL`, `2=BLOCKED`.

`adapter.py` reads one run directory (`surface-trace.jsonl` + `trace.json`) and
reports what happened. It never repairs or infers: absent evidence lands in
`missing_evidence` and returns BLOCKED rather than a false PASS.

### What each surface covers

**System** — the ten pipeline stages as ordered checkpoints: surface-scouting,
consolidation, topic-value, writer, narrative-editor, critic, deterministic-gates,
anti-slop, resonance, package. Gates cover presence, order, completion, no silent
loss, first-failure attribution, run identity, and topic/candidate continuity.

**Trajectory** — the agent-level view. `surface_scouting` records launched vs
returned vs observed, and every one of the seven scouts gets its own step carrying
`status`, `reason_code`, and `duration_ms`. This is what tells you *which* scout
failed and *why*, instead of only that four of seven came back.

**Outcome** — surface quorum, unclassified failures, orphan cluster signals,
Topic Value gate self-consistency, Critic anchor integrity, hook 5/5, the 24/25
bar, release status, and three safety gates: publishing stays disabled, nothing is
auto-approved, rejected prose never reaches the package.

There is no **memory** surface. LinkedIn OS makes no persistence promise, so
`state_contract` is deliberately absent rather than fabricated.

### Fault checks

`faults/specs.json` plants 22 named defects — scout silent drop, quorum breach,
uncoded failure, cluster miscount, orphan signal, Topic Value gate contradiction,
writer candidate count, Critic weaker than Writer, anchor break, lowered bar,
hook below bar, publishing enabled, auto-approval, prose leak, privacy leak,
stage failure, identity crosswire, continuity break, missing evidence, and more.

```bash
for n in $(python3 -c "import json;print(' '.join(json.load(open('faults/specs.json'))))"); do
  pm-verifier fault --project . --trials trials.executed.jsonl \
    --specs faults/specs.json --name "$n" --out trials.faulted.jsonl >/dev/null
  pm-verifier run --project . --trials trials.faulted.jsonl --out results.faulted.json >/dev/null 2>&1
  echo "$n exit=$?"   # 0 here means the suite MISSED the fault
done
```

Current state: 22 planted, 20 FAIL, 2 BLOCKED, 0 missed.

## Layer 1 — judge calibration

Two judges decide everything downstream: Topic Value picks the topic, the Critic
picks the post. Neither has ever been measured against you.

```bash
cd calibration
python3 make_goldens.py --campaigns ../../../campaigns \
  --out worksheet.jsonl --judge-out judge-labels.real.jsonl
# score worksheet.jsonl by hand, without looking at judge-labels.real.jsonl
pm-verifier calibrate --suite critic-suite.json \
  --goldens worksheet.jsonl --judgments judge-labels.real.jsonl --out calibration.json
```

`make_goldens.py` pulls real scored candidates out of the committed campaign
traces (48 today), so you label your own posts rather than invented ones. Score
them before you look at the judge's file.

Release thresholds in `critic-suite.json` / `topic-value-suite.json`: 30 golden
items minimum, agreement ≥ 0.80, Cohen's kappa ≥ 0.60, score MAE ≤ 0.75,
false-positive rate ≤ 0.10.

`demo/` contains a labeled synthetic worked pair showing the loop discriminating:
an aligned reviewer returns PASS (agreement 0.979, kappa 0.957, MAE 0.075), a
divergent one returns FAIL (0.667, 0.316, 0.479). It is a mechanism demo, not
evidence about the real Critic.

## Fixtures

`fixtures/daily-healthy` (7/7 surfaces) and `fixtures/daily-degraded` (5/7, with
`model-timeout` and `schema-violation` reason codes) are labeled synthetic. They
exist so the suite runs in CI without private data. Point `run_dir` at a real
private run directory to grade a real day.

## Prerequisite

Layer 3's scout attribution depends on the reason-code taxonomy added to
`momentum_surface_parallel.py`. Before that change every failure was
`UNAVAILABLE` with a free-text caveat and the aggregate trace carried only counts,
so "which scout failed and why" had no machine-readable answer.
