# Packet 05 — drafting, voice, Critic, acceptance, and packaging

## Scope

This packet owns the boundary from one selected, identity-bound thesis to one
private human-review package:

```text
selected thesis + exact evidence manifest + strategy
  -> Writer candidates
  -> Narrative Editor
  -> deterministic hook-register check
  -> score-only anchored Critic
  -> deterministic hard gates
  -> anti-slop and Resonance checks
  -> bounded repair or safe retention
  -> private review package
```

The 2026-09-04 live run shown by the owner did **not** enter this packet. It
stopped at evidence verification with `Scout timed out`; drafting and every
post-quality check were correctly `NOT_EVALUATED`. Packet 01 owns that immediate
failure. This packet prevents the rebuilt flow from reaching drafting and then
failing because the several currently overlaid acceptance definitions disagree.

## Product decisions already fixed

- Drafting consumes only the exact evidence identities selected upstream. Topic
  prose is display context, never a retrieval key.
- The Writer returns exactly three grounded, materially different candidates.
  It does not score, rank, gate, package, approve, schedule, or publish.
- The measured v2 voice standard is authoritative. It came from 30 owner posts:
  median word Zipf `5.72`, only `2.7%` of words below Zipf `3.0`, sentence length
  mean `12.5`, standard deviation `11.7`, maximum `150`, and `1.5`
  contractions per 100 words.
- Voice means plain spoken words, large sentence-length variation, both hook
  lines scored, and sparse—not constant—contractions. Domain language such as
  `eval`, `agentic`, `context window`, `frontier AI lab`, `inference`, `token`,
  and `RAG` is allowed. Literary register such as `shy of`, `delve`, `myriad`,
  `testament`, `underscore`, `paradigm`, `nuanced`, and `albeit` is not.
- The deterministic off-register hook check has no runtime dependency. It runs
  on the first two non-blank body lines before the Critic.
- The Critic is score-only. It scores all five axes from 1–5 and never sees or
  applies binary release gates:
  `hook_strength`, `middle_escalation`, `earned_closer`,
  `specificity_and_source_quality`, and `voice_fidelity`.
- `earned_closer` remains scored and gated at 3 by owner decision. Its observed
  inversion makes it a candidate for later review only after a held-out set
  exists; it is not demoted now.
- Acceptance is exactly:

  | Contract | Floor |
  | --- | ---: |
  | Five-axis total | `18/25` |
  | `hook_strength` | `4/5` |
  | `middle_escalation` | `3/5` |
  | `earned_closer` | `3/5` |
  | `specificity_and_source_quality` | `3/5` |
  | `voice_fidelity` | `4/5` |

- Voice is a values gate. It is never waived, traded against the total, or
  lowered because outcome data suggests a higher-performing artificial voice.
- Honesty, citation, proof, privacy, and relevance never weaken. A perfect
  Critic score cannot compensate for one of these failures. Proof may be
  `NOT_REQUIRED` only on a route where the proof contract does not apply.
- Authority conversion remains required by the current candidate gate set even
  though it is not one of the five owner-named safety gates.
- The `0.18` claim/body similarity diagnostic is outside this packet and remains
  unchanged.
- `24/25` remains an optimisation target for repair, not the release floor.
- `18/25` is a floor, not a ceiling: scores from 18 through 25 remain eligible
  when the post's per-axis floors and every required gate pass.
- First comments use a different set of scored axes, so the post's named per-axis
  floors are not copied onto that route. Their total eligibility floor is
  nevertheless `>= 18/25`, with the existing evidence, anti-slop, and artisanal
  checks still required. This is the owner-approved interim contract until the
  first-comment axes are separately calibrated; `24/25` is not eligibility.
- A miss records every failed axis, observed value, required value, and exact
  shortfall. One summary sentence is insufficient.
- Bounded failure may retain the best grounded candidate only as private
  `BEST_EFFORT — NOT READY_FOR_HUMAN_REVIEW`. It is never a package
  recommendation and never permits publishing.
- A successful package is `READY_FOR_HUMAN_REVIEW`, not approved. Manual fact
  verification remains required and automatic scheduling/publishing remains
  disabled.

No additional product decision is required for this packet. The remaining work
is to make these existing decisions one executable contract.

## Exact source-of-truth values on current `origin/main`

`src/authority_os/acceptance_policy.py` currently contains:

