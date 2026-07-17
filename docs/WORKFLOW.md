# LinkedIn Authority OS workflow

## Current implemented flow

The current runtime implements a safe Scout-to-Analyst evidence path, strategic goal routing, voice-grounded Writer drafting, five-axis Critic scoring, five deterministic local gates, an explicit local human-review package, and package-linked manual performance checkpoints. Ordinary drafting stops after gating the scored candidate set and at most one light revision. `draft --package` adds deterministic eligibility and package generation; it never selects a winner, approves content, schedules, or publishes.

### Research ledger

Research arrives from the visibly synthetic fixture or an explicit private JSON/JSONL import. Each item must contain a non-null public URL, title, source, timestamp, and `primary|secondary|mixed` quality. Python canonicalizes the URL, hashes normalized body content, and stores each unique URL and body once in the ignored SQLite ledger.

The ledger persists evidence provenance. Fixture imports are `synthetic-fixture`; explicit files are `private-import`; rows migrated from the older schema are `legacy-unverified`. A live draft queries only `private-import` rows. Re-importing the exact canonical URL and body through a private file promotes that one pair, while a one-key collision stays quarantined and a later fixture run can never demote private evidence. This fail-closed migration may require an explicit re-import of older private rows, but it prevents fixture data from being relabelled as live.

Malformed wrappers, null required fields, local/private URLs, corrupt databases, and unsupported schema versions fail without a traceback or partial import.

### Analysis pass 1 — metadata

Titles and source metadata are grouped into product themes without reading bodies or adding embeddings. Boundary-aware token and phrase matching prevents substring collisions, and stable tie-breaks make selection independent of ingestion order. Each cluster records item count, distinct source-hostname count, and recency-weighted bounded momentum. Broad discovery is sufficient only with at least seven viable clusters and four clusters backed by two or more source hostnames. Hostname diversity is a transparent heuristic, not proof of independent ownership.

### Analysis pass 2 — full bodies

Within each cluster, primary and mixed sources rank above secondary summaries. A primary-source quality pass requires a primary or mixed body that was actually read; a title-only primary source cannot lend quality to a secondary body. The Analyst reads up to three strongest bodies and reports:

- why the signal matters now;
- the dominant full-body take;
- the missing product-decision angle;
- traceable primary sources;
- whether source quality and body evidence are sufficient; and
- whether the thesis is too similar to recent work.

ISO timestamps are validated. Evidence no older than 90 days can support a why-now case; older evidence is labelled insufficient, and implausibly future timestamps fail. An explicitly requested topic may select a narrower cluster, but the broad-discovery shortfall remains visible. Empty evidence, missing bodies, weak source quality, and stale ideas are never filled with invented material.

Staleness is `not-evaluated` unless the user explicitly supplies a private JSON list of recent post text:

```sh
./bin/linkedin-os research --dry-run --recent-posts data/private/recent-posts.json
```

### Strategic routing

`draft --dry-run` turns the selected analysis and explicit strategy inputs into a small strategy brief. It carries the target reader, reader problem, core hypothesis, product decision, authority statement, and traceable primary-source URLs forward rather than asking the Writer to reconstruct them. The visibly synthetic fixture supplies these inputs and a fixed validated analysis timestamp for deterministic offline execution; its provenance is labelled `synthetic-fixture`, not explicit user input. Fixture analysis is isolated from newer live rows already present in the private ledger, while persistence still applies the same durable URL/hash deduplication. The router does not infer personal experience, ownership, or credentials. The strategic goals are:

- Reach — earn attention from relevant non-followers;
- Authority — demonstrate differentiated GenAI product judgement; and
- Opportunity — convert credibility into relevant profile, tool, and inbound interest.

Each goal uses its configured v6 narrative route from the supplied brief. Output format remains a separate optional choice among `text`, `carousel`, `vertical-video`, `article`, and `artifact-demo`; no goal implies a format. When no goal is supplied the safe default is Authority, while format remains unselected.

Weekly slots 1–4 resolve to Reach, Authority, Authority, and Opportunity. Slot 5 is optional and requires both an explicit goal and `--strong-current-signal`; the runtime does not infer that an incident or launch is strong. Opportunity requires a validated local proof manifest before live Writer egress; no proof is inferred or invented. Reach and Authority may accept one optional manifest when exact public-safe proof or personal/ownership attestation is needed.

The brief reports evidence limitations when readable primary/mixed evidence, a readable body, recent evidence, or a traceable primary URL is missing, and when comparison positively marks the topic similar to a recent post. If recent-post similarity was not supplied, it reports `recent-post-similarity-not-evaluated` instead of pretending that comparison passed. Candidate-level citation and relevance decisions are applied later, after scoring.

Routing is stateless. It does not add a calendar, scheduler, weekly-history table, package file, or publishing action; it only hands the selected brief to the separate drafting step.

### Voice-grounded drafting

The Writer receives only the selected topic cluster's strategy brief and evidence records. It produces exactly three meaningfully different, unscored plain-text candidates. Every candidate has exactly four fields:

