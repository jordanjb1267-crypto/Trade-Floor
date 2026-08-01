"""Alert severity, throttling, severe bypass, delivery gate, and invocation
budgets (§30.6, §30.15, §30.17 rows: alert throttling and severe-alert
bypass, materiality thresholds)."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.sessions import SessionClock
from trading_firm.surveillance.alerts import (
    SurveillanceAlertRecord,
    build_alerts,
    deliverable,
    severity_for,
)
from trading_firm.surveillance.budget import (
    BudgetState,
    InvocationBudget,
    fits_context,
    request_event_driven,
    request_scheduled,
)
from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    AlertSeverity,
    load_surveillance_config,
)
from trading_firm.surveillance.deduplication import decide
from trading_firm.surveillance.materiality import MaterialityAssessment
from trading_firm.surveillance.schemas import DataQualityStatus
from trading_firm.surveillance.state_builder import build_market_state

NOW = dt.datetime(2026, 7, 29, 8, 30, tzinfo=dt.UTC)
LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)


def record(
    severity: AlertSeverity = AlertSeverity.WATCH,
    change_type: str = "structure",
    content_hash: str = "abc123",
    ts: dt.datetime = NOW,
) -> SurveillanceAlertRecord:
    return SurveillanceAlertRecord(
        alert_id="alert.test",
        ts=ts,
        market_state_id="ms-1",
        severity=severity,
        change_type=change_type,
        what_changed="test",
        content_hash=content_hash,
        expires_at_utc=ts + dt.timedelta(minutes=30),
    )


class TestSeverityPolicy:
    def test_the_versioned_table_maps_change_classes(self) -> None:
        assert severity_for("regime.intraday: a -> b", DataQualityStatus.DEGRADED) is (
            AlertSeverity.MATERIAL
        )
        assert severity_for("spread: normal -> widened", DataQualityStatus.HEALTHY) is (
            AlertSeverity.WATCH
        )
        assert severity_for("first_state_of_session", DataQualityStatus.DEGRADED) is (
            AlertSeverity.INFO
        )

    def test_failed_data_quality_is_critical(self) -> None:
        assert severity_for(
            "data_quality: DataQualityStatus.DEGRADED -> DataQualityStatus.FAILED",
            DataQualityStatus.FAILED,
        ) is AlertSeverity.CRITICAL

    def test_build_alerts_one_per_material_change_content_hashed(self) -> None:
        clock = SessionClock(load_config(BASE_CONFIG_PATH).session)
        bars = tuple(
            Bar(
                instrument="GBP_USD",
                ts=dt.datetime.combine(DAY, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
                open=Decimal(o), high=Decimal(h), low=Decimal(lo), close=Decimal(c),
            )
            for hhmm, o, h, lo, c in (
                ("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
                ("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
                ("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
                ("06:45", "1.3320", "1.3330", "1.3312", "1.3326"),
                ("07:15", "1.3326", "1.3332", "1.3318", "1.3328"),
            )
        )
        state = build_market_state(
            instrument="GBP_USD",
            session_date=DAY,
            clock=clock,
            series=BarSeries(instrument="GBP_USD", granularity_minutes=15, bars=bars),
            spreads=None,
            permits=lambda fid: fid.startswith("session_features_v1."),
            config=load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH),
            configuration_version="test-cfg",
            as_of=NOW,
        )
        alerts = build_alerts(
            state, MaterialityAssessment(("first_state_of_session",)), NOW
        )
        assert len(alerts) == 1
        assert alerts[0].content_hash
        assert alerts[0].market_state_id == state.market_state_id


class TestThrottleAndSevereBypass:
    def test_new_content_emits(self) -> None:
        decision = decide(record(), {}, AlertSeverity.INFO)
        assert decision.should_emit

    def test_below_minimum_severity_does_not(self) -> None:
        decision = decide(record(severity=AlertSeverity.INFO), {}, AlertSeverity.WATCH)
        assert not decision.should_emit

    def test_state_change_only_suppresses_repeat_content(self) -> None:
        history = {record().content_hash: NOW - dt.timedelta(minutes=10)}
        decision = decide(record(), history, AlertSeverity.INFO)
        assert not decision.should_emit
        assert "state-change-only" in decision.reason

    def test_a_severe_alert_is_never_throttled(self) -> None:
        severe = record(severity=AlertSeverity.CRITICAL, change_type="data_quality")
        history = {severe.content_hash: NOW - dt.timedelta(minutes=10)}
        decision = decide(severe, history, AlertSeverity.INFO)
        assert decision.should_emit
        assert "§30.6" in decision.reason

    def test_but_an_exact_duplicate_within_the_window_collapses(self) -> None:
        severe = record(severity=AlertSeverity.CRITICAL, change_type="data_quality")
        history = {severe.content_hash: NOW - dt.timedelta(seconds=30)}
        decision = decide(severe, history, AlertSeverity.INFO)
        assert not decision.should_emit, "one event is one event, not two emergencies"

    def test_material_data_integrity_counts_as_severe(self) -> None:
        alert = record(
            severity=AlertSeverity.MATERIAL, change_type="news.unresolved_conflict"
        )
        assert alert.is_severe
        plain_material = record(severity=AlertSeverity.MATERIAL, change_type="regime.intraday")
        assert not plain_material.is_severe


class TestPhoneDeliveryGate:
    def test_the_shipped_config_delivers_severe_only_and_only_when_enabled(self) -> None:
        config = load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)
        material = record(severity=AlertSeverity.MATERIAL)
        info = record(severity=AlertSeverity.INFO)
        # Master switch off: nothing reaches the phone at all.
        assert not deliverable(material, config)
        assert not deliverable(info, config)

    def test_with_the_division_enabled_material_passes_info_does_not(self) -> None:
        import copy

        import yaml

        from trading_firm.surveillance.config import SurveillanceConfig

        raw = copy.deepcopy(
            yaml.safe_load(BASE_SURVEILLANCE_CONFIG_PATH.read_text())
        )["surveillance"]
        raw["enabled"] = True
        config = SurveillanceConfig.model_validate(raw)
        assert deliverable(record(severity=AlertSeverity.MATERIAL), config)
        assert deliverable(record(severity=AlertSeverity.CRITICAL), config)
        assert not deliverable(record(severity=AlertSeverity.WATCH), config)
        assert not deliverable(record(severity=AlertSeverity.INFO), config)


class TestInvocationBudget:
    BUDGET = InvocationBudget(
        max_scheduled_per_session=2,
        max_noncritical_event_driven_per_hour=2,
        minimum_materiality=AlertSeverity.MATERIAL,
        cooldown_seconds=300,
        max_context_bytes=100_000,
    )

    def test_scheduled_budget_exhausts(self) -> None:
        state = BudgetState()
        for _ in range(2):
            decision = request_scheduled(state, self.BUDGET, NOW)
            assert decision.may_invoke
            state = decision.state
        assert not request_scheduled(state, self.BUDGET, NOW).may_invoke

    def test_materiality_floor_blocks_noise(self) -> None:
        decision = request_event_driven(
            BudgetState(), self.BUDGET, NOW, AlertSeverity.WATCH
        )
        assert not decision.may_invoke
        assert "materiality" in decision.reason

    def test_cooldown_blocks_rapid_fire(self) -> None:
        first = request_event_driven(BudgetState(), self.BUDGET, NOW, AlertSeverity.MATERIAL)
        assert first.may_invoke
        second = request_event_driven(
            first.state, self.BUDGET, NOW + dt.timedelta(seconds=60), AlertSeverity.MATERIAL
        )
        assert not second.may_invoke and "cooldown" in second.reason

    def test_hourly_cap_exhausts_and_resets(self) -> None:
        state = BudgetState()
        at = NOW
        for _ in range(2):
            decision = request_event_driven(state, self.BUDGET, at, AlertSeverity.MATERIAL)
            assert decision.may_invoke
            state = decision.state
            at += dt.timedelta(minutes=10)
        exhausted = request_event_driven(state, self.BUDGET, at, AlertSeverity.MATERIAL)
        assert not exhausted.may_invoke
        assert "deterministic monitoring unaffected" in exhausted.reason
        next_hour = request_event_driven(
            exhausted.state, self.BUDGET, NOW + dt.timedelta(hours=2), AlertSeverity.MATERIAL
        )
        assert next_hour.may_invoke

    def test_critical_interpretation_is_outside_the_noncritical_budget(self) -> None:
        state = BudgetState(event_driven_this_hour=99, hour_started_at=NOW)
        decision = request_event_driven(
            state, self.BUDGET, NOW + dt.timedelta(seconds=1), AlertSeverity.CRITICAL
        )
        assert decision.may_invoke

    def test_context_size_limit(self) -> None:
        assert fits_context(50_000, self.BUDGET)
        assert not fits_context(200_000, self.BUDGET)

    def test_naive_time_rejected(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            request_event_driven(
                BudgetState(), self.BUDGET, NOW.replace(tzinfo=None), AlertSeverity.MATERIAL
            )
