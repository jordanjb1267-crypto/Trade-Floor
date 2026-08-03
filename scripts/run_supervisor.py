#!/usr/bin/env python3
"""§18 supervisor entry point — what the launchd agent keeps alive.

Composition only: every piece of behaviour lives in tested modules, and this
file wires the real dependencies into `runner.supervisor.Supervisor`. The
probe is READ-ONLY — it asks the practice broker for open positions and
nothing else, and this process's import graph cannot reach an order-placing
path (asserted by tests/acceptance/test_supervisor_no_order_path.py).

Run by deploy/macos/install.sh under launchd; runnable by hand for a
smoke check:

    python3 scripts/run_supervisor.py --once   # handle the next event, exit
    python3 scripts/run_supervisor.py          # run until SIGTERM

Observability (§18). The startup event is written BEFORE anything that can
fail — before the `.env` load, before config validation — because the failure
this closes was a process that died during import and left nothing behind but
a traceback repeated every throttle interval. A record that only exists once
initialisation succeeds cannot describe a start that never got that far.
"""

import datetime as dt
import os
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_firm.config import BASE_CONFIG_PATH, load_config  # noqa: E402
from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.notify.surface import (  # noqa: E402
    NotificationKind,
    notify_owner,
    redact,
)
from trading_firm.runner import liveness  # noqa: E402
from trading_firm.runner.schedule import next_event  # noqa: E402
from trading_firm.runner.supervisor import HealthReport, Supervisor  # noqa: E402
from trading_firm.sessions import SessionClock  # noqa: E402

LOG_DIR = REPO / "logs"
OPS_STATE = REPO / "state" / "ops"

# Two records, two questions (see runner/liveness.py). The delivery marker is
# written ONLY after Telegram confirms the message and governs dedup; the
# attempt ledger is written on every attempt and governs the retry interval and
# the bound. Both are on disk rather than in memory precisely because the thing
# being limited is process startup — an in-memory limiter resets on exactly the
# event it is meant to suppress.
DELIVERY_MARKER = OPS_STATE / "supervisor-startup-delivered.json"
ATTEMPT_LEDGER = OPS_STATE / "supervisor-startup-attempts.json"
# Canonical notifier-readiness evidence: when did ANY approved owner
# notification last succeed? Refreshed by every successful delivery through
# `deliver()` — startup health, session-start health, the daily report, and
# anything else routed through that one function.
#
# Deliberately SEPARATE from DELIVERY_MARKER, which answers a different
# question ("have we announced THIS startup?") and governs dedup. Folding the
# two together looked simpler and was wrong: a session message delivered
# shortly before a restart would dedup the startup announcement away, and the
# owner would never learn the supervisor had restarted. Two questions, two
# records — the same discipline the startup marker and attempt ledger already
# follow.
CONFIRMATION_MARKER = OPS_STATE / "notifier-last-delivery.json"
# The previous attempt-stamped marker. Migrated ONCE into an explicit, finite
# assumption — never read as a delivery, never written again.
LEGACY_MARKER = OPS_STATE / "supervisor-startup-notify.json"
ASSUMPTION_MARKER = OPS_STATE / "supervisor-startup-legacy-assumption.json"


def probe() -> HealthReport:
    """Read-only practice-account check: reachable, and flat?

    Imported lazily so the supervisor module itself never links the execution
    package — the no-order-path acceptance test checks the module graph, and
    this composition file is where the read-only exception is made and seen.
    """
    from trading_firm.execution.oanda_transport import OandaPracticeTransport

    transport = OandaPracticeTransport()
    positions = transport._request("GET", f"/v3/accounts/{transport._account_id}/openPositions")
    open_positions = positions.get("positions", [])
    return HealthReport(
        broker_reachable=True,
        account_flat=not open_positions,
        open_position_count=len(open_positions),
        detail="practice host",
    )


def deliver(kind: NotificationKind, body: str, now: dt.datetime | None = None):
    """THE single owner-notification delivery path for this process.

    Every approved §19 notification goes through here, and a delivery the API
    confirms — and only such a delivery — refreshes the canonical readiness
    evidence. One function rather than a marker write at each call site,
    because the defect this fixes was exactly that: the startup path recorded
    its success and the session path did not, so a supervisor delivering
    session messages perfectly still decayed to `unconfirmed` an hour after
    startup and failed `--require-notify-confirmed`.

    Confirmation is never written on a failure, a non-2xx response, a skipped
    or suppressed send, or a disabled notifier: those paths either never reach
    this function or return `ok=False`, and the marker is written strictly
    inside the `result.ok` branch. Nothing else in this process writes it.

    Confirmation does not become permanent. The marker is a timestamp read
    against `DELIVERY_CONFIRMED_TTL_SECONDS`, so readiness still expires
    unless a newer successful delivery refreshes it.
    """
    result = notify_owner(kind, body)
    if result.ok:
        liveness.record_delivered(CONFIRMATION_MARKER, now=now or dt.datetime.now(dt.UTC))
    return result


def notify(kind: NotificationKind, body: str) -> bool:
    """Injected into `Supervisor` — session-start health, the daily report, and
    every other §19 notification the trading loop emits. The loop itself knows
    nothing about delivery evidence; it calls a bool-returning callable, as
    before."""
    return deliver(kind, body).ok


def _announce_startup(started_at: dt.datetime, mode: str) -> dict:
    """Structured, flushed, secret-free. Every field is a process fact.

    Called before `load_env_file()`, so the credential variables may not be in
    the environment yet and `assert_secret_free` has less to match on. That is
    acceptable here and only here: this payload is built entirely from
    interpreter state (pid, executable, version, argv mode, repo path), none of
    which can carry a credential. Every later write happens with the guard
    fully armed.
    """
    return liveness.record_startup(
        LOG_DIR,
        now=started_at,
        pid=os.getpid(),
        interpreter=sys.executable,
        python_version=".".join(str(part) for part in sys.version_info[:3]),
        mode=mode,
        repo=str(REPO),
    )


