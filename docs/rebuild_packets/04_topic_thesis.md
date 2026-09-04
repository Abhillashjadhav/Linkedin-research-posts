# Packet 04 — Topic Value and thesis contract

## Scope

This packet owns the path after evidence verification and before drafting:

```text
verified evidence pool
  -> Topic Value selection
  -> atomic-value novelty / research-trust / claim-body diagnostics
  -> Topic Value projection
  -> thesis generation
  -> thesis scoring and deterministic selection
  -> exact evidence handoff to drafting
```

The live failure reported on 2026-09-04 did **not** enter this packet. It stopped
at evidence verification with `Scout timed out`; Topic Value and thesis search
were correctly marked `NOT_EVALUATED`. Packet 02/03 must make verified evidence
available within the global latency budget before this packet can run.

## Product rules that are already fixed

- Topic Value is selection, not drafting. It must choose a grounded situation
  with reader value before a thesis or post exists.
- Allowed reader-value routes are `CAPABILITY_DISCOVERY`, `DECISION_CHANGE`,
  `IMMEDIATE_UTILITY`, and `ACCELERATED_LEARNING`.
- Brand-strip, feed-value, and authority-goal checks are mandatory.
- Topic Value thresholds remain exactly:
  - total `>= 18/25`;
  - reader relevance `>= 4`;
  - reader value `>= 4`;
  - gravity `>= 2`;
  - evidence strength `>= 3`;
  - authority fit `>= 3`.
- High gravity is not mandatory. A useful medium-gravity situation may pass.
- Atomic value is one 5–45 word unit of reader value, not a broad topic or a
  brand name.
- Atomic-value novelty remains enforced at similarity `< 0.72` against
  **published** atomic-value history. A review-ready but unpublished draft does
  not enter that history.
- A published atomic value is not selected again. Reusing an eligible source is
  allowed when it supports a materially different atomic value and the evidence
  is still inside the requested window.
- Research trust remains enforced: factual use needs at least one body-read,
  non-social source. Social/community pages may nominate a topic but may not be
  laundered into primary factual evidence.
- Claim/body support remains a shadow diagnostic at similarity `>= 0.18`, with
  every number in the claim also present in the cited body. It is not a truth
  oracle and does not replace downstream honesty and citation gates.
- Thesis search generates exactly three candidates per cycle and scores five
  axes from 1–5: audience fit, distinctiveness, decision strength, proof fit,
  and simplicity.
- A thesis independently qualifies at total `>= 23/25` and simplicity `>= 4/5`.
  A weaker sibling must not veto a qualifying leader.
- At most three thesis cycles run. Rejected thesis text may not be reused in a
  later cycle.
- `--generate-post` selects the highest qualifying thesis deterministically;
  otherwise human thesis selection remains required. Neither path publishes.
- The narrative spine is advisory metadata, not a Writer template, weekday
  router, or quality gate.
- Every candidate and every decision is recorded before an enforced failure is
  raised. Observability failure must not alter product selection.
- Evidence must reach drafting by stable identity. Topic prose is display text,
  never a retrieval key.

## Current implementation inventory

| Concern | Current owner | Current behavior |
| --- | --- | --- |
| Topic Value schema and Python thresholds | `topic_value.py` | Three exact candidates; model status/gravity are recomputed locally |
| Exact transport IDs | `topic_value_id_contract.py` | Schema and prompt require `topic-1..topic-N` exactly once |
| Atomic value and V1 gates | `v1_gates.py` | Adds `atomic_value`; evaluates novelty, trust, and claim/body support |
| Published-only novelty history | `v1_completion.py` | Replaces novelty source with confirmed-published bindings |
| Topic Value observability | `daily_spine_cli.py`, `v1_completion.py` | Pre-gate/post-gate artifacts and nine decision rows for three candidates |
| Topic-to-signal projection | `topic_value.py`, V1 overlay | Filters selected signals and adds partial Topic Value annotations |
| Thesis generation and validation | `daily_cli.py`, `daily_spine_cli.py` | Three one-idea cards, 1–2 signal aliases, one valid proof ID, advisory spine |
| Thesis search | `daily_spine_cli.py` | Retains all independent qualifiers, sorts total → distinctiveness → ID |
| Draft evidence manifest | `daily_cli.py` | Resolves thesis signal aliases to canonical URL + content hash |

The shipped launcher installs Topic Value layers in this order:
`v1_gates.install()` -> `v1_completion.install()` ->
`topic_value_id_contract.install()` -> discovery runtime overlays. The clean
rebuild should expose the same behavior through explicit composition rather
than module-global monkeypatches.

## Semantic boundary risks found

### P0 — thesis is not bound to a passed Topic Value candidate

