# Rebuild packet 02: discovery architecture

Audit base: `origin/main` at `6dc917af05330cfdd8af54bcfb318ad0b696f40d`.

Scope: conversation discovery, surface scouting, conversation consolidation,
momentum ranking, authority-fit assessment, topic admission, rolling inventory,
and body-verified evidence acquisition. This packet specifies a replacement
boundary; it does not change the current runtime.

## Finding

The reported run did not fail in conversation discovery or topic admission.
Those stages passed, and five topics were admitted from the rolling seven-day
inventory. It failed in `daily_spine_cli._invoke_signal_scout()` at evidence
verification when its single 420-second `Scout` model call timed out. The public
dashboard correctly left every downstream stage `NOT_EVALUATED`.

This is a runtime-availability failure, not a content-gate rejection. It also
exposes two missing recovery contracts:

1. the rolling inventory retains topic prose and representative momentum URLs,
   but no exact body-verified evidence identities;
2. the evidence Scout has no timeout retry and does not reuse body-verified
   records that remain inside the requested window.

The current timeout ceilings cannot satisfy the product's seven-to-eight-minute
end-to-end target. Before evidence verification, the installed discovery path
can spend 360 seconds on two sequential 180-second surface attempts, 150 seconds
on consolidation, and 420 seconds on authority-fit scoring: 930 seconds. Evidence
verification can then spend another 420 seconds. The configured ceiling is thus
1,350 seconds (22.5 minutes) before Topic Value begins, excluding process startup
and persistence.

## Public entry point and installed path

The only supported operator entry point is:

```text
./bin/linkedin-os discover [arguments]
```

`bin/linkedin-os` installs runtime layers in this order:

1. `v1_gates.install()`
2. `v1_completion.install()`
3. `topic_value_id_contract.install()`
4. import `daily_discovery_cli`, whose import performs:
   1. `discovery_runtime_tuning.install()`
   2. `surface_scout_runtime_tuning.install()`
   3. `individual_launch_runtime_tuning.install()`
   4. `v1_consumability.install()`
   5. `daily_spine_cli.momentum = momentum_surface_parallel`
5. `daily_discovery_cli.main()` -> `daily_spine_cli.main()` -> the wrapped
   `daily_spine_cli.command()`

The active discovery implementation is therefore not the base
`momentum.invoke_scout()` or either batched adapter. It is
`momentum_surface_parallel.invoke_scout()`, with `_run_surface()` replaced by
`surface_scout_runtime_tuning` and `_consolidate()` replaced by
`v1_consumability`.

This import-time mutation is a material architecture risk: source-level review
of any one module does not reveal the shipped behavior. The replacement should
use one explicit composition root with injected adapters and no discovery
monkey-patching.

## Current inputs, outputs, state, and timing

### Operator inputs

| Input | Contract today |
|---|---|
| `--profile` | Required ignored private JSON: target audience, authority goal, proof inventory, avoided topics, and recent theses. |
| `--days` | Integer 1-30, default 7. The product-approved operating window is 7 days. |
| `--topic` | Optional prose scope. |
| `--as-of` | Optional parseable timestamp; generated once by the wrapper when absent. |
| `--db` | Private SQLite research ledger. |
| `--output-dir` | Optional private run directory. |
| `--allow-web-research` | Required explicit consent. |
| `--allow-model-egress` | Required before private profile data reaches zero-web model stages. |

The private profile is not sent to web-enabled surface or evidence scouts.
Authority-fit scoring receives it only in a zero-web call.

### Current stage map

| Stage | Implementation | Output | Timeout/recovery |
|---|---|---|---|
| Surface scouting | Seven lanes in `momentum_surface_parallel`, maximum seven workers | Up to five normalized public signals per lane plus status/caveat | Installed timeout 180s; one retry for `TIMEOUT` or `UNAVAILABLE`; no global deadline |
| Consolidation | Installed `v1_consumability._consolidate()` | Exactly ten clusters, each bound to one or more surface signal IDs | One zero-web call, 150s; no retry or cache fallback |
| Momentum score/rank | `momentum.validate_candidates()` and `rank_candidates()` | Five observed-axis scores, total, confidence, deterministic order | Local; fixed rubric; at least four observed axes for a usable total; authority floor 14/25 |
| Authority fit | `momentum.score_authority_fit()` | Five 1-5 axis scores, total | One zero-web call, 420s; the model assigns scores directly |
| Inventory update | `daily_spine_cli.update_candidate_inventory()` | Global private `candidate-inventory.json` | Local atomic replacement; retains combined score >=40/50 for the rolling window |
| Topic admission | `daily_spine_cli.select_topic_scope()` | A sequence of admitted topic dictionaries plus route | Prefer current momentum-qualified topics; otherwise inventory; otherwise authority-fit >=20/25 with >=4 observed momentum axes |
| Evidence verification | `daily_spine_cli._invoke_signal_scout()` | Three to seven prepared research records and run-local `signal-*` projections | One web-enabled 420s call; no retry; no cache fallback |

