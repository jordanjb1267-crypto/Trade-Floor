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
from trading_firm.models import Direction, InstrumentSpec
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
        # With the trail armed the effective stop is the entry (1.3342), so a
        # dip to 1.3341 exits AT breakeven rather than riding to the original
        # 1.3302 (§0.7). Asserted by exact value: the previous `>= 1.3301`
        # bound was tautological — the arrangement satisfied it whether or not
        # the trail did anything.
        bars = [
            *ASIAN,
            TRIGGER,
            bar("08:30", "1.3341", "1.3383", "1.3338", "1.3380"),
            bar("08:45", "1.3380", "1.3382", "1.3341", "1.3345"),  # touches 1.3342
        ]
        policy = ExitPolicy(target_r=Decimal("1.5"), breakeven_trigger_r=Decimal("1.0"))
        trade = run(env, bars, policy).trade
        assert trade.outcome is TradeOutcome.STOP
        assert trade.exit_ts == bars[-1].ts
        assert trade.exit_price == Decimal("1.3341")  # entry 1.3342 - half spread
        assert trade.pnl_usd == Decimal("-0.12")  # spread only
        # and the untrailed champion on the same bars does NOT stop out here
        assert run(env, bars, None).trade.outcome is not TradeOutcome.STOP


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


class TestShortSideExits:
    """The SHORT half of ExitPolicy had no coverage at all: sign flips and
    max/min swaps in the short target/trail arithmetic survived the suite.

    Mirror session: Asian range 1.3300-1.3340, SHORT trigger 1.3298, stop
    1.3338 (40-pip risk).
    """

    SHORT_TRIGGER = bar("08:15", "1.3305", "1.3320", "1.3297", "1.3299")

    def test_short_target_override_resolves(self, env: dict) -> None:
        bars = [
            *ASIAN,
            self.SHORT_TRIGGER,
            bar("08:30", "1.3299", "1.3300", "1.3256", "1.3260"),  # 1.0R = 1.3258
        ]
        outcome = run(env, bars, ExitPolicy(target_r=Decimal("1.0")))
        trade = outcome.trade
        assert trade.direction is Direction.SHORT
        assert trade.outcome is TradeOutcome.TARGET
        # short exits by buying: target + half spread
        assert trade.exit_price == Decimal("1.3259")
        assert trade.pnl_usd > 0

    def test_short_breakeven_trail_exits_at_entry(self, env: dict) -> None:
        # Falls to +1R (1.3258) arming the trail, then rallies back through
        # entry: the trail must exit at breakeven, not ride to the 1.3338 stop.
        bars = [
            *ASIAN,
            self.SHORT_TRIGGER,
            bar("08:30", "1.3299", "1.3300", "1.3256", "1.3260"),  # arms
            bar("08:45", "1.3260", "1.3310", "1.3258", "1.3305"),  # back through entry
        ]
        policy = ExitPolicy(target_r=Decimal("2.0"), breakeven_trigger_r=Decimal("1.0"))
        trade = run(env, bars, policy).trade
        assert trade.outcome is TradeOutcome.STOP
        assert trade.exit_ts == bars[-1].ts
        assert trade.exit_price == Decimal("1.3299")  # entry 1.3298 + half spread
        assert -trade.pnl_usd < trade.allowed_risk_usd  # spread only, not full risk

    def test_short_trail_only_tightens(self, env: dict) -> None:
        # With the trail armed, the effective stop is the entry (1.3298) —
        # never back out to the original 1.3338 (§0.7).
        bars = [
            *ASIAN,
            self.SHORT_TRIGGER,
            bar("08:30", "1.3299", "1.3300", "1.3256", "1.3260"),
            bar("08:45", "1.3260", "1.3299", "1.3258", "1.3290"),  # touches entry
        ]
        policy = ExitPolicy(target_r=Decimal("2.0"), breakeven_trigger_r=Decimal("1.0"))
        trade = run(env, bars, policy).trade
        assert trade.exit_price <= Decimal("1.3299")


class TestSameBarStopPriority:
    """A bar containing BOTH stop and target must resolve as STOP — the
    engine's core conservative-fill invariant, previously unpinned: swapping
    the check order left every test green.
    """

    def test_stop_wins_when_one_bar_holds_both(self, env: dict) -> None:
        bars = [
            *ASIAN,
            TRIGGER,
            # spans 1.3302 stop AND the 1.5R target 1.3402 in a single bar
            bar("08:30", "1.3341", "1.3410", "1.3295", "1.3400"),
        ]
        trade = run(env, bars, None).trade
        assert trade.outcome is TradeOutcome.STOP
        assert trade.pnl_usd == Decimal("-2.50")  # full approved risk, not a win

    def test_stop_priority_holds_for_shorts(self, env: dict) -> None:
        short_trigger = bar("08:15", "1.3305", "1.3320", "1.3297", "1.3299")
        bars = [
            *ASIAN,
            short_trigger,
            bar("08:30", "1.3299", "1.3345", "1.3230", "1.3240"),  # stop 1.3338 + target
        ]
        trade = run(env, bars, None).trade
        assert trade.outcome is TradeOutcome.STOP
