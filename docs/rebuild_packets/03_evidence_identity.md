# Rebuild packet 03 — evidence identity and same-window reuse

## Outcome

This packet owns the boundary from admitted conversation topics to the exact
evidence consumed by Topic Value, thesis selection, Writer, Critic, and the
publication-novelty ledger.

The merged implementation at `origin/main` commit
`6dc917af05330cfdd8af54bcfb318ad0b696f40d` fixes the former prose-topic handoff:
drafting now accepts a private manifest containing canonical URL and content hash,
looks those identities up exactly, keeps evidence from more than one cluster, and
fails closed if a selected record is missing or changed.

That fix should be retained. It does **not** yet provide safe recovery from the
current source-Scout timeout. The rebuild needs a durable verification receipt,
immediate evidence checkpointing, window-aware cache selection, and stable evidence
IDs in publication lineage.

## Product decisions already fixed

- A source may be reused while its `published_at` timestamp remains inside the
  current run's requested seven-day window and its exact body-verified version is
  still available.
- Reusing a source is not the same as reusing a post idea. The system must reject an
  atomic value already published, while allowing the same source to support a
  materially different atomic value.
- Only a timeout or explicitly classified transient availability failure may enter
  the reuse path. Invalid schemas, unsafe URLs, provenance failures, hash drift, or
  insufficient evidence remain hard failures.
- The topic is display and selection context. It is never an evidence identity.
- Social/community material may nominate a conversation, but factual evidence must
  include body-read, non-social material.
- Evidence selection and publication novelty are separate contracts. Cache recovery
  must not weaken the atomic-value novelty gate.

No further product choice is required for this packet.

## Audit of the current runtime

| Boundary | Current behavior | Assessment |
| --- | --- | --- |
| Source Scout | `_invoke_signal_scout()` makes one 420-second web call. | No timeout retry or local-evidence recovery exists at this boundary. A single timeout exhausts most of the 7–8 minute product budget. |
| Structural preparation | `prepare_research_items()` canonicalises URLs, parses timestamps, and hashes the Scout-returned `body`, but permits an empty body. The Scout prompt asks for concise evidence summaries, so this hash is normally a digest of the captured summary, not the remote page bytes. | Useful payload normalisation and within-run binding, not proof that a source body was read or a digest of the publisher's page version. |
| Evidence stage result | The dashboard calls every prepared/projected record “body-verified.” | The recorded reason is stronger than the implemented check. |
| Persistence point | `daily_spine_cli.command()` inserts research only after Topic Value and thesis search succeed. | Evidence that passed its own stage is lost as reusable state when a later stage fails. |
| Research ledger | `research_items` stores URL, body, publication/fetch timestamps, content hash, source quality, and origin. | It has no verification receipt, verifier version, verification timestamp, run/window link, or topic-evidence link. Unique URL and unique body hash also prevent versioned bodies at one URL. |
| Topic/Thesis identity | Topic Value and thesis cards use run-local `signal-*` IDs. | Correct inside one process, not durable across runs. |
| Drafting handoff | PR #138 maps run-local IDs to `(canonical_url, content_hash)` in a private manifest. | Correct stable handoff. Preserve it and extend its provenance/window fields. |
| Exact retrieval | `list_research_items_by_identity()` filters to `private-import`, preserves manifest order, and returns only exact URL/hash pairs. | Correct fail-closed behavior. |
| Multi-cluster thesis | Manifest-backed drafting disables topic re-selection and passes all bound records into drafting. | Correct. A thesis may use one or two evidence records from different clusters. |
| Review-ready novelty | Review-ready posts are bound to an artifact hash but do not enter published novelty history. | Correct product boundary. |
| Published novelty | Confirmed manual publication promotes the binding; live novelty checks use the published ledger at similarity threshold `0.72`. | Correct exclusion behavior. Keep distinct from the `0.18` claim/body diagnostic. |
| Publication evidence lineage | Review-ready and published rows store run-local `source_ids` such as `signal-1`. | Insufficient durable lineage. Store stable evidence IDs instead. |

Relevant current code:

- `src/authority_os/daily_spine_cli.py:1255-1282` — the single 420-second
  evidence-Scout call.
- `src/authority_os/daily_spine_cli.py:1433-1465` — preparation is labelled as
  body verification.
