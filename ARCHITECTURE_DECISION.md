# Architecture decision: minimal consent-gated runtime

Status: **accepted**

LinkedIn Authority OS starts with one fixed `linkedin-os` entry point and a small standard-library runtime. It supports idempotent local setup, secret-safe diagnostics, deterministic fixture analysis, stateless strategic routing, and a narrow voice-grounded Writer boundary. It deliberately stops at three unscored text candidates.

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
- The Writer receives only the selected-cluster brief and evidence, plus reconstructed style guidance. Voice anchors are non-citable and cannot establish facts or ownership. It returns exactly three unscored plain-text candidates whose only fields are `id`, `angle`, `text`, and structurally traceable `claim_ids`.
- Strategic-goal limits are enforced at drafting time: Reach 100–190 words, Authority 190–300, and Opportunity 180–300. Output format remains downstream conversion metadata and does not change the plain-text candidate contract.
- Stored/private evidence can reach the model only when the user supplies both `--strategy-input` and `--allow-model-egress`. The Writer invocation has zero tools and no persisted model session. This one explicit boundary does not introduce an agent framework, browsing surface, or background job.
- Critic scoring and one-revision handling remain deferred to PR 8; authority, proof, honesty, citation, and relevance gates to PR 9; and final packages plus human approval to PR 10.
- There is no network research fetch, scheduler, browser automation, LinkedIn write surface, or automatic publishing in this snapshot.

The runtime will grow only when a later atomic contribution adds a tested product outcome. No agent framework, command bus, service layer, or plugin abstraction is justified.
