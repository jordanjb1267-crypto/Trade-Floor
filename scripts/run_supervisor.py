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
"""

import datetime as dt
import signal
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_firm.config import BASE_CONFIG_PATH, load_config  # noqa: E402
from trading_firm.env_file import load_env_file  # noqa: E402
from trading_firm.notify.surface import NotificationKind, notify_owner  # noqa: E402
from trading_firm.runner.schedule import next_event  # noqa: E402
from trading_firm.runner.supervisor import HealthReport, Supervisor  # noqa: E402
from trading_firm.sessions import SessionClock  # noqa: E402


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


def notify(kind: NotificationKind, body: str) -> bool:
    return notify_owner(kind, body).ok


def main() -> int:
    load_env_file()
    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    supervisor = Supervisor(
        clock=clock,
        probe=probe,
        notify=notify,
        report_dir=REPO / "reports" / "ops",
        now=lambda: dt.datetime.now(dt.UTC),
        sleep=time.sleep,
    )

    def _stop(signum, frame):  # noqa: ARG001
        supervisor.stopping = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    if "--once" in sys.argv:
        supervisor.handle(next_event(clock, dt.datetime.now(dt.UTC)))
        return 0

    supervisor.run_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