- `src/authority_os/daily_spine_cli.py:1611-1615` — persistence occurs only after
  thesis success.
- `src/authority_os/storage.py:101-118` — current research table.
- `src/authority_os/workflow.py:738-780` — research preparation permits blank body.
- `src/authority_os/workflow.py:401-485` — private evidence-manifest validation.
- `src/authority_os/storage.py:1350-1400` — exact identity lookup.
- `src/authority_os/v1_completion.py:327-454` — review-ready binding and manual
  publication promotion.
- `src/authority_os/v1_gates.py:226-246` and `config/eval-v1.json` — published
  atomic-value novelty at `0.72`.

## Target architecture

The rebuild should separate immutable source content, verification events, selection
links, and thesis manifests.

1. `research_evidence` stores immutable, content-addressed evidence captures.
2. `evidence_verifications` records why one exact version qualified for factual use.
3. `topic_evidence_links` records which admitted inventory candidate an exact version
   supported when it passed verification.
4. `evidence_set_manifest` freezes the exact versions selected for one thesis.
5. `review_ready_atomic_bindings` binds one atomic value and the stable evidence set
   to the exact candidate artifact.
6. `published_atomic_values` is populated only after confirmed manual publication.

The stable captured-evidence identity is:

```text
evidence_id = sha256(canonical_url + "\n" + evidence_payload_sha256)
```

For compatibility, PR #138's `content_hash` is the current
`evidence_payload_sha256`. It must not be described as a hash of remote source
bytes. If the retrieval adapter can capture and hash the inspected publisher body,
store that separately as optional `source_body_sha256`; never fabricate it from a
model summary.

`signal-*` remains a convenient run-local label but must never be used as a durable
foreign key.

### Input contract: `RawScoutItem`

| Field | Contract |
| --- | --- |
| `url` | Public HTTP(S), canonicalisable, no credentials/private address. |
| `title` | Non-blank source title. |
| `body` | Non-blank body-derived evidence summary; a title or search snippet is insufficient. |
| `source` | Non-blank publisher/source label. |
| `author` | Text; may be blank. |
| `published_at` | Timezone-aware timestamp. Must be inside the current requested window. |
| `source_quality` | `primary`, `secondary`, or `mixed`. |

Invalid input does not enter the ledger.

### Output contract: `VerifiedEvidence`

| Field | Contract |
| --- | --- |
| `evidence_id` | Stable digest of canonical URL plus exact content hash. |
| `canonical_url` | Canonical public source URL. |
| `evidence_payload_sha256` | SHA-256 of the normalised non-blank captured evidence payload; current field name is `content_hash`. |
| `source_body_sha256` | Optional digest of actually fetched publisher-body bytes. It is absent when the adapter cannot prove those bytes. |
| `title`, `body`, `source`, `author` | Immutable captured evidence payload and source metadata. |
| `published_at` | Source publication timestamp. |
| `fetched_at` | When the exact evidence payload was captured. |
| `verification_id` | Stable receipt ID for this verification event. |
| `verified_at` | When deterministic body/source checks passed. |
| `verifier_version` | Version of the evidence-verification contract. |
| `verification_status` | Must be `PASS` to become reusable. |
| `verification_reasons` | Machine-readable checks: body-derived evidence present, retrieval/open observation present, URL safe, timestamp in window, allowed quality, factual-source eligibility. |
| `origin_run_id` | Run that first committed the exact version. |
| `reuse_mode` | `live-scout` or `same-window-cache`. |

### Topic-evidence link contract

Each link contains:

- stable `inventory_topic_id` plus the display topic captured at that time;
- `evidence_id` and `verification_id`;
- originating run ID;
- requested `window_start`, `window_end`, and `window_days`;
- link status `PASS` and the evidence-selection contract version.

This link is what makes fallback safe for a retained rolling-inventory candidate.
The rebuild must not try to recover that relationship by matching a later generated
topic sentence back to the ledger.

### Output contract: `EvidenceSetManifest`

```json
{
  "schema_version": 2,
  "run_id": "linkedin-...",
  "thesis_id": "thesis-1",
  "display_topic": "...",
  "requested_window": {
    "days": 7,
    "start": "...",
    "end": "..."
  },
  "evidence": [
    {
      "signal_id": "signal-1",
      "evidence_id": "<sha256>",
      "canonical_url": "https://...",
      "evidence_payload_sha256": "<sha256>",
      "source_body_sha256": null,
      "verification_id": "<stable receipt>",
      "published_at": "...",
      "verified_at": "...",
      "reuse_mode": "live-scout"
    }
  ]
}
```