- `id` — one member of a complete neutral `candidate-1` through `candidate-3` sequence (the equivalent goal-prefixed sequence is also accepted);
- `angle` — the candidate's distinct narrative entry;
- `text` — the complete plain-text candidate; and
- `claim_ids` — the selected-cluster evidence IDs used by its factual claims.

Claim IDs are structural output, not citations hidden in prose. Evidence from an unselected cluster cannot be used. A candidate may additionally cite one validated `proof-*` ID (required for Opportunity and optional for Reach or Authority), but every candidate must still cite research evidence. The reconstructed voice guide and performance-pattern anchors calibrate style only: they are non-citable, do not prove that an event occurred, and cannot support facts or personal ownership.

Word ranges follow the strategic goal: Reach is 100–190 words, Authority is 190–300, and Opportunity is 180–300. `--format` remains downstream conversion metadata. Candidates remain plain text in this stage rather than being converted into slides, video scripts, articles, or artefacts.

The visibly synthetic fixture exercises this contract without exposing private data. Drafting from research stored in the private ledger requires both explicit strategy input and explicit model-egress consent:

```sh
./bin/linkedin-os draft \
  --strategy-input data/private/strategy.json \
  --allow-model-egress
```

The command fails closed if either flag is absent, and the Writer invocation itself requires the same explicit consent value. Consent means the selected strategy, evidence, and any supplied public proof claim or attestation text leave this machine for the configured Claude service through the local CLI; inference is not described as local. A consented live invocation sends only the selected-cluster brief, evidence, reconstructed voice instructions, and optional public-safe proof projection to the Writer; source-URL query strings are removed at that boundary while the local ledger remains unchanged. The artifact path and contents remain local. The Writer runs with zero tools and no persisted model session; it cannot browse or write files.

### Critic scoring and bounded revision

After the Writer contract is validated, the Critic scores every candidate from 1 to 5 on exactly these axes:

1. `hook_strength`
2. `middle_escalation`
3. `earned_closer`
4. `specificity_and_source_quality`
5. `voice_fidelity`

The model returns only candidate IDs and those five integer scores. Python rejects missing, extra, duplicated, unknown, non-integer, or out-of-range values and calculates the totals locally. A `hook_strength` score of 3 or below caps the effective total at 18 even when the five-axis raw total is higher.

The effective-total bands have narrow meanings:

- 24–25 means advance to the local safety gates. It does not mean approved, ready for approval, recommended, scheduled, or published.
- 22–23 permits one light revision of the current score leader. The Writer may be invoked once, the replacement candidate must still satisfy the full drafting contract, and the Critic may rescore it once. Revision does not recurse.
- 21 or below is below the Critic bar for this run; major rewriting is outside this stage.

The runtime reports a deterministic **score leader**, not a winner or recommended candidate. Candidate order cannot change the result: ranking compares effective total descending, raw total descending, the five rubric axes descending in the order listed above, and finally candidate ID ascending. Scoring is intentionally separated from safety policy: the Critic prompt contains the recovered five-axis rubric but excludes the authority-conversion, proof, honesty, citation, and relevance gates. Those gates run locally afterward. Only the later package stage can combine the score band and gate result into a recommendation for human review.

The visibly synthetic fixture contains validated scorecards and remains fully offline: it invokes neither Writer nor Critic. A private run requires the existing explicit `--allow-model-egress` consent before any Writer or Critic invocation. Live model calls remain zero-tools, stateless, and stdin-only; the Critic receives only the validated candidates, minimal selected evidence and voice context, and the scoring rubric. A 22–23 revision uses the same explicit consent for at most one further Writer call and one rescore.

### Deterministic authority and safety gates

Python evaluates all three final candidates independently in the fixed order `authority_conversion`, `proof`, `honesty`, `citation`, and `relevance`. Each gate returns an exact `PASS`, `FAIL`, or `NOT_REQUIRED` status and ordered static reason codes. Reach and Authority proof is `NOT_REQUIRED`; Opportunity proof passes only when the candidate cites the exact validated proof ID and uses its exact normalized public claim.

Proof manifests live under ignored `data/private/`, use an exact schema, and point to a distinct non-empty regular file relative to the manifest. Descriptor-anchored traversal rejects symlinks and path races; the runtime never reads artifact contents. It projects only proof ID, type, public claim, and exact public-safe personal/ownership attestations to Writer or score-only Critic prompts. Local paths are absent from prompts, stdout, gate results, and errors.

Honesty rejects detected personal or ownership sentences unless the complete normalized sentence exactly matches an attestation. It also rejects malformed direct quotations and unsupported explicit or citation-like bare/Markdown source references. Citation requires at least one body-read research record, refuses factual work supported only by Reddit or Hacker News, and checks high-risk numbers, structurally named entities, attributed quotations, directional relationships, and concrete incidents against one cited claim at a time. Matching preserves clause polarity, ordered associations, and the exact canonical query of query-addressed sources; private query data remains excluded from Writer and Critic prompts. A closed grammar canonicalises simple acquisition, hiring, and ownership claims across active and passive voice, allowing equivalent paraphrases while rejecting reversed actors. Bare sentence-leading Titlecase subjects are inherently ambiguous in opaque prose. The gate therefore fails closed unless high-confidence entity syntax applies or the subject belongs to an audited Authority OS generic-discourse registry. This prevents combining a name from one source and a number from another into unsupported precision. These bounded checks are deliberately conservative and cannot establish truth.

