# Rebuild packet 10 — review, publication, performance, and learning

## Mission

Own the boundary from an evaluated candidate to a private human-review package,
then from an externally published post to durable novelty exclusion, performance
observations, and evidence-thresholded learning.

This packet must guarantee both product decisions at the same time:

- a manually published atomic value is permanently ineligible for later selection;
- the exact source evidence may be reused while it remains body-verified and inside
  the frozen seven-day window, provided it supports a materially different atomic
  value.

The runtime stops at `READY_FOR_HUMAN_REVIEW`. It never approves, schedules, edits
LinkedIn, or publishes. Publication is a human action outside the system and is
recorded locally only after it happens.

## Ownership and non-ownership

This packet owns:

- immutable review-package construction and consumption;
- the human publication boundary and exact candidate assertion;
- published atomic-value promotion and permanent novelty exclusion;
- package-linked organic and paid performance observations;
- observation-only weekly learning and calibration recommendations.

It consumes, but does not redefine:

- evidence identity and same-window cache eligibility from packet 03;
- Topic Value's atomic-value schema and `0.72` published-value similarity policy;
- the v2 Critic rubric and acceptance policy from packet 05;
- the five hard gates: honesty, citation, proof, privacy, and relevance;
- orchestration, deadline, journal, and first-blocker behavior from packet 06.

It does not fetch analytics, infer that publication occurred, change a rubric,
weaken a gate, or use performance to resurrect a published idea.

## Product decisions already fixed

1. `READY_FOR_HUMAN_REVIEW` is not approval and is not publication.
2. Only a live candidate that passes the current acceptance policy and every hard
   gate may be placed in the publishable set. A human may select any eligible
   candidate, not only the system recommendation.
3. Publishing is manual and outside the runtime. The system records the event only
   through an explicit local confirmation after publication.
4. Review-ready or rejected drafts do not enter published novelty history. An idea
   becomes unavailable only after its exact candidate is confirmed as published.
5. Once published, its atomic value remains in novelty history permanently,
   regardless of performance. A flop is still a used idea.
6. A source and an atomic value are different identities. Reusing eligible
   seven-day evidence is allowed; reusing a published atomic value is not.
7. Organic and paid observations remain separate. Paid results are descriptive and
   never substitute for organic learning evidence.
8. Learning may produce a versioned recommendation for human product review. It
   never changes the voice floor, hard gates, thresholds, prompts, or rubric.
9. Manual fact verification remains required before publication.

No further product decision is required for this packet.

## Current-runtime audit

### What should be retained

- `package.py` produces a private, committed six-file package with manifest-last
  semantics, no-clobber writes, owner-only modes, and strict live/fixture/blocked
  statuses.
- The package revalidates Critic ranking and deterministic gates before recommending
  the first eligible candidate.
- `performance.py` reopens only a canonical committed package, validates the exact
  package inventory and eligibility, and permits an eligible human override.
- Publication context is immutable after the first record; observations are keyed
  by package, checkpoint, and channel.
- Organic and paid rows cannot overwrite one another. Corrections are complete,
  explicit, and monotonic.
- `learning.py` uses comparable organic 72-hour observations, goal-specific
  lexicographic outcomes, explicit evidence minimums, bounded context, and no
  automatic rubric mutation.
- Review-ready atomic values are already separated from published atomic values.

### Gaps the rebuild must remove

| Priority | Current behavior | Risk | Clean contract |
| --- | --- | --- | --- |
| P0 | The first `record-performance` write doubles as the assertion that publication occurred. | Novelty exclusion can be delayed until somebody has metrics to enter. A run started after publication but before the first checkpoint can select the used idea. | Record publication immediately in a separate operation; metrics are optional later observations. |
| P0 | SQLite performance commit happens first; atomic-value promotion to a JSONL sidecar is attempted afterward and failures are swallowed. | A post can be durably recorded as published while its idea remains eligible. | Publication receipt and published atomic value commit atomically under one authority, or through a durable transactional outbox that selection treats as authoritative. |
| P0 | Selection reads a published-value sidecar, while publication identity lives in the performance database. | Split authority permits drift, partial repair, and races. | One `PublicationLedger` owns publication and novelty state. Derived exports are never selection authority. |
| P0 | The review package has no machine-readable candidate-to-atomic-value-to-evidence-set lineage. Promotion recovers it indirectly by hashing candidate Markdown and looking up a prior sidecar binding. | Formatting changes, missing bindings, or ambiguous hashes can prevent promotion after the business event. | Freeze exact lineage for every eligible candidate when the package commits. |
| P0 | A package can be selected while another process publishes the same atomic value after the earlier Topic Value check. | Two concurrent runs can both reach review with the same idea. | Recheck published novelty under the publication-ledger lock at package commit and again when recording publication. |
| P1 | `--confirm-manual-publication` proves intent but not that the externally published text exactly matches the evaluated candidate. | Material human edits can bypass the gates while retaining the package's score and performance attribution. | Confirm the package candidate's exact artifact hash. Any content edit must return through evaluation and create a new package. |
| P1 | Existing published rows without an atomic-value binding remain metric-eligible but cannot protect novelty. | Historical publication and novelty history may disagree. | Preserve them as explicit lineage gaps; never invent an atomic value. Require human backfill if they are expected to protect future selection. |
| P1 | The current performance snapshot still contains historical Critic-band fields whose arithmetic may differ from the live acceptance policy. | A later reader can trust stale derived fields even when the live policy changed. | Store rubric and acceptance-policy digests with the evaluated snapshot and revalidate against that exact version. Do not reinterpret historical scores under a new policy. |
| P2 | Package parsing reconstructs learning context from fixed Markdown formatting. | Presentation changes can break trusted learning even if semantic data is intact. | Put bounded structured learning context in the committed machine manifest; render Markdown as a view. |

