# Architecture decision: LinkedIn Authority OS v6

Status: **APPROVED** on 2026-07-16 by the read-only Architecture Simplicity Reviewer, subject to the boundary below.

## Current repository state

The starting branch contains a concise v6 intent, a draft-post coordinator, a simplified Scout, and an Analyst stub. It does not contain a runnable CLI, database setup, voice files, Writer, Critic, fixtures, tests, privacy controls, output packaging, or CI. The draft skill points to missing voice files and an obsolete single-file `drafts/` destination.

An unrelated-root historical branch contains several generations of agents. It is valuable as provenance but internally inconsistent: its agents disagree on schema names, draft counts, score thresholds, and revision limits, and they depend on absent data. Importing the branch would also add duplicate prompts and out-of-scope supervisor, narrator, article, course, Gmail, browser, and scheduling concepts.

The local working copy also has an untracked `.agents/` mirror. It belongs to the user's environment, is preserved locally, and is ignored rather than committed or deleted.

## Recovered architecture

Only these evidence-backed responsibilities are retained:

1. Scout records traceable source items and fails honestly when research is insufficient.
2. Analyst performs metadata clustering first, then reads the strongest bodies, checks source diversity, proposes a differentiated angle, and marks recent repetition stale.
3. Writer reads reconstructed voice guidance and creates exactly three materially different entry angles.
4. Critic applies the recovered five-axis, 25-point rubric plus v6 authority-conversion, proof, honesty, relevance, and citation gates.
5. At most one selected-candidate revision is permitted.
6. A complete package is handed to a human. Nothing publishes, comments, messages, or changes LinkedIn state.

The v6 strategy routes `reach`, `authority`, and `opportunity` independently from format and uses `Incident → Mechanism → Decision → Artifact` as a default, not a forced template.

## Minimal proposed implementation

```text
bin/linkedin-os
src/authority_os/{__init__.py,__main__.py,workflow.py,storage.py}
.claude/agents/{scout.md,analyst.md,writer.md,critic.md}
.claude/skills/draft-post/SKILL.md
data/voice/{voice-guide.md,abhillash-best-posts.md}
data/samples/{dry-run.json,performance.csv}
scripts/check_privacy.py
tests/{test_workflow.py,test_storage.py,test_cli.py}
outputs/.gitkeep
```

- `__main__.py` owns fixed `argparse` command routing and no generic command execution.
- `workflow.py` owns research normalisation, deterministic safety gates, stale similarity, optional Claude subprocess calls, the one-revision limit, and atomic five-file package rendering.
- `storage.py` owns direct, parameterised SQLite functions for two tables. There is no ORM, repository class, or migration framework.
- The four `.claude/agents/` files are the only role prompts. The draft-post skill is the only coordinator.
- Dry-run mode reads a committed synthetic fixture and never invokes Claude or the network.
- Live mode may invoke the local authenticated `claude` executable. Calls use safe mode, load one canonical role prompt explicitly, pass dynamic input over stdin, and persist no session. Scout is restricted to read-only web tools; Analyst, Writer, and Critic receive data in their prompt and get no tools. Python alone writes repository/runtime files.
- The default daily draft never sends stored/private research to a model; it uses fresh public Scout results held in memory. Reusing selected database excerpts requires `--allow-model-egress`. The README enumerates the transmitted fields.
- Successful packages are assembled in a sibling temporary directory and atomically renamed. Existing packages are never overwritten.

The only database is ignored at `data/private/authority_os.sqlite`. It has exactly two tables:

- `research_items`, with unique canonical URL and normalised-content hash;
- `performance`, keyed by post, checkpoint, and channel so organic and paid observations cannot overwrite one another.

Draft packages remain the draft source of truth; no drafts table is needed.

## Files genuinely required

- User surface: `README.md`, `Makefile`, `requirements.txt`, `bin/linkedin-os`.
- Governance: this file, `RECOVERY_MANIFEST.md`, `DECISIONS.md`, `.gitignore`.
- Runtime: the four Python package files listed above.
- Claude Code compatibility: four agents and one draft-post skill. The unrelated existing `prd-first` skill remains unchanged.
- Calibration: two reconstructed, clearly labelled voice files with aggregate patterns only.
- Safe operation: one synthetic dry-run fixture, one performance import example, `.gitkeep`, and the privacy check.
- Verification: three test files and one push/pull-request-only GitHub Actions workflow.
- Workflow explanation: `docs/WORKFLOW.md`.

No other folder or module has a current responsibility.

## Dependencies genuinely required

- Python 3.11 or newer.
- Python standard library only at runtime and in tests.
- SQLite through Python's standard-library `sqlite3` module.
- Optional local `claude` executable for live research and drafting.

There are zero pip runtime dependencies. `requirements.txt` documents that fact; setup does not download packages.

## Alternatives rejected

- LangGraph, LangChain, CrewAI, agent frameworks, microservices, web apps, dashboards, vector databases, plugin systems, event buses, dependency injection, ORMs, schedulers, and provider registries.
- A Supervisor or Narrator layer, because the draft-post coordinator and single revision rule are sufficient.
- A Tracker agent or browser automation; performance is explicit CLI/CSV input only.
- Gmail/newsletter ingestion, raw social scraping, source-specific MCP integrations, feed-health state, and an embedded HTTP crawler.
- Duplicate `prompts/`, `.archive/`, `.bak`, or committed `.agents/` copies.
- A drafts table, jobs table, user table, configuration table, or migration framework.
- LinkedIn OAuth, API calls, browser clicks, automatic publishing, commenting, messaging, or generic webhooks.
- Scheduled research or review workflows.
- Automatic rubric tuning from performance data.
- Separate carousel, video, and article modules; Writer may recommend those formats in the package.

## Complexity deliberately avoided

- Two modules hold runtime responsibilities until their size or change rate demonstrates a need to split.
- One SQLite file and two tables provide cross-run deduplication and channel-safe metrics without a service layer.
- The CLI uses a fixed command allowlist; there is no command bus or extension mechanism.
- Dry-run is deterministic fixture playback. It is never presented as live research or a publishable personal story.
- Source traceability is a validation mechanism, not a claim that a source is true. Human verification remains mandatory.
- No workflow writes outside ignored private/generated paths, and no diagnostic prints credential values.

## Reviewer agreements and disagreement resolution

All three initial reviewers agreed on the privacy boundary, standard-library implementation, ignored persistence, exact three-draft/one-revision constraints, truthful provenance, fixture coverage, and absence of any publishing surface.

The Test, Privacy and Reliability Reviewer proposed separate `quality.py`, `research.py`, and `cli.py` modules. The Architecture Simplicity Reviewer approved the smaller two-module runtime. The approved smaller boundary is adopted because each responsibility remains directly testable and no current change pattern justifies additional module seams. The stricter privacy and reliability recommendations still apply in full.

## Known limitations

- The original voice-anchor post text, raw research corpus, and personal analytics were not found and are not reconstructed. Calibration uses only the user-supplied aggregate patterns until the user imports private local data.
- Live quality depends on the locally authenticated Claude CLI and current web access. Fixture mode remains fully offline.
- Reusing imported/private research with a live model requires explicit `--allow-model-egress`; the default daily command performs fresh public research instead.
- Canonicalisation and content hashes remove exact/normalised duplicates; they are not semantic search or fact verification.
- The simple token-similarity stale check may require human judgment at the boundary.
- Weekly review reports patterns but never changes the frozen rubric automatically.
- Output status means ready for human review, not fact-checked, approved, scheduled, or published.
