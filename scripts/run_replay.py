#!/usr/bin/env python3
"""Run the london_breakout historical replay over a research fixture (§12.2).

Usage:
    python3 scripts/run_replay.py <fixture.json> <INSTRUMENT> <margin_rate>

Example:
    python3 scripts/run_replay.py \
        data/research/GBPUSD_M5_london_sessions_2026-06-08_2026-07-29_nytz.json \
        GBP_USD 0.05

The fixture holds raw FMP intraday rows whose naive timestamps are
America/New_York local (pinned empirically on 2026-07-30: the newest bar was
3 minutes old under that zone and hours off under every other candidate).
Margin rates come from the broker audit (F-1): GBP_USD 0.05, EUR_USD 0.02.

Output is a framework replay report — NOT validation (§12.4, §12.6).
"""

import json
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.config import BASE_CONFIG_PATH, load_config  # noqa: E402
from trading_firm.market_data import SpreadSeries, from_fmp_rows, from_oanda_candles  # noqa: E402
from trading_firm.models import InstrumentSpec  # noqa: E402
from trading_firm.research import replay_range  # noqa: E402
from trading_firm.research.replay import SessionStatus  # noqa: E402
from trading_firm.risk import RiskEngine  # noqa: E402
from trading_firm.sessions import SessionClock  # noqa: E402
from trading_firm.strategies import load_manifests  # noqa: E402

SOURCE_TZ = "America/New_York"
LONDON = ZoneInfo("Europe/London")
NY = ZoneInfo(SOURCE_TZ)


def main() -> int:
    if len(sys.argv) not in (4, 5):
        print(__doc__)
        print("Optional 4th argument: strategy_id (default london_breakout).")
        return 2
    fixture, instrument, margin_rate = sys.argv[1], sys.argv[2], Decimal(sys.argv[3])
    strategy_id = sys.argv[4] if len(sys.argv) == 5 else "london_breakout"

    payload = json.loads(Path(fixture).read_text())
    spreads = None
    if isinstance(payload, dict) and "candles" in payload:
        # OANDA practice fixture (scripts/fetch_oanda_candles.py): aware-UTC
        # timestamps, no pinning question. Execution costs use MEASURED
        # per-bar spreads; sizing keeps the flat assumption (as live would).
        series = from_oanda_candles(
            payload["candles"], instrument=instrument, granularity_minutes=5
        )
        spreads = SpreadSeries.from_oanda_candles(payload["candles"], instrument=instrument)
        print("costs: measured per-bar spreads (sizing still uses the flat assumption)")
        session_dates = sorted({b.ts.astimezone(LONDON).date() for b in series.bars})
    else:
        series = from_fmp_rows(
            payload, instrument=instrument, granularity_minutes=5, source_tz=SOURCE_TZ
        )
        session_dates = sorted(
            {
                datetime.fromisoformat(r["date"]).replace(tzinfo=NY).astimezone(LONDON).date()
                for r in payload
            }
        )
    print(f"{instrument}: {len(series.bars)} bars, {len(series.quality_events)} quality events")

    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    engine = RiskEngine(config, clock)
    manifest = load_manifests(
        BASE_CONFIG_PATH.parents[1] / "research" / "strategies"
    )[strategy_id]
    spec = InstrumentSpec(name=instrument, margin_rate=margin_rate)
    # only completed sessions: require bars beyond the entry cutoff
    last_bar_london = series.bars[-1].ts.astimezone(LONDON)
    session_dates = [
        d for d in session_dates
        if d < last_bar_london.date()
        or last_bar_london.time() >= clock.boundaries(d)["flatten"].timetz().replace(tzinfo=None)
    ]

    report = replay_range(
        series,
        session_dates,
        config=config,
        clock=clock,
        engine=engine,
        manifest=manifest,
        spec=spec,
        spreads=spreads,
    )

    print(f"\n{'DATE':<12}{'STATUS':<12}{'OUTCOME':<10}{'UNITS':>7}{'PNL':>9}")
    for outcome in report.outcomes:
        trade = outcome.trade
        print(
            f"{outcome.session_date.isoformat():<12}{outcome.status.value:<12}"
            f"{(trade.outcome.value if trade else '-'):<10}"
            f"{(trade.units if trade else 0):>7}"
            f"{(str(trade.pnl_usd) if trade else '-'):>9}"
        )
        if outcome.status is SessionStatus.REJECTED:
            for reason in outcome.reasons[:2]:
                print(f"{'':<12}reject: {reason}")

    print(
        f"\n{report.strategy_id} v{report.strategy_version} on {instrument} | "
        f"sessions={report.sessions} traded={report.traded} "
        f"W/L/F={report.wins}/{report.losses}/{report.flat_exits}"
    )
    print(
        f"net=${report.net_pnl_usd} expectancy=${report.expectancy_usd} "
        f"PF={report.profit_factor} maxDD=${report.max_drawdown_usd}"
    )
    print(f"\n{report.disclaimer}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
