# Packet 09 — release evaluation and proof

## Mission

Prove that the contract-first local workflow is repeatable before any rebuild is
replicated to GitHub. This packet owns the test pyramid, installed-runtime proof,
live release trials, evidence collection, and the release-verifier decision. It
does not change discovery, evidence, Topic Value, drafting, acceptance, or
observability behavior.

The release question is not "did one command return zero?" It is:

> Did one immutable runtime plan repeatedly produce an honest terminal outcome
> inside the product budget, using the exact evidence selected upstream, with a
> complete and internally consistent evaluation record?

## Product contract carried into this packet

- Normal end-to-end target: `<= 420` seconds.
- Hard end-to-end deadline: `<= 480` seconds, including durable finalization.
- Evidence is body-verified, exact-identity-bound, and inside the requested
  seven-day window.
- Evidence from that same window may be reused after bounded transient Scout
  failures. Topic inventory or social summaries are not evidence.
- Reusing evidence never permits reuse of an already published atomic value.
- The live v2 voice rubric and the locked five-axis acceptance policy remain in
  force. Honesty, citation, proof, privacy, relevance, and voice cannot be traded
  against latency or total score.
- `READY_FOR_HUMAN_REVIEW` is not publication approval. The runtime never
  schedules or publishes.
- A legitimate product-gate rejection is an evaluated outcome. Timeout,
  unavailable dependency, identity drift, contract drift, missing observation,
  and budget overrun are system failures.
- GitHub push, pull request, merge, or deployment is outside this local-only
  packet and requires separate approval.

## Consecutive-run decision

The owner requires exactly **three consecutive live runs**. The release verifier
embeds that value in the immutable release plan:

```text
REQUIRED_CONSECUTIVE_LIVE_RUNS = 3
```

No implementation, test, or operator flag may silently weaken it. A system failure
or any release-candidate change resets the streak.

The evidence strength changes materially with `N`. If the true independent
system-failure probability is 20%, the chance that a trial streak observes at
least one failure is:

| `N` | Chance of observing at least one 20% failure |
| ---: | ---: |
| 2 | 36.0% |
| 3 | 48.8% |
| 5 | 67.2% |
| 10 | 89.3% |
| 15 | 96.5% |

Those figures explain the selected value; they do not establish a reliability
SLA. Live calls are also not
statistically independent, and a short same-day streak says little about
provider-day or topic diversity. The release report must state the selected value of three
and these limitations rather than describing any streak as a reliability SLA.

## What "consecutive" means

A release streak is valid only when all of these remain true:

1. Every trial uses the same commit/tree SHA, `RuntimePlan` SHA-256, contract
   digests, model assignments, profile digest, requested window, and CLI flags.
2. Every trial starts in a fresh process through the public installed command.
   Importing an internal `command()` function is not a live release trial.
3. Runs have distinct run IDs and fresh canonical journals. Prior output folders
   are never edited to make a later run pass.
4. No source, scorecard, draft, gate decision, or dashboard row is manually
   injected or repaired between trials.
5. Eligible private evidence cache state may carry forward because that is
   approved product behavior. Every use must be visible as `verified-cache`, with
   the exact scope, age, URL/hash identities, and live-attempt reasons recorded.
6. Any `SYSTEM_FAILED`, `CANCELLED`, deadline overrun, missing observation,
   artifact-integrity failure, or unexplained process exit resets the streak.
7. A code, configuration, prompt, rubric, model-assignment, or test-harness change
   resets the streak because it creates a new release candidate.

A `REJECTED_BY_PRODUCT_GATE` can demonstrate operational integrity if the correct
gate was fully evaluated and recorded, but it does not prove post generation.
Therefore the release evidence must satisfy both:

- three consecutive trials with no system failure; and
- at least one `READY_FOR_HUMAN_REVIEW` package in that streak.

