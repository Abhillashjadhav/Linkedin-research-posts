# Packet 06 — Runtime orchestration and observability

## Mission

Build the one local composition root that runs the contract-first workflow, enforces
the seven-to-eight-minute end-to-end budget, and produces an exact durable account
of what ran. A failed run must identify one immutable first blocker. Every later
stage must remain `NOT_EVALUATED` and name that blocker as the reason it did not run.

This packet owns runtime composition, stage transitions, time budgets, failure
classification, the canonical event journal, the run snapshot, and dashboard
projection. It does not own discovery ranking, evidence rules, Topic Value, thesis
quality, writing, Critic scoring, or acceptance policy.

## Product contract carried into this packet

- Target runtime: normally complete in 7 minutes; hard stop at 8 minutes.
- Local success requires three consecutive live runs. The owner-approved value is
  embedded in the immutable release plan and cannot be reduced by an operator flag.
- A legitimate Topic Value, thesis, voice, quality, or hard-gate rejection is an
  evaluated product outcome. A timeout, unavailable dependency, signature mismatch,
  identity mismatch, hidden stage, or missing observation is a system failure.
- Body-verified evidence may be reused only while it remains inside the requested
  seven-day window. Previously published atomic value must not be selected again.
- No acceptance, evidence, privacy, or voice gate may be weakened to complete a run.
- Human review remains separate. The runtime never publishes.

## Current-runtime audit

### Installation and dispatch

The shipped launcher does not have one application composition. It creates two
different monkey-patched runtimes in fresh interpreters.

| Path | Current installation order |
| --- | --- |
| `discover` | `v1_gates` → `v1_completion` → `topic_value_id_contract` → import `daily_discovery_cli`, which installs `discovery_runtime_tuning` → `surface_scout_runtime_tuning` → `individual_launch_runtime_tuning` → `v1_consumability`, replaces `daily_spine_cli.momentum`, and replaces `daily_spine_cli.command` |
| `draft` | `v1_gates` → `v1_completion` → `topic_value_id_contract` → `v1_length_policy` → `single_topic_codex` → `human_readability` → `critic_anchor_retry` → `actionable_diagnostics` → `social_media_gate_policy` → `v1_consumability` → conditional `v1_runtime_tuning` → `quality_optimizer` → import `integrated_cli` → rewire integrated dispatch → wrap with `standalone_draft_observability` |

The installed-runtime probe currently observes 32 discovery replacements and 47
draft replacements. Signature compatibility tests are valuable, but they prove only
call compatibility. They do not prove semantic compatibility, shared configuration,
stage order, identity continuity, or budget continuity.

Additional dispatch findings:

- `discover --generate-post` launches `bin/linkedin-os draft` as an unbounded child,
  so one user run crosses two separately installed runtimes.
- The parent infers child failure by scanning captured text for the last `ERROR:`
  line instead of consuming a typed result.
- `--dry-run` dispatches to `python -m authority_os` and bypasses the installed live
  stack. A passing dry run therefore does not prove the live composition.
- `--run-spec` conditionally omits `v1_runtime_tuning`, creating another runtime
  variant.
- The current overlay-inventory test can detect an added installer only when the
  hand-maintained expected list is also reviewed. It cannot make the composition
  self-describing.

### State and first-blocker handling

Useful behaviour already exists: all workflow stages start as `NOT_EVALUATED`, the
first `FAIL` sets `stopped_at` once, and downstream cards stay visible. The rebuild
must preserve that operator experience.

The implementation is nevertheless a mutable dictionary rather than a state
machine:

- `mark_run_stage()` permits stages to be updated out of order or more than once.
- It does not enforce `NOT_EVALUATED → RUNNING → terminal` transitions.
- `PASS`, `FAIL`, `BLOCKED`, `REJECTED`, and `UNAVAILABLE` share one status set even
  though some describe stages, some candidates, and some dependencies.
- The dashboard recomputes the first blocker from list order rather than rendering
  a canonical, immutable blocker record.
- Downstream stages say only `stage was not reached`; they do not identify the
  upstream blocker that prevented evaluation.
- The UI calls every `NOT_EVALUATED` item an “observability gap.” Downstream
  non-evaluation after a blocker is expected control flow, not missing telemetry.
- If snapshot or HTML persistence raises while handling another failure, the
  observability error can mask the original blocker.