## Clean local architecture

Construct these dependencies once; no module installs itself or replaces another
callable:

```text
ReviewPackageBuilder
  -> PackageRepository
  -> PublicationLedger
  -> NoveltyPolicy

PublicationRecorder
  -> PackageRepository
  -> PublicationLedger

PerformanceRecorder
  -> PublicationLedger
  -> PerformanceStore

LearningService
  -> PublicationLedger
  -> PerformanceStore
  -> PackageRepository
```

`PackageRepository` is immutable content storage. `PublicationLedger` is the sole
authority for whether an atomic value has been published. `PerformanceStore` owns
mutable observation snapshots but cannot create or change publication identity.

## Review-package contract

### Status vocabulary

- `READY_FOR_HUMAN_REVIEW`: at least one eligible live candidate exists.
- `BLOCKED`: no live candidate passes the acceptance and hard-gate contracts.
- `FIXTURE_REVIEW_ONLY`: synthetic contract output; never publishable.

Every package records:

```json
{
  "human_approval_status": "NOT_APPROVED",
  "publishing_status": "DISABLED",
  "manual_fact_verification_required": true
}
```

No score, recommendation, or gate pass changes those fields.

### Immutable package manifest

The committed machine manifest must include:

- `package_id`, `run_id`, `created_at`, `mode`, and schema version;
- run-plan, voice-rubric, acceptance-policy, and hard-gate digests;
- goal, output format, weekly slot, and narrative route;
- all candidates with exact artifact SHA-256, Critic scores, per-axis shortfall,
  ranking, acceptance result, and hard-gate results;
- the eligible candidate IDs and optional recommended candidate ID;
- for every eligible candidate, `topic_value_id`, canonical `atomic_value`,
  `atomic_value_sha256`, `evidence_set_id`, and stable `evidence_ids`;
- package-file inventory, size, and digest.

Candidate bodies, evidence bodies, proof content, model prompts, credentials, and
private paths remain private package files or excluded data. Public source views use
query-free canonical URLs. The machine manifest is strict, bounded, owner-only, and
committed last after every referenced file has been fsynced.

### Package-time novelty revalidation

Before a live package becomes `READY_FOR_HUMAN_REVIEW`, the builder must:

1. snapshot the current published atomic-value ledger under its read lock;
2. evaluate every otherwise-eligible candidate against the `0.72` similarity rule;
3. remove any candidate that now matches a published atomic value;
4. record the matched publication ID, similarity, and reason without exposing text;
5. commit `BLOCKED` if no candidate remains.

Review-ready packages do not reserve an idea indefinitely. If two packages contain
the same unused atomic value, the first one actually published wins; the second is
rejected when publication is attempted.

## Human publication boundary

The lifecycle is explicit:

```text
READY_FOR_HUMAN_REVIEW
  -> human verifies facts and selects an eligible candidate
  -> human publishes outside the system
  -> human immediately records the exact publication locally
  -> PUBLISHED receipt and atomic-value exclusion commit together
  -> performance observations may be added later
```

The publication recorder requires:

- canonical package ID;
- selected eligible candidate ID;
- exact candidate artifact SHA-256;
- timezone-aware whole-second `published_at` that is not before package creation;
- explicit assertions that publication happened and the published content is the
  exact evaluated candidate;
- explicit assertion that manual fact verification was completed.

It reopens the complete committed package without following symlinks, verifies all
file digests and policy provenance, revalidates candidate eligibility, and acquires
the publication-ledger write lock. It then rechecks novelty. A matching published
atomic value from another receipt is a hard conflict, not a human override.

An exact repeat is idempotent. A different candidate, timestamp, artifact hash, or
atomic value for the same package fails as an immutable-publication conflict. One
package can identify at most one published candidate.