```python
ACCEPTABLE_QUALITY_FLOOR = 18
MIN_HOOK_SCORE = 4
MIN_MIDDLE_ESCALATION_SCORE = 3
MIN_EARNED_CLOSER_SCORE = 3
MIN_SPECIFICITY_AND_SOURCE_QUALITY_SCORE = 3
MIN_VOICE_FIDELITY_SCORE = 4
```

The live rubric path is `config/critic-rubric-v2.json`, rubric ID
`linkedin-authority-critic-v2`. At the audited tree its raw-file SHA-256 is:

```text
966472fde4d31a2f857442df499ecd0eed43c3ed0434407db640ff5a8c0381bf
```

The v2 rubric, measured voice profile, hook gate, and calibrated acceptance
policy landed on main in PR #137 (`63096ef`). The earlier
`.claude/agents/critic.md` still describes the obsolete v1 `24–25` release
bands, but the installed single-topic Critic uses
`workflow.critic_scoring_system_prompt()` and therefore renders v2. The clean
rebuild must remove the possibility of any caller loading the stale file.

## Current behavior worth preserving

- `workflow.critic_scoring_system_prompt()` loads all 25 v2 behavioral anchors
  and excludes binary gates from the scored prompt.
- The V1 Critic schema requires an exact candidate excerpt and adjacent-anchor
  reasons for every axis. Invalid anchor formatting may retry once on the same
  candidates; the second failure remains fail-closed.
- Each anchored audit row records candidate text SHA-256, five scores, anchor
  details, and `critic_rubric_sha256`.
- Writer, Narrative Editor, Writer revision, and Critic model calls are zero-tool
  and require explicit egress consent.
- Writer candidates are structurally revalidated: exact field inventory,
  distinct IDs/openings, bounded length, supplied claim IDs only, research
  evidence required, no deferred decision metadata, no banned language, and no
  superficial three-way rewrite.
- Narrative Editor output may not change candidate ID, angle, or claim IDs. An
  invalid/editor-infrastructure result falls back to the already grounded Writer
  candidates. It may not regress honesty or citation from a prior non-failure to
  `FAIL`.
- Repair retains the best grounded candidate and carries its full text, axes,
  gate failures, and concrete repair instructions forward. At most four quality
  cycles run; identical hard-gate failure signatures stop after two attempts
  without score improvement.
- Every candidate's total, every axis decision, and every gate result is written
  to the private decision ledger before acceptance filters it.
- Package writes are owner-only (`0700` directories, `0600` files), no-clobber,
  symlink resistant, staged, and committed by linking `manifest.json` last. The
  package contains six files and no raw source bodies, query strings, private
  proof path/content, credentials, prompts, or model stderr.

## Semantic and overlay risks found

### P0 — acceptance has several incompatible sources of truth

The new policy is central only in the final quality overlay. Base
`workflow.validate_critic_scorecards()`, `workflow.rank_critic_scorecards()`,
`storage.validate_performance_record()`, `performance._validate_package_context()`,
the campaign coordinator, the legacy package builder, README, and workflow docs
still encode the old `24/22` bands. Several values are hard-coded rather than
read from `acceptance_policy.py`.

This causes real semantic breaks:

- the quality/package overlay can promote an `18–23` candidate to
  `READY_FOR_HUMAN_REVIEW`;
- performance validation then recomputes eligibility from the old
  `band == "advance-to-gates"` rule and rejects that same package;
- weekly learning accepts only the obsolete band;
- `draft --run-spec` uses campaign `MIN_SCORE = 24` and does not apply the new
  per-axis floors;
- the documented `--dry-run` deliberately bypasses the full installed stack, so
  it cannot prove the live acceptance contract.

**Clean contract:** one pure `evaluate_acceptance(scorecard, gates, checks)`
function owns total, axis floors, hard-gate status, and reason codes. Package,
performance, learning, campaign, direct drafting, dashboards, and tests consume
its versioned result; none reconstruct eligibility from legacy bands.

### P0 — the social-media overlay contradicts the hard-gate decision

`social_media_gate_policy` changes honesty/citation `FAIL` to `HUMAN_REVIEW`,
sets `passes_required_gates=True` when no other literal failure remains, and
instructs the Writer that these diagnostics are advisory. It also invites `XX%`
and `XXx` placeholders. Later acceptance currently rejects `HUMAN_REVIEW`, so
the final guard happens to remain strict, but the intermediate envelope and
prompt assert the opposite policy. `soften_gate_result()` is tested but not wired
to package generation.

