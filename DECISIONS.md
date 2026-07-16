# Decision log

## 2026-07-16 — Milestone 1: recovery audit

- Audited all three local and remote branch heads, all eight reachable commits, reflogs, repository trees, and unreachable-object state.
- Confirmed that the starting branch is a non-runnable six-file scaffold and that no exact June 25 backup is verifiable in Git.
- Selected only traceable Scout, Analyst, three-draft Writer, 25-point Critic, and performance-learning semantics for adaptation.
- Preserved the unrelated `prd-first` skill and the local untracked `.agents/` mirror.
- Rejected wholesale recovery of the orphan historical branch and excluded its Gmail, browser, scheduling, supervisor, narrator, course, article, and publishing-adjacent concepts.
- Added ignore protection before runtime work so private inputs, databases, environments, generated packages, and local skill mirrors cannot be committed accidentally.

Check: `git diff --check`.

## 2026-07-16 — Milestone 2: architecture approval

- Accepted the Architecture Simplicity Reviewer's `APPROVE` verdict and its conditional boundary.
- Chose one standard-library CLI, two runtime modules, one ignored SQLite database, two tables, four canonical role prompts, and zero pip dependencies.
- Resolved the module-count disagreement in favour of the smaller approved design while retaining every privacy and failure-path test requested by the reliability review.
- Restricted optional live Claude calls: Scout may use read-only web tools; all later roles receive data directly and get no tools. Python alone owns runtime writes.
- Rejected direct HTTP crawling, duplicate prompts, orchestration layers, schedulers, browser/Gmail access, and every LinkedIn write surface.

Check: `git diff --check`.

## 2026-07-16 — Milestone 3: minimal implementation

- Added the fixed `linkedin-os` CLI with `init`, `doctor`, `research`, `draft`, `record-performance`, and `weekly-review` only.
- Implemented canonical URL/content deduplication, two-pass analysis, exactly three candidates, the recovered five-axis rubric, v6 binary gates, one-revision cap, collision-safe atomic five-file packages, and explicit paid/organic checkpoints.
- Kept one ignored SQLite database with exactly `research_items` and `performance` tables.
- Reconstructed the missing voice files honestly from supplied aggregate patterns and made four role prompts canonical under `.claude/agents/`.
- Moved the Analyst stub into its canonical agent and removed the duplicate `prompts/` location.
- Added a synthetic offline fixture using traceable NIST/Anthropic sources, transparent arithmetic, and a committed proof framework. Fixture packages are labelled `Do not publish`.
- Preserved the unrelated `prd-first` skill unchanged and kept generated/private state ignored.

Checks: `make setup`, `make doctor`, Python compilation, fixture JSON validation, all six CLI surfaces, two complete dry-run packages (including Opportunity), performance recording, weekly review, and `git diff --check`.