### Persistent state

| State | Current contents | Limitation |
|---|---|---|
| `surface-<lane>.json` | Per-run surface result/status/signals | Written only under the current trace directory; not a reusable cache contract |
| `surface-trace.jsonl` | Per-run surface lifecycle events | Observability only |
| `momentum.json` | Current top five, scores, evidence URLs | Momentum evidence is not body-verified factual evidence |
| `candidate-inventory.json` | Topic, why-now, timestamps, two totals, representative URLs, `AVAILABLE` | No stable candidate ID, body-evidence identities, or used/published transition; documentation calls it "unused" but code never marks it used |
| private research ledger | Canonical URL, body/content hash, provenance, source metadata | New Scout records are inserted only after Topic Value and thesis search succeed; a later-stage failure can discard otherwise useful freshly verified evidence |
| `published-atomic-values.jsonl` | Published atomic values promoted after confirmed manual publication | Correct final novelty authority, but consulted later at Topic Value rather than at discovery admission |

## Current contracts that must be preserved

1. Social/community data may establish momentum but cannot establish factual
   research trust.
2. Surface access is public and unauthenticated. No private profile, local files,
   credentials, shell, plugins, browser session, or publishing capability reaches
   a web Scout.
3. Unknown momentum measurements remain `UNKNOWN`/`null`; they are never
   fabricated as zero.
4. Momentum axis scoring, total calculation, eligibility, and ordering are local
   Python operations with stable tie-breaks. Authority fit never reorders the
   momentum ranking.
5. A topic requires at least four observed momentum axes and normally at least
   14/25. The authority-only fallback requires at least four observed momentum
   axes and authority fit >=20/25. Inventory retention requires combined score
   >=40/50.
6. Evidence must be canonical, body-read, non-social for factual use, source
   quality validated, and published inside the requested window.
7. Previously published *atomic value* is excluded from selection. Reusing a
   source for a materially different unpublished value is allowed. The published
   atomic-value ledger remains the authority for this rule.
8. No stage selects, approves, schedules, or publishes a post.
9. Every failure records the first failed stage; unexecuted downstream stages stay
   explicitly `NOT_EVALUATED`.

Two current implementations do not fully prove their stated contract and must not
be copied:

- `workflow.prepare_research_items()` parses `published_at` but does not enforce
  that it falls inside the requested window, and permits a blank body. The
  dashboard currently calls these records body-verified before those conditions
  are checked.
- `MIN_SUCCESSFUL_SURFACES` is 4, but `invoke_scout()` continues with only three
  successful surfaces whenever ten signals exist; the test suite explicitly
  protects that behavior. The rebuild must choose one documented coverage rule,
  not retain both.

## Replacement boundary

### One composition root

Construct a `DiscoveryService` explicitly at the CLI boundary:

```text
DiscoveryService(
    surface_scouts,
    consolidator,
    momentum_scorer,
    authority_observer,
    authority_scorer,
    inventory_store,
    evidence_scouts,
    evidence_store,
    publication_history,
    clock,
    run_budget,
    recorder,
)
```

No component installs or replaces module globals. Model adapters return
observations and stable source references, never acceptance scores. All scores,
threshold decisions, exclusions, ranking, expiry checks, and route selection run
locally.

The authority observation schema uses one non-numeric level per existing axis:
`NONE`, `WEAK`, `PARTIAL`, `STRONG`, or `DIRECT`, plus a non-blank rationale bound
to the supplied topic/profile fields. Frozen local scorer version
`authority-fit-v1` maps those levels to `1, 2, 3, 4, 5` respectively and sums the
five existing axes. Momentum continues to use the existing frozen basis-value
bands. The bundle records both scorer version strings. A model response containing
a numeric score or an unknown level fails schema validation; it cannot override
the local map.

### Request contract

```json
{
  "schema_version": 1,
  "run_id": "stable non-secret run identifier",
  "as_of": "timezone-aware whole-second timestamp",
  "window_days": 7,
  "topic_scope": null,
  "authority_profile": "validated private profile projection",
  "allow_public_web": true,
  "allow_private_model_egress": true,
  "deadline_monotonic": "hard deadline owned by the orchestrator"
}
```

Validation occurs before any model call. `as_of - 7 days <= published_at <= as_of`
is the source window; `fetched_at` is not a substitute for source freshness.

### Stable records

`SurfaceSignal`

```json
{
  "signal_id": "sha256(lane + canonical_url)",
  "lane": "reddit",
  "topic": "display prose",
  "why_now": "display prose",
  "canonical_url": "https://...",
  "source": "public source",
  "published_at": "...",
  "freshness_hours": 12,
  "engagement_units": null,
  "status": "OBSERVED"
}
```