**Clean contract:** remove the advisory projection from the rebuilt flow.
Honesty/citation are `PASS` or blocking `FAIL`; a human-review label cannot turn
them into a pass. Unsupported numeric placeholders remain non-publishable and
must not make a package review-ready.

### P0 — the deterministic voice check runs on the wrong artifact

`__main__.command_draft()` runs the hook-register check on Writer output, then
`human_readability.run_critic_review()` may edit all three hooks before the
Critic. The one-light Writer revision can also change a candidate before its
rescore. Neither edited artifact is passed through the deterministic hook check.
An off-register phrase can therefore be introduced after the nominal pre-Critic
gate and still reach scoring/acceptance.

The profile loader also fails open: a missing or invalid voice profile produces
an empty vocabulary and flags nothing. Capitalised tokens are skipped wholesale,
so a sentence-initial literary word is indistinguishable from a proper noun.

**Clean contract:** run the deterministic hook check on the exact immutable
candidate bytes supplied to **every** Critic call and again on the final
packaged bytes. Missing/malformed profile is a configuration failure. Preserve
proper-noun tolerance without exempting every sentence-initial token.

### P0 — configured drafting latency cannot meet the 7–8 minute outcome

One normal cycle may permit Writer `300s`, Narrative Editor `480s`, Critic
`300s`, and an optional Writer revision plus rescore at `300s` each, before
Topic Value/Resonance overhead. Four quality cycles multiply that exposure. The
current stage-local timeouts therefore do not impose an end-to-end deadline.

**Clean contract:** the orchestrator owns one monotonic deadline. Every model
call receives `min(stage_allowance, remaining_run_budget)`. Repair starts only
when enough time remains for a full candidate evaluation and secure package
write. Timeout retry and semantic repair have separate counters. No path may
extend the global 7–8 minute budget.

### P1 — acceptable 22–23 candidates are still forced through an obsolete revision band

The base review revises the leader whenever its old band is `one-light-revision`
(`22–23`), before the outer 18-point policy can accept it. A candidate already
meeting all new floors can therefore be mutated and rescored unnecessarily;
the revised version may regress. Conversely, the old band remains embedded in
stored scorecards even when it no longer determines release.

**Clean contract:** compute the immutable Critic scorecard, then evaluate the
new acceptance rule. Repair/revision runs only when no candidate accepts. The
24-point target may rank repair priorities but cannot replace the 18-point
release rule.

### P1 — rubric provenance is not bound to the package or run

The Critic anchor JSONL records the correct v2 file hash, but its rows have no
run ID or package ID. `manifest.json` and `evaluation.json` do not record the
rubric hash. Correlation currently depends on candidate text hashes across
separate state files.

**Clean contract:** every scorecard carries `rubric_id`, raw-file SHA-256,
acceptance-policy version/hash, model identity, candidate artifact SHA-256, and
run ID. The package copies those immutable values and performance validation
checks them rather than assuming the current checkout's rubric.

### P1 — best-effort retention covers only one exception string

The best-effort wrapper writes only when the error starts with
`No candidate cleared the locked `. Repeated-failure fast-stop, model timeouts,
Resonance exceptions, anchor failures, packaging errors, and other later-stage
stops bypass retention even when a previously observed candidate is safe.
Conversely, best effort must never be produced before a candidate has completed
all hard gates.

**Clean contract:** maintain explicit run state, not exception-message matching.
On any terminal outcome after at least one fully gated candidate, select the best
candidate whose honesty, citation, proof, relevance, and private-write checks
pass. Persist it privately with all shortfalls. Otherwise write no prose and
name the missing/failed hard contracts.

### P1 — the installed-runtime test is not the production launcher path

`test_installed_public_draft_uses_identity_manifest_and_reaches_critic` installs
only `v1_gates` and `v1_completion`, then calls the base CLI directly. It does
not exercise the launcher stack containing voice length, Codex routing,
Narrative Editor, anchor retry, social policy, consumability, runtime tuning,
quality optimisation, integrated selection, and standalone observability.
Signature probes confirm callable shapes, not acceptance semantics.

**Clean contract:** an end-to-end test must invoke the same public composition
root as `bin/linkedin-os draft`, with only external model/network ports stubbed.
It must assert stage order, final artifact identities, gate outcomes, package
status, and exit code.

### P1 — Writer voice instructions conflict and the measured profile is indirect

