# Architecture decision: minimal consent-gated runtime

Status: **accepted**

LinkedIn Authority OS starts with one fixed `linkedin-os` entry point and a small standard-library runtime. It supports idempotent local setup, secret-safe diagnostics, deterministic fixture analysis, stateless strategic routing, a narrow voice-grounded Writer boundary, and a score-only Critic boundary. It deliberately stops after scoring the candidate set and, only in the 22–23 band, at most one light Writer revision and one rescore.

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
- The Writer receives only the selected-cluster brief and evidence, plus reconstructed style guidance. Voice anchors are non-citable and cannot establish facts or ownership. It returns exactly three plain-text candidates whose only fields are `id`, `angle`, `text`, and structurally traceable `claim_ids`; scores remain a separate Critic-owned envelope.
- Strategic-goal limits are enforced at drafting time: Reach 100–190 words, Authority 190–300, and Opportunity 180–300. Output format remains downstream conversion metadata and does not change the plain-text candidate contract.
- Stored/private evidence can reach a model only when the user supplies both `--strategy-input` and `--allow-model-egress`. Writer and score-only Critic invocations have zero tools and no persisted model session. The offline fixture invokes neither model. This explicit boundary does not introduce an agent framework, browsing surface, or background job.
- The Critic accepts exactly five integer 1–5 axes: hook strength, middle escalation, earned closer, specificity and source quality, and voice fidelity. Python validates the scorecards and computes totals. Hook strength of 3 or below caps the effective total at 18.
- Effective totals of 24–25 advance to later gates, 22–23 permit exactly one light Writer revision and one rescore, and 21 or below fall below the Critic bar. Ranking compares effective total, raw total, and each rubric axis descending before candidate ID ascending, so input order cannot change the deterministic score leader. It is not a winner or recommendation, and no recursive revision is allowed.
- The model-facing Critic prompt is derived only from the recovered scoring rubric. It excludes the recovered authority, proof, honesty, citation, and relevance gates, which remain deferred to PR 9. Final packages and human-approval status remain deferred to PR 10. Neither a Critic score nor the `advance-to-gates` state is approval.
- There is no network research fetch, scheduler, browser automation, LinkedIn write surface, or automatic publishing in this snapshot.

The runtime will grow only when a later atomic contribution adds a tested product outcome. No agent framework, command bus, service layer, or plugin abstraction is justified.
