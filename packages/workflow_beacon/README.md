# Workflow Beacon bridge

Python 3.11+, no runtime dependencies. Record metadata from an existing launcher
without changing its model permissions, quality gates, stdout, stderr or result.
Beacon itself is installed separately. There is no TypeSafe or paid API dependency.

```sh
python3 -m pip install ./packages/workflow_beacon
workflow-beacon run --workflow linkedin-os --project-root /path/to/repository -- existing-command
```

Repositories can pin this package by Git commit and `#subdirectory=packages/workflow_beacon`.
Do not pin a moving branch for rollout. The monorepo may import the checked-in
`packages/workflow_beacon/src` directly, without installing during normal runs.

```python
from workflow_beacon import capture, current_run

with capture("linkedin-os", project_root=repo, run_id=existing_run_id) as run:
    result = existing_main(argv)
    run.set_result(result)  # Optional integer CLI return; bool is ignored.
    # Return result unchanged. Context also records raised errors and SystemExit.

run = current_run()  # None outside a capture context.
if run is not None:
    run.event("model.completed", stage="writer", status="completed",
              metadata={"call_id": call_id, "duration_ms": elapsed_ms})
```

For a single externally supplied hook, `Run(workflow, project_root, run_id).event(...)`
records only that event. Do not use a context for an event that does not represent
a complete workflow. Nested subprocesses inherit the root run ID and record their
own instance and parent-instance IDs. They do not invent independent root runs.

## Storage and delivery

State defaults to `~/.local/share/workflow-beacon`, overridden by
`WORKFLOW_BEACON_STATE_DIR`. Directory permission is 0700, database/lock 0600.
The local SQLite ledger is the bridge's report and retry source. It retains at
most seven days, with a 100 MiB database limit and a lower payload budget allowing
for database overhead. Individual events are at most 16 KiB. Oldest events are
evicted when needed, with an eviction counter. Corrections are separate and never
pruned to make room for telemetry. Transient SQLite journal files can add disk
usage during transactions. Unwritable storage means recording is incomplete;
the workflow still runs, and durability is not claimed.

Each event has a stable event ID, root run ID, process-instance ID and sequence.
Retries preserve those values. A detached worker handles networking; the workflow
never waits for network export. Database lock waits are bounded to 50 ms.
Only metadata identifiers, counts, flags, hashes and fixed action labels are
accepted. Unknown metadata keys and prose are dropped. Do not place secrets in
identifier fields. Prompts, drafts, tool arguments, command lines and environment
variables are never serialized by the recorder.

The OTLP endpoint defaults to `http://127.0.0.1:4318/v1/logs`. Only numeric loopback
HTTP addresses are allowed. The client ignores HTTP proxy environment variables
and never follows redirects. Each standalone worker request has a 500 ms total
deadline. A worker mutex prevents concurrent sends without holding a database
transaction over a network call. Retries back off approximately 1, 5, 30, 120 and
300 seconds. Normal runs launch a short-lived worker; the Mac setup additionally
schedules `workflow-beacon flush --quiet` for recovery between workflow runs.

### Local-only verification

Loopback alone does not prove local-only storage: a collector can forward onward.
Until installation creates `beacon-local-ready.json`, events stay queued. This
receipt requires schema version 1, `local_only: true`, the exact `endpoint`, a
nonfuture UTC `verified_at`, and absolute paths plus SHA-256 fingerprints for
both `config_path` (Beacon config.json) and `collector_config_path` (otelcol.yaml).
Keys are `config_sha256` and `collector_config_sha256`. Each delivery rechecks both
files; enabled managed ingestion or any configured external destination rejects
delivery. A changed configuration requires fresh verification.

`WORKFLOW_BEACON_ALLOW_UNVERIFIED_LOCAL=1` bypasses the receipt for a simulated
local collector or installation probe only. It still cannot target a remote
endpoint. Never persist this override in a workflow or service configuration.

### Honest delivery states

* `pending`: awaiting a retry or no local-only receipt.
* `accepted`: OTLP receiver accepted the event; this is **not** proof of durable
  ingestion or appearance in Beacon.
* `rejected`: nonretryable response or partial rejection; retained for diagnosis.
* `observed`: a matching marker was read from actual Beacon JSONL.

```sh
workflow-beacon status --run-id RUN_ID
workflow-beacon flush
workflow-beacon readback --log-path ~/.beacon/endpoint/logs/runtime.jsonl
```

Partial OTLP success is parsed, not treated as universal delivery. Retrying after
an ambiguous timeout can create Beacon duplicates; native deduplication is
limited. The bridge ledger/report deduplicates by its own stable ID. No exactly-once
claim is made. Readback scans at most the newest 64 MiB of the named runtime file.
It does not silently scan other users' data or rotated files.

## Disable and rollback

`WORKFLOW_BEACON_DISABLED=1` or a `disabled` file in the state directory stops new
recording and delivery. Remove the readiness receipt to keep recording but pause
delivery. Neither action removes logs or project corrections. The existing
workflow remains runnable, and task errors are not swallowed.

## Native Beacon boundary

The bridge uses native OTLP logs, explicit action/category attributes and a
`workflow_bridge` harness. It does not enable hooks/plugins/MCP inside an isolated
model call. It does not directly modify Beacon JSONL or memory.db. Reviewed
repository corrections are authoritative; Beacon memory indexing is optional.
Native MCP is read-only and its small context response is not a mandatory-rule
registry. The report is always optional, with no automatic browser opening.
