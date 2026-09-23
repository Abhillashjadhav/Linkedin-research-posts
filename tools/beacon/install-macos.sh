#!/bin/bash
# User-local install; no sudo, model API, cloud account, or automatic publication.
set -euo pipefail
umask 077

if [[ "${1:-}" == "--help" ]]; then
  cat <<'USAGE'
Usage: ./tools/beacon/install-macos.sh
Installs the local Beacon collector for Codex and the shared workflow adapter.
Requires Apple Silicon macOS and an existing writable Homebrew installation.
Existing Managed forwarding is backed up then disconnected. Other external
exporters are preserved and leave the adapter in queue-only mode.
USAGE
  exit 0
fi
[[ $# == 0 ]] || { echo "Unexpected arguments. Use --help." >&2; exit 2; }
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || {
  echo "Run this script in the Apple Silicon Mac's Terminal, not the cloud workspace." >&2
  exit 2
}
[[ "$(id -u)" != 0 ]] || { echo "Run as your normal Mac user, without sudo." >&2; exit 2; }
command -v brew >/dev/null || {
  echo "Homebrew is missing. Install Homebrew from https://brew.sh, then rerun this script." >&2
  exit 2
}

beacon_repo="$(cd "$(dirname "$0")/../.." && pwd -P)"
beacon_helper="$beacon_repo/tools/beacon/verify-local.py"
beacon_package="$beacon_repo/packages/workflow_beacon"
beacon_state="${WORKFLOW_BEACON_STATE_DIR:-$HOME/.local/share/workflow-beacon}"
[[ "$beacon_state" == /* && ! -L "$beacon_state" ]] || {
  echo "WORKFLOW_BEACON_STATE_DIR must be an absolute, non-symlinked directory." >&2; exit 2;
}
[[ -f "$beacon_package/pyproject.toml" ]] || {
  echo "Shared package missing. Run from the complete integration checkout." >&2; exit 2;
}
mkdir -p "$beacon_state"
chmod 700 "$beacon_state"
beacon_lock="$beacon_state/install.lock"
mkdir "$beacon_lock" 2>/dev/null || {
  echo "Another setup may be active; inspect $beacon_lock before retrying." >&2; exit 2;
}
beacon_run="$beacon_state/installations/$(date -u +%Y%m%dT%H%M%SZ)-$$"
mkdir -p "$beacon_run"
beacon_success=0
cleanup() {
  beacon_exit=$?
  if [[ "$beacon_success" != 1 ]]; then
    rm -f "$beacon_state/beacon-local-ready.json"
    echo "Setup incomplete; Beacon delivery remains disabled. Existing workflows can continue." >&2
    echo "Private diagnostics: $beacon_run" >&2
  fi
  rmdir "$beacon_lock" 2>/dev/null || true
  exit "$beacon_exit"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

# No Python API calls or environment dumps; diagnostic files remain owner-only.
beacon_python=""
for beacon_candidate in python3.13 python3.12 python3.11 python3; do
  if command -v "$beacon_candidate" >/dev/null 2>&1 && \
      "$beacon_candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 11))' 2>/dev/null; then
    beacon_python="$(command -v "$beacon_candidate")"
    break
  fi
done
if [[ -z "$beacon_python" ]]; then
  brew install python@3.11
  beacon_python="$(brew --prefix python@3.11)/bin/python3.11"
fi
"$beacon_python" "$beacon_helper" snapshot "$beacon_run/before"
if [[ -f "$beacon_state/beacon-local-ready.json" ]]; then
  cp "$beacon_state/beacon-local-ready.json" "$beacon_run/previous-readiness.json"
fi
rm -f "$beacon_state/beacon-local-ready.json"

# Keep the user workflow adapter separate from the upstream Beacon installation.
beacon_venv="$beacon_state/venv"
[[ ! -L "$beacon_venv" ]] || { echo "Refusing a symlinked adapter venv." >&2; exit 2; }
if [[ ! -x "$beacon_venv/bin/python" ]]; then
  "$beacon_python" -m venv "$beacon_venv"
fi
"$beacon_venv/bin/python" -m pip install --disable-pip-version-check --no-deps "$beacon_package" >"$beacon_run/package-install.log" 2>&1
"$beacon_venv/bin/python" -m workflow_beacon --help >"$beacon_run/adapter-help.txt"
"$beacon_python" "$beacon_helper" launcher --state "$beacon_state" --python "$beacon_venv/bin/python"
beacon_flush_label="com.abhillash.workflow-beacon.flush"
beacon_flush_plist="$HOME/Library/LaunchAgents/$beacon_flush_label.plist"
launchctl bootout "gui/$(id -u)/$beacon_flush_label" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$beacon_flush_plist"

# Never reset an existing custom forwarding configuration to make a check pass.
if ! "$beacon_python" "$beacon_helper" audit; then
  echo "Adapter installed, but existing Beacon configuration needs review; no events sent." >&2
  exit 3
fi

# brew trust is present only in newer Homebrew releases.
if brew help trust >/dev/null 2>&1; then
  brew trust asymptote-labs/tap
fi
brew tap asymptote-labs/tap
if ! brew list --versions asymptote-labs/tap/beacon >/dev/null 2>&1; then
  brew install asymptote-labs/tap/beacon
fi
beacon_binary="$(brew --prefix asymptote-labs/tap/beacon)/bin/beacon"
"$beacon_binary" version >"$beacon_run/beacon-version.txt"
brew info --json=v2 asymptote-labs/tap/beacon >"$beacon_run/homebrew-formula.json"
brew pin asymptote-labs/tap/beacon
"$beacon_binary" endpoint status --json >"$beacon_run/status-before.json" 2>"$beacon_run/status-before-error.txt" || true

# BEACON_MANAGED_INGEST=0 does NOT disconnect an existing managed forwarder.
if [[ "$("$beacon_python" "$beacon_helper" inspect)" == managed ]] || \
    [[ -f "$HOME/.beacon/endpoint/asymptote/enrollment.json" ]] || \
    [[ -f "$HOME/Library/LaunchAgents/com.beacon.endpoint.asymptote-forwarder.plist" ]]; then
  "$beacon_binary" endpoint disconnect --user --json >"$beacon_run/disconnect.json"
fi
"$beacon_python" "$beacon_helper" audit
BEACON_MANAGED_INGEST=0 "$beacon_binary" endpoint install --user --harness codex --dry-run </dev/null >"$beacon_run/install-dry-run.txt" 2>&1

if [[ -f "$HOME/.beacon/endpoint/config.json" ]]; then
  BEACON_MANAGED_INGEST=0 "$beacon_binary" endpoint repair --user --harness codex </dev/null >"$beacon_run/endpoint-install.log" 2>&1
else
  BEACON_MANAGED_INGEST=0 "$beacon_binary" endpoint install --user --harness codex </dev/null >"$beacon_run/endpoint-install.log" 2>&1
fi
"$beacon_binary" endpoint status --json >"$beacon_run/status-after.json"
"$beacon_binary" endpoint doctor --json >"$beacon_run/doctor.json"
"$beacon_binary" mcp doctor >"$beacon_run/mcp-doctor.txt"
"$beacon_python" "$beacon_helper" probe --state "$beacon_state" --diagnostics "$beacon_run" --beacon "$beacon_binary"
"$beacon_python" "$beacon_helper" snapshot "$beacon_run/after"
"$beacon_python" - "$beacon_run" "$beacon_repo" "$beacon_binary" <<'PY'
import hashlib, json, pathlib, subprocess, sys
run, repo, binary = map(pathlib.Path, sys.argv[1:])
commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
manifest = {"repository_commit": commit, "beacon_binary": str(binary),
            "beacon_binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "beacon_version": (run / "beacon-version.txt").read_text().strip(),
            "harnesses": ["codex"], "local_otlp_readback": True,
            "real_codex_session_verified": False, "mac_relogin_verified": False}
(run / "install-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
PY
rm -f "$beacon_state/disabled"
beacon_success=1
echo "Installed: Codex recording, shared workflow adapter, and automatic local queue delivery."
echo "Verified: unique OTLP probe read back from Beacon's local history."
echo "Pending: a fresh real Codex session and a login/restart check."
echo "Private diagnostics: $beacon_run"
echo "Command: $HOME/.local/bin/workflow-beacon"
