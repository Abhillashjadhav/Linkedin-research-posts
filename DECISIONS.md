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

## 2026-07-16 — Milestone 4: tests and privacy validation

- Added 35 standard-library tests covering all 13 mandated acceptance cases plus candidate distinctness, the one-revision ceiling, source-diversity shortfall, path traversal, prompt-injection inertness, package collisions, idempotent setup, transactional metric imports, score arithmetic, redaction, and rubric stability.
- Added a tracked/intended-file privacy check for ignored private paths, database/environment files, credential patterns, scheduled workflows, and LinkedIn/browser write surfaces.
- Added a minimal GitHub Actions workflow triggered only by pushes and pull requests.
- Tightened content deduplication to hash normalised bodies (title fallback), made CSV performance imports transactional, and made runtime stale checks compare the actual recommended winner rather than an entire package.
- Kept fixture mode model/network-free and verified that failed proof, honesty, citation, authority, relevance, or stale gates cannot produce a ready status.

Checks: `make test` (35 passed), privacy scan passed, Python compilation passed, and `git diff --check` passed.

## 2026-07-16 — Milestone 5: independent code review

- Accepted the skeptical staff review's `REQUEST CHANGES` verdict and corrected all five P1/P2 findings.
- Ranked only eligible candidates as winners, so a gated high score can never displace a ready draft.
- Added explicit `--allow-model-egress` consent for selected stored research; the default daily command now drafts only from fresh public Scout results held in memory.
- Labelled non-passing packages as rejected with their blocking gates, validated proof arguments unconditionally, and preserved live Critic observations as advisory output without letting them override deterministic gates.
- Hardened Claude calls with safe mode, canonical prompt loading, stdin-only dynamic evidence, no session persistence, and an allowlisted tool boundary.
- Made weekly review report the actual winning narrative angle and authority conversion from its matching package.
- The final independent pass returned `REQUEST CHANGES` for three remaining attribution defects. Opportunity proof is now candidate-specific and visible in the package; plural ownership and unsupported named terms fail deterministic gates; and performance uses the printed `YYYY-MM-DD/slug` package ID instead of guessing across repeated slugs.
- Fixture packages are excluded from live stale-history comparisons, and a scored revision is now shown beside initial Critic scores.

Checks: `make test` (49 passed), privacy scan passed, ResourceWarning-as-error suite passed, Python/fixture compilation passed, and `git diff --check` passed.
