# Security and privacy reference

This document holds the low-level runtime and filesystem material behind the concise safety summary in the README. The controls protect private research, proof, review packages, performance observations, and learning reports while preserving a fail-closed, publication-disabled boundary.

## Supported runtime

- Python 3.11 or newer.
- Standard library only; `requirements.txt` has no runtime packages.
- A secure POSIX filesystem runtime on macOS or Linux.
- Windows is not supported for private-data operations that require descriptor-relative traversal, no-follow opens, owner identity checks, restrictive modes, hard links, or POSIX locks.

When a required primitive is unavailable, the affected private operation fails. It does not fall back to a path-based or permissive implementation.

## Data locations

| Data | Default location | Git policy |
| --- | --- | --- |
| Research and performance ledger | `data/private/authority_os.sqlite` | Ignored |
| Private research, strategy, proof, and CSV imports | `data/private/` | Ignored |
| Weekly learning reports | `data/private/weekly-reviews/` | Ignored |
| Human-review packages | `outputs/YYYY-MM-DD/<topic-slug>[-N]/` | Ignored except `outputs/.gitkeep` |
| Synthetic fixtures | `data/samples/` | Tracked and visibly labelled |
| Reconstructed voice assets | `data/voice/` | Tracked and non-citable |

Private directories use mode `0700`; private files use `0600`. Mutating commands normalise owned private paths to those modes. Read-only diagnostics reject unsafe modes without silently repairing them.

## Descriptor-relative path handling

Private operations anchor traversal at a held repository or approved root descriptor. Each path component is opened without following symlinks and revalidated for directory type, identity, ownership, and expected mode. Leaf files must be regular files with bounded size. Intermediate symlinks, leaf symlinks, traversal components, directories in place of files, special files, and path swaps fail closed.

The proof loader applies the same boundary to a manifest and its relative artefact path. It rejects an empty artefact, a self-referential manifest, a path outside the allowed root, and a file that changes during validation. Artefact contents are never read.

## SQLite boundary

`init` is the explicit state-creation and schema-migration operation. It creates missing private parents descriptor-relative and applies atomic schema changes.

`doctor` uses read-only inspection. It does not create a missing database, migrate an old schema, change permissions, print private rows, or inspect environment values. Inspection attests the exact expected tables, columns, indexes, triggers, and schema version. Unknown objects, schema collisions, corruption, foreign-key damage, unsupported versions, and unsafe modes fail without repair.

Read-only inspection checks for SQLite sidecars before and after immutable access. A WAL, journal, or shared-memory file that appears during inspection prevents a clean result rather than being ignored.

## Research provenance isolation

Every stored research row is labelled `private-import`, `synthetic-fixture`, or `legacy-unverified`. Live drafting selects only `private-import` rows. An exact private re-import may promote the same canonical URL/body pair; fixture input cannot demote private evidence, and a one-key collision cannot relabel an unmatched body.

Canonical URL and normalised body hash are independent uniqueness keys. This prevents duplicate storage without treating a shared URL or partial content collision as proof of equivalent provenance.

## Model egress boundary

Live drafting requires both an explicit private strategy file and `--allow-model-egress`. Opportunity drafting also requires a proof manifest. Consent applies only to the selected strategy, selected evidence projection, reconstructed voice instructions, and any bounded public proof claim or attestation.

Before egress:

- source URL queries are removed;
- unrelated ledger rows are excluded;
- local proof paths and artefact contents are excluded;
- private source queries are excluded; and
- the Writer and Critic receive only the data required for their current role.

Writer and Critic processes are tool-free, use no persisted model session, and receive dynamic input on standard input. Errors are reduced to static safe messages; model standard error is not relayed. Fixture mode invokes neither model.

## Package write protocol

Package generation is an explicit `--package` side effect. The runtime:

1. opens the fixed ignored output root without following symlinks;
2. takes a per-date lock;
3. reserves a unique final topic directory without clobbering earlier packages;
4. renders exactly six owner-only files inside a private `.stage-*` directory;
5. publishes completed files with no-clobber hard links; and
6. publishes `manifest.json` last as the commit marker.

A hidden stage directory or a topic directory without `manifest.json` is incomplete internal state and must not be consumed. Existing packages are never overwritten. A suffix preserves each completed run when names collide or concurrent writers reserve the same topic.

Package files exclude raw evidence bodies and claims, source queries, proof paths, artefact contents, credentials, prompts, and model error output. Source metadata is canonical and query-free.

## Performance and learning writes

Performance entry accepts direct values or an exact-schema owner-only CSV under `data/private/`. A batch is validated completely before one transaction; one invalid or duplicate row writes nothing. Exact repeats are idempotent. Replacement is explicit, complete, monotonic in observation time, and isolated by paid/organic channel.

The first performance record anchors the committed `brief.md` and `candidates.md` snapshot with a SHA-256 fingerprint while storing no candidate body in the ledger. Learning context is loaded only for canonical tied leaders after cohort filtering, and only when the current package files match that fingerprint. Missing, changed, legacy-unanchored, or mismatched context becomes an evidence gap.

Weekly reports are deterministic owner-only JSON. Their writer applies the same descriptor boundary, no-clobber behaviour, and restrictive modes. Reports exclude full candidate bodies, source URLs, proof data, private paths, approval changes, and publishing instructions.

## Git-aware privacy gate

Run:

```sh
./bin/linkedin-os privacy-check
```

The gate asks Git for tracked files and prospective non-ignored worktree files using NUL-safe paths. It separately scans exact stage-0 regular blobs from the Git index, so a benign worktree copy cannot hide different staged bytes.

The scan rejects:

- private or generated paths;
- database files and sidecars;
- high-confidence credential and SQLite signatures;
- scheduled workflow triggers; and
- LinkedIn, generic network-client, or browser write surfaces in runtime code.

Ignored `data/private/` and `outputs/` trees are not traversed. Reads are bounded, and a matching sensitive value is never printed. Repository root, directory components, file identity, positional reads, streamed reads, and index identity are compared so same-size changes and path replacement cannot pass as a stable scan. Enumeration or revalidation failure returns a failed check.

## CI boundary

The GitHub Actions workflow runs `make check` on Python 3.11 and the current supported interpreter. Actions are pinned to immutable commits, job time is bounded, repository permission is read-only, and there is no scheduled trigger.

`make check` runs the privacy gate before the warnings-as-errors unit suite. The production-boundary tests also assert the exact CLI command set and the absence of a network, browser, approval, scheduler, messaging, or publishing surface.

## Operational commands

```sh
make setup      # explicit private state creation or migration
make doctor     # read-only schema, permission, asset, and boundary checks
make privacy    # Git-aware public-surface scan
make test       # privacy scan, then warnings-as-errors tests
make check      # aggregate verification target
```

The supported CLI commands are exactly `init`, `doctor`, `privacy-check`, `research`, `draft`, `record-performance`, and `weekly-review`. Publishing remains outside the runtime.