- A process crash during a model call leaves no durable `RUNNING` event because
  stages are generally marked only after the blocking call returns.

### Budgets

The current values do not compose into the product budget:

- Seven surface scouts may each use 180 seconds twice; consolidation may use another
  150 seconds.
- Evidence verification receives a fresh 420-second timeout.
- Thesis generation and thesis criticism each receive 420 seconds and can repeat for
  three cycles.
- The drafting child has no parent-enforced timeout.
- Each call owns a relative timeout; no call knows the run deadline or remaining
  stage budget.

The observed `Scout timed out.` failure is therefore accurate but insufficient. It
does not record elapsed time, attempt count, remaining run budget, fallback decision,
or whether eligible cached evidence was found.

### Dashboard and evaluator provenance

- `run-dashboard.json`, `eval-dashboard.json`, and the HTML view provide strong local
  visibility and should remain private, owner-only artifacts.
- The Critic audit ledger records the live rubric digest correctly through
  `workflow.CRITIC_RUBRIC_PATH`.
- `daily_spine_cli.evaluator_versions()` still hashes
  `critic-rubric-v1.json` by filename even though the live Critic path is v2.
- `monitoring_export.py` likewise points its prompt digest at the v1 file.
- Surface timeout is retained in details and reason text but is projected to the
  generic decision status `UNAVAILABLE`; this loses a useful machine-readable
  distinction.

## Clean runtime design

### One explicit composition root

`bin/linkedin-os` must do only environment selection and then invoke one Python
entrypoint, for example `authority_os.app:main`. The entrypoint constructs an
immutable `RuntimePlan` and injects explicit stage implementations into an
`Orchestrator`.

```python
@dataclass(frozen=True)
class RuntimePlan:
    plan_version: str
    stages: tuple[StageSpec, ...]
    run_budget_seconds: int
    target_budget_seconds: int
    model_assignments: Mapping[str, ModelConfig]
    contract_digests: Mapping[str, str]

@dataclass(frozen=True)
class StageSpec:
    id: StageId
    input_schema: str
    output_schema: str
    budget_seconds: int
    execute: StageCallable
```

Requirements:

1. No import-time `install()` calls or module-global function replacement.
2. No conditional composition based on `--dry-run` or `--run-spec`. Those flags
   select injected adapters or inputs within the same stage graph.
3. The same composition root serves installed CLI tests and live execution.
4. Standalone `draft` may begin at `evidence_binding`, but it uses the same stage
   implementations and policies as the full run.
5. Prefer in-process typed stage calls. If process isolation remains necessary, the
   child receives a versioned request containing `run_id`, `plan_sha256`, exact
   evidence identity, and absolute monotonic deadline, then returns a versioned JSON
   result. Logs are diagnostic artifacts, never the API.
6. The plan, ordered stage registry, model configs, contract hashes, and CLI version
   are hashed and recorded before the first stage starts.

The legacy overlay probes remain temporarily as regression protection for the
repair flow. The rebuild is complete only when its production path has zero runtime
overlays.

### Canonical ordered stage registry

| Order | Stage ID | Success output |
| ---: | --- | --- |
| 0 | `preflight` | validated permissions, paths, model availability, profile, and run plan |
| 1 | `conversation_discovery` | ranked current conversations with per-surface provenance |
| 2 | `topic_admission` | admitted unused topics or inventory route |
| 3 | `evidence_verification` | 3–7 exact, body-verified evidence records |
| 4 | `topic_value` | selected situations and all recorded gate decisions |
| 5 | `thesis_search` | ranked qualifying theses with stable evidence references |
| 6 | `evidence_binding` | immutable manifest verified against exact stored identities |
| 7 | `drafting` | candidate drafts and writer traces |
| 8 | `final_evals` | Critic scorecards plus deterministic hard-gate results |
| 9 | `packaging` | private `READY_FOR_HUMAN_REVIEW` package and dashboard artifacts |

No stage can be skipped implicitly. A deliberate standalone start records earlier
stages as `NOT_APPLICABLE` in a separate applicability field; it must not claim they
were evaluated.

## State-machine contract

### Separate vocabularies

Stage status:

- `NOT_EVALUATED`: execution has not started.
- `RUNNING`: a durable start event exists and the stage owns the current transition.
- `PASS`: the stage output validated against its contract.
- `FAIL`: the stage reached a terminal blocker.