If the selected topic is rejected before a downstream stage can legitimately run,
the run may remain in the reliability streak only when the journal proves a valid
product rejection and all later stages are explicitly `NOT_EVALUATED` because of
that immutable blocker. It does not count as proof of the skipped stages. Every
stage must separately have deterministic and installed-runtime coverage.

## Test pyramid

### Level 0 — static and contract checks

These checks run without model or network access:

1. Validate every versioned input/output JSON schema and fixture.
2. Hash the ordered stage registry, acceptance policy, Topic Value policy, claim
   support policy, v2 Critic rubric, voice profile, prompts, and model assignments.
3. Assert the public CLI and the installed-runtime test resolve the same
   `RuntimePlan` hash.
4. Reject import-time installers, runtime monkey patches, unregistered stages, and
   alternate dry-run composition roots from the rebuild path.
5. Assert no runtime dependency was added to `hook_stake`.
6. Assert the runtime has no LinkedIn/browser publication client surface.

### Level 1 — deterministic unit tests

Use fake clocks, in-memory adapters, and immutable fixtures. These tests own edge
conditions, not happy-path orchestration:

- legal stage transitions and immutable first blocker;
- global/stage budget arithmetic and retry reservation;
- URL canonicalization, content-addressed evidence IDs, manifest hashes, and
  exact identity lookup;
- body/window/source-quality verification and cache eligibility;
- published atomic-value exclusion independent of evidence reuse;
- all Topic Value, thesis, voice, Critic, hard-gate, and acceptance boundaries;
- deterministic journal-to-state/dashboard projection;
- secure artifact paths, modes, no-clobber writes, and digest validation.

Every time assertion uses a fake monotonic clock. Unit tests must not sleep.

### Level 2 — local stage integration tests

Join neighboring stages through their public typed contracts while replacing only
external model/web ports with deterministic adapters. Required seams:

1. conversation discovery -> topic admission;
2. topic admission -> live or cached evidence verification;
3. evidence verification -> Topic Value -> unpublished novelty;
4. Topic Value -> thesis -> immutable evidence manifest;
5. evidence manifest -> Writer -> Critic -> acceptance;
6. acceptance -> private package -> journal/dashboard projection.

Each producer output must be validated and serialized before the consumer starts.
Tests should deserialize the artifact rather than pass the producer's Python
object directly; otherwise serialization and schema drift remain untested.

### Level 3 — installed-runtime subprocess tests

Invoke the exact local executable that the owner will run, from a clean subprocess,
with a temporary private state root. The subprocess must build the same production
composition and exercise public entry points only. Stub only the explicit web and
model adapter ports; never patch a stage implementation after composition.

Required installed cases:

1. Full happy path reaches the Critic, accepts an 18-point boundary candidate,
   commits a `READY_FOR_HUMAN_REVIEW` package, writes both dashboards, and exits
   with the public success code.
2. Evidence primary attempt times out and retry succeeds within the original stage
   allocation.
3. Both live evidence attempts fail transiently and an exact current cache snapshot
   completes the run.
4. Cache scope, window, body, URL, hash, verification receipt, or count is invalid;
   the run fails at evidence verification and no Writer call occurs.
5. A deliberately unretrievable display topic plus valid evidence identities still
   drafts from the identities, including a multi-cluster thesis.
6. A decoy ledger record that lexically matches the display topic is never supplied
   to Writer, Critic, citations, or package lineage.
7. Each hard gate and each acceptance floor blocks independently, with every
   shortfall recorded.
8. A forced failure at each stage preserves that stage as the first blocker and
   marks all later stages `NOT_EVALUATED` with the blocker ID.
9. Simulated deadline exhaustion terminates the active adapter/process group,
   writes the canonical blocker, and never starts another stage.
10. Replaying the same deterministic adapter transcript yields the same normalized
    contract/artifact hashes. Run IDs and wall timestamps are excluded from the
    normalized comparison, not erased from the actual artifacts.

### Level 4 — offline replay