The recorder does not call LinkedIn, store credentials, or treat the confirmation
as system approval. It records a human-asserted external event.

## Atomic publication receipt

```json
{
  "schema_version": 1,
  "publication_id": "pub-...",
  "package_id": "2026-09-04-agent-reliability",
  "candidate_id": "candidate-2",
  "candidate_artifact_sha256": "...",
  "topic_value_id": "topic-1",
  "atomic_value": "...",
  "atomic_value_sha256": "...",
  "evidence_set_id": "...",
  "evidence_ids": ["..."],
  "package_created_at": "...",
  "published_at": "...",
  "confirmed_at": "...",
  "manual_fact_verification_confirmed": true,
  "exact_evaluated_candidate_confirmed": true,
  "rubric_sha256": "...",
  "acceptance_policy_sha256": "..."
}
```

The receipt and the published atomic-value index are one transaction. The index is
derived from receipts inside the same authority; it is not a second writable source
of truth. Failure before commit leaves neither visible. Failure after commit can
only affect derived dashboards and must not undo novelty exclusion.

## Source reuse versus value reuse

These checks are deliberately orthogonal:

| Identity | Reuse rule |
| --- | --- |
| Exact evidence version | May be reused only when packet 03's body-verification receipt remains valid, `published_at` is inside this run's frozen seven-day window, and the evidence remains linked to the admitted topic. |
| Canonical source URL | Does not by itself establish eligibility; the exact content identity and verification receipt are required. |
| Published atomic value | Never reusable. It has no expiry and is rejected at `>= 0.72` similarity, even if supported by different sources. |
| Unpublished review-ready atomic value | Does not enter published history. It may appear in a later run, subject to ordinary selection and any concurrent publication recheck. |
| Published post text or hook | Never copied as a new candidate. Exact artifact duplication is rejected independently of atomic-value similarity. |

The same source may therefore support a new post only when the reader decision or
insight is materially different. A new source cannot launder an old atomic value.
Strong performance cannot waive novelty, and poor performance cannot make an idea
unused again.

Novelty must run before selection, be recorded for every Topic Value candidate, and
be revalidated at package and publication boundaries. Selection consumes a frozen
published-ledger snapshot and records its digest for reproducibility.

## Performance-recording contract

Publication exists before and independently of performance observations.

Supported checkpoints remain `2h`, `24h`, `72h`, and `7d`; channels remain
`organic` and `paid`. Each observation contains all thirteen cumulative,
non-negative integer metrics already defined in `storage.PERFORMANCE_METRICS`.

Observation keys are `(publication_id, checkpoint, channel)`. Windows are:

- `2h`: `[2h, 24h)` after publication;
- `24h`: `[24h, 72h)`;
- `72h`: `[72h, 7d)` for collection;
- `7d`: `[7d, infinity)`.

`observed_at` cannot exceed `recorded_at`. Timestamps are timezone-aware,
whole-second, and normalized to UTC. An exact repeat is idempotent. A correction
requires an explicit replace flag, a complete snapshot, an equal-or-newer
observation time, and a recording time no earlier than the current update.

Performance cannot alter candidate ID, publication time, goal, output format,
scores, policy digests, atomic value, evidence lineage, or recommendation status.
Legacy free-form rows remain quarantined because they cannot prove publication
identity.

## Learning-loop contract

`weekly-review --as-of` is deterministic, cumulative, private, and observation-only.
The canonical comparison cohort is exactly one organic `72h` observation per
publication with exposure age in `[72h, 96h)`. Later 72-hour rows are explicit
exposure-comparability gaps. `2h` and `24h` are leading signals, organic `7d` is a
follow-up cohort, and paid observations are descriptive only.

Goal outcomes remain lexicographic, with no hidden engagement weights:

- Reach: `(non_follower_reach, impressions)`.
- Authority: `(saves + sends + reposts, external_comments, profile_visits)`.
- Opportunity: `(qualified_inbound, github_clicks, relevant_followers,
  profile_visits)`, where qualified inbound is recruiter + founder/advisor +
  speaking/podcast inbound.

The report may expose publication/package references, stored score vectors, bounded
hook excerpt, candidate angle, route, paragraph count, outcome vector, exclusions,
and provenance gaps. It does not expose full bodies, source bodies, proof, URLs, or
private paths, and it makes no causal claim about why a post performed.

Cross-publication Critic alignment remains `INSUFFICIENT` until at least three
distinct publications provide at least three scorable pairs. Axis-calibration review
requires, within one goal and known output format, both high and lower cohorts of at
least three comparable publications and at least two shared ISO publication weeks.

Any observed inversion, including the current `earned_closer` concern, can emit a
human-review recommendation only after its evidence contract is met. It cannot
demote the axis, change its floor, or modify acceptance automatically. Voice
fidelity and the five hard gates are values constraints and are never traded against
outcomes.