Candidate decision:

- `PASS`, `REJECTED`, `UNAVAILABLE`, or `NOT_EVALUATED`.

Run outcome:

- `RUNNING`
- `READY_FOR_HUMAN_REVIEW`
- `REJECTED_BY_PRODUCT_GATE`
- `SYSTEM_FAILED`
- `CANCELLED`

`BLOCKED` is a failure kind, not an ambiguous stage status. Existing dashboards may
display a `BLOCKED` badge during migration, but canonical storage uses `FAIL` plus a
typed failure record.

### Legal transitions

1. Create a run with every applicable stage `NOT_EVALUATED`.
2. Append and fsync `stage_started`; transition exactly the next stage to `RUNNING`.
3. A running stage may emit any number of progress, attempt, warning, candidate, and
   artifact events.
4. It terminates once as `PASS` or `FAIL`.
5. A `PASS` validates and stores its versioned output before the next stage starts.
6. A `FAIL` atomically stores `first_blocker` if none exists. That field is immutable.
7. No later stage starts. Each remains `NOT_EVALUATED` with:
   `reason_code=UPSTREAM_BLOCKER`, `blocked_by_stage`, and `blocked_by_failure_id`.
8. A stage cannot move from a terminal state, run twice, or be completed out of
   order. Resume is a new attempt recorded under the same run only when its input and
   plan hashes match; otherwise it is a new run.
9. Finalization derives the run outcome from the failure class, never from a child
   exit code alone.

### Immutable first-blocker record

```json
{
  "failure_id": "fail-0001",
  "stage": "evidence_verification",
  "kind": "DEPENDENCY_TIMEOUT",
  "code": "EVIDENCE_SCOUT_DEADLINE_EXCEEDED",
  "message": "Evidence Scout exhausted its stage budget after 2 attempts.",
  "expected": "3–7 body-verified records inside the seven-day window",
  "observed": "0 fresh records; 0 eligible cached records",
  "retryable": true,
  "attempts": 2,
  "elapsed_ms": 85012,
  "stage_budget_ms": 85000,
  "run_remaining_ms": 274988,
  "artifact_refs": ["attempt-evidence-verification.jsonl"]
}
```

Messages exposed to the operator must be exact enough to act on but must not contain
provider stderr, credentials, ignored private content, or paths outside the private
run folder.

## Failure taxonomy

| Kind | Examples | Retry/fallback | Final outcome when terminal |
| --- | --- | --- | --- |
| `PRODUCT_REJECTION` | no admissible unused topic; no thesis clears locked bar; voice or acceptance axis misses; honesty/citation/proof/privacy/relevance fails | Only the bounded product retry already defined by that stage; never weaken a bar | `REJECTED_BY_PRODUCT_GATE` |
| `DEPENDENCY_TIMEOUT` | web/model call exceeds its attempt deadline | Retry or eligible evidence fallback while stage and run budgets remain | `SYSTEM_FAILED` |
| `DEPENDENCY_UNAVAILABLE` | provider could not start, rate limit, network unavailable | Same bounded policy; record provider-neutral code | `SYSTEM_FAILED` |
| `INVALID_INPUT` | missing permission, invalid profile, unsafe path, unavailable configured model | No automatic repair | `SYSTEM_FAILED` |
| `CONTRACT_VIOLATION` | invalid JSON/schema, lost argument, output count mismatch, illegal transition | No retry unless a stage explicitly owns one corrective generation cycle | `SYSTEM_FAILED` |
| `IDENTITY_VIOLATION` | selected URL/hash absent or changed; topic substituted for evidence identity | Never fall back to approximate retrieval | `SYSTEM_FAILED` |
| `INTEGRITY_REJECTION` | evidence stale, not body-verified, published atomic value reused, privacy constraint fails | Use another explicitly eligible candidate only; never reinterpret the rule | Product rejection if candidate exhaustion is legitimate; otherwise system failure for corrupted state |
| `BUDGET_EXHAUSTED` | global monotonic deadline reached | None | `SYSTEM_FAILED` |
| `CANCELLED` | SIGINT/SIGTERM or explicit operator cancellation | None | `CANCELLED` |
| `OBSERVABILITY_FAILURE` | journal, snapshot, artifact manifest, or HTML projection failure | See durability rules below | `SYSTEM_FAILED` when canonical proof is lost; derived-view failure may be degraded but cannot count as a successful release run |

