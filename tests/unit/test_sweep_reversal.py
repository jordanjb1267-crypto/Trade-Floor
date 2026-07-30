"""Sweep-reversal rule logic + replay integration (research only, §12.1).

Engineered Asian range 1.3300-1.3340 (40 pips, inside the 15-60 regime
filter). Sweep threshold: 1.3343 high side / 1.3297 low side; acceptance:
1.3365 / 1.3275. All exact-pnl numbers derive from: allowed risk $2.50,
2.0-pip flat spread, sizing = floor(2.50 / (stop_distance + spread)).
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.features.engine import session_features
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.models import Direction, InstrumentSpec
from trading_firm.research import replay_session
from trading_firm.research.replay import SessionStatus, TradeOutcome
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests
from trading_firm.strategies.sweep_reversal import (
    SweepReversalParams,
    first_sweep_reversal_signal,
)

LONDON = ZoneInfo("Europe/London")
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))
DAY = dt.date(2026, 7, 29)
PARAMS = SweepReversalParams()


def bar(hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(DAY, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


ASIAN = [
    bar("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    bar("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    bar("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    bar("07:00", "1.3320", "1.3330", "1.3312", "1.3326"),
]
# Sweep of the high (1.3348 > 1.3343 threshold, < 1.3365 acceptance), still
# closing outside; next bar makes a higher extreme then closes back inside.
SWEEP = bar("08:15", "1.3338", "1.3348", "1.3330", "1.3346")
REENTRY = bar("08:30", "1.3346", "1.3350", "1.3334", "1.3336")


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
        )["asian_range_sweep_reversal"],
    }


def series_of(bars: list[Bar]) -> BarSeries:
    return BarSeries(
        instrument="GBP_USD",
        granularity_minutes=15,
        bars=tuple(sorted(bars, key=lambda b: b.ts)),
    )


def signal_for(env: dict, bars: list[Bar]):
    series = series_of(bars)
    features = session_features(series, DAY, env["clock"], GBP_USD.pip_size)
    boundaries = env["clock"].boundaries(DAY)
    active = series.between(boundaries["activation"], boundaries["entry_cutoff"])
    return first_sweep_reversal_signal(features, active, PARAMS, GBP_USD.pip_size)


def replay(env: dict, bars: list[Bar]):
    return replay_session(
        series_of(bars),
        DAY,
        config=env["config"],
        clock=env["clock"],
        engine=env["engine"],
        manifest=env["manifest"],
        spec=GBP_USD,
    )


class TestSignal:
    def test_sweep_then_reentry_shorts_at_close(self, env: dict) -> None:
        signal = signal_for(env, [*ASIAN, SWEEP, REENTRY])
        assert signal is not None
        assert signal.direction is Direction.SHORT
        assert signal.trigger_price == Decimal("1.3336")  # re-entry close
        assert signal.stop_price == Decimal("1.3352")  # extreme 1.3350 + 2p buffer
        assert signal.target_price == Decimal("1.3300")  # opposing liquidity
        assert signal.entry_at_close is True

    def test_same_bar_sweep_and_reentry_signals(self, env: dict) -> None:
        one_bar = bar("08:15", "1.3338", "1.3348", "1.3330", "1.3336")
        signal = signal_for(env, [*ASIAN, one_bar])
        assert signal is not None
        assert signal.stop_price == Decimal("1.3350")  # extreme 1.3348 + buffer

    def test_deep_sweep_is_acceptance_not_setup(self, env: dict) -> None:
        deep = bar("08:15", "1.3338", "1.3370", "1.3330", "1.3346")  # >= 1.3365
        assert signal_for(env, [*ASIAN, deep, REENTRY]) is None

    def test_slow_reentry_is_acceptance(self, env: dict) -> None:
        outside = [
            SWEEP,  # sweep starts (index 0 of the window)
            bar("08:30", "1.3346", "1.3349", "1.3344", "1.3347"),
            bar("08:45", "1.3347", "1.3350", "1.3344", "1.3346"),
            bar("09:00", "1.3346", "1.3348", "1.3334", "1.3336"),  # 4th bar: too late
        ]
        assert signal_for(env, [*ASIAN, *outside]) is None

    def test_range_regime_filter(self, env: dict) -> None:
        narrow = [  # 8-pip Asian range < 15 minimum
            bar("00:00", "1.3320", "1.3326", "1.3318", "1.3324"),
            bar("02:00", "1.3324", "1.3326", "1.3319", "1.3320"),
            bar("04:00", "1.3320", "1.3325", "1.3318", "1.3322"),
            bar("07:00", "1.3322", "1.3324", "1.3318", "1.3323"),
        ]
        sweep = bar("08:15", "1.3324", "1.3330", "1.3320", "1.3322")
        assert signal_for(env, [*narrow, sweep]) is None


class TestReplayIntegration:
    # A 16-pip stop wants floor(2.50/0.0018) = 1388 units, but the F-1
    # margin overlay binds FIRST on GBP_USD (5% rate): budget = 0.30 x $250
    # = $75 -> 75/(1.3336 x 0.05) = 1124 units -> risk cap 1124 x 0.0016 =
    # $1.79. Sizing then floors 1.79/(16p stop + 2p spread) = 994 units.
    # Entry exec: 1.3336 - 0.0001 = 1.3335 (short sells at bid).

    def test_target_hit_pays_opposing_liquidity(self, env: dict) -> None:
        bars = [*ASIAN, SWEEP, REENTRY,
                bar("08:45", "1.3336", "1.3338", "1.3298", "1.3305")]  # touches 1.3300
        outcome = replay(env, bars)
        trade = outcome.trade
        assert outcome.status is SessionStatus.TRADED
        assert trade.units == 994
        assert trade.allowed_risk_usd == Decimal("1.79")  # margin-bound (F-1)
        assert trade.outcome is TradeOutcome.TARGET
        assert trade.exit_price == Decimal("1.3301")  # target + half spread
        # 994 x (1.3335 - 1.3301) = $3.3796 -> $3.37 (floor)
        assert trade.pnl_usd == Decimal("3.37")

    def test_stop_loses_exactly_approved_risk(self, env: dict) -> None:
        bars = [*ASIAN, SWEEP, REENTRY,
                bar("08:45", "1.3336", "1.3353", "1.3334", "1.3340")]  # touches 1.3352
        trade = replay(env, bars).trade
        assert trade.outcome is TradeOutcome.STOP
        assert trade.exit_price == Decimal("1.3353")  # stop + half spread
        # 994 x (1.3335 - 1.3353) = -$1.7892 -> -$1.79: exactly the
        # margin-bound approved risk, never more (§0.7)
        assert trade.pnl_usd == Decimal("-1.79")
        assert trade.pnl_usd == -trade.allowed_risk_usd

    def test_trigger_bar_price_action_cannot_exit(self, env: dict) -> None:
        # The re-entry bar itself touches the 1.3300 target (low 1.3299 —
        # kept above the 1.3297 low-side sweep threshold so only one side
        # is in play) before closing at 1.3336: entry is AT the close, so
        # that touch is pre-entry history and must not count. With no later
        # bars, the trade flattens at the trigger bar close.
        plunge = bar("08:30", "1.3346", "1.3350", "1.3299", "1.3336")
        trade = replay(env, [*ASIAN, SWEEP, plunge]).trade
        assert trade.outcome is TradeOutcome.FLATTENED
        # flatten at 1.3336 close: exit 1.3337 short side -> 994 x -0.0002
        assert trade.exit_price == Decimal("1.3337")
        assert trade.pnl_usd == Decimal("-0.20")


class TestRewardInvariant:
    """Regression: a re-entry close outside the OPPOSITE extreme put the
    opposing-liquidity target behind the entry (negative reward), and replay
    scored the resulting loss as a TARGET win (adversarial review 2026-07-30).
    """

    def test_close_beyond_the_far_extreme_is_no_setup(self, env: dict) -> None:
        # Sweeps the high (1.3348), then a violent bar closes at 1.3295 —
        # BELOW the 1.3300 range low. A short entered at 1.3295 targeting
        # 1.3300 would be targeting a WORSE price than entry.
        violent = bar("08:30", "1.3346", "1.3350", "1.3290", "1.3295")
        assert signal_for(env, [*ASIAN, SWEEP, violent]) is None

    def test_long_side_sweep_produces_positive_reward(self, env: dict) -> None:
        # Mirror path (previously untested end to end): sweep BELOW the low
        # (1.3294 < 1.3297 threshold), close back inside -> LONG toward the
        # 1.3340 opposing extreme, which must be above the entry.
        low_sweep = bar("08:15", "1.3310", "1.3315", "1.3294", "1.3296")
        reentry = bar("08:30", "1.3296", "1.3312", "1.3292", "1.3310")
        signal = signal_for(env, [*ASIAN, low_sweep, reentry])
        assert signal is not None
        assert signal.direction is Direction.LONG
        assert signal.trigger_price == Decimal("1.3310")  # re-entry close
        assert signal.stop_price == Decimal("1.3290")  # extreme 1.3292 - 2p buffer
        assert signal.target_price == Decimal("1.3340")  # opposing liquidity
        assert signal.target_price > signal.trigger_price > signal.stop_price

    def test_long_side_replay_stop_respects_approved_risk(self, env: dict) -> None:
        low_sweep = bar("08:15", "1.3310", "1.3315", "1.3294", "1.3296")
        reentry = bar("08:30", "1.3296", "1.3312", "1.3292", "1.3310")
        stop_out = bar("08:45", "1.3310", "1.3312", "1.3288", "1.3289")
        trade = replay(env, [*ASIAN, low_sweep, reentry, stop_out]).trade
        assert trade.direction is Direction.LONG
        assert trade.outcome is TradeOutcome.STOP
        assert -trade.pnl_usd <= trade.allowed_risk_usd