`project_discovery_signals()` copies selected signals forward, but a thesis card
contains only `signal_ids`; it does not contain a `topic_value_id`. Validation
therefore proves that a thesis used selected evidence, but not that it preserved
the situation, atomic value, and reader-value route that passed Topic Value.
When several candidates share or contribute signals, the model may synthesize a
new value proposition that Topic Value never evaluated.

**Clean contract:** every thesis declares exactly one `topic_value_id`. Its
`signal_ids` must be a non-empty subset of that candidate's `source_ids`. The
selected Topic Value snapshot—situation, atomic value, reader-value route, and
stable evidence references—must accompany the thesis into scoring and drafting.
The thesis may add judgment; it may not silently replace the approved reader
value.

### P0 — stage-wide enforcement lets one weak sibling veto good candidates

Base Topic Value correctly retains passing candidates when siblings miss its
thresholds. The V1 evaluator, however, evaluates every retained candidate and
then raises on the first enforced novelty or research-trust failure. One repeated
atomic value can therefore discard another independently novel, trusted
candidate. This conflicts with both the independent-candidate thesis rule and
the product requirement to exclude already-published value without throwing
away unrelated eligible material.

**Clean contract:** evaluate and record all contracts for all candidates, then
filter candidate-locally. Retain every candidate whose base Topic Value,
novelty, and research-trust contracts pass. Fail the stage only when none remain.
Claim/body support remains recorded shadow data. This changes no threshold or
gate strength; it scopes enforcement to the candidate the decision describes.

### P0 — local aliases are not durable identities

`signal-1`, `topic-1`, and `thesis-1` are ordering labels recreated on each run.
The final evidence manifest correctly resolves `signal-*` to canonical URL plus
content hash, but Topic Value and thesis artifacts still rely on local aliases
internally. Reordering evidence during replay or resume can silently change what
an alias denotes.

**Clean contract:** create one immutable `EvidenceRef` immediately after
verification:

```json
{
  "evidence_id": "sha256:<canonical-url-and-content identity>",
  "canonical_url": "https://...",
  "content_sha256": "...",
  "published_at": "..."
}
```

Use `evidence_id` at every machine boundary. Keep `signal-*`, `topic-*`, and
`thesis-*` only as run-local presentation/order labels. Reject missing,
duplicate, changed, or out-of-window evidence before invoking the next model.

### P0 — configured timeouts cannot satisfy the product latency budget

Topic Value alone permits 300 seconds plus a 420-second timeout retry. One thesis
cycle permits a 420-second generator call followed by a 420-second critic call;
three cycles can consume 42 minutes before other stages. The product target is a
complete run in 7–8 minutes. Component-local timeout limits are therefore not a
bounded end-to-end retry policy.

**Clean contract:** the orchestrator owns one monotonic run deadline. Each call
receives the smaller of its stage allowance and remaining run budget. A timeout
may retry only when enough budget remains for both the retry and all mandatory
downstream stages. Semantic thesis regeneration and transport retry use separate
counters. No timeout path may extend the global deadline.

Suggested allocation is an orchestration dependency, not a threshold change;
Packet 10 should set exact numbers after all stage costs are measured.

### P1 — retry feedback is incomplete and exact-text-only

Thesis retry feedback carries scores and prior thesis text, but reuse detection
is normalized exact equality. A near-paraphrase can consume another full model
cycle. No deterministic reason codes distinguish a low total from simplicity,
proof mismatch, invalid schema, or model transport failure.

**Clean contract:** record separate `attempt_type` (`transport` or `semantic`),
machine-readable misses per axis, and a stable candidate fingerprint. Do not add
a new similarity threshold without product approval. Until then, exact reuse
remains the only blocking reuse rule and near-duplicate similarity is diagnostic.

### P1 — research trust names quality but does not gate it

The trust decision records `source_quality`, but any body-read non-social host
passes even when quality is `secondary`, blank, or malformed. This may be
intentional because downstream gates own factual strength, but the name
`research_trust` can overstate what is proven.

**Clean contract:** preserve current enforcement, and name the actual invariant
in artifacts: `body_read_non_social_source_present`. Keep `source_quality` as an
explicit input and diagnostic. Any stronger primary-source requirement is a new
product decision, not an implementation cleanup.

### P1 — the topic prompt retains an obsolete retrieval instruction

Thesis prompts still require topic words copied from a source title “so stored
evidence can be retrieved later.” Drafting now uses canonical URL and content
hash manifests. Keeping the instruction pressures the model toward awkward or
misleading topic labels and suggests prose is still an identity mechanism.

**Clean contract:** keep `topic` as concise human-facing display text. Remove
only the obsolete retrieval rationale; evidence resolution must never read it.

### P1 — installed composition is signature-safe but semantically opaque

Multiple installers capture and replace the same callable. Signature inventory
tests catch renamed parameters, but they cannot prove that each wrapper preserved
the exact candidate set, evidence identity, contract modes, or selection
semantics.

