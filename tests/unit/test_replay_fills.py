"""Achievable-fill regressions (adversarial review, 2026-07-30).

The defect: a stop-order entry was filled at the strategy's trigger price even
when the first ACTIVE bar had already OPENED beyond it — a price no broker
could give, because the Asian range freezes at 07:30 while entries open at
08:00. Trades that broke during that gap booked fictitious profit and, worse,
were SIZED against a stop distance the trade never had, breaching the §3 risk
cap.

These tests pin the corrected behavior on BOTH directions; the mutation audit
found the SHORT paths were entirely unguarded.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.models import Direction, InstrumentSpec
from trading_firm.research import replay_session
from trading_firm.research.replay import SessionStatus, TradeOutcome
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests

LONDON = ZoneInfo("Europe/London")
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))
DAY = dt.date(2026, 7, 29)

# Asian range 1.3300-1.3340 -> long trigger 1.3342 / short trigger 1.3298.
ASIAN = [
    ("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    ("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    ("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    ("07:00", "1.3320", "1.3330", "1.3312", "1.3326"),
]


def bar(hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(DAY, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


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


def replay(env: dict, active: list[Bar]):
    bars = [bar(*row) for row in ASIAN] + active
    series = BarSeries(
        instrument="GBP_USD",
        granularity_minutes=15,
        bars=tuple(sorted(bars, key=lambda b: b.ts)),
    )
    return replay_session(
        series,
        DAY,
        config=env["config"],
        clock=env["clock"],
        engine=env["engine"],
        manifest=env["manifest"],
        spec=GBP_USD,
    )


class TestGapThroughEntry:
    def test_long_gap_fills_at_the_open_not_the_stale_trigger(self, env: dict) -> None:
        # Break happened in the 07:30-08:00 blackout: the ACTIVE bar opens at
        # 1.3360, 18 pips beyond the 1.3342 trigger, and its LOW never returns
        # there. The old engine booked 1.3342; 1.3360 is the real first
        # obtainable price.
        outcome = replay(
            env,
            [
                bar("08:00", "1.3360", "1.3380", "1.3355", "1.3375"),
                bar("08:30", "1.3375", "1.3378", "1.3299", "1.3305"),  # -> stop
            ],
        )
        trade = outcome.trade
        assert outcome.status is SessionStatus.TRADED
        assert trade.direction is Direction.LONG
        # entry mid 1.3360 (bar open), + 1-pip half spread
        assert trade.entry_price == Decimal("1.3361")
        # Sizing saw the TRUE 58-pip stop distance (1.3360 -> 1.3302), not the
        # 40-pip distance from the stale trigger, so the stop costs no more
        # than the approved risk.
        assert trade.outcome is TradeOutcome.STOP
        assert -trade.pnl_usd <= trade.allowed_risk_usd

    def test_short_gap_fills_at_the_open_not_the_stale_trigger(self, env: dict) -> None:
        # Mirror case: opens 1.3280, 18 pips below the 1.3298 short trigger.
        outcome = replay(
            env,
            [
                bar("08:00", "1.3280", "1.3285", "1.3260", "1.3265"),
                bar("08:30", "1.3265", "1.3345", "1.3262", "1.3341"),  # -> stop
            ],
        )
        trade = outcome.trade
        assert trade.direction is Direction.SHORT
        assert trade.entry_price == Decimal("1.3279")  # 1.3280 open - half spread
        assert -trade.pnl_usd <= trade.allowed_risk_usd

    def test_no_gap_still_fills_at_the_trigger(self, env: dict) -> None:
        # The ordinary case must be untouched: the bar opens BELOW the trigger
        # and trades up through it, so the trigger price is genuinely available.
        outcome = replay(
            env,
            [
                bar("08:15", "1.3335", "1.3343", "1.3320", "1.3341"),
                bar("08:30", "1.3341", "1.3405", "1.3338", "1.3400"),
            ],
        )
        trade = outcome.trade
        assert trade.entry_price == Decimal("1.3343")  # 1.3342 trigger + half spread
        assert trade.units == 595
        assert trade.pnl_usd == Decimal("3.45")  # unchanged golden number

    def test_entry_stays_on_the_live_side_of_the_stop(self, env: dict) -> None:
        # Clamping moves entry only ADVERSELY (away from the stop), so no gap
        # size can put entry and invalidation on the same side. This pins the
        # invariant that makes a "gapped past the stop" branch unnecessary.
        for open_px in ("1.3299", "1.3280", "1.3200", "1.3100"):  # ever-larger short gaps
            outcome = replay(
                env,
                [
                    bar("08:00", open_px, str(Decimal(open_px) + Decimal("0.0005")),
                        str(Decimal(open_px) - Decimal("0.0005")), open_px),
                    bar("08:30", open_px, "1.3345", str(Decimal(open_px) - Decimal("0.0010")),
                        "1.3341"),
                ],
            )
            if outcome.status is not SessionStatus.TRADED:
                continue
            trade = outcome.trade
            assert trade.direction is Direction.SHORT
            # short: entry strictly below the stop it is invalidated by
            assert trade.entry_price < Decimal("1.3338"), f"collision at open {open_px}"
            assert -trade.pnl_usd <= trade.allowed_risk_usd

    def test_risk_cap_holds_across_gapped_entries(self, env: dict) -> None:
        # The property the defect broke, stated directly: for ANY gap size the
        # engine accepts, a stopped trade never loses more than approved risk.
        for open_px in ("1.3343", "1.3350", "1.3360", "1.3370", "1.3380"):
            outcome = replay(
                env,
                [
                    bar("08:00", open_px, "1.3390", str(Decimal(open_px) - Decimal("0.0002")),
                        "1.3385"),
                    bar("08:30", "1.3385", "1.3386", "1.3295", "1.3300"),
                ],
            )
            if outcome.status is not SessionStatus.TRADED:
                continue
            trade = outcome.trade
            assert trade.outcome is TradeOutcome.STOP
            assert -trade.pnl_usd <= trade.allowed_risk_usd, f"breach at open {open_px}"
