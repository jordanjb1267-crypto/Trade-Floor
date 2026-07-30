"""Continuation rules + prior-session structure features (research, §12.1).

Current session: the engineered Asian range 1.3300-1.3340 with a LONG
breakout at 1.3342 (identical to test_replay's winning case). Prior day
(2026-07-28) London windows are engineered bullish (+30 pips), bearish
(-30 pips), or flat (+10 pips) to exercise the one-variable filter.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.features.engine import prior_session_structure, session_features
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.models import Direction, InstrumentSpec
from trading_firm.research import replay_session
from trading_firm.research.replay import SessionStatus, TradeOutcome
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests
from trading_firm.strategies.continuation import (
    ContinuationParams,
    first_continuation_signal,
)

LONDON = ZoneInfo("Europe/London")
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))
DAY = dt.date(2026, 7, 29)  # Wednesday
PRIOR = dt.date(2026, 7, 28)
PARAMS = ContinuationParams()


def bar(day: dt.date, hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def prior_window(net_pips: int) -> list[Bar]:
    # Prior London window: 08:00 opens 1.3300, 10:45 closes 1.3300 + net.
    pip = Decimal("0.0001")
    start = Decimal("1.3300")
    mid = start + Decimal(net_pips) * pip / 2
    end = start + Decimal(net_pips) * pip

    def ohlc(o: Decimal, c: Decimal) -> tuple[str, str, str, str]:
        return str(o), str(max(o, c) + 2 * pip), str(min(o, c) - 2 * pip), str(c)

    return [
        bar(PRIOR, "08:00", *ohlc(start, mid)),
        bar(PRIOR, "10:45", *ohlc(mid, end)),
    ]


TODAY = [
    bar(DAY, "00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    bar(DAY, "02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    bar(DAY, "04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    bar(DAY, "07:00", "1.3320", "1.3330", "1.3312", "1.3326"),
    bar(DAY, "08:15", "1.3335", "1.3343", "1.3320", "1.3341"),  # long trigger 1.3342
    bar(DAY, "08:30", "1.3341", "1.3405", "1.3338", "1.3400"),  # runs to 1.5R target
]


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
        )["london_continuation"],
    }


def series_of(bars: list[Bar]) -> BarSeries:
    return BarSeries(
        instrument="GBP_USD",
        granularity_minutes=15,
        bars=tuple(sorted(bars, key=lambda b: b.ts)),
    )


class TestPriorSessionStructure:
    def test_reads_prior_london_window(self, env: dict) -> None:
        structure = prior_session_structure(
            series_of([*prior_window(30), *TODAY]), DAY, env["clock"]
        )
        assert structure is not None
        assert structure.prior_session_date == PRIOR
        assert structure.net_move_pips == Decimal("30")
        # no-lookahead: the feature is stamped at TODAY's activation and
        # every contributing bar closed the prior day
        assert structure.computed_at.date() == DAY

    def test_skips_empty_days_up_to_lookback(self, env: dict) -> None:
        monday = dt.date(2026, 7, 27)
        friday = dt.date(2026, 7, 24)  # weekend gap between Friday and Monday
        fri_bars = [
            bar(friday, "08:00", "1.3300", "1.3332", "1.3298", "1.3305"),
            bar(friday, "10:45", "1.3305", "1.3332", "1.3300", "1.3330"),
        ]
        structure = prior_session_structure(series_of(fri_bars), monday, env["clock"])
        assert structure is not None
        assert structure.prior_session_date == friday
        assert structure.net_move_pips == Decimal("30")

    def test_no_prior_data_fails_closed(self, env: dict) -> None:
        assert prior_session_structure(series_of(TODAY), DAY, env["clock"]) is None


class TestFilter:
    def signal(self, env: dict, net_pips: int | None):
        bars = [*prior_window(net_pips), *TODAY] if net_pips is not None else TODAY
        series = series_of(bars)
        features = session_features(series, DAY, env["clock"], GBP_USD.pip_size)
        structure = prior_session_structure(series, DAY, env["clock"], GBP_USD.pip_size)
        boundaries = env["clock"].boundaries(DAY)
        active = series.between(boundaries["activation"], boundaries["entry_cutoff"])
        return first_continuation_signal(features, structure, active, PARAMS, GBP_USD.pip_size)

    def test_aligned_bullish_prior_passes_the_long_breakout(self, env: dict) -> None:
        signal = self.signal(env, 30)
        assert signal is not None
        assert signal.direction is Direction.LONG
        assert signal.trigger_price == Decimal("1.3342")  # champion mechanics

    def test_counter_trend_prior_blocks(self, env: dict) -> None:
        assert self.signal(env, -30) is None

    def test_unvalidated_small_prior_move_blocks(self, env: dict) -> None:
        assert self.signal(env, 10) is None  # |10| < 20 minimum

    def test_missing_structure_blocks(self, env: dict) -> None:
        assert self.signal(env, None) is None


class TestReplayIntegration:
    def test_aligned_session_trades_like_the_champion(self, env: dict) -> None:
        outcome = replay_session(
            series_of([*prior_window(30), *TODAY]),
            DAY,
            config=env["config"],
            clock=env["clock"],
            engine=env["engine"],
            manifest=env["manifest"],
            spec=GBP_USD,
        )
        assert outcome.status is SessionStatus.TRADED
        # identical numbers to the champion's engineered win: 595 units,
        # 1.5R target at 1.3402, exit 1.3401, +$3.45
        trade = outcome.trade
        assert trade.outcome is TradeOutcome.TARGET
        assert trade.units == 595
        assert trade.pnl_usd == Decimal("3.45")

    def test_no_prior_day_is_no_features(self, env: dict) -> None:
        outcome = replay_session(
            series_of(TODAY),
            DAY,
            config=env["config"],
            clock=env["clock"],
            engine=env["engine"],
            manifest=env["manifest"],
            spec=GBP_USD,
        )
        assert outcome.status is SessionStatus.NO_FEATURES


class TestPriorCoverageGuard:
    """A partially-covered prior window is not 'validated structure' (§0.10):
    a single bar's open-to-close would gate entries on almost no evidence.
    """

    def test_single_bar_prior_day_is_not_validated(self, env: dict) -> None:
        thin = [bar(PRIOR, "08:00", "1.3300", "1.3335", "1.3298", "1.3330")]
        assert prior_session_structure(series_of([*thin, *TODAY]), DAY, env["clock"]) is None

    def test_late_starting_prior_window_is_not_validated(self, env: dict) -> None:
        late = [
            bar(PRIOR, "09:00", "1.3300", "1.3312", "1.3298", "1.3310"),
            bar(PRIOR, "10:45", "1.3310", "1.3335", "1.3308", "1.3330"),
        ]
        assert prior_session_structure(series_of([*late, *TODAY]), DAY, env["clock"]) is None

    def test_strategy_declines_on_uncovered_prior_day(self, env: dict) -> None:
        thin = [bar(PRIOR, "08:00", "1.3300", "1.3335", "1.3298", "1.3330")]
        outcome = replay_session(
            series_of([*thin, *TODAY]),
            DAY,
            config=env["config"],
            clock=env["clock"],
            engine=env["engine"],
            manifest=env["manifest"],
            spec=GBP_USD,
        )
        assert outcome.status is SessionStatus.NO_FEATURES
