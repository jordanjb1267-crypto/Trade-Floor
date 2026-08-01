"""The surveillance sweep (§30.9): observe-only flow, event recording,
severe-only delivery, and containment of persistence failures."""

import copy
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
import yaml

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.notify.surface import NotificationKind
from trading_firm.runner.schedule import ScheduledEvent, SessionEvent
from trading_firm.sessions import SessionClock
from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    SurveillanceConfig,
)
from trading_firm.surveillance.coordinator import Coordinator
from trading_firm.surveillance.state_builder import build_market_state

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)
NOW = dt.datetime.combine(DAY, dt.time(8, 30), tzinfo=LONDON)


def bar(hhmm: str, o: str, h: str, low: str, c: str) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(DAY, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o), high=Decimal(h), low=Decimal(low), close=Decimal(c),
    )


ASIAN = (
    bar("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    bar("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    bar("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    bar("06:45", "1.3320", "1.3330", "1.3312", "1.3326"),
    bar("07:15", "1.3326", "1.3332", "1.3318", "1.3328"),
)
BREAK_BAR = bar("08:00", "1.3330", "1.3350", "1.3328", "1.3348")


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


@pytest.fixture()
def enabled_config() -> SurveillanceConfig:
    raw = copy.deepcopy(
        yaml.safe_load(BASE_SURVEILLANCE_CONFIG_PATH.read_text())
    )["surveillance"]
    raw["enabled"] = True
    return SurveillanceConfig.model_validate(raw)


def scheduled(event=SessionEvent.ACTIVATION) -> ScheduledEvent:
    return ScheduledEvent(
        event=event,
        at=dt.datetime.combine(DAY, dt.time(8, 0), tzinfo=LONDON),
        session_date=DAY,
    )


class Fixture:
    def __init__(self, config, clock, extra_bars=()) -> None:
        self.sent: list[tuple[NotificationKind, str]] = []
        self.events: list = []
        self.clock = clock
        self.config = config
        self.bars = list(ASIAN) + list(extra_bars)
        self.as_of = NOW
        self.coordinator = Coordinator(
            config=config,
            build_state=self._build,
            record_event=self.events.append,
            notify=self._notify,
            now=lambda: self.as_of,
            configuration_version="test-cfg",
        )

    def _notify(self, kind, body) -> bool:
        self.sent.append((kind, body))
        return True

    def _build(self, event, prior):
        return build_market_state(
            instrument="GBP_USD",
            session_date=DAY,
            clock=self.clock,
            series=BarSeries(
                instrument="GBP_USD", granularity_minutes=15, bars=tuple(self.bars)
            ),
            spreads=None,
            permits=lambda fid: fid.startswith("session_features_v1."),
            config=self.config,
            configuration_version="test-cfg",
            as_of=self.as_of,
            prior=prior,
        )


class TestObserveOnlyFlow:
    def test_first_sweep_publishes_records_and_keeps_info_local(
        self, enabled_config, clock
    ) -> None:
        fixture = Fixture(enabled_config, clock)
        result = fixture.coordinator.run(scheduled())
        assert result.market_state_id is not None
        assert result.material_changes == 1  # first_state_of_session
        assert result.alerts_emitted == 1
        assert result.delivered_to_owner == 0, "INFO stays off the phone (severe-only)"
        event_types = [e.event_type.value for e in fixture.events]
        assert "market_state.published" in event_types
        assert "opportunity.material_change_detected" in event_types

    def test_an_unchanged_second_sweep_is_quiet(self, enabled_config, clock) -> None:
        fixture = Fixture(enabled_config, clock)
        fixture.coordinator.run(scheduled())
        second = fixture.coordinator.run(scheduled())
        assert second.material_changes == 0
        assert second.alerts_emitted == 0
        assert fixture.sent == []

    def test_a_material_change_is_delivered_severe_only(
        self, enabled_config, clock
    ) -> None:
        fixture = Fixture(enabled_config, clock)
        fixture.coordinator.run(scheduled())
        # A break of the Asian high arrives: structure change -> MATERIAL.
        fixture.bars.append(BREAK_BAR)
        fixture.as_of = NOW + dt.timedelta(minutes=15)
        result = fixture.coordinator.run(scheduled())
        assert result.material_changes >= 1
        assert result.delivered_to_owner == 1
        kind, body = fixture.sent[0]
        assert kind is NotificationKind.SURVEILLANCE_ALERT
        assert "structure" in body
        assert "BUY" not in body and "SELL" not in body

    def test_no_inputs_fails_closed_with_no_events(self, enabled_config, clock) -> None:
        fixture = Fixture(enabled_config, clock)
        fixture.coordinator._build_state = lambda event, prior: None
        result = fixture.coordinator.run(scheduled())
        assert result.market_state_id is None
        assert fixture.events == [] and fixture.sent == []

    def test_a_locked_outbox_does_not_stop_the_sweep(self, enabled_config, clock) -> None:
        fixture = Fixture(enabled_config, clock)

        def locked(event):
            raise RuntimeError("database is locked")

        fixture.coordinator._record_event = locked
        result = fixture.coordinator.run(scheduled())  # does not raise
        assert result.market_state_id is not None