`ConversationCandidate`

```json
{
  "candidate_id": "sha256(sorted surface signal identities)",
  "topic": "display prose only",
  "surface_signal_ids": ["..."],
  "momentum_observations": {"five fixed axes": "OBSERVED or UNKNOWN"},
  "momentum_scores": {"computed locally": "0..5 or null"},
  "authority_observations": {"five fixed axes": "bounded facts/enums"},
  "authority_scores": {"computed locally": "1..5"},
  "admission": {"status": "ADMITTED", "route": "current|inventory|authority"}
}
```

`EvidenceRecord`

```json
{
  "evidence_id": "sha256(canonical_url + content_hash)",
  "canonical_url": "https://...",
  "content_hash": "64 lowercase hex characters",
  "title": "non-blank",
  "body": "non-blank body-read text",
  "source": "non-blank",
  "author": "optional",
  "published_at": "inside request window",
  "fetched_at": "timezone-aware timestamp",
  "source_quality": "primary|secondary|mixed",
  "evidence_origin": "live-body-read|verified-cache"
}
```

`AdmittedTopic` binds `candidate_id` to exact `evidence_id` values. Topic prose is
never used to reconstruct that binding downstream.

### Output contract

The service returns one `DiscoveryBundle`, even on a recoverable degraded route:

```json
{
  "schema_version": 1,
  "run_id": "...",
  "status": "PASS|FAIL",
  "route": "live|live-plus-cache|verified-cache",
  "surface_results": [],
  "ranked_candidates": [],
  "admitted_topics": [],
  "evidence_records": [],
  "candidate_evidence_bindings": [],
  "first_failure": null,
  "timing": {"started_at": "...", "elapsed_ms": 0, "budget_ms": 180000}
}
```

A `PASS` bundle guarantees:

- at least one topic is admitted;
- three to seven distinct body-verified evidence records exist;
- every evidence record is inside the requested window;
- every admitted topic used later has at least one exact evidence identity;
- every score and threshold decision can be recomputed locally from stored
  observations;
- no selected atomic value matches published history once the downstream Topic
  Value novelty gate runs.

## Deadline and recovery policy

Discovery receives 180 seconds of the 480-second end-to-end hard budget. The
orchestrator, not individual calls, owns the deadline.

| Work | Target | Hard behavior |
|---|---:|---|
| Preflight, cache, history | 5s | Local failure before egress |
| Seven surface lanes in parallel | 70s | One bounded concurrent attempt; failed lanes may retry concurrently only from remaining stage budget |
| Consolidation + authority observations + local scoring/admission | 35s | No retry that can breach the stage deadline; use a still-valid candidate snapshot if live coverage is insufficient |
| Evidence fan-out | 60s | One worker per admitted topic; retry only failed workers within remaining time, then exact verified-cache fallback |
| Validation and atomic persistence | 10s | Fail closed on any identity, body, date, or persistence error |

The 180-second value is a hard ceiling, not five independent timeout allowances.
Each adapter receives `remaining_seconds()` and must stop at the shared deadline.
Late futures are cancelled and cannot mutate state.

### Verified-cache fallback

The product-approved fallback is narrow:

1. live evidence work is attempted first;
2. only failed/missing evidence workers are retried;
3. after those retries, cached evidence may be used only if it was previously
   body-verified, its `published_at` remains in this request's seven-day window,
   its canonical URL/content hash still matches, and it is already bound to the
   admitted candidate;
4. cache selection is by exact identity binding, never lexical topic matching;
5. stale, changed, social-only, unbound, or unverifiable records are rejected;
6. insufficient valid evidence produces a visible `evidence_verification` system
   failure. It never manufactures a content result.

Persist each verified record immediately after validation, before Topic Value or
thesis generation. A later stage failure must not force the same body-read work to
be repeated.

### Published-content exclusion

The discovery service loads published atomic history at the start and forwards
its immutable snapshot to Topic Value. It may annotate obvious prior topics for
efficiency, but it must not equate a repeated source or broad topic with a repeated
atomic value. Final exclusion remains the local novelty comparison against
confirmed manually published atomic values. Review-ready but unpublished work does
not enter this history.

The rolling inventory gains explicit lifecycle fields:

```text
AVAILABLE -> SELECTED_FOR_RUN -> AVAILABLE   (run failed or draft not published)
AVAILABLE -> SELECTED_FOR_RUN -> PUBLISHED   (confirmed manual publication)
AVAILABLE -> EXPIRED                         (outside seven-day window)
```

Transitions are atomic and tied to stable candidate/evidence identities. A
`PUBLISHED` atomic value is never eligible again. Merely selecting or drafting a
candidate does not consume it.

## Failure taxonomy