Do not classify errors by searching human-readable strings such as `"timed out"`.
Adapters must raise a typed `StageFailure` containing `kind`, `code`, safe message,
retryability, and structured details. Unexpected exceptions become
`CONTRACT_VIOLATION/UNEXPECTED_EXCEPTION` after safe redaction.

Per-surface timeout is not automatically the first blocker. It is a dependency
event. It becomes the stage blocker only when the stage cannot satisfy its explicit
coverage/output contract through other surfaces or allowed fallback.

## Deadline and budget contract

Use `time.monotonic_ns()` for enforcement and UTC only for human timestamps.

- Target end-to-end duration: 420 seconds.
- Hard end-to-end deadline: 480 seconds.
- Reserve 10 seconds for final journal/snapshot/dashboard persistence.
- Every adapter receives a `Budget` object; it cannot choose an independent timeout.
- Call timeout is `min(attempt_cap, stage_remaining, run_remaining - reserve)`.
- Retries consume the original stage allocation; they never extend it.
- Parallel work shares one stage deadline. A thread/process completing late cannot
  mutate state after the stage terminal event.
- The drafting child, if retained, must run in a process group and be terminated at
  its deadline. The parent must still persist the exact timeout blocker.

Initial allocation for integration tests (subject to measurement, not gate changes):

| Stage | Hard allocation |
| --- | ---: |
| Preflight | 10 s |
| Conversation discovery | 100 s |
| Topic admission | 5 s |
| Evidence verification including reuse decision | 85 s |
| Topic Value | 40 s |
| Thesis search | 65 s |
| Evidence binding | 5 s |
| Drafting | 100 s |
| Final evals | 50 s |
| Packaging/dashboard reserve | 10 s |
| **Total** | **470 s** |

The remaining 10 seconds is process-shutdown margin. Faster stages do not grant a
stage an unlimited timeout; the orchestrator may lend unused time only up to a named
attempt cap and never beyond the 480-second run deadline. Runtime measurements must
be reported as p50, p90, and maximum by stage across the consecutive live trials.

## Durable observability contract

### Canonical artifacts

Each owner-only run folder contains:

- `run-plan.json`: immutable plan, stage order, budgets, configs, and digests.
- `events.jsonl`: append-only canonical journal, fsynced per terminal event.
- `run-state.json`: atomic snapshot derived from the journal.
- `artifact-manifest.json`: relative paths, schema versions, sizes, and SHA-256.
- `eval-dashboard.json`: deterministic dashboard projection.
- `eval-dashboard.html`: escaped, zero-network local view.
- Stage-specific private inputs, outputs, and attempt traces.

The journal is authoritative. JSON and HTML dashboards are projections and must
never be read back to decide workflow behaviour.

Every event contains:

```text
schema_version, sequence, event_id, run_id, plan_sha256,
timestamp_utc, elapsed_ms, stage, event_type, status,
failure_kind, reason_code, safe_message, expected, observed,
subject_id, attempt, retryable, stage_budget_remaining_ms,
run_budget_remaining_ms, input_sha256, output_sha256, artifact_refs
```

### Durability rules

- Append to the journal before displaying a transition in terminal or HTML.
- Write snapshots and manifests through owner-only temp files, fsync, then atomic
  replace inside the private run directory.
- Canonical journal append failure stops new work: the runtime cannot honestly prove
  which stage ran.
- Snapshot/HTML projection failure does not erase a valid journal or stop an already
  running safe model call. It records to a minimal owner-only emergency file and
  stderr, retries projection during finalization, and prevents the run from counting
  as a successful release-verification run if still unresolved.
- Browser-open failure is an operator convenience warning only. The paths remain
  printed and the workflow outcome is unchanged.
- A partial final line after process loss is ignored during recovery; sequence and
  hashes detect gaps or tampering.

### Dashboard semantics

The first panel must render `run_state.first_blocker` directly. It must not rediscover
the blocker by scanning cards.

For every downstream stage after a failure, display:

```text
NOT_EVALUATED — stopped after <stage>: <reason_code>
```

Use separate counts for:

- passed stages;
- legitimate product rejections;
- system failures;
- downstream not-evaluated stages;
- missing observations (which should always make release verification fail).

