# LinkedIn OS local rebuild — orchestrator plan

## Two isolated tracks

| Track | Purpose | Branch/workspace | Remote policy |
| --- | --- | --- | --- |
| 1 — repair | Restore the existing workflow after the evidence Scout timeout | `fix/evidence-scout-timeout-recovery` in a separate worktree | May be offered as a runnable repair after verification; no merge without approval |
| 2 — rebuild | Build a contract-first replacement component by component | `rebuild/contract-first-workflow` | WIP branch may be pushed for visibility; no merge until runnable and release-verified |

Track 2 never imports uncommitted Track 1 code. A repair may be deliberately
ported only after its contract and tests pass against the clean architecture.

## Outcome contract

The authoritative product contract is in `docs/CONTRACT_FIRST_REBUILD.md`.
The local command must repeatedly complete all executable stages in 420 seconds
target / 480 seconds hard maximum. Its terminal product outcome is either:

- `READY_FOR_HUMAN_REVIEW`, with one evidence-bound candidate; or
- `BLOCKED`, because a named product/quality contract legitimately failed.

Timeouts, wrong identity, signature drift, inconsistent acceptance, missing
observability, and invalid state transitions are system failures—not acceptable
blocked outcomes.

## The CEO/orchestrator

One `RuntimePlan` owns composition, dependencies, capabilities, deadlines,
contract versions, and terminal state. It executes ten typed stages through one
public local entry point. No module patches another module at import time.

```text
DISCOVERY -> TOPIC_ADMISSION -> EVIDENCE -> TOPIC_VALUE -> THESIS
          -> DRAFTING -> CRITIC_AND_GATES -> FINAL_EVALS -> PACKAGE
          -> HUMAN_PUBLICATION_LIFECYCLE
```

Independent work inside a stage may run concurrently. Stage transitions are
serial and consume immutable envelopes. The first blocker is immutable; every
unreached downstream stage records `NOT_EVALUATED` with that blocker ID.

## Propagation rule

Every shared product rule is one versioned executable contract with:

1. exactly one implementation;
2. a stable contract ID, version, and SHA-256;
3. declared producers and consumers;
4. declared persisted artifacts and dashboard projections;
5. boundary, negative, replay, and installed-runtime tests;
6. an inventory assertion that fails when a consumer is added or omitted.

Consumers receive the immutable decision; they never recompute it. This applies
to acceptance, evidence identity/freshness, novelty, gate status, and run state.

The acceptance contract is fixed:

```text
total >= 18/25
hook_strength >= 4
middle_escalation >= 3
earned_closer >= 3
specificity_and_source_quality >= 3
voice_fidelity >= 4
honesty, citation, proof, privacy, relevance all pass
```

Scores 21–25 also pass when every floor/gate passes. `24/25` is an optimization
target only. It cannot appear as an eligibility condition in any producer,
package, dashboard, performance validator, learning reader, or alternate route.

## Ten independently verifiable build packets

### T01 — contracts and immutable envelopes

```yaml
objective: Define versioned schemas for RunContext, StageResult, EvidenceRef, TopicValueDecision, ThesisDecision, CandidateDecision, AcceptanceDecision, and PackageReceipt.
depends_on: []
inputs: product contract and packets 01-10
write_boundary: new local rebuild package and its contract tests only
definition_of_done: invalid/missing/extra fields fail; every identity and contract hash survives round-trip; consumer inventory is exhaustive
verification_owner: T10
```

### T02 — CEO runtime plan and deadline scheduler

```yaml
objective: Implement the explicit stage registry, dependency graph, capability plan, 420/470/480-second deadlines, cancellation, and idempotent resume.
depends_on: [T01]
inputs: packet 07
write_boundary: orchestrator modules and scheduler tests
definition_of_done: no work starts without downstream reserve; illegal transitions fail; first blocker is immutable; no import-time monkey patching
verification_owner: T10
```

### T03 — conversation discovery and topic admission

```yaml
objective: Collect broad public conversations, locally score momentum/authority fit, and persist stable admitted topic identities.
depends_on: [T01, T02]
inputs: packet 02
write_boundary: discovery adapters, deterministic ranking, topic inventory
definition_of_done: partial surfaces are explicit; scores are local; admitted topics carry stable identity; stage stays within its plan budget
verification_owner: T09
```

