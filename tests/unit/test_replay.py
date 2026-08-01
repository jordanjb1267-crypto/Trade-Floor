"""Replay engine tests (§12.2): the full pipeline — features → signal → risk
engine → sizing → simulated fills → mandatory flatten — with exact expected
P&L, on engineered synthetic sessions.

Shared setup: Asian range 1.3300–1.3340 (40 pips, inside the [15, 60] filter);
long trigger 1.3342 (2-pip buffer); stop 1.3302 (40-pip cap); target 1.3402
(1.5R). Risk approval $2.50 (Standard tier cap binds); sizing at 2-pip spread
gives loss/unit 0.0042 → 595 units.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from replay_series import (  # noqa: E402
    FLAT_DAY,
    LOSS_DAY,
    NARROW_DAY,
    QUIET_DAY,
    WIN_DAY,
    asian_bars,
    bar,
    build_series,
    trigger_bar,
)

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data.bars import BarSeries
from trading_firm.models import Direction, InstrumentSpec
from trading_firm.research import replay_range, replay_session, tradeable_session_dates
from trading_firm.research.replay import SessionStatus, TradeOutcome
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests

LONDON = ZoneInfo("Europe/London")
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))


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
        "spec": GBP_USD,
        "series": build_series(),
    }


def run_day(env: dict, day: dt.date):
    return replay_session(
        env["series"],
        day,
        config=env["config"],
        clock=env["clock"],
        engine=env["engine"],
        manifest=env["manifest"],
        spec=env["spec"],
    )


class TestSessionOutcomes:
    def test_win_session_exact_pnl(self, env: dict) -> None:
        outcome = run_day(env, WIN_DAY)
        assert outcome.status is SessionStatus.TRADED
        trade = outcome.trade
        assert trade.direction is Direction.LONG
        assert trade.units == 595
        assert trade.allowed_risk_usd == Decimal("2.50")
        assert trade.outcome is TradeOutcome.TARGET
        # entry 1.3342+0.0001, exit 1.3402-0.0001 -> 58 pips * 595 units = $3.45
        assert trade.pnl_usd == Decimal("3.45")

    def test_loss_session_bounded_by_approved_risk(self, env: dict) -> None:
        outcome = run_day(env, LOSS_DAY)
        trade = outcome.trade
        assert trade.outcome is TradeOutcome.STOP
        # entry 1.3343, stop exit 1.3301 -> -42 pips * 595 = -$2.50, == approved risk
        assert trade.pnl_usd == Decimal("-2.50")
        assert -trade.pnl_usd <= trade.allowed_risk_usd

    def test_flatten_boundary_is_inviolate(self, env: dict) -> None:
        outcome = run_day(env, FLAT_DAY)
        trade = outcome.trade
        assert trade.outcome is TradeOutcome.FLATTENED
        # exit at the 10:45 close (1.3350) minus half-spread, at the boundary,
        # never touching the poison 11:00 bar's 1.4000 high.
        assert trade.exit_price == Decimal("1.3349")
        assert trade.exit_ts == env["clock"].boundaries(FLAT_DAY)["flatten"]
        assert trade.pnl_usd == Decimal("0.35")

    def test_quiet_session_is_no_signal(self, env: dict) -> None:
        assert run_day(env, QUIET_DAY).status is SessionStatus.NO_SIGNAL

    def test_narrow_range_filtered(self, env: dict) -> None:
        # 10-pip Asian width fails the [15, 60] regime filter despite a huge move.
        assert run_day(env, NARROW_DAY).status is SessionStatus.NO_SIGNAL

    def test_missing_data_fails_closed(self, env: dict) -> None:
        assert run_day(env, dt.date(2026, 7, 22)).status is SessionStatus.NO_FEATURES


class TestReplayRange:
    def test_aggregate_report(self, env: dict) -> None:
        report = replay_range(
            env["series"],
            [FLAT_DAY, LOSS_DAY, WIN_DAY],
            config=env["config"],
            clock=env["clock"],
            engine=env["engine"],
            manifest=env["manifest"],
            spec=env["spec"],
        )
        assert report.sessions == 3
        assert report.traded == 3
        assert (report.wins, report.losses, report.flat_exits) == (2, 1, 1)
        assert report.net_pnl_usd == Decimal("1.30")  # 0.35 - 2.50 + 3.45
        assert report.gross_win_usd == Decimal("3.80")
        assert report.gross_loss_usd == Decimal("2.50")
        assert report.profit_factor == Decimal("1.52")
        assert report.expectancy_usd == Decimal("0.43")
        # cumulative: +0.35, -2.15, +1.30 -> peak 0.35, trough -2.15 -> dd 2.50
        assert report.max_drawdown_usd == Decimal("2.50")
        assert "NOT validation" in report.disclaimer

    def test_unimplemented_strategy_raises(self, env: dict) -> None:
        # All three declared strategies gained rules 2026-07-30, so the
        # guard is exercised with a synthetic unknown strategy id.
        manifests = load_manifests(BASE_CONFIG_PATH.parents[1] / "research" / "strategies")
        unknown = manifests["london_breakout"].model_copy(
            update={"strategy_id": "not_a_real_strategy"}
        )
        with pytest.raises(NotImplementedError):
            replay_session(
                env["series"],
                WIN_DAY,
                config=env["config"],
                clock=env["clock"],
                engine=env["engine"],
                manifest=unknown,
                spec=env["spec"],
            )


class TestTradeableSessionDates:
    """Sunday-reopen bars create a London date that can never produce
    features. Counting it inflates the denominator of every published rate
    (§12.4 honest reporting).
    """

    def test_sunday_reopen_bars_do_not_count_as_a_session(self, env: dict) -> None:
        sunday = dt.date(2026, 7, 26)  # Sunday
        monday = dt.date(2026, 7, 27)
        bars = [
            # Sunday 22:00 London reopen — no 00:00-07:30 Asian window
            bar(sunday, "22:00", "1.3300", "1.3310", "1.3295", "1.3305"),
            bar(sunday, "23:00", "1.3305", "1.3312", "1.3300", "1.3308"),
            *asian_bars(monday),
            trigger_bar(monday),
        ]
        series = BarSeries(
            instrument="GBP_USD",
            granularity_minutes=15,
            bars=tuple(sorted(bars, key=lambda b: b.ts)),
        )
        raw = sorted({b.ts.astimezone(LONDON).date() for b in series.bars})
        assert raw == [sunday, monday]  # the naive denominator counts both
        assert tradeable_session_dates(series, env["clock"]) == [monday]

    def test_covered_weekday_survives_the_filter(self, env: dict) -> None:
        # Guard against over-filtering: a normal session must be kept.
        assert WIN_DAY in tradeable_session_dates(env["series"], env["clock"])
