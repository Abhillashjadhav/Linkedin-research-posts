# Packet 01 — evidence Scout timeout

## Verdict

The live failure is an availability/latency failure at the second research
boundary, not a product-quality rejection:

```text
Conversation discovery  PASS
Topic admission         PASS (rolling seven-day topic inventory)
Evidence verification   FAIL: Scout timed out.
Everything downstream   NOT_EVALUATED
```

`model_runtime.invoke_structured()` killed the evidence Scout subprocess after
420 seconds and converted `subprocess.TimeoutExpired` to
`WorkflowError("Scout timed out.")`. The dashboard correctly attributed the first
blocker. No Topic Value, thesis, Writer, Critic, or final gate ran.

## Exact installed call path

The public command is composed in this order:

1. `bin/linkedin-os discover` resolves the installed V1 discovery entry point.
2. `daily_discovery_cli` installs discovery, surface, individual-launch, and V1
   consumability overlays, then assigns
   `daily_spine_cli.momentum = momentum_surface_parallel`.
3. `daily_spine_cli.command()` runs conversation discovery:
   `momentum_surface_parallel.invoke_scout()` -> seven shallow surface workers in
   parallel -> consolidation -> local momentum ranking ->
   `momentum.score_authority_fit()`.
4. `update_candidate_inventory()` persists qualified topic descriptions, and
   `select_topic_scope()` admits momentum topics, the rolling topic inventory, or
   the authority-fit fallback.
5. `daily_spine_cli._invoke_signal_scout()` starts a new, independent Codex call
   with live web search. It asks one high-reasoning model call to find five sources,
   read every source body, and return the complete 3–7-item research schema.
6. `model_runtime.invoke_structured(... timeout=420, stage_label="Scout")` reaches
   the subprocess timeout. It raises before an output file can be accepted.

The successful conversation-discovery Scout and the failed evidence Scout are
therefore different calls with different contracts and resilience behavior.

## Why conversation discovery can pass while evidence verification fails

| Boundary | Work shape | Runtime behavior | Failure tolerance |
|---|---|---|---|
| Surface discovery | Seven shallow, source-family-specific retrieval calls | Parallel, medium reasoning, 180 seconds per attempt | Each lane retries a timeout/unavailable result once; partial lane coverage can continue when at least 10 signals exist |
| Consolidation | No-web clustering of supplied surface summaries | One 150-second call | Fails closed |
| Authority fit | Scores five topic summaries; no web | One call with a 420-second cap | Fails closed |
| Evidence Scout | Searches across admitted topics, opens sources, and returns five full research records | One high-reasoning, live-web call with a 420-second cap | No retry, no partial result, no cache fallback |

The screenshot's `rolling seven-day inventory` describes cached **topic
descriptions**, not cached source bodies. The candidate inventory cannot satisfy
the evidence contract.

## Current timeout and cache facts

- The evidence Scout has exactly one 420-second attempt. `_invoke_signal_scout()`
  has no timeout loop and no timeout classification of its own.
- A timeout discards all in-progress work because structured output is accepted
  only after the subprocess exits successfully and the JSON output file parses.
- `research_items` in SQLite can contain prior exact URL/content-hash records, but
  the discovery command never queries it as an evidence fallback.
- New source records are inserted into SQLite only **after** Topic Value and thesis
  search succeed. A successful evidence Scout followed by a later failure does not
  populate the reusable research database.
- `candidate-inventory.json` is written before evidence verification. It contains
  topic text, scores, and representative momentum URLs, but no verified bodies and
  no exact topic-to-body binding.
- Existing surface artifacts contain short momentum observations, not factual
  source bodies. Promoting them to research evidence would weaken the contract.
- There is no command-level monotonic deadline. Current nominal worst-case caps
  before Topic Value are about 1,350 seconds: 360 for two parallel surface attempts,
  150 for consolidation, 420 for authority fit, and 420 for evidence verification.
  Later 300/420-second model caps make a guaranteed 7–8-minute end-to-end run
  impossible under the current independent timeout design.

