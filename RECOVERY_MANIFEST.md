# Recovery manifest

This manifest uses repository evidence, not filenames or embedded version labels, to describe provenance. `RECOVERED` means exact historical text was retained. `RECOVERED AND MODIFIED` means a traceable historical component was adapted. `RECONSTRUCTED` means the requested asset was absent and was rebuilt from the supplied v6 brief. `NEW` means it did not exist in reachable history.

## Audit boundary

- Starting branch: `recovery/linkedin-authority-os-v6` at `69e40f2`.
- Historical prompt branch: the unrelated-root `origin/pipeline-v3-dual-score` at `c4dc07c`; selected semantics may be adapted, but the branch is not merged or cherry-picked wholesale.
- Eight commits are reachable across the three repository branches. `git fsck --full --strict` found no unreachable recovery objects.
- No commit, tag, or branch is dated June 25. Git proves a May 29 historical prompt set and a July 16 recovery scaffold, not an exact June 25 backup.
- The raw 8K-post dataset, personal analytics, voice-anchor post text, SQLite databases, and claimed Analyst/Critic v5 originals do not exist in reachable repository history.

## Evidence-backed classifications

| Component | Classification | Evidence and treatment |
| --- | --- | --- |
| `.claude/skills/prd-first/SKILL.md` | RECOVERED | Existing unrelated file from `09b9cf0`; preserved unchanged. |
| `README.md` | RECONSTRUCTED | The July 16 overview from `abfd710` established intent; this recovery-stage README documents only the assets present now. |
| `.claude/agents/scout.md` | RECOVERED AND MODIFIED | The current scaffold is reconstructed; source/storage semantics are selectively adapted from `21e04d5:.claude/agents/scout.md` (embedded Scout v5 label). Gmail, bespoke collectors, and source quotas are excluded. |
| `.claude/agents/analyst.md` | RECOVERED AND MODIFIED | The July stub `69e40f2:prompts/analyst.md` is combined with clustering, source-diversity, and stale-topic semantics from `21e04d5:.claude/agents/analyst.v4.bak.md`. The duplicate `prompts/` copy is removed. |
| `.claude/agents/writer.md` | RECOVERED AND MODIFIED | Three-candidate and voice-safety semantics come from `21e04d5:.claude/agents/writer.v1.bak.md`; forced stylistic devices and database writes are removed. |
| `.claude/agents/critic.md` | RECOVERED AND MODIFIED | The five-axis 25-point rubric comes from `21e04d5:.claude/agents/critic.v4.bak.md`; thresholds and v6 binary gates follow the supplied brief. |
| Voice guide and performance-pattern anchors | RECONSTRUCTED | The originals are absent. Only user-supplied aggregate patterns and voice rules are recorded; missing post text is never fabricated. |
| `.gitignore` | NEW | Protects private inputs, databases, credentials, generated packages, and the local `.agents/` mirror. |
| `bin/linkedin-os`, `src/authority_os/*` | NEW | Minimal offline CLI and fixture-validation runtime; no historical executable exists. |
| `src/authority_os/storage.py` | NEW | Direct research-ledger persistence with canonical URL and normalized-content deduplication. |
| `data/samples/dry-run.json` | NEW | Visibly synthetic offline fixture data. |
| `Makefile`, `requirements.txt` | NEW | Zero-download setup and verification commands. |
| `ARCHITECTURE_DECISION.md` | NEW | Records the deliberately small current runtime boundary. |
| `tests/test_cli.py`, `tests/test_storage.py` | NEW | Setup, diagnostics, fixture, research persistence, failure, and no-publishing tests. |
| `tests/test_recovery.py` | NEW | Validates the asset inventory, provenance labels, exclusions, and private-path ignore boundary. |
| `.github/workflows/test.yml` | NEW | Runs the recovery validation on pushes and pull requests; it has no schedule. |
| `RECOVERY_MANIFEST.md` | NEW | This evidence-backed provenance record. |
| `prompts/analyst.md` | RECONSTRUCTED, THEN REMOVED | Its useful July stub content moved into the one canonical Analyst agent; no duplicate prompt remains. |

## Deliberately not recovered

- Supervisor, Narrator, Tracker, Article Writer, Course Builder, archived prompts, backup copies, and the dual-score Critic.
- Gmail newsletter ingestion, authenticated browser analytics, secret-printing diagnostics, scheduled course triggers, comment-codeword flows, and any publishing or messaging behaviour.
- Historical claims such as forced seven-post cadence, fixed source quotas, forced Indian analogies, forced numbers, and unsupported reach-loss percentages.

## Safely deferred

- `.claude/skills/draft-post/SKILL.md` is `RECONSTRUCTED`, not an original. It remains preserved on the superseded source branch and will land only when its referenced CLI, workflow document, and output contract are runnable.

The historical branch remains untouched as provenance. Existing untracked `.agents/` files are locally preserved and ignored; they are not part of this recovery. Runtime code is intentionally out of scope for this asset-only contribution and follows in later atomic work.
