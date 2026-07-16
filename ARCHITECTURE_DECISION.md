# Architecture decision: minimal offline runtime

Status: **accepted**

LinkedIn Authority OS starts with one fixed `linkedin-os` entry point and one small standard-library workflow module. The runtime supports idempotent local setup, secret-safe diagnostics, deterministic fixture analysis, and stateless strategic routing. It deliberately does not draft live content or generate an approval package yet.

## Current boundary

- Python 3.11+ standard library only; setup downloads nothing.
- `bin/linkedin-os` is the only executable entry point.
- `src/authority_os/__main__.py` owns fixed command routing.
- `src/authority_os/workflow.py` owns the synthetic fixture contract.
- Private state and generated outputs are ignored from Git.
- `src/authority_os/storage.py` owns one ignored SQLite research table with direct parameterized queries; no ORM or migration framework is needed.
- Research import validates public URLs and source quality, then deduplicates by canonical URL and normalized content hash without fetching.
- `workflow.py` performs deterministic two-pass analysis in place: metadata clustering followed by strongest-body interpretation and stale comparison. A separate analytics service, embedding index, or clustering dependency is not justified.
- The same module routes analysis plus explicit reader/decision inputs to Reach, Authority, or Opportunity, carries primary-source and input provenance, reports non-gating evidence limitations, and implements the four-post weekly mix. Citation/relevance pass-fail gates remain deferred. Goal and format are independent values; optional slot 5 requires an explicit human assertion of a strong incident or launch. A calendar, scheduler, routing service, or weekly-history table is not justified.
- There is no model invocation, network fetch, scheduler, browser automation, or LinkedIn write surface in this snapshot.

The runtime will grow only when a later atomic contribution adds a tested product outcome. No agent framework, command bus, service layer, or plugin abstraction is justified.