## Secondary contract defect found during the audit

`workflow.prepare_research_items()` requires title, source, timestamp, URL, and a
valid source-quality label, but it does **not** require `body` to be non-blank.
`daily_spine_cli` nevertheless records the stage as "body-verified signal(s)
prepared." A selected Topic Value candidate is checked later by
`v1_gates.evaluate_research_trust()`, but the evidence-stage PASS claim is stronger
than its deterministic validation. The rebuilt evidence boundary must reject blank
bodies before recording PASS.

## Root cause

Primary: the evidence step is an all-or-nothing, single high-latency web/model call
whose timeout equals almost the entire product latency budget.

Contributing causes:

1. no retry at this boundary;
2. no eligible body-verified fallback despite a product-approved seven-day reuse
   window;
3. verified evidence is persisted too late to survive downstream failures;
4. cached topics and cached evidence have no stable association;
5. no global deadline reserves time for Topic Value, thesis, drafting, and Critic;
6. the deterministic pre-gate does not actually require a non-blank body.

This is not fixed by increasing 420 seconds. That would directly violate the
7–8-minute outcome without improving bounded recovery.

## Smallest safe recovery design

Add one evidence-resolver boundary around the existing Scout; do not change Topic
Value or any downstream gate.

### 1. One explicit stage budget

Proposed constants, owned together:

```python
EVIDENCE_STAGE_BUDGET_SECONDS = 120
EVIDENCE_PRIMARY_TIMEOUT_SECONDS = 75
EVIDENCE_RETRY_TIMEOUT_SECONDS = 45
MIN_VERIFIED_EVIDENCE = 3
MAX_VERIFIED_EVIDENCE = 7
```

Use a monotonic command deadline. Each subprocess receives the smaller of its
attempt cap and the remaining stage/global time. Never start a retry that consumes
the reserve assigned to later stages. The complete rebuild still needs a global
480-second scheduler; this packet only bounds evidence verification to 120 seconds.

The two live attempts keep the same model family, web capability boundary, admitted
scope, output schema, and source-quality rules. A timeout or provider-unavailable
result is retryable. Invalid schema, unsafe URL, invalid timestamp, blank body, or
content-integrity failure is not converted into a cache success; those failures
remain fail-closed.

### 2. Persist verified evidence immediately

After deterministic validation succeeds, write an owner-only evidence snapshot
before Topic Value begins and insert the records into the private research store.
The snapshot must contain:

- the exact admitted candidate identities and a deterministic scope fingerprint;
- requested window start/end and collection timestamp;
- canonical URL and recomputed content hash for every record;
- the admitted candidate identity or identities supported by each record;
- title, non-blank body, source, author, publication timestamp, source quality, and
  fetch timestamp;
- route and attempt provenance (`live-primary`, `live-retry`, or
  `verified-cache`).

The stable candidate identity should be persisted with the rolling topic inventory.
Until that exists, cache fallback may use only an exact scope fingerprint built
from normalized admitted topic text plus sorted representative URLs. It must not use
fuzzy topic matching or sweep unrelated recent rows from SQLite.

### 3. Cache fallback only after bounded live attempts

When both eligible live attempts fail transiently, load the newest matching
evidence snapshot. Accept it only when all of these are true:

1. its scope fingerprint matches the current admitted scope, and every selected
   record is linked to at least one currently admitted stable candidate identity;
2. every selected record's `published_at` is no earlier than `as_of - days` and no
   later than `as_of`;
3. every record has a non-blank body, canonical public HTTP(S) URL, and allowed
   source-quality value;
4. recomputing the content hash produces the stored hash;
5. URL/hash identities are distinct;
6. 3–7 records remain after validation;
7. the stored origin is a prior body-verified private import, never a social
   momentum observation or synthetic fixture.

