"""Exit-policy tests for the replay engine (challenger machinery, §15).

Same engineered Asian range as test_replay.py: range 1.3300–1.3340, long
trigger 1.3342, stop 1.3302 (40-pip risk), 595 units at $2.50 approved risk.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.models import InstrumentSpec
from trading_firm.research import ExitPolicy, replay_session
from trading_firm.research.replay import TradeOutcome
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests

LONDON = ZoneInfo("Europe/London")
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))
DAY = dt.date(2026, 7, 29)


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
TRIGGER = bar("08:15", "1.3335", "1.3343", "1.3320", "1.3341")


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
    }


def run(env: dict, bars: list[Bar], policy: ExitPolicy | None):
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
        spec=env["spec"],
        exit_policy=policy,
    )


class TestBreakevenTrail:
    def test_retrace_after_1r_exits_at_breakeven(self, env: dict) -> None:
        # +1R = 1.3382 reached at 08:30 arms the trail; 08:45 retraces through
        # entry. Champion would FLATTEN at 11:00 for -$0.54; the trail exits at
        # the 1.3342 breakeven, paying only the 2-pip spread.
        bars = [
            *ASIAN,
            TRIGGER,
            bar("08:30", "1.3341", "1.3383", "1.3338", "1.3380"),  # arms trail
            bar("08:45", "1.3380", "1.3381", "1.3330", "1.3335"),  # retrace
        ]
        policy = ExitPolicy(target_r=Decimal("1.5"), breakeven_trigger_r=Decimal("1.0"))
        outcome = run(env, bars, policy)
        trade = outcome.trade
        assert trade.outcome is TradeOutcome.STOP
        assert trade.exit_ts == bars[-1].ts
        assert trade.exit_price == Decimal("1.3341")  # breakeven mid - half spread
        # 595 units x (1.3341 - 1.3343) = -$0.12: spread cost only
        assert trade.pnl_usd == Decimal("-0.12")
        champion = run(env, bars, None)
        assert champion.trade.outcome is TradeOutcome.FLATTENED
        assert champion.trade.pnl_usd == Decimal("-0.54")

    def test_trail_never_acts_within_the_arming_bar(self, env: dict) -> None:
        # The SAME bar reaches +1R and collapses through the ORIGINAL stop.
        # Activation is next-bar by design (within-bar sequence is unknowable),
        # so the spike does not rescue the trade at breakeven: it takes the
        # full original-stop loss under same-bar stop priority.
        bars = [
            *ASIAN,
            TRIGGER,
            bar("08:30", "1.3341", "1.3383", "1.3301", "1.3310"),  # spike and collapse
        ]
        policy = ExitPolicy(target_r=Decimal("1.5"), breakeven_trigger_r=Decimal("1.0"))
        outcome = run(env, bars, policy)
        assert outcome.trade.outcome is TradeOutcome.STOP
        assert outcome.trade.exit_ts == bars[-1].ts
        assert outcome.trade.exit_price == Decimal("1.3301")  # original stop - half spread
        assert outcome.trade.pnl_usd == Decimal("-2.50")  # exactly the approved risk

    def test_stop_never_widens(self, env: dict) -> None:
        # With the trail armed, the effective stop is entry (1.3342) — never
        # below the original 1.3302 for a long (§0.7 invariant).
        bars = [
            *ASIAN,
            TRIGGER,
            bar("08:30", "1.3341", "1.3383", "1.3338", "1.3380"),
            bar("08:45", "1.3380", "1.3382", "1.3341", "1.3345"),  # touches 1.3342
        ]
        policy = ExitPolicy(target_r=Decimal("1.5"), breakeven_trigger_r=Decimal("1.0"))
        outcome = run(env, bars, policy)
        assert outcome.trade.exit_price >= Decimal("1.3301")


class TestTargetOverride:
    def test_one_r_target_resolves_where_champion_flattens(self, env: dict) -> None:
        # High of the session is 1.3383 = +1.02R: a 1.0R target (1.3382) fills,
        # while the champion's 1.5R (1.3402) would have flattened at 11:00.
        bars = [
            *ASIAN,
            TRIGGER,
            bar("08:30", "1.3341", "1.3383", "1.3338", "1.3380"),
            bar("10:45", "1.3380", "1.3381", "1.3350", "1.3355"),
        ]
        champion = run(env, bars, None)
        challenger = run(env, bars, ExitPolicy(target_r=Decimal("1.0")))
        assert champion.trade.outcome is TradeOutcome.FLATTENED
        assert challenger.trade.outcome is TradeOutcome.TARGET
        # exit 1.3382 - 0.0001 spread = 1.3381; 595 x 0.0038 = $2.26
        assert challenger.trade.pnl_usd == Decimal("2.26")

    def test_none_policy_identical_to_champion(self, env: dict) -> None:
        bars = [*ASIAN, TRIGGER, bar("08:30", "1.3341", "1.3405", "1.3338", "1.3400")]
        default = run(env, bars, None)
        explicit = run(env, bars, ExitPolicy(target_r=Decimal("1.5")))
        assert default.trade.pnl_usd == explicit.trade.pnl_usd == Decimal("3.45")
