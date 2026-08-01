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

# Same reasoning for the interpreter. The plist pins $REPO/.venv/bin/python
# rather than resolving `python3` on launchd's PATH, so a missing venv — or one
# without the project installed — is a 60-second crash loop that looks like a
# successful install. Refuse both here, where the message is actually read.
if [[ ! -x "$REPO/.venv/bin/python" ]]; then
  echo "No virtualenv at $REPO/.venv (§23 requires Python >=3.11). Create it:" >&2
  echo "    python3 -m venv .venv && .venv/bin/pip install -e \".[dev]\"" >&2
  echo "Nothing installed." >&2
  exit 3
fi

if ! "$REPO/.venv/bin/python" -c "import trading_firm, yaml" 2>/dev/null; then
  echo "$REPO/.venv exists but the project is not installed into it:" >&2
  echo "    .venv/bin/pip install -e \".[dev]\"" >&2
  echo "Nothing installed." >&2
  exit 4
fi

# Interpreter floor and TLS trust, checked with the interpreter that will
# actually run — not the one in the installing shell's PATH. A framework Python
# with no root bundle fails every HTTPS call with an error that reads like a bad
# credential; catching it here keeps that misdiagnosis out of the operator's
# hands. check_runtime.py prints the certificate repair and never performs it.
if ! "$REPO/.venv/bin/python" "$REPO/scripts/check_runtime.py"; then
  echo "Runtime checks failed. Nothing installed." >&2
  exit 5
fi

sed "s|__REPO_PATH__|$REPO|g" "$PLIST_SRC" > "$PLIST_DST"

# Sequoia: modern bootstrap/bootout, not the deprecated load/unload.
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true

# `bootout` is ASYNCHRONOUS: it returns before launchd has finished tearing the
# old job down, and bootstrapping into a domain that still holds it fails with
# "Input/output error" (EIO, 5). That makes reinstall intermittently fail — it
# succeeds when the previous job happened to be gone already and fails when it
# did not. Wait for the teardown instead of racing it.
for _ in $(seq 1 40); do
  launchctl print "gui/$(id -u)/$LABEL" >/dev/null 2>&1 || break
  sleep 0.25
done

if ! launchctl bootstrap "gui/$(id -u)" "$PLIST_DST"; then
  echo >&2
  echo "INSTALLATION FAILED: launchctl bootstrap was rejected." >&2
  echo "  EIO/5 usually means the previous job is still loaded — check:" >&2
  echo "      launchctl print gui/$(id -u)/$LABEL" >&2
  echo "  A malformed plist is the other cause — check:" >&2
  echo "      plutil -lint $PLIST_DST" >&2
  exit 7
fi
launchctl enable "gui/$(id -u)/$LABEL"

# ---------------------------------------------------------------- verification
#
# `launchctl bootstrap` returning 0 means launchd ACCEPTED the job, not that the
# process survived. The previous version of this script printed "Installed and
# started" while the supervisor was dying on import every 60 seconds. Poll until
# the process proves it reached its own entry point, then assert three things:
# it is still running, the heartbeat came from the pinned venv interpreter, and
# that heartbeat is fresh. Anything else is an installation FAILURE.
STATUS="$REPO/scripts/supervisor_status.py"
EXPECTED_PYTHON="$REPO/.venv/bin/python"
DEADLINE=$((SECONDS + 30))
VERIFIED=0

echo "Verifying the supervisor actually started..."
while (( SECONDS < DEADLINE )); do
  if "$REPO/.venv/bin/python" "$STATUS" \
       --expect-interpreter "$EXPECTED_PYTHON" \
       --max-beat-age 60 >/dev/null 2>&1; then
    VERIFIED=1
    break
  fi
  sleep 2
done

if (( VERIFIED == 0 )); then
  echo >&2
  echo "INSTALLATION FAILED: the agent was loaded but did not reach a healthy" >&2
  echo "running state within 30s. Diagnosis:" >&2
  echo >&2
  "$REPO/.venv/bin/python" "$STATUS" --expect-interpreter "$EXPECTED_PYTHON" >&2 || true
  echo >&2
  echo "Recent stderr:" >&2
  tail -20 "$REPO/logs/supervisor.err.log" >&2 2>/dev/null || true
  echo >&2
  echo "Unloading so it does not crash-loop in the background." >&2
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  exit 6
fi

# Notifier health is an INDEPENDENT axis from process health, so a dead
# notification path does not fail the install — the supervisor is genuinely
# running and uninstalling it would be the wrong remedy. But it is never
# allowed to pass silently: a §19 alert nobody receives is the failure mode
# that makes every other guarantee here worthless.
NOTIFY_STATE="$("$REPO/.venv/bin/python" "$STATUS" --json 2>/dev/null \
  | sed -n 's/.*"notify_state": "\([^"]*\)".*/\1/p')"

if [[ "$NOTIFY_STATE" != "confirmed" ]]; then
  echo >&2
  echo "  ****************************************************************" >&2
  echo "  *  WARNING: the supervisor is running, but the §19 notification" >&2
  echo "  *  path is NOT confirmed. State: ${NOTIFY_STATE:-unknown}" >&2
  echo "  *" >&2
  echo "  *  Alerts may not reach you. The install SUCCEEDED — process and" >&2
  echo "  *  notifier health are independent axes — but a risk-halt alert" >&2
  echo "  *  nobody receives is worse than no alert at all." >&2
  echo "  *" >&2
  echo "  *  Diagnose:  .venv/bin/python scripts/supervisor_status.py" >&2
  echo "  *             .venv/bin/python scripts/verify_telegram.py" >&2
  echo "  *  Outcomes:  $REPO/logs/supervisor-events.jsonl" >&2
  echo "  *" >&2
  echo "  *  NO live-readiness step may pass in this state: it requires" >&2
  echo "  *  supervisor_status.py --require-notify-confirmed to exit 0," >&2
  echo "  *  and 'legacy_assumed_confirmation' does not satisfy it." >&2
  echo "  ****************************************************************" >&2
  echo >&2
fi

echo "Installed, started, and VERIFIED running: $LABEL"
echo "  logs:      $REPO/logs/supervisor.{out,err}.log"
echo "  events:    $REPO/logs/supervisor-events.jsonl"
echo "  heartbeat: $REPO/logs/supervisor-heartbeat.json"
echo "  status:    .venv/bin/python scripts/supervisor_status.py"
echo "  notify:    ${NOTIFY_STATE:-unknown}"
echo "  stop:      launchctl bootout gui/$(id -u)/$LABEL"
echo
echo "The status command distinguishes healthy / stale / stopped / crash-looping"
echo "and exits 0 only when healthy, so it is usable in a monitoring check."
echo
echo "First run performs §18 startup reconciliation and sends the §19"
echo "session-start health report to Telegram at the next session boundary."