Retain sanitized adapter request/response envelopes from a successful live run.
They may contain source metadata and hashes but not credentials, provider stderr,
or raw private proof. Offline replay proves that a known external transcript still
flows through the current local composition.

Replay is useful for regression and incident reproduction, but never substitutes
for live release trials: it cannot prove current provider, web, or latency behavior.

### Level 5 — live local release trials

Live trials use the real configured web/model adapters, the owner-supplied profile,
the real published atomic-value ledger, and private local output. No test fixture
may satisfy a live evidence or Critic call.

Before starting the streak:

- `make check` passes, excluding only explicitly identified managed-sandbox probes;
- the installed-runtime suite passes from a clean subprocess;
- preflight records available models, permissions, private paths, plan digest, and
  remaining local disk without printing secrets;
- an eligible cache snapshot, if any, is validated but not assumed to be selected;
- the chosen `N` is written to the release-session plan.

Every trial must record its route (`live-primary`, `live-retry`, or
`verified-cache`), terminal outcome, total duration, stage durations, first
blocker, evidence identities, thesis/manifest identity, package identity, Critic
scores, gate decisions, and dashboard completeness result.

## Exact proofs required

### Multiple-run proof

The release verifier groups trials by this immutable session key:

```text
release_candidate_id = sha256(
    tree_sha + runtime_plan_sha256 + profile_sha256 +
    requested_window + canonical_cli_arguments
)
```

It orders them by canonical journal start event, rejects duplicate run IDs, and
counts only the uninterrupted suffix matching the key. It reports:

- requested `N` and achieved streak;
- outcome counts and route counts;
- number of `READY_FOR_HUMAN_REVIEW` packages;
- system-failure and product-rejection counts;
- whether any configuration changed between trials;
- exact run IDs and artifact-manifest hashes.

Do not delete failed runs or restart numbering. A reset begins a new release
session and preserves the prior session as evidence.

### Latency proof

Enforce latency with monotonic time in the runtime, not shell wall-clock output.
Every stage start/end and adapter attempt contains elapsed and remaining-budget
milliseconds. The verifier recomputes duration from the canonical journal and
rejects negative, overlapping-serial, missing, or post-deadline events.

Per trial:

- `total_elapsed_ms <= 480000` is mandatory;
- `total_elapsed_ms <= 420000` is the normal-target result recorded separately;
- final journal, state, manifest, and dashboard persistence are included;
- no external child remains alive after finalization.

Across the streak, report p50, p90, and maximum for the total and every stage.
With three trials, label interpolated percentiles as descriptive only. A run over 420
seconds but no more than 480 seconds may remain operationally valid, but the release
report must visibly mark `TARGET_MISS`; it cannot claim the normal latency target
passed. Any run above 480 seconds is a system failure and resets the streak.

### Quality-gate proof

One pure acceptance evaluator must be exercised with named axes:

| Hook | Middle | Closer | Specificity | Voice | Total | Hard gates | Result |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 5 | 4 | 4 | 4 | 4 | 21 | pass | advance |
| 5 | 3 | 3 | 3 | 4 | 18 | pass | advance |
| 5 | 4 | 4 | 4 | 2 | 19 | pass | reject; voice short by 2 |
| 4 | 4 | 4 | 4 | 2 | 18 | pass | reject; voice short by 2 |
| 5 | 5 | 5 | 5 | 5 | 25 | honesty fail | reject; honesty |

Also place each of middle, closer, and specificity one point below 3 while keeping
the total high, place hook below 4, and fail citation, proof, privacy, and relevance
one at a time. Every decision must contain observed, required, and shortfall for
every missed axis plus every failed hard gate. Highest-in-batch status, repair
exhaustion, or a high total never waives voice or a hard gate.

The separate first-comment evaluator must accept totals from 18 through 25 when
its evidence, anti-slop, and artisanal checks pass, reject 17, and reject a perfect
25 when any of those checks fails. Because its axes differ from the post axes,
the post's per-axis floors are not copied into this interim contract.

