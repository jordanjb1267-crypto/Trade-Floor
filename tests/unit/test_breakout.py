"""Champion breakout signal construction (§11 rules), both directions.

The SHORT branch previously had no test anywhere: mutating its stop-cap
expression left the whole suite green. These pin both sides by exact Decimal
equality, including either side of the stop-cap boundary.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_firm.features.engine import FEATURES_VERSION, SessionFeatures
from trading_firm.market_data.bars import Bar
from trading_firm.models import Direction
from trading_firm.strategies.breakout import BreakoutParams, first_breakout_signal

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)
PARAMS = BreakoutParams()


def features(high: str, low: str) -> SessionFeatures:
    width = (Decimal(high) - Decimal(low)) / Decimal("0.0001")
    return SessionFeatures(
        feature_version=FEATURES_VERSION,
        session_date=DAY,
        computed_at=dt.datetime.combine(DAY, dt.time(7, 30), tzinfo=LONDON),
        asian_high=Decimal(high),
        asian_low=Decimal(low),
        asian_width_pips=width,
        asian_bar_count=90,
        pre_london_range_pips=Decimal("10"),
        compression_ratio=Decimal("0.25"),
    )


def bar(hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(DAY, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


class TestShortBranch:
    def test_short_stop_uses_asian_high_when_inside_the_cap(self) -> None:
        # 40-pip range: short trigger 1.3298, opposite side 1.3340 is 42 pips
        # away — wider than the 40-pip cap, so the CAP binds at 1.3338.
        f = features("1.3340", "1.3300")
        signal = first_breakout_signal(
            f, (bar("08:15", "1.3310", "1.3315", "1.3297", "1.3299"),), PARAMS
        )
        assert signal is not None
        assert signal.direction is Direction.SHORT
        assert signal.trigger_price == Decimal("1.3298")
        assert signal.stop_price == Decimal("1.3338")  # trigger + 40-pip cap
        assert signal.target_price == Decimal("1.3238")  # 1.5R below trigger

    def test_short_stop_uses_the_cap_when_range_is_wider(self) -> None:
        # 55-pip range: opposite side 1.3355 is 57 pips from the 1.3298
        # trigger, so the cap binds and the stop is NOT the Asian high.
        f = features("1.3355", "1.3300")
        signal = first_breakout_signal(
            f, (bar("08:15", "1.3310", "1.3315", "1.3297", "1.3299"),), PARAMS
        )
        assert signal.stop_price == Decimal("1.3338")
        assert signal.stop_price != f.asian_high

    def test_short_stop_uses_range_side_when_narrower_than_cap(self) -> None:
        # 20-pip range: opposite side 1.3320 is only 22 pips away, inside the
        # cap, so the TECHNICAL level wins. A mutation swapping min/max here
        # would produce 1.3338 and is now caught.
        f = features("1.3320", "1.3300")
        signal = first_breakout_signal(
            f, (bar("08:15", "1.3310", "1.3315", "1.3297", "1.3299"),), PARAMS
        )
        assert signal.stop_price == Decimal("1.3320")

    def test_short_target_is_below_entry(self) -> None:
        f = features("1.3320", "1.3300")
        signal = first_breakout_signal(
            f, (bar("08:15", "1.3310", "1.3315", "1.3297", "1.3299"),), PARAMS
        )
        assert signal.target_price < signal.trigger_price < signal.stop_price


class TestLongBranch:
    def test_long_stop_uses_range_side_when_narrower_than_cap(self) -> None:
        f = features("1.3320", "1.3300")
        signal = first_breakout_signal(
            f, (bar("08:15", "1.3315", "1.3323", "1.3310", "1.3321"),), PARAMS
        )
        assert signal.direction is Direction.LONG
        assert signal.trigger_price == Decimal("1.3322")
        assert signal.stop_price == Decimal("1.3300")
        assert signal.target_price > signal.trigger_price > signal.stop_price


class TestAmbiguity:
    def test_both_sides_in_one_bar_is_no_trade(self) -> None:
        f = features("1.3340", "1.3300")
        both = bar("08:15", "1.3320", "1.3345", "1.3295", "1.3330")
        assert first_breakout_signal(f, (both,), PARAMS) is None