The reconstructed voice guide says `mechanism before consequence`; Writer v9
and the Narrative Editor say consequence before mechanism. The Writer receives
the older prose voice guide, not the measured profile. The profile reaches the
flow only through the deterministic hook check, while the Critic sees a summary
inside v2 anchors.

**Clean contract:** compile one versioned Writer voice projection from the four
owner rules. Remove contradictory ordering advice. Keep corpus/frequency data
as non-citable style context and never allow it to become factual post content.

### P2 — rubric metadata contains a dead bonus rule

`critic-rubric-v2.json` contains `bonus.big_name_present = 2`, but the runtime
correctly ignores it and the owner acceptance total remains five axes out of 25.
An external consumer could reasonably interpret the JSON as permitting 27.

**Clean contract:** acceptance schema validation must reject unimplemented
release semantics or explicitly mark this value diagnostic-only. It must never
change the 25-point total without a new product decision.

## Clean local interfaces

### `DraftRequest`

```json
{
  "run_id": "...",
  "thesis_id": "thesis-1",
  "topic_value_id": "topic-1",
  "display_topic": "...",
  "strategy": {
    "target_reader": "...",
    "reader_problem": "...",
    "core_hypothesis": "...",
    "product_decision": "...",
    "authority_statement": "..."
  },
  "evidence_manifest_sha256": "...",
  "evidence": [{"evidence_id": "...", "content_sha256": "..."}],
  "deadline_at": "..."
}
```

The adapter resolves exact evidence before model egress. Missing, changed,
duplicated, out-of-window, or unverified evidence fails closed by ID.

### `CriticScorecard`

```json
{
  "candidate_id": "candidate-1",
  "candidate_sha256": "...",
  "rubric_id": "linkedin-authority-critic-v2",
  "rubric_sha256": "966472fde4d31a2f857442df499ecd0eed43c3ed0434407db640ff5a8c0381bf",
  "axes": {
    "hook_strength": 5,
    "middle_escalation": 3,
    "earned_closer": 3,
    "specificity_and_source_quality": 3,
    "voice_fidelity": 4
  },
  "raw_total": 18,
  "anchors": {},
  "attempt": 1
}
```

Every anchor has an exact excerpt and adjacent-boundary reasons. Total is
computed locally; the model cannot supply it.

### `AcceptanceDecision`

```json
{
  "contract_version": "draft-acceptance-v2",
  "candidate_id": "candidate-1",
  "candidate_sha256": "...",
  "status": "PASS",
  "total": {"observed": 18, "required": 18, "shortfall": 0},
  "axes": {
    "hook_strength": {"observed": 5, "required": 4, "shortfall": 0},
    "middle_escalation": {"observed": 3, "required": 3, "shortfall": 0},
    "earned_closer": {"observed": 3, "required": 3, "shortfall": 0},
    "specificity_and_source_quality": {"observed": 3, "required": 3, "shortfall": 0},
    "voice_fidelity": {"observed": 4, "required": 4, "shortfall": 0}
  },
  "hard_gates": {
    "honesty": "PASS",
    "citation": "PASS",
    "proof": "NOT_REQUIRED",
    "privacy": "PASS",
    "relevance": "PASS"
  },
  "other_required_checks": {
    "authority_conversion": "PASS",
    "off_register_hook": "PASS",
    "anti_slop": "PASS",
    "resonance": "PASS"
  },
  "failure_codes": []
}
```

No downstream component recomputes this decision from score bands.

### Terminal outcomes

| Outcome | Exit | Artifact | Meaning |
| --- | ---: | --- | --- |
| `READY_FOR_HUMAN_REVIEW` | `0` | committed six-file package | At least one candidate passed the complete contract; still unapproved |
| `BEST_EFFORT` | `1` | private owner-only draft with all misses | A fully hard-gated candidate exists but missed quality/secondary checks |
| `BLOCKED` | `2` | structured run/eval record; no usable prose | Evidence, identity, hard gate, privacy, provider, schema, or deadline prevented a safe candidate |

The exact global CLI exit mapping should be defined once by Packet 10. The
distinction above is the required semantic contract.

## Required test matrix

### Voice and rubric

1. Critic prompt renders rubric ID v2 and all 25 anchors; binary gates and
   release language are absent.
2. Recorded and packaged `critic_rubric_sha256` equals the raw v2 file hash and
   does not equal the v1 Critic file hash.
3. Both hook lines are inspected. `shy of` fails; `frontier AI lab` passes; a
   capitalised product name passes; a sentence-initial literary word does not
   evade the check.