def _startup_body(payload: dict) -> str:
    return redact(
        f"supervisor initialised at {payload['at']} — pid {payload['pid']}, "
        f"Python {payload['python_version']}, mode {payload['mode']}. "
        f"Scheduled operation only: this process cannot place an order (§0 rule 1) "
        f"and nothing is live."
    )


def attempt_startup_notification(payload: dict, now: dt.datetime) -> bool:
    """Try once to tell the owner the supervisor is up. Returns True if confirmed.

    The old version discarded the NotifyResult and stamped a "sent" marker on
    ATTEMPT, so a failed delivery was recorded as a success and never retried.
    Now the outcome is captured and the two records are kept apart:

      * the delivery marker is written ONLY when Telegram confirms;
      * the attempt ledger is written either way, which is what keeps a failing
        path rate-limited and bounded instead of retrying on every restart.

    Both outcomes are appended to the events log, so an unconfirmed surface is
    visible in `scripts/supervisor_status.py` rather than silently absent.
    """
    # Migrated once, and recorded as an assumption rather than a delivery: the
    # legacy marker proved only that a send was attempted.
    assumed_at = liveness.migrate_legacy_marker(
        legacy=LEGACY_MARKER, assumption=ASSUMPTION_MARKER, log_dir=LOG_DIR, now=now
    )
    decision = liveness.plan_notification(
        delivered_at=liveness.read_delivery_marker(DELIVERY_MARKER),
        assumed_at=assumed_at,
        ledger=liveness.read_attempt_ledger(ATTEMPT_LEDGER),
        now=now,
    )
    if not decision.should_send:
        return False

    # Same shared path as every session notification, so a confirmed startup
    # delivery refreshes the canonical readiness evidence too.
    result = deliver(NotificationKind.SUPERVISOR_STARTUP_HEALTH, _startup_body(payload), now)

    # The transport sanitises its own detail; redact again because this string
    # is about to become an immutable record (§0 rule 11, §0 iron rule 5).
    liveness.record_notification_attempt(
        LOG_DIR,
        now=now,
        ok=result.ok,
        stage=result.stage,
        status=result.status,
        attempt=decision.attempt_number,
        detail=redact(result.detail),
    )
    liveness.record_attempt(ATTEMPT_LEDGER, now=now, ok=result.ok)
    if result.ok:
        liveness.record_delivered(DELIVERY_MARKER, now=now)
    return result.ok


class StartupAnnouncer:
    """Heartbeat wrapper that keeps retrying an unconfirmed startup message.

    Composed here rather than inside `Supervisor`: the trading loop takes a
    plain callable and knows nothing about delivery state. Beats FIRST, so a
    slow or hanging notification can never delay the liveness signal that
    exists to detect exactly that.
    """

    def __init__(self, beat, payload: dict, clock) -> None:
        self._beat = beat
        self._payload = payload
        self._clock = clock
        self.confirmed = False

    def __call__(self, phase: str) -> None:
        self._beat(phase)
        if self.confirmed:
            return
        # plan_notification enforces the interval and the bound, so riding the
        # heartbeat cannot turn into a retry storm.
        self.confirmed = attempt_startup_notification(self._payload, self._clock())


def main() -> int:
    started_at = dt.datetime.now(dt.UTC)
    once = "--once" in sys.argv
    payload = _announce_startup(started_at, "once" if once else "loop")

    load_env_file()
    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)

    # §30.12: surveillance ships disabled, so the sweep composes to None and
    # the supervisor is byte-identical to the pre-amendment build. Enabling
    # the flag does not silently start anything here — the live-data sweep
    # composition arrives with rollout step 3, and until it exists an enabled
    # flag is a loud configuration error, not a quiet no-op.
    from trading_firm.surveillance.config import (  # noqa: E402
        BASE_SURVEILLANCE_CONFIG_PATH,
        load_surveillance_config,
    )

    sweep = None
    if BASE_SURVEILLANCE_CONFIG_PATH.exists():
        surveillance_config = load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)
        if surveillance_config.enabled:
            raise RuntimeError(
                "surveillance.enabled is true, but the live-data sweep composition "
                "lands with rollout step 3 (§30.12) — this build supports steps 1-2 "
                "(disabled; research replay). Set enabled back to false."
            )

    now_utc = lambda: dt.datetime.now(dt.UTC)  # noqa: E731
    beat = liveness.HeartbeatWriter(
        LOG_DIR,
        started_at=started_at,
        pid=payload["pid"],
        interpreter=payload["interpreter"],
        python_version=payload["python_version"],
        now=now_utc,
    )
    announcer = StartupAnnouncer(beat, payload, now_utc)

    supervisor = Supervisor(
        clock=clock,
        probe=probe,
        notify=notify,
        report_dir=REPO / "reports" / "ops",
        now=now_utc,
        sleep=time.sleep,
        heartbeat=announcer,
        sweep=sweep,
    )

    def _stop(signum, frame):  # noqa: ARG001
        supervisor.stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    # Initialisation is complete: config validated, clock built, supervisor
    # wired. Only now is a "healthy startup" claim true.
    beat("initialised")
    if "--no-notify" in sys.argv:
        announcer.confirmed = True  # smoke check: suppress the send entirely
    else:
        announcer.confirmed = attempt_startup_notification(payload, started_at)

    if once:
        supervisor.handle(next_event(clock, dt.datetime.now(dt.UTC)))
        return 0

    supervisor.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
