# LinkedIn Authority OS v6

This repository preserves the evidence-backed role, voice, and rubric assets recovered for LinkedIn Authority OS v6 and provides a deliberately small research, analysis, strategic-routing, voice-grounded drafting, Critic-scoring, deterministic safety-gate, local human-review-package, and manual performance-recording runtime.

The intended workflow boundary is Scout → Analyst → Writer → Critic → human approval. Historical Gmail ingestion, authenticated browser analytics, schedulers, messaging, and publishing-adjacent components are deliberately excluded.

## Offline quick start

Requires Python 3.11 or newer and no third-party packages.

```sh
make setup
make doctor
./bin/linkedin-os research --dry-run
./bin/linkedin-os draft --dry-run
./bin/linkedin-os draft --dry-run --package
make test
```

`research --dry-run` validates and stores the visibly synthetic fixture in the ignored SQLite research ledger. Every row retains `synthetic-fixture`, `private-import`, or quarantined `legacy-unverified` provenance. Live drafting reads only explicitly private-imported rows, so fixture research cannot become a live recommendation. An exact private re-import can promote the same stored URL/body pair; a fixture import can never demote private evidence. Canonical URL and normalized body hash remain independent uniqueness keys, so rerunning the command is safe. `draft --dry-run` analyses the fixture, builds the strategy brief, emits exactly three text candidates, applies deterministic fixture scorecards, and evaluates the five local gates without writing files. Fixture execution is offline: it invokes neither Writer nor Critic models. Add the explicit `--package` flag to create one ignored, review-only local package. Synthetic data can exercise eligibility, but fixture packages never recommend a candidate, record approval, or publish.

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

The Writer receives only the selected-cluster brief and evidence. Opportunity work requires the public-safe projection of one validated proof manifest; Reach and Authority may use one when a real incident or ownership sentence needs exact attestation. The projection contains only proof ID, type, public claim, and exact personal/ownership attestations. The local artifact path and contents never enter a prompt or output. The reconstructed voice guide and performance-pattern anchors calibrate style; they are not citable sources and cannot support a factual or ownership claim. Each of the three candidates contains exactly `id`, `angle`, `text`, and `claim_ids`, so factual claims remain structurally traceable. A proof ID is additive and cannot replace a research evidence ID. Candidate IDs must form one neutral sequence (`candidate-1` through `candidate-3`, or the equivalent goal-prefixed sequence) and cannot smuggle scoring, gate, approval, or ranking metadata into this stage.

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

Live Opportunity drafting additionally requires a private manifest and a distinct, non-empty local artifact, both under ignored `data/private/`. `artifact_path` is relative to the manifest. Reach and Authority accept the same optional manifest when exact public-safe proof or attestation text is needed. Descriptor-anchored validation rejects symlinks, traversal, directories, empty files, self-referential manifests, and paths outside that directory; artifact contents are never read.

```json
{
  "schema_version": 1,
  "proof_id": "proof-evaluation-record",
  "proof_type": "evaluation-result",
  "artifact_path": "evaluation-record.pdf",
  "public_claim": "A documented evaluation record exists for this workflow.",
  "attested_personal_sentences": []
}
```

```sh
./bin/linkedin-os draft \
  --goal opportunity \
  --strategy-input data/private/strategy.json \
  --proof-manifest data/private/proof.json \
  --allow-model-egress
```

Without both `--strategy-input` and `--allow-model-egress`, live/private drafting fails closed. Consent means that the selected strategy, evidence, and any supplied public proof claim or attestation text leave this machine for the configured Claude service through the local CLI; it does not mean inference is local. Local proof paths and artifact contents never cross that boundary. When consent is present, Writer and score-only Critic invocations have zero tools and no persisted model session. If the bounded revision path is reached, the same consent covers one additional Writer invocation and its one Critic rescore; there is no recursive revision. Fixture drafting and scoring remain suitable for offline tests and never invoke a model.

