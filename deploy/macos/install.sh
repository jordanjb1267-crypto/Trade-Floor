#!/bin/bash
# §18 supervisor install for macOS (Sequoia 15.x). LaunchAgent, not
# LaunchDaemon: it runs in the owner's login session, where the untracked
# .env and any keychain material live. Run from the repository root:
#
#   bash deploy/macos/install.sh
#
set -euo pipefail

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.tradefloor.supervisor"
PLIST_SRC="$REPO/deploy/macos/$LABEL.plist"
PLIST_DST="$HOME/Library/LaunchAgents/$LABEL.plist"

if [[ "$(uname)" != "Darwin" ]]; then
  echo "This installer is for macOS (§18: launchd). Detected: $(uname)" >&2
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$REPO/logs"

# Refuse to install without credentials in place: a supervisor that starts
# and immediately fails preflight every 60 seconds is noise, not operation.
if [[ ! -f "$REPO/.env" ]]; then
  echo "No .env at $REPO/.env — copy .env.example and fill in the practice" >&2
  echo "and Telegram values first (§17). Nothing installed." >&2
  exit 2
fi

sed "s|__REPO_PATH__|$REPO|g" "$PLIST_SRC" > "$PLIST_DST"

# Sequoia: modern bootstrap/bootout, not the deprecated load/unload.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"
launchctl enable "gui/$(id -u)/$LABEL"

echo "Installed and started: $LABEL"
echo "  logs:    $REPO/logs/supervisor.{out,err}.log"
echo "  status:  launchctl print gui/$(id -u)/$LABEL | head -20"
echo "  stop:    launchctl bootout gui/$(id -u)/$LABEL"
echo
echo "First run performs §18 startup reconciliation and sends the §19"
echo "session-start health report to Telegram at the next session boundary."