## Failure and durability rules

- Package contract, identity, provenance, or digest failures are typed system
  failures; never reinterpret them as content rejection.
- A candidate that misses acceptance or a hard gate is a product rejection and
  cannot be published through this boundary.
- Publication recording fails closed if exact candidate, lineage, or novelty cannot
  be proven.
- A performance or learning write failure does not erase an already committed
  publication or novelty exclusion.
- Failure to update a derived dashboard is observable degradation. Failure to
  commit the canonical publication receipt is a system failure.
- All mutating operations use owner-only local state, descriptor-relative no-follow
  access, bounded inputs, atomic commit, and explicit schema versions.

## Required tests

### Review package

1. A live candidate satisfying the current per-axis/total acceptance policy and all
   hard gates enters `eligible_candidate_ids`; the first ranked eligible candidate is
   recommended.
2. A human-selected eligible non-recommended candidate is accepted by the
   publication boundary.
3. `BLOCKED` and `FIXTURE_REVIEW_ONLY` packages cannot be published.
4. Every eligible candidate has exact atomic-value and evidence-set lineage in the
   committed machine manifest.
5. Missing lineage, stale policy digests, changed candidate bytes, added files,
   symlinks, unsafe modes, or absent manifest-last marker fail closed.
6. A value published after Topic Value but before package commit removes that
   candidate; if none remain, the package is `BLOCKED` with the exact novelty reason.

### Publication and novelty

7. Creating a review-ready package does not add its atomic value to published
   history.
8. Confirming exact manual publication atomically creates one receipt and makes the
   value immediately ineligible, before any performance checkpoint exists.
9. Inject failures at every transaction boundary; no state may show publication
   without novelty exclusion or novelty exclusion without its publication receipt.
10. An exact repeated confirmation is idempotent; changing candidate, timestamp,
    artifact hash, or atomic value for that package fails.
11. A second package with atomic-value similarity `>= 0.72` cannot publish and is
    rejected in future Topic Value selection even when it cites different evidence.
12. A package below `0.72` may use the same exact eligible evidence version and
    publish a materially different value.
13. A same-window cached source remains eligible under packet 03; an expired,
    unverified, hash-drifted, or unrelated source does not.
14. Concurrent publication attempts for matching values yield exactly one committed
    receipt. The loser receives a typed novelty conflict.
15. Confirmation without manual fact verification or exact-candidate assertion
    fails and makes no state change.
16. There is no LinkedIn/browser write surface, credential access, scheduler, or
    automatic approval path.

### Performance

17. Performance can be recorded only for an existing publication receipt; recording
    metrics cannot create publication implicitly.
18. Checkpoint boundaries, timezone normalization, non-negative integer metrics,
    and observed/recorded ordering are enforced exactly.
19. Organic and paid rows with the same publication/checkpoint coexist and never
    overwrite or aggregate into one another.
20. Exact repeats are idempotent. Corrections require complete equal-or-newer
    snapshots; older corrections and partial updates fail.
21. Publication context and its candidate/atomic/evidence/policy lineage remain
    immutable across all checkpoints.
22. Batch import is all-or-nothing, validates every publication/package, rejects
    duplicate keys, and never promotes legacy unverified rows.

### Learning

23. Only organic 72-hour rows observed at 72–96 hours enter the canonical outcome
    comparison; early, late, 7-day, paid, future-as-of, and legacy rows are reported
    separately or excluded.
24. Each goal's exact lexicographic vector determines leaders and preserves ties.
25. Learning context is reopened only for canonical leaders, matches the stored
    package fingerprint/digest, is bounded, and excludes sensitive/full-body data.
26. Critic alignment stays `INSUFFICIENT` below three posts and three scorable
    pairs.
27. Calibration emits no change below both cohort/week minima, emits only a human
    review recommendation after repeated inversion, and never mutates a rubric or
    acceptance constant.
28. Poor performance does not remove a published value from novelty history; strong
    performance does not extend source evidence beyond seven days.

### Installed local workflow

29. Through public local entry points: build a review-ready package, assert manual
    publication, immediately rerun selection with the same atomic value, and prove
    it is rejected before Writer while the same seven-day evidence can support a
    distinct passing atomic value.
30. Repeat the scenario across three consecutive isolated local runs and verify
    deterministic publication/novelty state, exact dashboard attribution, and zero
    network publishing actions.

## Completion criteria

This packet is complete when a local installed-runtime test proves the full boundary
from eligible package to manual publication receipt, immediate permanent novelty
exclusion, later performance observations, and an observation-only weekly review.
The proof must also demonstrate the inverse case: same-window source reuse succeeds
for a materially new atomic value without relaxing evidence verification.

No code from this packet is pushed until the parallel rebuild's composition and
plumbing review accepts the contracts.