## Critic scoring boundary

The Critic assigns an integer from 1 to 5 on exactly five axes: `hook_strength`, `middle_escalation`, `earned_closer`, `specificity_and_source_quality`, and `voice_fidelity`. Python validates the scorecard and calculates both its raw total and effective total. A hook score of 3 or below caps the effective total at 18, regardless of the raw total.

- 24–25: advance to the local safety gates; this is not approval.
- 22–23: permit one light Writer revision of the score leader, followed by one rescore. One revision is the hard maximum.
- 21 or below: below the Critic bar for this run.

The runtime uses a deterministic **score leader**, never a winner or recommended candidate. Ties resolve by effective total, raw total, the five rubric axes in their documented order, and then candidate ID; the result does not depend on candidate input order. The Critic model receives a scoring-only prompt derived from the recovered rubric. Binary gates are deliberately excluded from that model prompt and applied locally afterward. A score cannot approve, schedule, or publish content.

## Authority and safety gates

Every final candidate is evaluated independently, without a model, in this fixed order:

- `authority_conversion` — the supplied authority statement and product decision must be materially reflected;
- `proof` — `NOT_REQUIRED` for Reach and Authority; Opportunity requires the exact validated `proof-*` ID and public claim;
- `honesty` — rejects unsupported personal/ownership statements, malformed direct quotations, title-only claims, concrete untraceable incidents, unsupported source references, and unsupported high-risk factual markers;
- `citation` — requires known body-read research evidence, rejects Reddit/Hacker News-only factual support, and checks that numbers, named factual markers, attributed quotations, directional relationships, and URL/domain references coexist with matching support in one cited claim rather than being laundered across sources; and
- `relevance` — requires one recovered target-audience family and material reader-problem overlap.

Factual matching preserves clause-level polarity, ordered associations, structurally named entities, and the exact canonical query of query-addressed citations. A closed set of simple acquisition, hiring, and ownership statements is canonicalised across active and passive voice so equivalent wording passes while reversed actors do not. Source queries stay local and are still removed from model prompts. A bare sentence-leading Titlecase subject is linguistically ambiguous, so the gate fails closed unless it has high-confidence entity syntax or belongs to the small audited generic-discourse vocabulary used by this product. These bounded heuristics are intentionally conservative, not natural-language proof. Each gate returns only `PASS`, `FAIL`, or `NOT_REQUIRED` plus static reason codes. `passes_required_gates` alone is not approval or a recommendation. Structural traceability cannot prove truth, so `manual_fact_verification_required` is always true.

## Human-review package

Package generation is an explicit local side effect:

```sh
./bin/linkedin-os draft --dry-run --package
```

A live candidate is eligible only when its final Critic band is `advance-to-gates` **and** every required local gate passes. Eligible candidates retain the existing deterministic Critic order; the first is recommended for human review. A lower-ranked candidate may therefore be recommended when a higher-ranked candidate fails a gate. If none qualify, a complete `BLOCKED` package is still written so the failure is inspectable. A recommendation is not a winner, approval, schedule, or publishing instruction.

Fixture packages are always `FIXTURE_REVIEW_ONLY` and suppress the recommendation even when mechanical eligibility exists. Every manifest keeps `human_approval_status` at `NOT_APPROVED`, `publishing_status` at `DISABLED`, and `manual_fact_verification_required` at `true`.

Packages live under ignored `outputs/YYYY-MM-DD/<topic-slug>[-N]/` and contain exactly:

- `manifest.json` — schema, provenance, statuses, inventory, and optional live recommendation;
- `brief.md` — the selected strategic brief and evidence limitations;
- `candidates.md` — all three final candidates and their claim IDs;
- `evaluation.json` — Critic scores/ranking, revision metadata, gate results, and eligibility;
- `sources.md` — query-free public source metadata and optional public-safe proof only; and
- `final-package.md` — the recommendation or blocked/fixture explanation plus a human verification checklist.