4. Missing/malformed voice profile fails before Critic. No runtime `wordfreq` or
   other dependency is imported.
5. Narrative Editor and Writer revision fixtures that introduce an off-register
   phrase are rejected before their respective Critic calls.

### Exact acceptance boundaries

Use the named axis order below rather than an ambiguous five-number tuple:

| Hook | Middle | Closer | Specificity | Voice | Total | Hard gates | Expected |
| ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 5 | 4 | 4 | 4 | 4 | 21 | pass | advance |
| 5 | 3 | 3 | 3 | 4 | 18 | pass | advance |
| 5 | 4 | 4 | 4 | 2 | 19 | pass | reject: voice short by 2 |
| 4 | 4 | 4 | 4 | 2 | 18 | pass | reject: voice short by 2 |
| 5 | 5 | 5 | 5 | 5 | 25 | honesty fail | reject: honesty |

Also test every other axis one point below its floor with a compensating high
total, and each hard gate independently. The returned record must name every
miss and exact shortfall, not only the first failure.

For the distinct first-comment scorecard, prove totals 18, 19, 20, and 25 are
eligible when its evidence, anti-slop, and artisanal checks pass; 17 is rejected;
and failure of any of those checks rejects even a 25. Do not apply the post-axis
floors to differently named first-comment axes before separate calibration.

### Regeneration and best effort

1. A candidate meeting 18 plus all axis/hard floors exits immediately without
   an obsolete mandatory 22–23 revision.
2. A batch-leading voice-3 candidate is rejected even when it has the highest
   total; the voice reason is recorded.
3. Repair keeps the strongest safe evidence-bound seed, never a higher-scoring
   hard-gate failure.
4. Four-cycle exhaustion writes one private best-effort artifact only when a
   fully hard-gated candidate exists.
5. Repeated-failure fast-stop and a later provider timeout exercise the same
   safe-retention state transition without matching error text.
6. Deadline exhaustion cannot begin another full cycle and the total elapsed
   simulated time stays inside the run budget.

### Package and lifecycle

1. An 18-point boundary candidate produces a `READY_FOR_HUMAN_REVIEW` package;
   performance validation accepts that exact package under the same policy.
2. Voice 3, any hard-gate failure, off-register hook, anti-slop finding, or
   Resonance block produces no review-ready recommendation.
3. Package includes run ID, candidate/evidence hashes, v2 rubric hash, and
   acceptance-policy provenance; tampering any one value fails closed.
4. Manifest remains the last commit marker, repeated writes never overwrite,
   symlink/path/mode failures produce no committed package, and no package can
   record approval or publishing.
5. Direct draft, discover-generated child draft, and `--run-spec` all return the
   same acceptance decision for the same candidate envelope.

### Installed production composition

Run the real public launcher composition with only external network/model ports
stubbed. Assert this exact semantic sequence:

```text
identity-bound evidence -> Writer -> Narrative Editor -> final hook-register check
-> anchored v2 Critic -> local totals -> hard/secondary gates -> acceptance
-> repair or secure package -> dashboard
```

The test must activate every production installer or, preferably, the rebuilt
explicit composition root. It must prove that the exact candidate scored is the
one gated and packaged, and that the accepted evidence IDs are a subset of the
upstream approved IDs.

## Verification performed during this audit

A focused `unittest` run covered Critic, v2 gates, hook/register, acceptance,
repair, best effort, packaging, social policy, installed smoke, and installer
contracts: 122 tests executed. All functional assertions in this packet passed.
Two managed-sandbox filesystem probes failed (`inspect_database_health` on a
temporary SQLite path and the simulated missing-`fcntl` subprocess); neither
failure changed the semantic findings above.

Passing current tests does not clear this packet: the tests validate individual
overlays while the P0 issues are contradictions **between** overlays and
downstream consumers.

## Definition of done for Packet 05

- One explicit production composition owns drafting through packaging; no
  import-order monkeypatch determines product behavior.
- Every runtime path uses the exact 18-point/per-axis/hard-gate acceptance
  contract and the same decision object.
- The exact final artifact is checked for off-register language, v2-scored,
  hard-gated, and package-bound with full provenance.
- Repair and best-effort are state transitions bounded by the global deadline,
  not exception-string handlers.
- An 18-point accepted package survives package, performance, and learning
  validation unchanged.
- Full installed-runtime tests pass through public entry points, and repeated
  local live trials finish within the product's seven-to-eight-minute budget.
