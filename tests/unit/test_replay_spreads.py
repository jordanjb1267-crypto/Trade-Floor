"""Spread-aware replay (§12.2): measured per-bar costs vs the flat assumption.

Same engineered session as test_replay_exits.py: range 1.3300-1.3340, long
trigger 1.3342, stop 1.3302 (40-pip risk), 595 units sized at $2.50 approved
risk under the 2.0-pip ASSUMPTION. Sizing never changes with measured
spreads — only realized execution costs do.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data import SpreadSeries
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.models import InstrumentSpec
from trading_firm.research import replay_session
from trading_firm.research.replay import TradeOutcome
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests

LONDON = ZoneInfo("Europe/London")
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))
DAY = dt.date(2026, 7, 29)
PIP = Decimal("0.0001")


def bar(hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(DAY, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


BARS = [
    bar("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    bar("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    bar("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    bar("07:00", "1.3320", "1.3330", "1.3312", "1.3326"),
    bar("08:15", "1.3335", "1.3343", "1.3320", "1.3341"),  # trigger
    bar("08:30", "1.3341", "1.3350", "1.3301", "1.3310"),  # hits 1.3302 stop
]


def spread_series(pips_by_hhmm: dict[str, str]) -> SpreadSeries:
    by_ts = {
        dt.datetime.combine(DAY, dt.time.fromisoformat(k), tzinfo=LONDON).astimezone(
            dt.UTC
        ): Decimal(v) * PIP
        for k, v in pips_by_hhmm.items()
    }
    # every bar needs a measured spread; default the rest to 2.0 pips
    for b in BARS:
        by_ts.setdefault(b.ts.astimezone(dt.UTC), Decimal("2.0") * PIP)
    return SpreadSeries(instrument="GBP_USD", by_ts=by_ts)


@pytest.fixture(scope="module")
def env() -> dict:
    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    return {
        "config": config,
        "clock": clock,
        "engine": RiskEngine(config, clock),
        "manifest": load_manifests(
            BASE_CONFIG_PATH.parents[1] / "research" / "strategies"
        )["london_breakout"],
    }


def run(env: dict, spreads: SpreadSeries | None):
    series = BarSeries(instrument="GBP_USD", granularity_minutes=15, bars=tuple(BARS))
    return replay_session(
        series,
        DAY,
        config=env["config"],
        clock=env["clock"],
        engine=env["engine"],
        manifest=env["manifest"],
        spec=GBP_USD,
        spreads=spreads,
    )


class TestMeasuredSpreads:
    def test_measured_equal_to_assumption_reproduces_flat_result(self, env: dict) -> None:
        flat = run(env, None)
        measured = run(env, spread_series({}))  # all bars at 2.0 pips
        assert flat.trade.pnl_usd == measured.trade.pnl_usd == Decimal("-2.50")

    def test_wider_measured_spread_loses_more_than_approved(self, env: dict) -> None:
        # 3.0 pips at entry and exit vs the 2.0 sized-for assumption:
        # excess = 595 units x 1.0 pip = $0.0595 -> -$2.56 (floor rounding).
        outcome = run(env, spread_series({"08:15": "3.0", "08:30": "3.0"}))
        trade = outcome.trade
        assert trade.outcome is TradeOutcome.STOP
        assert trade.allowed_risk_usd == Decimal("2.50")  # sizing unchanged
        assert trade.pnl_usd == Decimal("-2.56")  # measured drift now visible

    def test_tighter_measured_spread_loses_less_than_approved(self, env: dict) -> None:
        outcome = run(env, spread_series({"08:15": "1.0", "08:30": "1.0"}))
        assert outcome.trade.pnl_usd == Decimal("-2.44")  # 1 pip saved x 595

    def test_missing_bar_spread_fails_closed(self, env: dict) -> None:
        incomplete = SpreadSeries(
            instrument="GBP_USD",
            by_ts={BARS[4].ts.astimezone(dt.UTC): Decimal("2.0") * PIP},
        )
        with pytest.raises(KeyError, match="no measured spread"):
            run(env, incomplete)


class TestSpreadSeriesFromCandles:
    def test_builds_from_mab_candles_and_rejects_mid_only(self) -> None:
        # Each OHLC field carries a DISTINCT spread, so reading the wrong one
        # (o/h/l instead of c) changes the answer. The previous fixture used a
        # uniform 2-pip spread across all four fields, which made the test
        # blind to exactly that mutation.
        candles = [
            {
                "time": "2026-07-01T08:00:00.000000000Z",
                "complete": True,
                "mid": {"o": "1.33", "h": "1.34", "l": "1.32", "c": "1.335"},
                "ask": {"o": "1.3304", "h": "1.3406", "l": "1.3208", "c": "1.3351"},
                "bid": {"o": "1.3296", "h": "1.3394", "l": "1.3192", "c": "1.3349"},
            }
        ]
        series = SpreadSeries.from_oanda_candles(candles, instrument="GBP_USD")
        ts = dt.datetime(2026, 7, 1, 8, 0, tzinfo=dt.UTC)
        # close spread is 2 pips; open would be 8, high 12, low 16
        assert series.at(ts) == Decimal("0.0002")
        with pytest.raises(ValueError, match="bid/ask"):
            SpreadSeries.from_oanda_candles(
                [{"time": "2026-07-01T08:00:00Z", "mid": {"c": "1.33"}}],
                instrument="GBP_USD",
            )