Replace the current statement that every `NOT_EVALUATED` is an observability gap.
The dashboard must explain that it is neither a pass nor a failure by itself; its
reason identifies whether it is expected downstream control flow or truly missing
telemetry.

Evaluator provenance must use live configured paths. The dashboard should record
the full SHA-256 for the v2 Critic rubric, voice profile, acceptance-policy module,
Topic Value contract, claim-support contract, prompt templates, schemas, model
assignments, and run plan. No filename may be hard-coded separately from the path
the evaluator actually loaded.

## Public CLI contract

The full local run remains one command and streams concise progress:

```text
linkedin-os run --profile ... --days 7 --allow-web-research \
  --allow-model-egress --generate-post
```

`discover --generate-post` may remain as a compatibility alias during migration.
Both must resolve to the same `RuntimePlan` hash.

Terminal progress format:

```text
[02/10] topic_admission PASS  1.2s  358.4s remaining
[03/10] evidence_verification RUNNING  attempt 1/2
[03/10] evidence_verification FALLBACK  4 eligible cached records
[03/10] evidence_verification PASS  71.0s  286.2s remaining
```

On termination print exactly one first-blocker block, the run outcome, total elapsed
time, and artifact paths. Do not print a generic success merely because a subprocess
returned zero.

Exit codes must be stable and tested:

| Code | Meaning |
| ---: | --- |
| 0 | `READY_FOR_HUMAN_REVIEW` |
| 2 | `REJECTED_BY_PRODUCT_GATE` |
| 3 | `SYSTEM_FAILED` |
| 4 | `CANCELLED` |

A discovery-only compatibility command may return 0 with
`AWAITING_HUMAN_SELECTION`, but that outcome must never be reported as a completed
end-to-end run.

## Required tests

### Unit: state machine

1. All ten stages initialise as `NOT_EVALUATED`.
2. Only the next stage can transition to `RUNNING`.
3. A stage cannot pass without a durable start event.
4. Terminal stages cannot be overwritten or rerun.
5. The first failure is stored once and cannot be replaced by cleanup, final-eval,
   dashboard, or child-process failures.
6. Every downstream stage remains `NOT_EVALUATED` and references the same failure ID.
7. Candidate `REJECTED` and surface `UNAVAILABLE` cannot be assigned as stage status.
8. A product rejection yields `REJECTED_BY_PRODUCT_GATE`; dependency and contract
   failures yield `SYSTEM_FAILED`.
9. `READY_FOR_HUMAN_REVIEW` is impossible unless all ten applicable stages pass.

### Unit: budget and cancellation

Use a fake monotonic clock; no test sleeps.

1. Each adapter timeout is bounded by attempt, stage, and run remaining time.
2. A retry consumes remaining stage time and cannot extend the deadline.
3. Seven parallel scouts share one deadline rather than seven additive budgets.
4. Eligible evidence reuse can complete the evidence stage within its original
   budget; ineligible/stale/published atomic value cannot.
5. The run stops by 480 seconds plus deterministic teardown tolerance.
6. An unresponsive child is terminated and produces one exact timeout blocker.
7. A late future cannot append output after its stage has terminated.
8. SIGINT/SIGTERM records cancellation without converting it to a product rejection.

### Unit: failure taxonomy

Table-test every typed adapter failure and resulting exit code. Assert safe redaction
of provider stderr and secrets. Assert that timeout classification never depends on
English substring matching.

### Unit: journal and dashboard

1. Journal sequence is monotonic and event IDs are unique.
2. Recovery tolerates one partial trailing record but rejects a sequence gap.
3. Snapshot is a deterministic projection of the journal.
4. The HTML first-blocker panel matches the canonical failure ID and reason exactly.
5. Downstream cards say why they were not evaluated.
6. Derived-view failure preserves the first blocker and prevents release success.
7. Browser-open failure is non-blocking.
8. All rendered strings are escaped; private paths and provider text are absent.
9. Provenance digest equals the v2 file actually loaded, not v1.
10. The artifact manifest detects mutation of an evidence, scorecard, or package.

### Integration: composition and public dispatch

1. Importing any rebuild module performs no installation or global replacement.
2. `linkedin-os run`, the compatibility alias, dry run, installed-runtime test, and
   live run use the same ordered registry and plan schema.
