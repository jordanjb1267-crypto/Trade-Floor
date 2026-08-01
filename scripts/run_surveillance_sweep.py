#!/usr/bin/env python3
"""One observe-only surveillance sweep over research fixtures (§30, Phase C).

Builds a Market State Object from stored OANDA practice candles, runs
materiality and the alert discipline, and writes a local report — no
network, no broker, no Telegram, no database writes unless --db is given.
This is the rollout ladder's "research replay only" step made runnable:

    python3 scripts/run_surveillance_sweep.py --date 2026-07-29
    python3 scripts/run_surveillance_sweep.py --date 2026-07-29 --as-of 09:30

The report lands in reports/ops/surveillance/. The division's flags stay
exactly as configured — this script constructs its own coordinator against
fixtures and never touches the supervisor.
"""

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from trading_firm.config import BASE_CONFIG_PATH, load_config  # noqa: E402
from trading_firm.market_data.bars import BarSeries, from_oanda_candles  # noqa: E402
from trading_firm.market_data.spreads import SpreadSeries  # noqa: E402
from trading_firm.policy import load_adaptive_policy  # noqa: E402
from trading_firm.sessions import SessionClock  # noqa: E402
from trading_firm.surveillance.alerts import build_alerts  # noqa: E402
from trading_firm.surveillance.config import (  # noqa: E402
    BASE_SURVEILLANCE_CONFIG_PATH,
    load_surveillance_config,
)
from trading_firm.surveillance.deduplication import decide  # noqa: E402
from trading_firm.surveillance.materiality import MaterialityAssessment  # noqa: E402
from trading_firm.surveillance.state_builder import build_market_state  # noqa: E402

LONDON = ZoneInfo("Europe/London")
DEFAULT_FIXTURE = (
    REPO / "data" / "research" / "GBP_USD_M5_oanda_practice_2026-03-30_2026-07-29.json"
)
REPORT_DIR = REPO / "reports" / "ops" / "surveillance"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--instrument", default="GBP_USD")
    parser.add_argument("--date", required=True, help="London session date, YYYY-MM-DD")
    parser.add_argument("--as-of", default="08:30", help="London wall-clock HH:MM")
    args = parser.parse_args()

    session_date = dt.date.fromisoformat(args.date)
    as_of = dt.datetime.combine(
        session_date, dt.time.fromisoformat(args.as_of), tzinfo=LONDON
    )

    raw = json.loads(args.fixture.read_text())
    candles = raw["candles"]
    series: BarSeries = from_oanda_candles(
        candles, instrument=args.instrument, granularity_minutes=5
    )
    spreads = SpreadSeries.from_oanda_candles(candles, instrument=args.instrument)

    clock = SessionClock(load_config(BASE_CONFIG_PATH).session)
    policy = load_adaptive_policy(REPO / "config" / "research" / "adaptive_policy.yaml")
    surveillance = load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)

    state = build_market_state(
        instrument=args.instrument,
        session_date=session_date,
        clock=clock,
        series=series,
        spreads=spreads,
        permits=policy.permits_feature,
        config=surveillance,
        configuration_version="research-fixture",
        as_of=as_of,
    )
    state.verify(state.market_state_id)

    assessment = MaterialityAssessment(tuple(state.change_summary.material_changes))
    alerts = build_alerts(state, assessment, as_of)
    decisions = [
        (alert, decide(alert, {}, surveillance.alerts.minimum_severity))
        for alert in alerts
    ]

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORT_DIR / f"{session_date}-{args.as_of.replace(':', '')}-sweep.json"
    report = {
        "mode": "observe_only_research_fixture",
        "instrument": args.instrument,
        "session_date": session_date.isoformat(),
        "as_of_london": args.as_of,
        "market_state_id": state.market_state_id,
        "session_phase": state.session_state.phase,
        "regime": {
            "intraday": state.market_regime.intraday,
            "daily": state.market_regime.daily,
        },
        "structure_state": state.technical_state.structure_state,
        "liquidity": state.liquidity_state.classification,
        "spread_state": state.liquidity_state.spread_state,
        "data_quality": state.data_quality.overall_status,
        "missing_components": state.data_quality.missing_components,
        "material_changes": list(assessment.material_changes),
        "alerts": [
            {
                "severity": alert.severity,
                "what_changed": alert.what_changed,
                "would_emit": decision.should_emit,
                "reason": decision.reason,
            }
            for alert, decision in decisions
        ],
        "orders_placed": 0,
        "note": "observe-only: no order path exists from this process (§30.2)",
    }
    report_path.write_text(json.dumps(report, indent=2, default=str) + "\n")

    print(f"market state {state.market_state_id[:16]}  phase={state.session_state.phase}")
    print(
        f"regime intraday={state.market_regime.intraday}  "
        f"structure={state.technical_state.structure_state}  "
        f"liquidity={state.liquidity_state.classification}  "
        f"dq={state.data_quality.overall_status}"
    )
    for alert, decision in decisions:
        print(f"alert [{alert.severity}] {alert.what_changed}  emit={decision.should_emit}")
    print(f"report: {report_path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
