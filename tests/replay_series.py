"""The canonical five-day synthetic replay series, importable as a bare
module (same mechanism as `a2_guard`). Moved out of test_replay.py so the
surveillance replay and integration suites compare against the exact same
bars without a cross-package test import that CI cannot resolve."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_firm.market_data.bars import Bar, BarSeries

LONDON = ZoneInfo("Europe/London")

WIN_DAY = dt.date(2026, 7, 29)
LOSS_DAY = dt.date(2026, 7, 28)
FLAT_DAY = dt.date(2026, 7, 27)
QUIET_DAY = dt.date(2026, 7, 24)
NARROW_DAY = dt.date(2026, 7, 23)


def bar(day: dt.date, hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def asian_bars(day: dt.date) -> list[Bar]:
    return [
        bar(day, "00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
        bar(day, "02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
        bar(day, "04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
        bar(day, "07:00", "1.3320", "1.3330", "1.3312", "1.3326"),
    ]


def trigger_bar(day: dt.date) -> Bar:
    # high 1.3343 >= trigger 1.3342; low stays above the 1.3302 stop.
    return bar(day, "08:15", "1.3335", "1.3343", "1.3320", "1.3341")


def build_series() -> BarSeries:
    bars: list[Bar] = []
    # WIN: trigger at 08:15, target 1.3402 hit at 08:30.
    bars += asian_bars(WIN_DAY)
    bars += [trigger_bar(WIN_DAY), bar(WIN_DAY, "08:30", "1.3341", "1.3405", "1.3338", "1.3400")]
    # LOSS: trigger at 08:15, stop 1.3302 hit at 08:30.
    bars += asian_bars(LOSS_DAY)
    bars += [trigger_bar(LOSS_DAY), bar(LOSS_DAY, "08:30", "1.3341", "1.3345", "1.3300", "1.3305")]
    # FLAT: trigger at 08:15, drifts, still open at the 11:00 flatten boundary.
    bars += asian_bars(FLAT_DAY)
    bars += [
        trigger_bar(FLAT_DAY),
        bar(FLAT_DAY, "09:00", "1.3341", "1.3360", "1.3330", "1.3355"),
        bar(FLAT_DAY, "10:00", "1.3355", "1.3370", "1.3340", "1.3348"),
        bar(FLAT_DAY, "10:45", "1.3348", "1.3358", "1.3342", "1.3350"),
        # poison: a huge bar AT the flatten boundary must never be consumed (§14, F-5)
        bar(FLAT_DAY, "11:00", "1.3350", "1.4000", "1.3350", "1.3990"),
    ]
    # QUIET: active bars never reach either trigger.
    bars += asian_bars(QUIET_DAY)
    bars += [bar(QUIET_DAY, "08:15", "1.3320", "1.3330", "1.3315", "1.3325")]
    # NARROW: 10-pip Asian range fails the regime filter. Starts at 00:00 so
    # the session passes the Asian-window COVERAGE guard and genuinely
    # exercises the width filter rather than failing closed on missing data.
    bars += [
        bar(NARROW_DAY, "00:00", "1.3304", "1.3309", "1.3300", "1.3305"),
        bar(NARROW_DAY, "02:00", "1.3305", "1.3310", "1.3300", "1.3306"),
        bar(NARROW_DAY, "08:15", "1.3306", "1.3400", "1.3300", "1.3395"),
    ]
    ordered = tuple(sorted(bars, key=lambda b: b.ts))
    return BarSeries(instrument="GBP_USD", granularity_minutes=15, bars=ordered)
