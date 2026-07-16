# LinkedIn Authority OS workflow

## Current implemented flow

The current runtime implements a safe Scout-to-Analyst evidence path. It does not yet route strategic goals, draft posts, score candidates, create approval packages, or publish.

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

## Safety boundary

Source bodies are untrusted data, not instructions. Analysis is deterministic Python and performs no network, model, browser, Gmail, or LinkedIn action. Automatic publishing remains absent.