One or two items remain the thesis contract today. They may come from different
research clusters. The loader must use an exact schema, owner-only private storage,
bounded size, no parent traversal, no symlink following, and change-during-read
detection, preserving the PR #138 hardening.

### Output contract: `EvidenceRecoveryDecision`

Every evidence attempt emits:

| Field | Meaning |
| --- | --- |
| `status` | `PASS`, `FAIL`, or `NOT_EVALUATED`. |
| `mode` | `live-scout`, `timeout-retry`, or `same-window-cache`. |
| `reason` | Exact machine-readable reason. |
| `attempt_count` | Actual web attempts. |
| `elapsed_ms` | Evidence-stage elapsed time. |
| `eligible_cached` | Count passing every cache predicate. |
| `selected_evidence_ids` | Exact identities passed downstream. |
| `rejections` | Counts by stale, blank-body, unverified, unsafe, unrelated, changed, or unsupported-origin. |

## Bounded same-window recovery algorithm

1. Freeze one run `as_of` and calculate `[as_of - days, as_of]` once. Every stage
   receives that exact window rather than recalculating the clock.
2. Load candidate-linked cached verification receipts before the web call, but do not
   select them yet. This makes timeout recovery immediate.
3. Run the source Scout under the evidence-stage budget supplied by the orchestrator.
   Permit one bounded retry only for a classified timeout/transient availability
   result. Do not retry contract or safety failures.
4. If the live call succeeds, validate every item and commit `VerifiedEvidence` plus
   topic links **before** invoking Topic Value. This checkpoint survives any later
   failure.
5. If both allowed live attempts time out, select only cached records for an admitted
   `inventory_topic_id` that satisfy every predicate below.
6. Require three to seven usable records for the evidence stage. Deduplicate by stable
   identity and preserve deterministic order. If fewer than three remain, fail with
   the rejection counts; never widen the time window or infer evidence.
7. Re-run current deterministic trust checks on the recovered set and record its
   `same-window-cache` provenance.
8. Topic Value then selects exact source identities and evaluates research trust,
   claim/body support, and published atomic-value novelty normally.

### Cache eligibility predicates

A cached record is eligible only when all are true:

- its latest receipt is `verification_status=PASS` under a supported verifier version;
- its exact `(canonical_url, evidence_payload_sha256)` captured payload remains
  present;
- `published_at` is inside the current requested window, including the cutoff and
  excluding future timestamps;
- its captured body-derived evidence is non-blank, has a retrieval/open observation,
  and was not derived from a title/snippet fallback;
- origin is an explicit private live import, never a fixture or legacy-unverified row;
- it has a prior PASS link to one of the currently admitted stable inventory topics;
- it meets the existing factual-source boundary, including at least one non-social
  body-read source in any selected Topic Value candidate;
- it has not been invalidated by a later integrity or verification event.

Do **not** reject a cached source merely because it supported a published post. Source
reuse is allowed. The newly proposed atomic value must still clear the published
atomic-value ledger independently.

## Invariants

1. No blank body can produce `body_verified=true`.
2. A title or web-search snippet never substitutes for inspected body evidence.
3. Evidence is immutable by capture. A changed captured payload at the same URL (or
   a changed publisher body digest, when available) creates a new evidence ID; it
   never silently rewrites a manifest-bound capture.
4. Every stage after evidence verification consumes explicit stable evidence IDs.
5. The exact Writer evidence set equals the thesis manifest set. Critic and citation
   gates receive that same set; extra ledger rows cannot enter by topic search.
6. Multi-cluster theses are valid. No downstream stage may require all topic words to
   occur in one cluster.
7. A manifest outside its requested window cannot be replayed in a later run.
8. Cache fallback is allowed only after the declared transient-attempt policy is
   exhausted and is always visible in the dashboard.
9. A successful evidence stage commits its reusable checkpoint before Topic Value.
10. Review-ready-but-unpublished atomic values do not block future selection.
11. Confirmed published atomic values do block equal or materially similar values at
    the existing `0.72` threshold.