Authority conversion requires material overlap with both the explicit authority statement and product decision. Relevance requires a recognised v6 audience family plus material reader-problem overlap. Gate evaluation invokes no model and does not alter Critic ranking. A required-gate pass is not a winner, recommendation, approval, package, schedule, or publishing permission; human fact verification is always required.

### Explicit human-review package

`draft --package` revalidates the final candidates, computed scorecards, deterministic ranking, revision metadata, and strategy/proof provenance, then recomputes all five gates locally. A candidate is eligible only when its final Critic band is `advance-to-gates` and `passes_required_gates` is true. The package walks the validated Critic ranking and recommends the first eligible live candidate. No eligible candidate produces a complete `BLOCKED` package with a null recommendation; it is not a command failure.

Fixture provenance can never cross into a live package. Fixture packages expose mechanical eligible IDs for contract testing but set `recommended_candidate_id` to null and `review_status` to `FIXTURE_REVIEW_ONLY`. Live eligible packages use `READY_FOR_HUMAN_REVIEW`; live ineligible packages use `BLOCKED`. In all cases:

- `human_approval_status` is exactly `NOT_APPROVED`;
- `publishing_status` is exactly `DISABLED`; and
- `manual_fact_verification_required` is `true`.

The six-file package carries the brief, all candidates, scorecards, ranking, gates, source index, and human checklist. Source URLs are canonical and query-free. Raw evidence claims/bodies, private proof paths, artifact contents, credentials, prompts, and model stderr are not serialized. The fixed ignored output root is descriptor-opened without following symlinks. A final `outputs/YYYY-MM-DD/<topic-slug>[-N]/` name is reserved atomically, while six files are rendered into a private `.stage-*` directory with mode `0600`; both directories are `0700`. Completed regular files are published with no-clobber hard links, and `manifest.json` is linked last as the commit marker. The per-date lock and exclusive reservation preserve earlier entries even across a name race. Hidden stage directories and final topic directories without a manifest are incomplete internal state and must never be consumed as packages.

### Manual performance checkpoints

`record-performance` is observation-only. It requires the canonical package ID printed by `draft --package`, an explicitly selected eligible candidate, a timezone-aware external publication time, and `--confirm-manual-publication`. It descriptor-opens only the fixed ignored output root, rejects symlinks and manifestless or expanded package inventories, revalidates the Critic ranking and computed fields, and accepts only a committed `live` package whose review status is `READY_FOR_HUMAN_REVIEW`. Fixture, blocked, unknown, and ineligible candidates cannot enter the performance ledger. An eligible non-recommended candidate is allowed because a human may make a different final choice; that choice is recorded rather than inferred.

The `published_posts` row snapshots the package creation time, chosen candidate, goal/format/slot, revision metadata, five Critic axes, raw/effective total, hook-cap state, rank, and whether it was recommended. It stores no candidate body or private package content. The asserted publication time cannot precede package creation. `performance_observations` then keys each snapshot by package, checkpoint, and `organic|paid` channel. Organic and paid data never overwrite or aggregate into one another.

All thirteen recovered leading indicators are cumulative non-negative SQLite integers: impressions, non-follower reach, external comments, reactions, reposts, saves, sends, profile visits, relevant followers, GitHub/tool clicks, recruiter inbound, founder/advisor inbound, and speaking/podcast inbound. Timestamps must be timezone-aware, use whole-second precision, and normalize to UTC. A checkpoint observation must fall in its named half-open window: `2h=[2h,24h)`, `24h=[24h,72h)`, `72h=[72h,7d)`, and `7d=[7d,∞)`, and it cannot be later than the recording time.

An exact repeat is idempotent. A conflicting row requires `--replace`, a complete metric snapshot, and an equal-or-newer observation timestamp. CSV imports use the exact header order documented in the README, live package validation for every row, duplicate-key rejection, and one database transaction. `init` secures the fixed private input directory and ledger; nested CSV directories must be mode `0700` and CSV files mode `0600`. Package directories and all six committed files must retain the same owner-only invariants produced by package generation. Older free-form performance tables from the recovered draft implementation are renamed to `legacy_performance_unverified` and preserved, but they are not treated as learning evidence because they lack trusted package/candidate provenance.

## Safety boundary

Source bodies, candidates, public proof fields, package files, CSV rows, and metrics are untrusted data, not instructions. Analysis, routing, all five gates, eligibility, package rendering, and performance validation are deterministic Python. Only an explicitly consented live drafting run can cross the Writer or Critic model boundary, under the zero-tools and no-session restrictions above. Critic scores, gate passes, package recommendations, and performance records are not human approval. There is no browser, Gmail, LinkedIn write, approval-recording command, scheduler, or automatic publishing action.