**Clean contract:** assemble one explicit `TopicThesisService` from typed ports:

```text
TopicValueSelector
NoveltyLedger (published history, read-only during selection)
TopicGateEvaluator
ThesisGenerator
ThesisCritic
DecisionRecorder (best effort)
RunDeadline
```

No component installs itself at import time. The public command constructs the
service once and records component/rubric/config hashes in the run manifest.

### P2 — artifacts cannot fully reproduce selection

The Topic Value artifact records candidates and selected local IDs, and the
thesis trace records scores, but neither is a single immutable input/output
envelope with evidence hashes, prompt/rubric/config hashes, model identity, and
attempt timing. A successful run cannot be replayed without consulting adjacent
state.

**Clean contract:** every stage writes one append-only envelope before the next
stage runs. It includes run ID, schema version, stable input refs and hashes,
configuration provenance, attempt number, started/ended times, all candidates,
all decisions, selected IDs, and failure reason.

## Clean local interfaces

### Topic Value input

```json
{
  "run_id": "...",
  "target_reader": "...",
  "authority_goal": "...",
  "evidence": [{"evidence_id": "...", "canonical_url": "...", "content_sha256": "..."}],
  "published_atomic_values_snapshot_sha256": "...",
  "deadline_at": "..."
}
```

### Topic Value output

```json
{
  "candidates": [{
    "candidate_id": "topic-1",
    "evidence_ids": ["..."],
    "situation": "...",
    "atomic_value": "...",
    "reader_value_type": "DECISION_CHANGE",
    "scores": {},
    "base_pass": true,
    "contract_decisions": {},
    "eligible": true
  }],
  "selected_candidate_ids": ["topic-1"]
}
```

Python—not the model—derives gravity, totals, base status, contract eligibility,
and ranking. All candidates are recorded before filtering.

### Thesis input

```json
{
  "run_id": "...",
  "topic_value_candidates": [{"candidate_id": "topic-1", "evidence_ids": ["..."]}],
  "proof_inventory_snapshot_sha256": "...",
  "avoid_topics": [],
  "recent_theses": [],
  "deadline_at": "..."
}
```

### Thesis output

```json
{
  "theses": [{
    "thesis_id": "thesis-1",
    "topic_value_id": "topic-1",
    "evidence_ids": ["..."],
    "proof_id": "proof-...",
    "topic": "display text only",
    "scores": {},
    "total": 23,
    "qualifies": true,
    "rejection_reasons": []
  }],
  "selected_thesis_id": "thesis-1"
}
```

Selection order remains total descending, distinctiveness descending, then
stable thesis order. Automatic drafting uses only the first independent
qualifier; manual mode may select any qualifier.

## Failure and retry matrix

| Failure | Retry? | Required result |
| --- | --- | --- |
| Topic Value transport timeout | Once only if global deadline permits | Same immutable input and same candidate-ID contract |
| Topic Value invalid schema/IDs | No transport retry | Fail stage with raw provider diagnostic safely recorded |
| Candidate misses base Topic Value | No | Record and filter candidate-locally |
| Candidate repeats published atomic value | No | Record and filter candidate-locally |
| Candidate lacks trusted research | No | Record and filter candidate-locally |
| Claim/body diagnostic misses 0.18 | No | Record shadow failure; do not represent it as enforced |
| Thesis transport timeout | Once only if global deadline permits | Retry same cycle without incrementing semantic cycle |
| Thesis invalid schema or evidence binding | No automatic semantic recovery | Fail closed; do not repair identity fields with inference |
| Thesis scores below 23 or simplicity below 4 | Yes, up to remaining semantic cycles and deadline | Supply bounded score/reason feedback; generate a genuinely different batch |
| One thesis passes, siblings fail | No further cycle | Return the qualifying thesis(es) immediately |
| Evidence missing/changed/out of window at handoff | No | Fail closed naming the stable evidence ID |

## Required tests

All tests use `unittest`, and installed-runtime coverage must call public entry
points rather than private helper functions alone.

### Deterministic unit tests

1. Assert every Topic Value threshold and the total boundary exactly; include a
   medium-gravity pass and each individual floor miss.
2. Assert model-reported gravity/status cannot override Python-derived values.
3. Assert atomic novelty is PASS below `0.72`, FAIL at/above `0.72`, and reads
   confirmed-published history only.
4. Assert published atomic value is excluded while an unpublished review-ready
   binding is not.
5. Assert research trust rejects missing bodies and social laundering and passes
   a body-read non-social source while recording its quality.
6. Assert claim/body support records PASS at `>= 0.18`, FAIL below it, rejects
   unsupported numbers, and stays `shadow` in configuration.
7. Assert observability receives immutable pre-gate and post-gate snapshots and
   cannot change selection.
