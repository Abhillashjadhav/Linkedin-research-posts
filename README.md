# LinkedIn Authority OS v6

This repository preserves the evidence-backed role, voice, and rubric assets recovered for LinkedIn Authority OS v6 and provides a deliberately small research, analysis, strategic-routing, voice-grounded drafting, and Critic-scoring runtime.

The intended workflow boundary is Scout → Analyst → Writer → Critic → human approval. Historical Gmail ingestion, authenticated browser analytics, schedulers, messaging, and publishing-adjacent components are deliberately excluded.

## Offline quick start

Requires Python 3.11 or newer and no third-party packages.

```sh
make setup
make doctor
./bin/linkedin-os research --dry-run
./bin/linkedin-os draft --dry-run
make test
```

`research --dry-run` validates and stores the visibly synthetic fixture in the ignored SQLite research ledger. Canonical URL and normalized body hash are independent uniqueness keys, so rerunning the command is safe. `draft --dry-run` analyses the fixture, builds the strategy brief, emits exactly three text candidates grounded in that selected cluster and the reconstructed voice guidance, and applies deterministic fixture scorecards. Fixture execution is offline: it invokes neither Writer nor Critic models. It does not apply safety gates, approve a candidate, create a final package, or publish.

After ingestion, the command performs two-pass topic analysis: metadata-only clustering first, then strongest full-body interpretation. It prints broad-discovery, recency, and source-quality status without manufacturing missing evidence. Staleness is clearly `not-evaluated` unless `--recent-posts data/private/recent-posts.json` supplies a JSON list of prior post text.

Route a selected topic by strategic outcome and choose the output format separately:

```sh
./bin/linkedin-os draft --dry-run --goal reach --format text
./bin/linkedin-os draft --dry-run --goal authority --format carousel
./bin/linkedin-os draft --dry-run --goal opportunity --format artifact-demo
./bin/linkedin-os draft --dry-run --week-slot 3
./bin/linkedin-os draft --dry-run --week-slot 5 --goal opportunity --strong-current-signal
```

The default four-post weekly mix is one Reach, two Authority, and one Opportunity post. A fifth slot is rejected unless the user explicitly supplies a goal and confirms a strong current incident or launch. Goal never chooses format: omitting `--format` leaves it unselected.

## Voice-grounded drafting boundary

The Writer receives only the selected-cluster brief and evidence. The reconstructed voice guide and performance-pattern anchors calibrate style; they are not citable sources and cannot support a factual or ownership claim. Each of the three candidates contains exactly `id`, `angle`, `text`, and `claim_ids`, so factual claims remain structurally traceable to selected-cluster evidence. Candidate IDs must form one neutral sequence (`candidate-1` through `candidate-3`, or the equivalent goal-prefixed sequence) and cannot smuggle scoring, gate, approval, or ranking metadata into this stage.

Candidate length is enforced by strategic goal: Reach is 100–190 words, Authority is 190–300, and Opportunity is 180–300. `--format` remains downstream conversion metadata: all three candidates are plain text at this stage, even when a later format such as `carousel` is selected.

Drafting from the stored private ledger requires both an explicit private strategy file and explicit consent for model egress:

```json
{
  "target_reader": "AI product leaders",
  "reader_problem": "The concrete decision they cannot make yet.",
  "core_hypothesis": "The evidence-backed mechanism to explain.",
  "product_decision": "The falsifiable action the reader can take.",
  "authority_statement": "What the reader should remember the author for."
}
```

```sh
./bin/linkedin-os draft \
  --strategy-input data/private/strategy.json \
  --allow-model-egress
```

Without both `--strategy-input` and `--allow-model-egress`, live/private drafting fails closed. Consent means that the selected strategy and evidence leave this machine for the configured Claude service through the local CLI; it does not mean inference is local. When consent is present, Writer and score-only Critic invocations have zero tools and no persisted model session. If the bounded revision path is reached, the same consent covers one additional Writer invocation and its one Critic rescore; there is no recursive revision. Fixture drafting and scoring remain suitable for offline tests and never invoke a model.

## Critic scoring boundary

The Critic assigns an integer from 1 to 5 on exactly five axes: `hook_strength`, `middle_escalation`, `earned_closer`, `specificity_and_source_quality`, and `voice_fidelity`. Python validates the scorecard and calculates both its raw total and effective total. A hook score of 3 or below caps the effective total at 18, regardless of the raw total.

- 24–25: advance to the later safety-gate stage; this is not approval.
- 22–23: permit one light Writer revision of the score leader, followed by one rescore. One revision is the hard maximum.
- 21 or below: below the Critic bar for this run.

The runtime uses a deterministic **score leader**, never a winner or recommended candidate. Ties resolve by effective total, raw total, the five rubric axes in their documented order, and then candidate ID; the result does not depend on candidate input order. The Critic model receives a scoring-only prompt derived from the recovered rubric; the recovered authority, proof, honesty, citation, and relevance gates are deliberately excluded from that prompt. Those gates remain deferred to PR 9, while final package generation and human-approval status remain deferred to PR 10. A score cannot approve, schedule, or publish content.

Private JSON, JSONL, and NDJSON imports belong under ignored `data/private/`:

```sh
./bin/linkedin-os research --input data/private/research.jsonl
```

Each item needs a public HTTP(S) URL, title, publisher/source, ISO timestamp, and `primary|secondary|mixed` quality; body and author are optional. Live source collection remains unavailable; the consented Writer boundary only drafts from evidence already stored locally.

See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the implemented analysis path, [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md) for the current boundary, and [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md) for provenance.

Automatic LinkedIn publishing is absent and remains out of scope.
