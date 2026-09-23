#!/bin/bash
# Disable this integration without deleting Beacon history or workflow outbox.
set -euo pipefail
umask 077
if [[ "${1:-}" == --help ]]; then
  echo "Usage: ./tools/beacon/rollback-macos.sh"
  echo "Disable the adapter and stop its delivery job, retaining all history."
  echo "The Beacon collector stays installed; see docs/BEACON_MAC_SETUP.md for removal."
  exit 0
fi
[[ "$(uname -s)" == Darwin && "$(id -u)" != 0 ]] || {
  echo "Run in the Mac's Terminal as the normal user, without sudo." >&2; exit 2;
}
[[ $# == 0 ]] || exit 2
beacon_state="${WORKFLOW_BEACON_STATE_DIR:-$HOME/.local/share/workflow-beacon}"
[[ "$beacon_state" == /* && ! -L "$beacon_state" ]] || exit 2
mkdir -p "$beacon_state"
touch "$beacon_state/disabled"
chmod 600 "$beacon_state/disabled"
rm -f "$beacon_state/beacon-local-ready.json"
launchctl bootout "gui/$(id -u)/com.abhillash.workflow-beacon.flush" 2>/dev/null || true
beacon_plist="$HOME/Library/LaunchAgents/com.abhillash.workflow-beacon.flush.plist"
if [[ -f "$beacon_plist" ]]; then
  mv "$beacon_plist" "$beacon_state/flush.plist.disabled.$(date -u +%Y%m%dT%H%M%SZ)"
fi
echo "Integration disabled. Beacon logs, approved memory, queued events, reports and backups retained."