8. Assert a failed novelty/trust sibling cannot veto a separate candidate that
   passes every enforced candidate-local contract; assert the stage fails when
   no candidate remains.
9. Assert every thesis contains a valid `topic_value_id`, and every thesis
   evidence ID is a subset of that Topic Value candidate's evidence IDs.
10. Assert cross-candidate signal mixing is rejected even when every signal ID
    exists in the global evidence pool.
11. Assert `topic` is never consulted for evidence resolution.
12. Assert a mixed thesis batch returns the independent qualifier without
    spending another cycle.
13. Assert total 22 fails, total 23 with simplicity 3 fails, and total 23 with
    simplicity 4 passes.
14. Assert ranking is deterministic under input order changes.
15. Assert retry feedback has per-axis misses, semantic and transport counters
    are distinct, and rejected exact thesis text cannot recur.
16. Assert the run deadline prevents any stage retry that would exceed the
    global 7–8 minute budget.

### Contract and replay tests

17. Serialize then reload Topic Value and thesis envelopes; hashes and selected
    evidence identities must remain unchanged.
18. Reorder the verified evidence pool; stable evidence IDs must still select
    the same records.
19. Change a body while keeping its URL; content-hash verification must fail
    closed before thesis scoring or drafting.
20. Use a thesis spanning two evidence clusters; selection and drafting must
    succeed because identity, not lexical cluster lookup, owns the handoff.
21. Delete one selected record after thesis selection; drafting must fail naming
    the missing stable ID.

### Installed local path

22. Start through `./bin/linkedin-os discover` with all production composition
    active and stub only external model/web ports. Assert verified evidence
    reaches Topic Value, a candidate-local gate failure is filtered, one thesis
    reaches the Critic, and the exact evidence hashes seen by drafting are a
    subset of those approved by Topic Value.
23. Run the same fixture three times with evidence input order shuffled. Assert
    the same selected atomic value, thesis, evidence identities, and decision
    envelope hashes, excluding timestamps.
24. Force each timeout location with a fake clock. Assert the workflow either
    completes inside the global budget or stops with `deadline_exhausted`; it
    must never begin a model call whose allowance exceeds remaining time.
25. Assert every rejected candidate and downstream `NOT_EVALUATED` stage remains
    visible after a legitimate stage failure.

## Dependencies

- **Packet 01 — orchestration contract:** supplies run ID, immutable clock, global
  deadline, stage budget API, and standard envelope/decision schema.
- **Packet 02/03 — discovery and evidence:** supplies 3–7 body-verified,
  in-window `EvidenceRef` records and bounded reuse of eligible seven-day
  evidence after Scout timeout. This packet never fetches the web itself.
- **Proof/profile owner:** supplies a validated, public-safe proof inventory
  snapshot; thesis generation may reference only its IDs.
- **Novelty ledger owner:** supplies an immutable snapshot of confirmed-published
  atomic values. Selection is read-only; promotion occurs only after separately
  confirmed manual publication.
- **Drafting packet:** accepts the selected thesis plus its exact `EvidenceRef`
  set. It must not query by topic text or independently reselect evidence.
- **Observability packet:** records every candidate and decision best-effort,
  without being able to mutate selection or turn successful work into failure.
- **Release packet:** owns installed-public-entry tests, consecutive live trials,
  and the 7–8 minute end-to-end budget report.

## Definition of done for this packet

- All fixed thresholds and modes above are asserted from one named configuration
  source and recorded with provenance.
- Every qualifying thesis is provably bound to one passed Topic Value candidate
  and to the exact verified evidence that candidate used.
- A failed sibling cannot discard an unrelated qualifying candidate.
- Published-value exclusion is proven without treating unpublished work as
  published history.
- No stage retrieves evidence from generated prose or run-local ordering aliases.
- Retries are bounded by the shared run deadline and distinguish transport from
  semantic regeneration.
- All 25 tests above pass under `unittest`, including the installed public path.
- This packet introduces no change to Topic Value, thesis, claim-support, or
  downstream post-acceptance thresholds.

## Audit verification on the current baseline

The focused current-runtime suite was invoked with:

```bash
PYTHONPATH=src python3 -m unittest \
  tests.test_topic_value \
  tests.test_topic_value_id_contract \
  tests.test_v1_gates \
  tests.test_v1_completion \
  tests.test_evidence_handoff \
  tests.test_daily_spine_cli
```

Result: 68 tests ran; 66 passed and two database-health tests stopped at the
managed sandbox's private-path safety check (`Private database is unavailable
or unsafe`). No runtime code was changed by this packet. The passing suite
confirms the current thresholds, timeout-only Topic Value retry, published-only
novelty promotion, observer behavior, mixed-batch thesis retention, and final
canonical URL/content-hash handoff that this audit describes. The new tests in
this packet are rebuild acceptance criteria; they do not exist yet.
