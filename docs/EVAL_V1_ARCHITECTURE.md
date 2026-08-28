# LinkedIn Authority OS — V1 eval architecture

V1 is an additive layer over the working V0 runtime. It does not replace Scout, Topic Value, Resonance, Critic, deterministic gates, anti-slop, packaging, or performance learning.

## Product contracts

1. **Broad relevance + atomic value** — the topic must matter to the broader GenAI audience and each post must deliver one concrete atomic unit of reader value. Reusing a repository or broad theme is allowed when the atomic value is materially different.
2. **Why now + research trust** — momentum can nominate a topic, but factual use requires body-read non-social evidence. Social/community sources are discovery signals, not factual proof by themselves. Claim/body binding remains a shadow diagnostic until calibrated.
3. **Score integrity** — the five-axis Critic uses 25 behaviorally anchored levels. Every score needs an exact candidate excerpt and adjacent-boundary rationale. Python owns totals, caps, ranking, and bands.
4. **Solution plausibility** — the existing Resonance Critic records whether a proposed solution is coherent and reasonably implementable. V1 keeps this shadow-only.
5. **Reader attention** — the existing Resonance gate remains authoritative. V1 records explicit attribution so attention failure can be separated from source, scoring, or anti-slop failure.

## Runtime flow

```text
public web
  ↓
Momentum / Scout
  ↓
Topic Value
  ├─ research trust               [enforce]
  ├─ claim/body support           [shadow]
  └─ atomic-value novelty         [enforce against published V1 history]
  ↓
Writer → Narrative Editor
  ↓
Critic
  ├─ 25 behavioral anchors        [enforce]
  └─ one repeated score sample    [shadow, once per live command]
  ↓
existing deterministic gates
  ↓
existing anti-slop / regeneration
  ↓
existing Resonance
  ├─ reader attention             [existing gate; V1 attribution shadow]
  └─ solution plausibility        [shadow]
  ↓
review-ready artifact
  └─ bind atomic value to exact post SHA-256
  ↓
human publication outside the system
  ↓
record-performance --confirm-manual-publication
  └─ only now promote atomic value into published novelty history
  ↓
weekly-review
  └─ append V1 calibration snapshot for monthly product review
```

## Why novelty advances only after publication

A review-ready draft is not a published post. If review-ready drafts entered novelty history, a rejected or never-published idea could incorrectly block a later useful post. V1 therefore stores two separate private ledgers:

- `review-ready-atomic-bindings.jsonl` — atomic value + exact final artifact hash;
- `published-atomic-values.jsonl` — promoted only after a successful confirmed performance/publication record.

The promotion row includes package ID, candidate ID, artifact hash, topic-value ID, and source IDs. This binds the product decision to the business event that actually happened.

## Attribution and calibration

`data/private/v1-evals/decisions.jsonl` records the contract, stage, mode, status, reason, subject identity, and artifact hash for V1 decisions. It does not change release behavior.

Critic reproducibility is a **meta-eval**, not another product gate. Once per live command the existing Critic is called again with the same input. The score delta is recorded in shadow. A disagreement never blocks a post; it tells us whether the behavioral anchors are calibrated well enough.

The existing `weekly-review` command also appends `calibration-snapshots.jsonl`, combining:

- V1 PASS / FAIL / BLOCKED counts by contract;
- review-ready vs published atomic-value counts;
- published atomic values linked to organic 72h observations;
- medians for existing organic 72h performance metrics.

The snapshot explicitly records `rubric_mutated=false`. Monthly review can change a versioned contract deliberately; the runtime never rewrites its own rubric from engagement data.

## Reversibility

The canonical V0 rollback branch remains:

```text
baseline/v0-pre-eval-v1
91ee0b88b3371a6fce4eb08fc66951588f687997
```

V1 does not add a table to `authority_os.sqlite`, does not bump `SCHEMA_VERSION`, does not add a new CLI command, and does not add another model provider. All new state is under ignored `data/private/v1-evals/`.

Public `--dry-run` continues through the V0 path and does not install V1 overlays.

## Monthly product review

Review lagging outcomes against leading contract decisions. At minimum inspect distribution/impressions, saves, sends, substantive comments, profile activity, relevant followers, tool/repository clicks, and qualified inbound where available. Use the evidence to propose a versioned contract change; do not auto-tune thresholds or prompts from a single month.
