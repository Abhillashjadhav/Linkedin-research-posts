# Recovery manifest

This manifest uses repository evidence, not filenames or embedded version labels, to describe provenance. `RECOVERED` means exact historical text was retained. `RECOVERED AND MODIFIED` means a traceable historical component was adapted. `RECONSTRUCTED` means the requested asset was absent and was rebuilt from the supplied v6 brief. `NEW` means it did not exist in reachable history.

## Audit boundary

- Starting branch: `recovery/linkedin-authority-os-v6` at `69e40f2`.
- Historical prompt branch: the unrelated-root `origin/pipeline-v3-dual-score` at `c4dc07c`; selected semantics may be adapted, but the branch is not merged or cherry-picked wholesale.
- At the initial recovery audit, eight commits were reachable across the three repository branches. `git fsck --full --strict` found no unreachable recovery objects at that boundary; later atomic implementation commits are not historical recovery evidence.
- No commit, tag, or branch is dated June 25. Git proves a May 29 historical prompt set and a July 16 recovery scaffold, not an exact June 25 backup.
- The raw 8K-post dataset, personal analytics, voice-anchor post text, SQLite databases, and claimed Analyst/Critic v5 originals do not exist in reachable repository history.

## Evidence-backed classifications

| Component | Classification | Evidence and treatment |
| --- | --- | --- |
| `.claude/skills/prd-first/SKILL.md` | RECOVERED | Existing unrelated file from `09b9cf0`; preserved unchanged. |
| `README.md` | RECONSTRUCTED | The July 16 overview from `abfd710` established intent; the current document describes the completed, deliberately bounded runtime without presenting reconstructed material as an original. |
| `.claude/skills/draft-post/SKILL.md` | RECONSTRUCTED | The July coordinator from `7d1e0d2` was not an historical original and referenced obsolete flags and package semantics. It is reconstructed against the completed fixed CLI, explicit model-egress consent, six-file review package, and disabled-publishing boundary. |
| `.claude/agents/scout.md` | RECOVERED AND MODIFIED | The current scaffold is reconstructed; source/storage semantics are selectively adapted from `21e04d5:.claude/agents/scout.md` (embedded Scout v5 label). Gmail, bespoke collectors, and source quotas are excluded. |
| `.claude/agents/analyst.md` | RECOVERED AND MODIFIED | The July stub `69e40f2:prompts/analyst.md` is combined with clustering, source-diversity, and stale-topic semantics from `21e04d5:.claude/agents/analyst.v4.bak.md`. The duplicate `prompts/` copy is removed. |
| `.claude/agents/writer.md` | RECOVERED AND MODIFIED | Three-candidate and voice-safety semantics come from `21e04d5:.claude/agents/writer.v1.bak.md`; forced stylistic devices and database writes are removed. |
| `.claude/agents/critic.md` | RECOVERED AND MODIFIED | The five-axis 25-point rubric comes from `21e04d5:.claude/agents/critic.v4.bak.md`; thresholds and v6 binary gates follow the supplied brief. |
| Voice guide and performance-pattern anchors | RECONSTRUCTED | The originals are absent. Only user-supplied aggregate patterns and voice rules are recorded; missing post text is never fabricated. |
| `.gitignore` | NEW | Protects private inputs, databases, credentials, generated packages, and the local `.agents/` mirror. |
| `bin/linkedin-os`, `src/authority_os/*` | NEW | Fixed standard-library CLI and its tested research, analysis, drafting, scoring, gating, packaging, performance, and learning runtime; no historical executable exists. |
| `src/authority_os/storage.py` | NEW | Direct research and performance persistence with fail-closed provenance/migrations and paid/organic separation. |
| `src/authority_os/package.py` | NEW | Deterministic, private six-file human-review packaging with live-only recommendation eligibility and no approval or publishing authority. |
| `src/authority_os/performance.py` | NEW | Package-linked manual checkpoint validation; no analytics fetch, approval mutation, or publishing action. |
| `src/authority_os/learning.py`, `tests/test_learning.py` | NEW | Compares trusted mature organic observations with stored Critic snapshots, reports paid observations separately, and permits rubric recommendations only after repeated independent evidence. It never edits the rubric. |
| `src/authority_os/privacy.py`, `scripts/check_privacy.py`, `tests/test_privacy.py` | NEW | Enforces ignored private/generated paths, credential-pattern checks, push/pull-request-only automation, and the absence of LinkedIn or browser write surfaces. |
| `data/samples/dry-run.json` | NEW | Visibly synthetic offline fixture data. |
| `data/samples/proof-fixture.json`, `data/samples/synthetic-proof.md` | NEW | Visibly synthetic local-proof fixture; it contains no personal data or publishing authority. |
| `Makefile`, `requirements.txt` | NEW | Zero-download setup plus test, diagnostic, and privacy verification commands. |
| `ARCHITECTURE_DECISION.md` | NEW | Records the deliberately small current runtime boundary. |
| `docs/WORKFLOW.md` | RECONSTRUCTED | Documents the completed evidence-to-learning boundary without claiming absent automation or historical assets. |
| `tests/test_cli.py`, `tests/test_storage.py` | NEW | Setup, diagnostics, fixture, research/performance persistence, migration, failure, and no-publishing tests. |
| `tests/test_performance.py` | NEW | Validates live-package binding, strict timestamps/metrics, private CSV batches, and fixture/symlink rejection. |
| `tests/test_gates.py` | NEW | Validates strict proof privacy and deterministic authority, proof, honesty, citation, and relevance gates. |
| `tests/test_package.py` | NEW | Validates eligibility, fixture suppression, blocked outcomes, privacy projections, collision safety, atomic writes, restrictive modes, and rollback. |
| `tests/test_recovery.py` | NEW | Validates the asset inventory, coordinator contract, provenance labels, exclusions, and private-path ignore boundary. |
| `.github/workflows/test.yml` | NEW | Runs the full tests and privacy validation on pushes and pull requests; it has no schedule or publishing authority. |
| `RECOVERY_MANIFEST.md` | NEW | This evidence-backed provenance record. |
| `prompts/analyst.md` | RECONSTRUCTED, THEN REMOVED | Its useful July stub content moved into the one canonical Analyst agent; no duplicate prompt remains. |

