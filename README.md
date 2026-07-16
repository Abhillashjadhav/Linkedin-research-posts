# LinkedIn Authority OS v6

This repository preserves the evidence-backed role, voice, and rubric assets recovered for LinkedIn Authority OS v6 and provides a deliberately small research, analysis, strategic-routing, and voice-grounded drafting runtime.

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

`research --dry-run` validates and stores the visibly synthetic fixture in the ignored SQLite research ledger. Canonical URL and normalized body hash are independent uniqueness keys, so rerunning the command is safe. `draft --dry-run` analyses the fixture, builds the strategy brief, and emits exactly three unscored text candidates grounded in that selected cluster and the reconstructed voice guidance. It does not score, gate, approve, or package them.

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

Without both `--strategy-input` and `--allow-model-egress`, live/private drafting fails closed. Consent means that the selected strategy and evidence leave this machine for the configured Claude service through the local CLI; it does not mean inference is local. When consent is present, the Writer invocation has zero tools and no persisted model session. Fixture drafting remains suitable for offline tests.

Critic scoring and the single permitted revision are deferred to PR 8. Authority, proof, honesty, citation, and relevance gates are deferred to PR 9. Final packaging and human-approval status are deferred to PR 10.

Private JSON, JSONL, and NDJSON imports belong under ignored `data/private/`:

```sh
./bin/linkedin-os research --input data/private/research.jsonl
```

Each item needs a public HTTP(S) URL, title, publisher/source, ISO timestamp, and `primary|secondary|mixed` quality; body and author are optional. Live source collection remains unavailable; the consented Writer boundary only drafts from evidence already stored locally.

See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the implemented analysis path, [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md) for the current boundary, and [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md) for provenance.

Automatic LinkedIn publishing is absent and remains out of scope.
