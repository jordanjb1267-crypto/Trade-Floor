"""Replay-scale surveillance properties (§30.17 replay rows).

The one that matters most: existing strategy results remain unchanged while
influence flags are disabled — the golden replay. It is nearly tautological
today because nothing couples surveillance into replay, and pinning it is
the point: the day someone wires influence in, this test is the tripwire
that makes it a reviewed rollout step instead of a drift.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest

from tests.unit.test_replay import build_series
from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.models import InstrumentSpec
from trading_firm.research import replay_range, tradeable_session_dates
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.strategies import load_manifests
from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    load_surveillance_config,
)
from trading_firm.surveillance.state_builder import build_market_state

LONDON = ZoneInfo("Europe/London")


@pytest.fixture(scope="module")
def env() -> dict:
    """Same environment as tests/unit/test_replay.py — the same synthetic
    five-day series, so the golden comparison is against the known replay."""
    from decimal import Decimal

    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    return {
        "config": config,
        "clock": clock,
        "engine": RiskEngine(config, clock),
        "manifest": load_manifests(
            BASE_CONFIG_PATH.parents[1] / "research" / "strategies"
        )["london_breakout"],
        "spec": InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05")),
        "series": build_series(),
    }


def _replay(env):
    series = env["series"]
    days = tradeable_session_dates(series, env["clock"])
    return replay_range(
        series,
        days,
        config=env["config"],
        clock=env["clock"],
        engine=env["engine"],
        manifest=env["manifest"],
        spec=env["spec"],
    )


def _sweep_all_days(env) -> list[str]:
    """Run observe-only state builds across every session day, mid-session."""
    surveillance = load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)
    ids = []
    for day in tradeable_session_dates(env["series"], env["clock"]):
        state = build_market_state(
            instrument="GBP_USD",
            session_date=day,
            clock=env["clock"],
            series=env["series"],
            spreads=None,
            permits=lambda fid: fid.startswith("session_features_v1."),
            config=surveillance,
            configuration_version="replay-test",
            as_of=dt.datetime.combine(day, dt.time(9, 0), tzinfo=LONDON),
        )
        state.verify(state.market_state_id)
        ids.append(state.market_state_id)
    return ids


class TestGoldenReplay:
    def test_strategy_results_identical_with_surveillance_observing(self, env) -> None:
        before = _replay(env)
        state_ids = _sweep_all_days(env)
        assert len(state_ids) >= 4, "the sweep must actually have run"
        after = _replay(env)
        assert before.outcomes == after.outcomes, (
            "observe-only surveillance changed a replay outcome — the influence "
            "flags are off, so this is the regression §30.17 exists to catch"
        )
        assert before.net_pnl_usd == after.net_pnl_usd

    def test_states_are_reproducible_across_passes(self, env) -> None:
        # §30.1 rule 10 at replay scale: same stored inputs, same identities.
        assert _sweep_all_days(env) == _sweep_all_days(env)


class TestNoLookAheadAtReplayScale:
    @pytest.mark.parametrize("hhmm", ["08:30", "09:30", "10:30"])
    def test_a_state_never_sees_past_its_build_moment(self, env, hhmm) -> None:
        """Build over the full multi-day series vs over a series truncated at
        as_of: identical identity, on real replay data shapes."""
        surveillance = load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)
        day = dt.date(2026, 7, 29)
        as_of = dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON)
        series = env["series"]
        truncated = type(series)(
            instrument=series.instrument,
            granularity_minutes=series.granularity_minutes,
            bars=tuple(b for b in series.bars if b.ts < as_of),
        )

        def build(with_series):
            return build_market_state(
                instrument="GBP_USD",
                session_date=day,
                clock=env["clock"],
                series=with_series,
                spreads=None,
                permits=lambda fid: fid.startswith("session_features_v1."),
                config=surveillance,
                configuration_version="replay-test",
                as_of=as_of,
            ).market_state_id

        assert build(series) == build(truncated)


class TestAlertVolumeStaysManageable:
    def test_a_full_session_of_sweeps_emits_a_bounded_alert_count(self, env) -> None:
        """§30.17: alert volume remains manageable. Sweep every 15 minutes
        through a session with a real breakout; state-change-only discipline
        must keep emissions to the changes, not the sweeps."""
        import copy

        import yaml

        from trading_firm.runner.schedule import ScheduledEvent, SessionEvent
        from trading_firm.surveillance.config import SurveillanceConfig
        from trading_firm.surveillance.coordinator import Coordinator

        raw = copy.deepcopy(
            yaml.safe_load(BASE_SURVEILLANCE_CONFIG_PATH.read_text())
        )["surveillance"]
        raw["enabled"] = True
        config = SurveillanceConfig.model_validate(raw)
        day = dt.date(2026, 7, 29)
        moments = [
            dt.datetime.combine(day, dt.time(8, 0), tzinfo=LONDON) + dt.timedelta(minutes=15 * i)
            for i in range(12)  # 08:00 .. 10:45
        ]
        current = {"as_of": moments[0]}

        def build(scheduled, prior):
            return build_market_state(
                instrument="GBP_USD",
                session_date=day,
                clock=env["clock"],
                series=env["series"],
                spreads=None,
                permits=lambda fid: fid.startswith("session_features_v1."),
                config=config,
                configuration_version="replay-test",
                as_of=current["as_of"],
                prior=prior,
            )

        coordinator = Coordinator(
            config=config,
            build_state=build,
            record_event=lambda e: None,
            notify=lambda kind, body: True,
            now=lambda: current["as_of"],
            configuration_version="replay-test",
        )
        emitted = 0
        for moment in moments:
            current["as_of"] = moment
            result = coordinator.run(
                ScheduledEvent(event=SessionEvent.ACTIVATION, at=moment, session_date=day)
            )
            emitted += result.alerts_emitted
        assert emitted <= 6, (
            f"{emitted} alerts from 12 sweeps of one session: state-change-only "
            f"discipline failed (§30.6, §30.17)"
        )
        assert emitted >= 1, "a session with a real breakout produced no alert at all"
