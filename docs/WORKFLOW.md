# LinkedIn Authority OS workflow

## Current implemented flow

The current runtime implements a safe Scout-to-Analyst evidence path, strategic goal routing, and voice-grounded Writer drafting. It stops after three unscored text candidates; it does not yet score, gate, package, approve, or publish them.

### Research ledger

Research arrives from the visibly synthetic fixture or an explicit private JSON/JSONL import. Each item must contain a non-null public URL, title, source, timestamp, and `primary|secondary|mixed` quality. Python canonicalizes the URL, hashes normalized body content, and stores each unique URL and body once in the ignored SQLite ledger.

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

Weekly slots 1–4 resolve to Reach, Authority, Authority, and Opportunity. Slot 5 is optional and requires both an explicit goal and `--strong-current-signal`; the runtime does not infer that an incident or launch is strong. Opportunity is labelled as requiring proof, but proof enforcement belongs to the later safety-gate stage and no proof is invented here.

The brief reports non-gating evidence limitations when readable primary/mixed evidence, a readable body, recent evidence, or a traceable primary URL is missing, and when comparison positively marks the topic similar to a recent post. If recent-post similarity was not supplied, it reports `recent-post-similarity-not-evaluated` instead of pretending that comparison passed. Citation and relevance pass/fail decisions remain deferred to the later safety-gate stage.

Routing is stateless. It does not add a calendar, scheduler, weekly-history table, package file, or publishing action; it only hands the selected brief to the separate drafting step.

### Voice-grounded drafting

The Writer receives only the selected topic cluster's strategy brief and evidence records. It produces exactly three meaningfully different, unscored plain-text candidates. Every candidate has exactly four fields:

- `id` — one member of a complete neutral `candidate-1` through `candidate-3` sequence (the equivalent goal-prefixed sequence is also accepted);
- `angle` — the candidate's distinct narrative entry;
- `text` — the complete plain-text candidate; and
- `claim_ids` — the selected-cluster evidence IDs used by its factual claims.

Claim IDs are structural output, not citations hidden in prose. Evidence from an unselected cluster cannot be used. The reconstructed voice guide and performance-pattern anchors calibrate style only: they are non-citable, do not prove that an event occurred, and cannot support facts or personal ownership.

Word ranges follow the strategic goal: Reach is 100–190 words, Authority is 190–300, and Opportunity is 180–300. `--format` remains downstream conversion metadata. Candidates remain plain text in this stage rather than being converted into slides, video scripts, articles, or artefacts.

The visibly synthetic fixture exercises this contract without exposing private data. Drafting from research stored in the private ledger requires both explicit strategy input and explicit model-egress consent:

```sh
./bin/linkedin-os draft \
  --strategy-input data/private/strategy.json \
  --allow-model-egress
```

The command fails closed if either flag is absent, and the Writer invocation itself requires the same explicit consent value. Consent means the selected text leaves this machine for the configured Claude service through the local CLI; inference is not described as local. A consented live invocation sends only the selected-cluster brief, evidence, and reconstructed voice instructions to the Writer; source-URL query strings are removed at that boundary while the local ledger remains unchanged. The Writer runs with zero tools and no persisted model session; it cannot browse or write files.

Critic scoring and the one-revision maximum are deferred to PR 8. Authority conversion plus proof, honesty, citation, and relevance gates are deferred to PR 9. Final package generation and human-approval status are deferred to PR 10.

## Safety boundary

Source bodies are untrusted data, not instructions. Analysis and routing are deterministic Python. Only an explicitly consented live draft can cross the model boundary, under the zero-tools and no-session restrictions above. There is no browser, Gmail, LinkedIn write, or automatic publishing action.