If any condition fails, evidence verification fails visibly. Cache age, exact
identities, live attempt outcomes, and fallback reason belong directly on the run
dashboard.

For a one-time bootstrap, an old successful run may be converted to the new snapshot
only when its `run-dashboard.json` admitted-topic set, `theses.json` raw signals, and
SQLite URL/hash rows all agree exactly. Do not infer a link from lexical similarity.

### 4. Keep publication novelty separate

Evidence reuse is not atomic-value reuse. Cached bodies may support a materially
new value, but `v1_completion.load_published_atomic_values()` and the locked Topic
Value novelty contract must still evaluate every candidate. An atomic value at or
above the existing similarity threshold against published history must not reach
drafting, regardless of evidence route. The cache must never mark a topic/value as
novel and must never waive that gate.

## Deterministic tests

1. Primary live attempt succeeds with 3, 5, and 7 valid bodies; no retry/cache read.
2. Primary timeout, retry succeeds; route is `live-retry`, with 75/45 caps asserted.
3. Both live attempts time out; a matching current snapshot supplies 3–7 records and
   records route `verified-cache`.
4. Both attempts time out and cache has only two valid records; fail closed with
   exact count and all downstream stages `NOT_EVALUATED`.
5. Reject individually: expired source, future source, blank body, social-only
   factual source, invalid URL, invalid quality, changed body/hash, duplicate URL,
   duplicate content hash, synthetic fixture, and mismatched scope fingerprint.
6. Persist a live-verified snapshot before forcing Topic Value to fail; the snapshot
   remains available for the next run.
7. Use a fake monotonic clock to prove the retry is skipped when the remaining
   global reserve is insufficient and that no attempt receives an over-budget
   timeout.
8. Seed a published atomic value, recover its evidence from cache, and make the
   selector propose that value again; novelty blocks it and the dashboard names
   `atomic_value_novelty`.
9. Verify deterministic evidence-stage PASS requires every emitted `signal-*` to
   have a non-blank body and an exact URL/hash identity.
10. Verify cache fallback cannot use the rolling candidate inventory or surface
    summary files as body evidence.

## Installed-runtime tests

Run in a fresh Python subprocess so all production `install()` calls are active and
use public entry points only:

1. Invoke `daily_discovery_cli.main()` with stage-labelled stubbed model responses:
   conversation discovery passes, evidence primary/retry time out, an exact current
   cache snapshot is loaded, Topic Value receives those exact signal identities,
   and execution reaches the public drafting/Critic boundary.
2. Repeat with a cache scope mismatch; assert evidence verification is FAIL and
   Topic Value, thesis, drafting, and final evals are `NOT_EVALUATED`.
3. Repeat with an expired record and with a body/hash drift; both fail closed and
   name the bad identity.
4. Seed the published atomic-value ledger and return the same atomic value from the
   installed Topic Value selector; assert no drafting child starts.
5. Assert the run dashboard exposes live attempt durations, configured budgets,
   cache route/age, selected URL/hash identities, and the first blocker without
   provider output or body text.
6. Fake the monotonic clock across the installed command and assert it never starts
   work after the 480-second deadline.

CI should keep these deterministic. Release validation should additionally execute
three consecutive live runs under the owner-approved 7–8-minute budget, including
at least one forced timeout/cache-recovery run. The release count is enforced by
the orchestrator, not implemented by Scout.

## Course correction for the current flow

The bounded two-attempt resolver plus exact verified-snapshot fallback is the
smallest defensible current-flow fix. It preserves 3–7 body-verified sources, the
requested seven-day window, fail-closed integrity, and published atomic-value
novelty. It also makes the existing screenshot recoverable when a valid matching
snapshot exists.

It does **not** by itself guarantee 7–8-minute end-to-end latency. The orchestrator
must replace independent per-call ceilings with one global budget and stage
reserves; otherwise later 420-second calls can still violate the product outcome.