3. Adapter substitution changes only adapter identity in the plan, not stage order or
   contracts.
4. Full execution uses public entrypoints only and reaches the Critic with all stage
   start/pass events in order.
5. Standalone drafting consumes the same evidence-binding, drafting, eval, and
   packaging services as the full run.
6. A typed child response is consumed without parsing log text.
7. Legacy overlay probes still pass for the repair flow until that flow is retired;
   rebuild tests assert zero overlay replacements.

### End-to-end scenarios

1. Fresh evidence path → review-ready package, code 0.
2. Evidence Scout timeout → bounded retry → eligible seven-day body-verified unused
   evidence → full successful run.
3. Timeout with no eligible evidence → evidence stage exact blocker, code 3, every
   later stage `NOT_EVALUATED` with the same failure ID.
4. Topic Value rejection → code 2; drafting never starts.
5. Multi-cluster thesis with exact evidence manifest → Critic reached.
6. Missing or changed evidence hash → evidence-binding system failure; no draft.
7. Highest Critic total with voice 3 → product rejection naming the voice shortfall.
8. Perfect score with failing honesty/citation/proof/privacy/relevance → product
   rejection; no package advances.
9. Critic malformed result → contract system failure, not a low score.
10. Dashboard projection initially fails, recovers from the journal, and preserves
    the original first blocker.

### Release verification

- `make check` must pass under the repository's `unittest` entrypoint.
- The installed local artifact, not an import from the source tree, runs all
  end-to-end tests.
- Run three consecutive live trials. Every trial must
  finish within 480 seconds, contain no system failure or missing observation, and
  preserve all locked gates. At least one trial must produce
  `READY_FOR_HUMAN_REVIEW`; a legitimate product rejection is evaluated but does not
  by itself prove the post-generation happy path.
- Report p50/p90/max runtime by stage and fallback usage. Do not publish or push from
  this packet.

## Dependencies and handoffs

| Dependency | Required contract |
| --- | --- |
| Discovery packet | typed surface events, coverage result, stable candidate IDs, deadline-aware adapter |
| Evidence/recovery packet | typed fresh/reuse decision, exact evidence identities, expiry and publication-novelty status |
| Topic Value/thesis packet | versioned inputs/outputs, candidate decisions, stable selected evidence references |
| Draft/acceptance packet | candidate and scorecard schemas, hard-gate results, rubric/profile digests, no log-based API |
| Privacy/storage packet | owner-only append/atomic-write primitives, artifact hashing, safe error redaction |
| Packaging packet | package schema and `READY_FOR_HUMAN_REVIEW` invariant |
| Release packet | exact consecutive-live-run count and installed-artifact verification harness |

This packet supplies all other workstreams with `RunContext`, `Budget`, `StageResult`,
`StageFailure`, event-journal, and artifact-reference interfaces. Those interfaces
must be frozen before plumbing begins.

## Build slices

1. Freeze schemas and typed enums for plan, stage result, failure, event, snapshot,
   and artifact reference.
2. Implement the pure state reducer and exhaustive transition tests.
3. Implement monotonic `Budget` and fake-clock tests.
4. Implement owner-only journal plus atomic snapshot/artifact manifest.
5. Build deterministic JSON/HTML projection from journal state.
6. Add the single composition root and CLI dispatch; initially wire stub stages.
7. Integrate stage adapters one packet at a time through typed interfaces.
8. Add failure-path and installed-runtime end-to-end tests.
9. Run consecutive live local verification and report budgets/failures.
10. Prepare, but do not perform, GitHub replication.

## Definition of done

- One explicit plan and one public composition path execute the full local workflow.
- There are no rebuild runtime overlays or import-order dependencies.
- Hard completion is enforced at 480 seconds, including child teardown and final
  observability persistence.
- Every run has a durable plan, ordered journal, exact first blocker, typed outcome,
  artifact hashes, and live evaluator provenance.
- Downstream stages after a blocker are visibly and correctly `NOT_EVALUATED`.
- The current Scout timeout class is recoverable only through the approved bounded
  retry/evidence-reuse contract; exhaustion remains a clear system failure.
- Required unit, integration, end-to-end, `make check`, and consecutive live local
  verification pass.
- Nothing from this packet is pushed, merged, deployed, published, or scheduled.