| Code | Stage | Meaning | Recovery |
|---|---|---|---|
| `SURFACE_TIMEOUT` | conversation discovery | One public lane exceeded its allocation | Continue with other lanes; retry only within shared budget; use valid candidate cache if coverage becomes insufficient |
| `INSUFFICIENT_SURFACE_COVERAGE` | conversation discovery | Evidence cannot support ten defensible conversations | Valid cache or fail; never add invented topics |
| `BAD_SURFACE_SCHEMA` | conversation discovery | Adapter returned invalid data | Do not treat as no signal; record and fail/cache |
| `CONSOLIDATION_TIMEOUT` | conversation discovery | Non-web clustering exceeded allocation | Valid candidate cache or fail |
| `NO_ADMISSIBLE_TOPIC` | topic admission | All topics missed documented floors or published-value exclusion | Legitimate evaluated rejection, not availability failure |
| `EVIDENCE_TIMEOUT` | evidence verification | One or more topic evidence workers exceeded allocation | Retry missing workers, then exact verified cache |
| `INSUFFICIENT_VERIFIED_EVIDENCE` | evidence verification | Fewer than three valid records remain | Fail closed |
| `STALE_EVIDENCE` | evidence verification | `published_at` is outside the request window | Reject record |
| `EMPTY_OR_UNREAD_BODY` | evidence verification | No inspectable source body | Reject record |
| `EVIDENCE_IDENTITY_DRIFT` | evidence verification | URL/hash no longer matches binding | Fail closed and name identity |
| `DEADLINE_EXHAUSTED` | orchestration | Shared 180-second discovery budget ended | Stop all work; persist first failure and timings |

`NO_SIGNAL` is a valid observed surface result. It must not be conflated with
timeout, malformed response, provider failure, or cancellation.

## Verification tests

All tests use repository-native `unittest` and public composition entry points.

### Pure contract tests

1. Reject a blank body, invalid URL, invalid timestamp, future timestamp, and
   source older than the requested seven-day window.
2. Given the same observations in any input order, produce byte-identical scores,
   ranking, eligibility, stable IDs, and tie-break order.
3. Keep an unobserved axis `UNKNOWN`/`null`; prove it never becomes zero.
4. Prove authority adapters cannot provide or override scores; only the local
   scorer can.
5. Prove social-only evidence may affect momentum but cannot enter factual
   evidence bindings.

### Concurrency and budget tests

6. Launch all seven surface lanes concurrently and prove wall time follows the
   slowest lane, not their sum.
7. Time out two lanes, preserve five successful lanes, and complete without
   changing deterministic rank order.
8. Make a retry consume the remaining budget; prove no second retry starts and all
   futures are cancelled by 180 seconds under a fake monotonic clock.
9. Time out consolidation and prove only an unexpired identity-valid candidate
   snapshot can recover it.
10. Assert the complete discovery service never supplies an adapter a deadline
    beyond the orchestration deadline.

### Inventory and evidence recovery tests

11. Evidence Scout timeout + three exact body-verified in-window cached records =
    `PASS`, route `verified-cache`, with cache provenance recorded.
12. The same records at seven days plus one second = fail with `STALE_EVIDENCE`.
13. A changed content hash = fail with `EVIDENCE_IDENTITY_DRIFT`.
14. A cache record related only by topic prose = ineligible.
15. Persist successful evidence from a run that later fails Topic Value; the next
    run can reuse it while still inside the window.
16. A selected-but-unpublished candidate returns to `AVAILABLE`; a confirmed
    published atomic value becomes permanently ineligible; a reused source with a
    materially different atomic value remains possible.

### Installed end-to-end tests

17. Invoke `./bin/linkedin-os discover` through the public composition root with
    stubbed external adapters and both V1 install layers active; prove discovery
    reaches Topic Value with exact candidate/evidence identities.
18. Reproduce the reported case: current momentum has no eligible topic, five
    inventory topics are admitted, live evidence times out, valid in-window bound
    evidence is reused, and Topic Value is reached within budget.
19. Repeat the same fixture three times and prove stable scoring, identity binding,
    state transitions, and artifacts.
20. Make verified cache insufficient and prove the dashboard reports
    `evidence_verification: FAIL`, preserves earlier `PASS` stages, and leaves all
    later stages `NOT_EVALUATED`.

## Implementation split

This packet can be built independently in five small units before plumbing:

1. schemas, stable identities, clock, and shared deadline;
2. explicit surface adapter fan-out and status taxonomy;
3. observation-only consolidation/authority adapters plus local scorers;
4. versioned inventory/evidence stores and lifecycle transitions;
5. parallel evidence acquisition, exact verified-cache recovery, and public-entry
   integration tests.

No acceptance threshold, Topic Value rule, claim-support similarity, voice rule,
hard gate, or publishing boundary needs to change.