### T04 — verified evidence resolver and cache

```yaml
objective: Resolve 3-7 body-read sources with exact URL/hash identity, bounded retries, and exact-scope same-window fallback.
depends_on: [T01, T02, T03]
inputs: packets 01, 03, 08
write_boundary: evidence adapter, verifier, private snapshot/store
definition_of_done: blank/stale/future/drifted/duplicate/untrusted evidence fails; snapshot persists before Topic Value; timeout recovery fits its reserve
verification_owner: T09
```

### T05 — Topic Value, novelty, and thesis binding

```yaml
objective: Evaluate candidates independently, exclude published atomic values, and bind every thesis to one passed Topic Value decision and exact evidence refs.
depends_on: [T01, T04]
inputs: packet 04
write_boundary: Topic Value and thesis components
definition_of_done: one failed sibling cannot veto unrelated passers; multi-source thesis works; generated prose is never an identity; existing thresholds stay fixed
verification_owner: T09
```

### T06 — Writer, Narrative Editor, and voice

```yaml
objective: Generate three grounded candidates, edit safely, and enforce measured v2 voice on the exact bytes sent to every Critic call.
depends_on: [T01, T05]
inputs: packet 05 and voice v2 assets
write_boundary: writer/editor/voice components
definition_of_done: claim IDs remain a selected-evidence subset; hook checks both lines after every mutation; missing voice profile fails closed; no runtime wordfreq dependency
verification_owner: T09
```

### T07 — Critic, deterministic gates, and acceptance

```yaml
objective: Produce anchored five-axis scores, run hard gates, and emit the one immutable AcceptanceDecision used everywhere.
depends_on: [T01, T06]
inputs: packet 05
write_boundary: critic adapter, gates, acceptance contract
definition_of_done: exact 18/per-axis/hard-gate boundaries pass; 24 is target-only; every shortfall is recorded; all routes consume the same decision
verification_owner: T09
```

### T08 — final evals, dashboard, and package

```yaml
objective: Join stage evidence into one append-only trace and create a private human-review package only from an accepted decision.
depends_on: [T01, T02, T07]
inputs: packets 06, 08
write_boundary: journal, dashboard projection, package writer
definition_of_done: exact first blocker; downstream linkage; v2 rubric and acceptance hashes recorded; package never recomputes eligibility; publishing remains disabled
verification_owner: T10
```

### T09 — security and component verification

```yaml
objective: Test every producer/consumer boundary, capability restriction, cache adversary, gate edge, and installed local composition.
depends_on: [T01, T03, T04, T05, T06, T07]
inputs: packets 08, 09
write_boundary: adversarial, contract, integration, and installed-runtime tests
definition_of_done: all component contracts pass independently; no private/model/web boundary violation; semantic inventory detects stale consumers
verification_owner: T10
```

### T10 — integration, release streak, and publication lifecycle

```yaml
objective: Join the ten stages, verify consecutive live executions, and atomically exclude a manually published atomic value from future selection.
depends_on: [T02, T08, T09]
inputs: packets 07, 09, 10
write_boundary: local composition root, release verifier, publication ledger
definition_of_done: public entry point meets 420s target/480s hard cap; at least one READY package; legitimate BLOCKED outcomes remain complete; publication receipt and novelty exclusion commit together
verification_owner: independent final reviewer
```

## Dependency waves

| Wave | Parallel work | Join condition |
| --- | --- | --- |
| A | T01, test fixtures, adapter interfaces | Contract schemas frozen locally |
| B | T02, T03, T04 foundations | Typed stage envelopes and budgets pass |
| C | T05, T06, T07 | One evidence-bound candidate receives one acceptance decision |
| D | T08, T09, publication ledger | Trace, security, and package contracts pass |
| E | T10 integration and live trials | Consecutive-run release record complete |

## Architecture-review decisions closed

The product owner requires exactly three consecutive live runs for release
success. The release verifier therefore sets
`REQUIRED_CONSECUTIVE_LIVE_RUNS = 3`; any system failure or release-candidate
change resets the streak. The first-comment route uses its own axes, but its total
eligibility floor is `>= 18/25` and its evidence, anti-slop, and artisanal checks
remain mandatory pending separate calibration. `18` is a floor, not a ceiling,
and `24/25` is not an eligibility threshold on either route.