12. Published source lineage uses stable evidence IDs, not `signal-*` labels.
13. The same evidence may support a different unpublished atomic value when all other
    gates pass.
14. Atomic novelty, research trust, and claim/body support keep their existing modes
    and thresholds; this packet does not weaken them.

## Test packet

### Research and verification unit tests

- Reject an empty body even when title, URL, and timestamp are valid.
- Reject title/snippet-only evidence as body verified.
- Accept `published_at` exactly on the window cutoff and exactly at `as_of`.
- Reject one second before the cutoff and any implausible future timestamp.
- Reject fixture and legacy-unverified origins from live reuse.
- Preserve two distinct evidence captures at one canonical URL as two evidence IDs.
- Detect malformed/tampered verification receipts.
- Commit verified evidence immediately, then simulate Topic Value and thesis failures;
  the evidence must remain reusable.

### Timeout and fallback tests

- First attempt succeeds: cache is not selected and mode is `live-scout`.
- First attempt times out, retry succeeds: mode is `timeout-retry`.
- Both attempts time out, three eligible linked records exist: mode is
  `same-window-cache`, and the stage advances.
- A malformed Scout response does not enter cache fallback.
- Cache with two valid records fails closed because the minimum is three.
- Cache containing stale, blank-body, fixture, changed, and unrelated rows reports a
  separate rejection count for each.
- Recovered items retain exact stable IDs and deterministic order.
- Simulated clock proves the evidence recovery remains inside the orchestrator's total
  7–8 minute run budget.

### Identity and manifest tests

- Retain PR #138's unretrievable-display-topic test: valid exact identities still
  reach Critic.
- Retain exact lookup order and changed-hash fail-closed tests.
- Reject display-topic mismatch, duplicate identities, unsafe paths, oversized files,
  and changed-during-read manifests.
- A one-source thesis succeeds.
- A two-source thesis spanning two clusters succeeds.
- Writer, Critic, citation, and proof gates receive exactly the manifest identities.
- Replaying a valid old manifest outside its stored requested window fails before
  Writer.

### Published atomic-value tests

- A review-ready binding alone does not enter novelty history.
- Confirmed manual publication promotes only the exact artifact binding.
- The same atomic value and a value at or above `0.72` similarity are rejected after
  promotion.
- The same sources with a materially new atomic value are allowed.
- A published ledger row contains stable evidence IDs matching the final manifest.
- A performance record with no exact review-ready binding does not promote an atomic
  value.
- Source reuse never bypasses research-trust or claim/body evaluation.

### Installed-runtime tests

- Use the public `linkedin-os discover --generate-post` entry point with the complete
  installer stack active. Force the source Scout to time out twice, provide eligible
  same-window cached receipts, and assert the run reaches Critic.
- Run the installed case twice. The second run may reuse the same verified evidence,
  but after simulated confirmed publication it must reject the same atomic value.
- With no eligible cache, assert the dashboard names evidence verification as the first
  blocker and all later stages remain `NOT_EVALUATED`.
- Assert the installed draft receives an evidence manifest and performs no topic-based
  ledger lookup.

## Interfaces to other rebuild packets

- **Orchestrator/latency:** supplies the evidence-stage deadline and classifies which
  failures are transient; this packet returns elapsed time and recovery mode.
- **Discovery/topic inventory:** supplies stable admitted `inventory_topic_id` values
  and preserves them across the rolling window.
- **Topic Value/thesis:** consumes run-local labels plus stable evidence IDs and emits
  the selected identities without rewriting them.
- **Drafting/Critic/gates:** consumes only `EvidenceSetManifest`; no ledger search by
  generated prose is permitted.
- **Packaging/performance:** returns the selected manifest identity with the final
  artifact so manual publication can promote the correct atomic binding.
- **Observability:** renders live versus cached evidence, exact identities, window,
  rejection counts, and the first blocker without exposing source bodies.

## Definition of done

- PR #138 behavior remains covered and unchanged.
- A verified evidence set is durable immediately after its stage passes.
- A source-Scout timeout can recover from three to seven exact, linked, body-verified,
  same-window records without extending the requested window.
- The final draft, Critic, gates, package, and publication binding can be traced to the
  exact evidence versions selected upstream.
- A published atomic value cannot be selected again, while source reuse for a new
  atomic value remains possible.
- The full installed-runtime test demonstrates this path through public entry points.