The verifier additionally proves:

- the recorded `critic_rubric_sha256` equals the exact loaded v2 file;
- the scorecard candidate SHA-256 equals the immutable candidate bytes evaluated;
- both hook lines pass the deterministic off-register check on the evaluated and
  packaged artifacts;
- the model supplies axes and anchor evidence, while Python recomputes the total
  and acceptance decision;
- claim/body similarity remains a separate `0.18` diagnostic and is not confused
  with published atomic-value novelty;
- `READY_FOR_HUMAN_REVIEW` is impossible when any required evaluation is missing.

### Exact evidence-binding proof

For every accepted candidate, persist and verify this lineage:

```text
admitted candidate identity
  -> verified evidence IDs (canonical URL + evidence payload SHA-256)
  -> Topic Value selected signal IDs
  -> thesis evidence-set manifest SHA-256
  -> DraftRequest evidence IDs
  -> Writer candidate claim/source IDs
  -> Critic candidate SHA-256
  -> package manifest and evaluation
```

Required invariants:

1. `DraftRequest.evidence_ids` equals the thesis manifest's ordered identity set;
   it is not recomputed from display topic.
2. Every Writer/packaged claim ID is a member of that exact set. No extra ledger
   record is present, even if it has a stronger lexical topic match.
3. Every identity resolves to the same canonical URL and payload hash captured at
   verification. A missing or changed record is an `IDENTITY_VIOLATION` before
   Writer egress.
4. Package and evaluation record the evidence-manifest SHA-256, candidate SHA-256,
   rubric SHA-256, acceptance-policy digest, run ID, and plan digest.
5. Multi-cluster evidence remains valid; cluster slug is never used as identity.
6. The published atomic-value check runs after cached evidence is selected and may
   still reject it. Evidence route never supplies a novelty decision.

Test this with a valid manifest, reordered manifest, duplicate ID, missing ID,
changed payload, stale record, multi-cluster set, and lexical decoy.

### Cache-recovery proof

The deterministic and installed tests use a matrix, not one happy fixture:

| Live attempts | Cache | Expected |
| --- | --- | --- |
| primary succeeds | irrelevant | `live-primary`; cache not read |
| primary transient failure; retry succeeds | irrelevant | `live-retry` |
| both transiently fail | exact, current, 3–7 verified records | `verified-cache` |
| both transiently fail | fewer than 3 valid records | fail closed |
| both transiently fail | scope mismatch | fail closed |
| both transiently fail | outside seven-day window | fail closed |
| both transiently fail | body/hash/receipt mismatch | fail closed |
| schema, identity, or integrity failure | valid cache exists | fail closed; no laundering as availability |

For the release candidate, run one controlled recovery rehearsal after a successful
live evidence snapshot exists. Inject transient failure only at the explicit
evidence-adapter port; do not add a hidden production environment switch or wait
for a natural provider outage. The recovered run uses the real local runtime and
real snapshot, and must stay inside 480 seconds. Record it separately from the
ordinary live streak unless the owner explicitly includes controlled-fault trials
in `N`.

The rehearsal proves availability recovery. It does not prove fresh web retrieval,
so the release evidence must also contain at least one `live-primary` or
`live-retry` evidence result.

### Dashboard-completeness proof

The canonical journal is the source; JSON and HTML are deterministic projections.
For every run, the verifier must assert:

1. The ten ordered stages are present exactly once in run state with legal status
   and applicability values.
2. Every started stage has one durable start and one terminal event. No terminal
   event, decision, or artifact reference has a sequence gap.
3. Every candidate considered by Topic Value, thesis selection, Writer, and Critic
   has a recorded decision before filtering.
4. Every Critic scorecard contains all five axes, total, anchor evidence, candidate
   hash, rubric hash, attempt/cycle, acceptance failures, and per-axis shortfalls.
