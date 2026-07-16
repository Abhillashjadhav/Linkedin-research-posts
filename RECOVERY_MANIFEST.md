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
| `README.md` | RECONSTRUCTED | July 16 v6 overview from `abfd710`; useful intent retained, but it is not an exact historical original. |
| `docs/WORKFLOW.md` | RECONSTRUCTED | July 16 v6 workflow summary from `dca32c2`; expanded to match the supplied acceptance criteria. |
| `.claude/skills/draft-post/SKILL.md` | RECONSTRUCTED | Added in `7d1e0d2`; no earlier draft-post skill exists in Git. |
| `.claude/agents/scout.md` | RECOVERED AND MODIFIED | The current scaffold is reconstructed; source/storage semantics are selectively adapted from `21e04d5:.claude/agents/scout.md` (embedded Scout v5 label). Gmail, bespoke collectors, and source quotas are excluded. |
| `.claude/agents/analyst.md` | RECOVERED AND MODIFIED | The July stub `69e40f2:prompts/analyst.md` is combined with clustering, source-diversity, and stale-topic semantics from `21e04d5:.claude/agents/analyst.v4.bak.md`. The duplicate `prompts/` copy is removed. |
| `.claude/agents/writer.md` | RECOVERED AND MODIFIED | Three-candidate and voice-safety semantics come from `21e04d5:.claude/agents/writer.v1.bak.md`; forced stylistic devices and database writes are removed. |
| `.claude/agents/critic.md` | RECOVERED AND MODIFIED | The five-axis 25-point rubric comes from `21e04d5:.claude/agents/critic.v4.bak.md`; thresholds and v6 binary gates follow the supplied brief. |
| Voice guide and performance-pattern anchors | RECONSTRUCTED | The originals are absent. Only user-supplied aggregate patterns and voice rules are recorded; missing post text is never fabricated. |
| `src/authority_os/__init__.py` | NEW | Package version only. |
| `src/authority_os/__main__.py` | NEW | Fixed CLI command router; no historical executable exists. |
| `src/authority_os/workflow.py` | NEW | Minimal workflow, gates, optional Claude calls, and atomic renderer. |
| `src/authority_os/storage.py` | NEW | Direct two-table SQLite persistence. |
| `bin/linkedin-os`, `Makefile`, `requirements.txt` | NEW | Zero-download setup and the single CLI entry point. |
| `data/samples/dry-run.json` | NEW | Synthetic offline evidence, drafts, and a small proof framework; visibly not live content. |
| `data/samples/performance.csv` | NEW | Synthetic import-schema example. |
| `scripts/check_privacy.py` | NEW | Public-boundary and no-publishing invariant check. |
| `tests/test_workflow.py` | NEW | Rubric, gates, stale detection, one-revision, atomic-output, and honest-failure tests. |
| `tests/test_storage.py` | NEW | Schema, deduplication, idempotence, transactional validation, and paid/organic tests. |
| `tests/test_cli.py` | NEW | Offline integration, redaction, command allowlist, ignore, and CI-trigger tests. |
| `.github/workflows/test.yml` | NEW | Push/pull-request test workflow only; no schedule. |
| `outputs/.gitkeep` | NEW | Preserves the ignored generated-output root. |
| `.gitignore` | NEW | Protects private inputs, databases, credentials, generated packages, and the local `.agents/` mirror. |
| `ARCHITECTURE_DECISION.md`, `RECOVERY_MANIFEST.md`, `DECISIONS.md` | NEW | Governance records produced by the required review process. |
| `prompts/analyst.md` | RECONSTRUCTED, THEN REMOVED | Its useful July stub content moved into the one canonical Analyst agent; no duplicate prompt remains. |

## Deliberately not recovered

- Supervisor, Narrator, Tracker, Article Writer, Course Builder, archived prompts, backup copies, and the dual-score Critic.
- Gmail newsletter ingestion, authenticated browser analytics, secret-printing diagnostics, scheduled course triggers, comment-codeword flows, and any publishing or messaging behaviour.
- Historical claims such as forced seven-post cadence, fixed source quotas, forced Indian analogies, forced numbers, and unsupported reach-loss percentages.

The historical branch remains untouched as provenance. Existing untracked `.agents/` files are locally preserved and ignored; they are not part of this pull request.