The runtime atomically reserves a new topic directory under a per-date lock, renders all six files in a private hidden directory, and publishes each completed file with a no-clobber hard link. `manifest.json` is published last and is the commit marker. Existing entries are never replaced; suffixes preserve prior packages even when another local writer claims a name concurrently. Directories use mode `0700` and files `0600`. Raw evidence bodies/claims, source queries, proof paths and artifact contents are excluded. A hidden `.stage-*` directory, or a topic directory without `manifest.json`, is incomplete internal state and must never be consumed as a package.

## Manual performance recording

After a human independently verifies, approves, and publishes an eligible live candidate, record a private checkpoint with the package ID printed by `draft --package`:

```sh
./bin/linkedin-os record-performance \
  --package-id 2026-07-16-agent-reliability \
  --candidate candidate-1 \
  --manually-published-at 2026-07-16T09:00:00+05:30 \
  --checkpoint 24h --channel organic \
  --observed-at 2026-07-17T09:15:00+05:30 \
  --impressions 1000 --profile-visits 30 --relevant-followers 8 \
  --saves 12 --sends 5 --reposts 2 \
  --confirm-manual-publication
```

The command accepts only a committed `live` package in `READY_FOR_HUMAN_REVIEW` state and an explicitly named eligible candidate. It does not infer the candidate from the recommendation. The package remains byte-for-byte unchanged with `human_approval_status=NOT_APPROVED` and `publishing_status=DISABLED`; the timestamp and confirmation flag assert that a separate human-controlled publication already happened. Publication cannot predate package creation.

Checkpoints are `2h`, `24h`, `72h`, and optional `7d`. Their observation windows are `[2h,24h)`, `[24h,72h)`, `[72h,7d)`, and `[7d,∞)`. All timestamps must be timezone-aware and use whole-second precision. Paid and organic rows have separate keys and are never combined; a missing paid row means unobserved, not zero. The ledger keeps impressions, non-follower reach, external comments, reactions, reposts, saves, sends, profile visits, relevant followers, GitHub/tool clicks, and recruiter, founder/advisor, and speaking/podcast inbound counts.

Omitted direct-entry metrics default to zero only for a new checkpoint. A differing existing checkpoint fails unless `--replace` is explicit; replacement requires all thirteen metrics and cannot use an older observation timestamp. Exact repeats are idempotent. Exact-schema CSV batches under `data/private/` are supported with `--csv` and validated completely before one transaction, so one bad or duplicate row writes nothing. The required header order is:

```text
package_id,candidate_id,published_at,checkpoint,channel,observed_at,impressions,non_follower_reach,external_comments,reactions,reposts,saves,sends,profile_visits,relevant_followers,github_clicks,recruiter_inbound,founder_advisor_inbound,speaking_podcast_inbound
```

Run `./bin/linkedin-os init` before the first import. Private input directories and files are deliberately owner-only; if a CSV was created by another editor or in a nested directory, enforce that boundary before import:

```sh
chmod 700 data/private
chmod 600 data/private/performance.csv
./bin/linkedin-os record-performance --csv data/private/performance.csv \
  --confirm-manual-publication
```

Private JSON, JSONL, and NDJSON imports belong under ignored `data/private/`:

```sh
./bin/linkedin-os research --input data/private/research.jsonl
```

Each item needs a public HTTP(S) URL, title, publisher/source, ISO timestamp, and `primary|secondary|mixed` quality; body and author are optional. Live source collection remains unavailable; the consented Writer boundary only drafts from evidence already stored locally.

See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the implemented analysis path, [ARCHITECTURE_DECISION.md](ARCHITECTURE_DECISION.md) for the current boundary, and [RECOVERY_MANIFEST.md](RECOVERY_MANIFEST.md) for provenance.

Automatic LinkedIn publishing is absent and remains out of scope.