5. A failed run displays the journal's immutable first blocker. All downstream
   stages say `NOT_EVALUATED` with `blocked_by_stage` and `failure_id`; expected
   downstream non-evaluation is not labelled missing telemetry.
6. A successful run has no missing required evaluation, unresolved
   `OBSERVABILITY_FAILURE`, or unreferenced package artifact.
7. `artifact-manifest.json` lists every required artifact with size and SHA-256;
   recomputation matches. `manifest.json` is the final package commit marker.
8. JSON and HTML show the same statuses, first blocker, evidence route, elapsed
   times, Critic axes, failure codes, and evaluator provenance.
9. HTML is escaped and has no network dependency. Private bodies, prompts, tokens,
   provider stderr, proof content/path, credentials, and URL query strings are not
   present in either dashboard.
10. Rebuilding the projections from `events.jsonl` yields the same normalized JSON
    digest. A projection failure prevents the run from counting in the streak even
    if the product artifact exists.

## Release-session record

The local verifier writes one owner-only `release-verification.json` containing:

```json
{
  "schema_version": 1,
  "release_candidate_id": "...",
  "required_consecutive_live_runs": 3,
  "status": "RUNNING",
  "tree_sha": "...",
  "runtime_plan_sha256": "...",
  "make_check": {"status": "PASS", "tests": 0, "exceptions": []},
  "installed_runtime": {"status": "PASS", "cases": []},
  "live_runs": [],
  "achieved_consecutive_runs": 0,
  "ready_for_human_review_runs": 0,
  "latency": {"target_ms": 420000, "hard_ms": 480000},
  "controlled_cache_recovery": {"status": "NOT_RUN"},
  "gate_contract": {"status": "PASS", "digest": "..."},
  "identity_contract": {"status": "PASS", "digest": "..."},
  "dashboard_contract": {"status": "PASS", "digest": "..."},
  "github_actions": []
}
```

The status may become `PASS` only when all required
deterministic/installed suites pass, the controlled recovery rehearsal passes,
the uninterrupted live suffix reaches three, at least one run is
`READY_FOR_HUMAN_REVIEW`, every run is no more than 480 seconds, and all canonical
artifacts validate. The report separately names any 420-second target misses.

## Suggested test ownership

Keep release proof separate from stage implementations:

```text
tests/rebuild/test_contract_digests.py
tests/rebuild/test_release_state_machine.py
tests/rebuild/test_release_budget.py
tests/rebuild/test_release_acceptance.py
tests/rebuild/test_release_evidence_binding.py
tests/rebuild/test_release_cache_recovery.py
tests/rebuild/test_release_dashboard.py
tests/rebuild/test_installed_full_run.py
tests/rebuild/fixtures/adapter_transcripts/
src/authority_os/release_verifier.py
```

`make check` remains the aggregate CI-equivalent command and must discover these
through `unittest`. A pytest-only pass is not release evidence.

## Definition of done

- The owner-approved count of three is embedded in the release-session plan and
  cannot be weakened by an operator flag.
- Static, unit, stage-integration, installed-runtime, replay, and live layers are
  separately reported rather than collapsed into one green check.
- The installed test invokes the same public composition as the owner command and
  reaches Critic/package without patching internal stages.
- Multiple-run evidence is tied to one immutable release candidate and cannot be
  cherry-picked across revisions.
- Total and per-stage latency are monotonic, include finalization, and enforce the
  420/480-second target/hard distinction.
- Acceptance boundary, v2 rubric provenance, absolute voice rule, and every hard
  gate are proven case by case.
- Exact evidence identity is continuous from verification through package, and a
  lexical decoy cannot enter drafting.
- Transient Scout failure recovers only through the approved exact, body-verified,
  same-window cache path; integrity failures never do.
- Every release-counted run has a complete canonical journal, consistent JSON/HTML
  dashboard, valid artifact hashes, and no unresolved observability failure.
- At least one run in the approved streak creates a private
  `READY_FOR_HUMAN_REVIEW` package. Nothing is published or pushed.
