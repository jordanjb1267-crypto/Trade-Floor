#!/usr/bin/env python3
"""§18 supervisor status: healthy, stale, stopped, or crash-looping.

`launchctl print` alone cannot answer the question the owner actually has.
It reports whether launchd is holding a job, not whether the supervisor's loop
is turning — a hung process and a working one look identical to it, and a
process that respawns every throttle interval reads as "running" at whichever
instant you happen to look. This combines three sources:

  * the launchd job state (loaded, running, run count, last exit code),
  * the heartbeat the supervisor writes each sleep slice,
  * the count of startup events inside the crash-loop window,

and resolves them with `runner.liveness.diagnose()`, which is a pure function
so every transition is unit-tested without launchd, a clock, or a process.

Exit codes are distinct so a script can branch on them:

    0  healthy        3  stale/hung
    2  usage error    4  stopped            5  crash-looping

Reads only. Nothing here can start, stop, or reconfigure anything — diagnosing
a trading system must never be able to change it.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_firm.runner import liveness  # noqa: E402

LABEL = "com.tradefloor.supervisor"
LOG_DIR = REPO / "logs"
REPORT_DIR = REPO / "reports" / "ops"
DB_PATH = REPO / "database" / "firm.sqlite"
OPS_STATE = REPO / "state" / "ops"
# Readiness reads the CANONICAL marker — refreshed by every successful owner
# notification — not the startup-dedup marker. Reading the startup marker was
# the defect: it is never refreshed after startup, so a healthy supervisor
# delivering session messages still reported `unconfirmed` once its startup
# confirmation aged past the TTL.
CONFIRMATION_MARKER = OPS_STATE / "notifier-last-delivery.json"
ATTEMPT_LEDGER = OPS_STATE / "supervisor-startup-attempts.json"
ASSUMPTION_MARKER = OPS_STATE / "supervisor-startup-legacy-assumption.json"

EXIT_BY_STATE = {
    liveness.SupervisorState.HEALTHY: 0,
    liveness.SupervisorState.STALE: 3,
    liveness.SupervisorState.STOPPED: 4,
    liveness.SupervisorState.CRASH_LOOPING: 5,
}

_INT_FIELD = {
    "pid": re.compile(r"^\s*pid\s*=\s*(\d+)\s*$", re.MULTILINE),
    "runs": re.compile(r"^\s*runs\s*=\s*(\d+)\s*$", re.MULTILINE),
}
_LAST_EXIT = re.compile(r"^\s*last exit code\s*=\s*(\d+)\s*$", re.MULTILINE)
_STATE = re.compile(r"^\s*state\s*=\s*(\S+)", re.MULTILINE)


def parse_launchctl(text: str, *, found: bool) -> liveness.LaunchdStatus:
    """Turn `launchctl print` output into a LaunchdStatus.

    Split out and pure so the parser is testable against captured fixtures —
    the shape of this output is an OS detail that changes between releases, and
    discovering that in production is how a status tool starts lying.
    """
    if not found:
        return liveness.LaunchdStatus(loaded=False)
    state = _STATE.search(text)
    running = bool(state and state.group(1).startswith("running"))
    values: dict[str, int | None] = {}
    for name, pattern in _INT_FIELD.items():
        match = pattern.search(text)
        values[name] = int(match.group(1)) if match else None
    exit_match = _LAST_EXIT.search(text)
    return liveness.LaunchdStatus(
        loaded=True,
        running=running,
        pid=values["pid"],
        runs=values["runs"],
        # Absent means launchd printed "(never exited)" — the healthy case for
        # a long-runner, and NOT the same as exit code 0.
        last_exit_code=int(exit_match.group(1)) if exit_match else None,
    )


def _operational_epoch() -> dt.date | None:
    """Database-initialization date; None when genuinely uninitialized."""
    if not DB_PATH.is_file():
        return None
    try:
        conn = sqlite3.connect(f"file:{DB_PATH}?immutable=1", uri=True)
        try:
            row = conn.execute("SELECT MIN(applied_at) FROM schema_migrations").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None
    if not row or not row[0]:
        return None
    try:
        return dt.datetime.fromisoformat(str(row[0]).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _attestation_backlog_count(now: dt.datetime) -> int | None:
    """Unresolved expected sessions since the epoch. None = uninitialized."""
    epoch = _operational_epoch()
    if epoch is None:
        return None
    from zoneinfo import ZoneInfo

    today = now.astimezone(ZoneInfo("Europe/London")).date()
    missing = 0
    day = epoch + dt.timedelta(days=1)
    while day < today:
        if day.weekday() < 5 and not (REPORT_DIR / f"{day}-session.json").exists():
            missing += 1
        day += dt.timedelta(days=1)
    return missing


def read_launchd(label: str) -> liveness.LaunchdStatus:
    try:
        completed = subprocess.run(
            ["launchctl", "print", f"gui/{os.getuid()}/{label}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return liveness.LaunchdStatus(loaded=False)
    return parse_launchctl(completed.stdout, found=completed.returncode == 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument(
        "--expect-interpreter",
        metavar="PATH",
        help="fail unless the live heartbeat was written by this interpreter",
    )
    parser.add_argument(
        "--max-beat-age",
        type=float,
        default=liveness.DEFAULT_MAX_BEAT_AGE_SECONDS,
        metavar="SECONDS",
        help="heartbeat older than this counts as stale",
    )
    parser.add_argument(
        "--require-notify-confirmed",
        action="store_true",
        help=(
            "also fail unless the §19 notification path has a CONFIRMED delivery. "
            "A legacy assumed confirmation does NOT satisfy this. Required by any "
            "live-readiness procedure (governance/strategy-promotion-policy.md)."
        ),
    )
    parser.add_argument("--label", default=LABEL)
    args = parser.parse_args(argv)

    now = dt.datetime.now(dt.UTC)
    launchd = read_launchd(args.label)
    heartbeat = liveness.read_heartbeat(LOG_DIR)
    diagnosis = liveness.diagnose(
        launchd=launchd,
        heartbeat=heartbeat,
        recent_starts=liveness.recent_start_count(LOG_DIR, now=now),
        now=now,
        max_beat_age_seconds=args.max_beat_age,
        heartbeat_pid_alive=(
            liveness.pid_alive(heartbeat.pid) if heartbeat is not None else None
        ),
    )

    # Reported on its own axis: a healthy process whose notification path is
    # dead is a real condition, and collapsing it into the supervisor state
    # would hide a silent alerting failure behind a green process.
    notify_state = liveness.notify_surface_state(
        delivered_at=liveness.read_delivery_marker(CONFIRMATION_MARKER),
        assumed_at=liveness.read_assumed_confirmation(ASSUMPTION_MARKER),
        ledger=liveness.read_attempt_ledger(ATTEMPT_LEDGER),
        now=now,
    )

    # §31.7 historical continuity: while any expected session since the
    # operational epoch lacks its terminal artifact, the deployment must not
    # read as fully reconciled. Read-only: epoch from the database baseline,
    # backlog from report-file existence and weekday arithmetic.
    backlog_count = _attestation_backlog_count(now)

    interpreter_ok = True
    interpreter_note = ""
    if args.expect_interpreter:
        actual = heartbeat.interpreter if heartbeat else None
        interpreter_ok = actual == args.expect_interpreter
        if not interpreter_ok:
            interpreter_note = (
                f"interpreter mismatch: heartbeat was written by "
                f"{actual or '(no heartbeat)'}, expected {args.expect_interpreter}"
            )

    if args.json:
        print(
            json.dumps(
                {
                    "state": str(diagnosis.state),
                    "reason": diagnosis.reason,
                    "beat_age_seconds": diagnosis.beat_age_seconds,
                    "recent_starts": diagnosis.recent_starts,
                    "launchd_loaded": launchd.loaded,
                    "launchd_running": launchd.running,
                    "launchd_runs": launchd.runs,
                    "interpreter": heartbeat.interpreter if heartbeat else None,
                    "python_version": heartbeat.python_version if heartbeat else None,
                    "interpreter_ok": interpreter_ok,
                    "notify_state": str(notify_state),
                    "attestation_backlog": backlog_count,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"{str(diagnosis.state).upper():<14} {diagnosis.reason}")
        if heartbeat is not None:
            print(f"  interpreter  {heartbeat.interpreter}")
            print(f"  python       {heartbeat.python_version}")
            print(f"  beats        {heartbeat.beats} since {heartbeat.started_at.isoformat()}")
        if launchd.loaded:
            print(f"  launchd      runs={launchd.runs} running={launchd.running}")
        print(f"  notify       {notify_state}")
        if backlog_count is None:
            print("  continuity   (uninitialized — no operational epoch)")
        elif backlog_count == 0:
            print("  continuity   reconciled — every expected session attested")
        else:
            print(
                f"  continuity   INCOMPLETE — {backlog_count} expected session(s) "
                f"since the epoch lack a terminal report"
            )
        if interpreter_note:
            print(f"  WARNING      {interpreter_note}")

    if not interpreter_ok:
        return 3
    if args.require_notify_confirmed and notify_state is not liveness.NotifyState.CONFIRMED:
        return 6
    return EXIT_BY_STATE[diagnosis.state]


if __name__ == "__main__":
    sys.exit(main())
