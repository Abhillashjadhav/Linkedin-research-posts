# Automatic local workflow recording

Run LinkedIn OS through `./bin/linkedin-os` as before. The launcher records workflow activity in the background and loads explicitly approved editorial corrections for live drafting. Opening a report is optional. Beacon delivery never decides whether a draft passes or whether the workflow succeeds.

## Installation and entry points

On the Mac, follow [Beacon Mac setup](BEACON_MAC_SETUP.md) and run the prepared installer from this checkout:

```sh
./tools/beacon/install-macos.sh
```

The repository includes the small reusable `workflow_beacon` package under `packages/workflow_beacon`. The launcher imports that checked-in code directly; it does not run pip or download dependencies during execution. The installer provisions the shared local collector and delivery worker separately.

Capture covers every launcher route: discovery, drafting (including campaign mode), frozen-package evaluation, dry-runs, resume, media, monitoring export, performance feedback, corrections, setup, diagnostics and help. Manual and scheduled runs must use the same launcher. Direct `python -m authority_os...` calls bypass this recording wrapper; the shared `python -m workflow_beacon run ... -- COMMAND` wrapper is available for other registered workflows.

`LINKEDIN_OS_RUN_ID` connects the root run, child draft and native decisions. The adapter executes the original Python module or inline composition code in the same process, preserving arguments, standard streams, return codes and signal behavior. Existing runtime overlays remain in their original order.

## What is recorded

- Command start/result and model-stage start/result/error, with timings, model configuration, input/output digests and call IDs.
- Correction IDs, registry version, context digest and count when context is frozen and inserted into a prompt.
- Separate delivery states; a queued event, collector acceptance and actual readback are different facts.

Model prompts, draft prose, evidence bodies and correction text are not included in these adapter events. User-level Beacon capture is a separate integration with its own capture scope; see the Mac setup documentation. Codex model calls retain their empty read-only workspace, ignored user configuration and disabled tools/hooks. The Python orchestrator performs recording; the bounded model subprocess does not call Beacon.

If recording or delivery is unavailable, execution continues. Events that can be stored enter the bounded private outbox for later delivery. Recording failures do not retry research, model calls, publication or any other business action. If local storage itself fails, complete capture cannot be guaranteed; this must not be presented as complete history.

## Accepted corrections

Save the exact correction in a local UTF-8 file, then record the explicit feedback with its source reference. For a correction the owner has already approved:

```sh
./bin/linkedin-os corrections add \
  --text-file /absolute/path/correction.txt \
  --source-ref 'Owner feedback from the source run' \
  --source-kind user \
  --workflow linkedin-os \
  --role writer --role critic \
  --key clear-editorial-rule \
  --approve --reviewed-by Abhillash
```

Machine suggestions remain pending and need explicit review. The add command returns the correction ID; use that returned value here:

```sh
./bin/linkedin-os corrections list
./bin/linkedin-os corrections approve CORRECTION_ID --reviewed-by Abhillash
./bin/linkedin-os corrections revoke CORRECTION_ID --reviewed-by Abhillash
```

Use `list --show-text` only when you want to inspect private rule text. Use `approve NEW_ID --reviewed-by Abhillash --supersedes OLD_ID` for an explicitly reviewed replacement of a conflicting named rule.

Rules and frozen run snapshots stay under ignored `data/private/workflow-beacon`. Only approved rules matching the project, workflow and role enter context. A running workflow keeps one frozen snapshot; approval or revocation affects the next run. Approval refuses a set exceeding 32 approved rules or 16,000 rendered characters across the repository, so approved rules are never silently omitted. Revoke or supersede an existing rule before approving more.

If the current registry is malformed, the store uses its last-known-good copy. Supported mutations update that copy before the current registry, including revocations, so fallback does not restore the preceding approved version. If neither copy is usable, the launcher records unavailable correction context and continues with existing workflow instructions. A busy registry lock never blocks execution; an already frozen snapshot can be read without that lock.

Coverage includes the common Writer, Critic and Writer-revision prompt builders used by single-topic and campaign drafting. Campaign hook, narrative-editor and first-comment prompts do not independently receive correction context; later common Critic calls do. The Critic keeps its existing five-axis score schema. Corrections do not override evidence, scoring, privacy, consent or publication rules, and they can reach the existing model only as part of an already consented invocation.

`corrections.injected` proves which context was supplied, **not that the model followed every rule**. For an objectively checkable correction, add either `--forbid-literal 'exact phrase'` or `--require-literal 'exact phrase'` to the `corrections add` command before approving it. These are exact, case-sensitive substring checks. Rules without a literal check remain explicitly `not_evaluated`; the system does not claim semantic compliance or approve lessons mined from logs.

Exact checks run locally on validated Writer output, Critic input, and revision input/output. Their IDs, candidate-text digest and pass/violation/not-evaluated counts are recorded separately from the five-axis scores. The private check record retains recent results without candidate prose. If the **selected quality-passing draft** violates a reviewed Writer rule, the single-topic and campaign coordinators use a remaining existing cycle to repair it, even when its scores already pass. A discarded candidate's violation does not trigger that repair. No extra cycles, score axes, acceptance thresholds or publishing permissions are added.

If the existing cycle budget is exhausted, unresolved checks remain visible and the normal quality result is preserved. If later repair attempts lose quality, the coordinator retains the earlier quality-passing draft and reports the unresolved correction. Required wording cannot override the evidence or safety requirements. There is no automatic semantic compliance grader or new per-rule blocking gate.

To inspect the separate check record when needed:

```sh
./bin/linkedin-os corrections checks --run-id RUN_ID
```

## Optional inspection

LinkedIn OS keeps its native private JSON/HTML reports and prints the report location for supported drafting/discovery runs. They no longer open a browser automatically. To request that behavior on macOS:

```sh
LINKEDIN_OS_OPEN_REPORT=1 ./bin/linkedin-os draft [your existing arguments]
```

From a source checkout, inspect the separate delivery queue without running the workflow again:

```sh
PYTHONPATH=packages/workflow_beacon/src python3 -m workflow_beacon status
PYTHONPATH=packages/workflow_beacon/src python3 -m workflow_beacon status --run-id RUN_ID
```

After installation, the shared interpreter is available at `~/.local/share/workflow-beacon/venv/bin/python`; use it if `python3` is older than the required Python 3.11.

The existing PM Evals exporter remains independent. Beacon recording does not expand its redacted payload, grant export consent, change quality gates or enable publishing.

## Verified and still pending

Implementation validation passed 23 focused tests covering launcher overlay order, model isolation, argument/exit preservation, recorder failure and optional browser opening. An actual offline `draft --dry-run` completed successfully and queued four lifecycle events under one run ID. This verifies the adapter and local outbox, not Beacon retention or a live model's correction compliance.

Correction validation passed 11 store checks, six integration checks, and eight existing Codex-runtime checks without model calls. The coordinator fixture covers a 25/25 draft with a literal violation taking a second compliant attempt, a compliant selected draft ignoring a violating discarded candidate, and unresolved checks stopping at the unchanged cycle budget. These fixtures verify deterministic routing and context delivery, not a real model's ability to follow subjective corrections.

Mac service installation and real collector readback require the installer on the target Mac. Compare that checkout's current changes before installing; do not overwrite unrelated work. Neither publishing nor a live model call is needed for the installation probe.