## Deliberately not recovered

- Supervisor, Narrator, Tracker, Article Writer, Course Builder, archived prompts, backup copies, and the dual-score Critic.
- Gmail newsletter ingestion, authenticated browser analytics, secret-printing diagnostics, scheduled course triggers, comment-codeword flows, and any publishing or messaging behaviour.
- Historical claims such as forced seven-post cadence, fixed source quotas, forced Indian analogies, forced numbers, and unsupported reach-loss percentages.

## Superseded large-PR artifacts

The original combined implementation remains on `build/linkedin-authority-os-v6-complete` at `54c8d61` as provenance. Its usable outcomes were rebuilt through the atomic sequence rather than merged wholesale:

- The old draft-post coordinator is replaced by the current reconstructed coordinator. Its obsolete proof flags, implicit live research, five-file package, and ready-for-approval wording are not retained.
- `data/samples/performance.csv` is not restored because its free-form post ID cannot prove which eligible package candidate a human published. The package-linked exact CSV contract is documented instead, and private imports remain under ignored `data/private/`.
- The old `weekly_review_markdown` implementation is not retained because it guessed from Markdown, could substitute paid observations for organic learning, and did not establish repeated independent evidence. The new learning boundary consumes verified package-linked snapshots and never tunes the rubric automatically.
- The old `DECISIONS.md` is superseded by the current architecture record and atomic pull-request history; copying it would reintroduce inaccurate two-table, live-Scout, and five-file-package claims.
- The monolithic `tests/test_workflow.py` is superseded by focused analysis, strategy, drafting, Critic, gate, package, performance, learning, privacy, storage, CLI, and recovery tests.

The historical branches remain untouched as provenance. Existing untracked `.agents/` files are locally preserved and ignored; they are not part of this recovery. The implemented runtime remains deliberately local, consent-gated, human-reviewed, and unable to publish automatically.
