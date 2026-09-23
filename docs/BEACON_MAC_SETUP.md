# Local Beacon on the M4 Mac

Status: implementation prepared and checked in the cloud. **Not installed or tested
on the Mac yet.** The Mac's Terminal must run the installer. No paid model API,
Beacon account, root access, or per-run dashboard login is used by this setup.

## One-time handoff

In the existing LinkedIn OS checkout, fetch and check out the integration branch.
Preserve local work first; do not force a checkout
or reset the repository. Then run:

```bash
(
set -e
git fetch origin codex/beacon-local-workflows
git switch codex/beacon-local-workflows
git merge --ff-only origin/codex/beacon-local-workflows
./tools/beacon/install-macos.sh
)
```

If the branch exists only remotely, use
`git switch --track origin/codex/beacon-local-workflows` instead. Run these commands
from the actual LinkedIn OS repository, not the cloud scratch directory.

The script requires an existing Homebrew installation. If it is missing, it stops
with the official Homebrew link. It installs Python 3.11 through Homebrew only when
no compatible Python is found. It never invokes `sudo`. Installing free packages
can require network access; normal recording and queued delivery remain local.

The installer:

1. Creates a private, timestamped backup of the affected Codex, Beacon and launchd
   configuration; retains existing runtime logs and approved memory in place.
2. Installs the reusable Python adapter in
   `~/.local/share/workflow-beacon/venv`, with a command at
   `~/.local/bin/workflow-beacon` and a launchd delivery worker that retries queued
   events automatically when the collector recovers.
3. Installs Beacon from the official Homebrew tap and pins the installed version.
   It records the exact version, binary SHA-256 and formula information.
4. Backs up and explicitly disconnects existing Beacon Managed forwarding.
   It configures only **Codex**, using user-mode paths and loopback listeners.
5. Runs Beacon's status, endpoint doctor and MCP doctor. It uses the real shared
   adapter's OTLP serializer to send one synthetic event to the live collector,
   then verifies its exact event marker, `workflow_bridge` harness, session ID,
   trace ID and repository context in Beacon's runtime history. It never writes
   a fake event directly into that history.
6. Writes a local-delivery receipt bound to the checksums of both Beacon config
   files. The adapter stays queue-only without a valid receipt. Existing workflow
   success/failure behavior does not depend on the installer or collector.

Private diagnostics are under
`~/.local/share/workflow-beacon/installations/<timestamp>/`. Do not commit or paste
the whole folder: targeted backups can include old forwarding credentials.
The final output states whether setup completed and which checks remain pending.

An existing non-Managed external exporter, custom HTTP port, unfamiliar collector
configuration, or conflicting command is preserved and reported. Setup leaves the
adapter in queue-only mode and exits nonzero rather than claiming local-only
delivery. Do not delete an existing service to resolve this automatically.

## What still needs a real Mac check

The synthetic probe proves the **adapter serialization, collector ingestion and
project-scoped readback path**. It does not prove real Codex hooks, full session
coverage, correction reuse, or startup
after login. Complete these checks after installation:

1. Start a fresh Codex session in this repository and ask it to print a unique,
   harmless marker such as `LINKEDIN_BEACON_SMOKE_20260923`.
2. Run `beacon endpoint doctor --json` and inspect that session with `beacon traces`
   or `beacon endpoint dashboard`. Confirm the marker and repository are recorded.
3. Run the repository's normal offline dry run. Verify its existing result remains
   unchanged, its adapter report exists, and queued telemetry drains to Beacon.
4. Repeat a brief check after the next normal logout/login or restart. Do not
   interrupt other work merely to restart the machine.

`harness_observed` may warn before the first real agent session. A passing synthetic
probe is not evidence that this warning has been resolved. Local launchd services
do not keep a sleeping or powered-off Mac running.

## Other repositories and execution environments

The collector and delivery worker are shared. Each repository must still route
its **real entry points** through the adapter. Installing the central venv does
not add the package to other Python interpreters.

For PEOS, AI ContextPort and Dream Job adapters, check out each integration branch,
activate its actual execution venv, and run that repository's
`scripts/install_beacon_adapter.py` using the same interpreter used by its workflow.
Follow that repository's pinned adapter lock and instructions. Do not install into
global Python automatically. LinkedIn OS bundles the package source for its native
launcher, so its normal command does not depend on activating the central venv.

Manual commands, scheduled jobs and alternative launchers must all use the same
instrumented entry point. A cloud execution environment cannot reach the Mac's
`127.0.0.1`; it requires its own local collector or queues events for a separate,
explicit transfer. This installer does not create a remote tunnel.

## Receipt renewal, updates and rollback

Any change to either collector configuration file invalidates the readiness
receipt and the adapter queues locally. Rerun the installer after a configuration
change to inspect the settings and repeat the real OTLP probe; no dashboard login
or scheduled manual renewal is needed.

Beacon is pinned to prevent a routine Homebrew upgrade changing the pilot. Review
the new release before deliberately updating:

```bash
brew unpin asymptote-labs/tap/beacon
brew update
brew upgrade asymptote-labs/tap/beacon
./tools/beacon/install-macos.sh
```

Homebrew does not provide Beacon's signed-package automatic health rollback. Keep
the recorded known-good version and private configuration backups. For a binary
downgrade, use the official versioned arm64 archive and verify its published
checksum; retain its matching CLI, hooks and collector binaries together.

To disable this integration without removing history:

```bash
./tools/beacon/rollback-macos.sh
```

This creates the shared adapter's `disabled` marker, revokes readiness and unloads
its delivery job. Existing workflows bypass adapter recording and delivery. It
retains outbox, reports, approved memory, Beacon logs, backup files and the upstream
collector. Rerunning a successful install re-enables the adapter.

If the collector was created solely for this pilot and should also be removed,
inspect the initial `before/snapshot.json` first, then use the documented
`beacon endpoint uninstall --user --keep-logs`. Do not replace whole Codex files
with old backups if they have since changed; merge only the affected configuration.
Never automatically restore old Managed forwarding credentials as part of rollback.

Default Beacon runtime retention is one active 10 MiB log and five rotated
archives. This is not indefinite archival. Approved correction files and adapter
outbox retention are separate from Beacon's runtime log rotation.

## Upstream evidence checked for this implementation

- [v1.3.22 release](https://github.com/Asymptote-Labs/agent-beacon/releases/tag/v1.3.22)
- [macOS service installation](https://github.com/Asymptote-Labs/agent-beacon/blob/main/docs/platforms/macos.mdx)
- [Endpoint install and exact harness selection](https://github.com/Asymptote-Labs/agent-beacon/blob/main/docs/cli/endpoint-install.mdx)
- [Managed forwarding and disconnect](https://github.com/Asymptote-Labs/agent-beacon/blob/main/docs/cli/endpoint-connect.mdx)
- [Upgrade paths](https://github.com/Asymptote-Labs/agent-beacon/blob/main/docs/cli/upgrade.mdx)
- [Loopback collector and exporter source](https://github.com/Asymptote-Labs/agent-beacon/blob/main/cli/beacon/internal/endpoint/collector/collector.go)
- [Runtime retention](https://github.com/Asymptote-Labs/agent-beacon/blob/main/docs/cli/endpoint-paths.mdx)

The code was checked with shell syntax validation and Python compilation in Linux.
Homebrew, launchd, the Mac service and real Codex integration remain untested until
the Terminal handoff runs successfully.
