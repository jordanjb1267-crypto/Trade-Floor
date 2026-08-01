"""Thesis monitoring plans and the contradiction monitor (§30.10, §30.17
rows: Thesis Monitoring Plan validation, post-entry contradiction
classification)."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError
from surveillance_fixtures import state_kwargs

from trading_firm.surveillance.monitoring import (
    REGISTERED_POLICY_ACTIONS,
    ContradictionClass,
    Escalation,
    PositionContradiction,
    ThesisMonitoringPlan,
)
from trading_firm.surveillance.positions.contradiction import (
    OpenPositionView,
    condition_holds,
    evaluate,
)
from trading_firm.surveillance.schemas import (
    DataQuality,
    DataQualityStatus,
    MarketStateObject,
    SurveillanceRegime,
)

NOW = dt.datetime(2026, 7, 29, 8, 45, tzinfo=dt.UTC)
FLATTEN = dt.datetime(2026, 7, 29, 10, 0, tzinfo=dt.UTC)  # 11:00 London


def plan(**overrides) -> ThesisMonitoringPlan:
    base = dict(
        monitoring_plan_id="plan-1",
        candidate_id="candidate-1",
        schema_version="thesis_monitoring_plan_v1",
        expected_confirmations=["structure:break:asian_high"],
        acceptable_noise_conditions=["spread:normal"],
        soft_contradictions=["regime.intraday:TRANSITIONAL"],
        hard_invalidation_conditions=["structure:failed_break:asian_high"],
        time_expiration_utc=NOW + dt.timedelta(minutes=30),
        event_invalidation_rules=["macro.blackout_active"],
        execution_degradation_rules=["spread:widened"],
        data_health_rules=["data_quality:FAILED"],
        review_required_on_soft_contradiction=True,
        policy_actions=["record_contradiction", "escalate_cro"],
        flatten_boundary_utc=FLATTEN,
    )
    base.update(overrides)
    return ThesisMonitoringPlan(**base)


def position() -> OpenPositionView:
    return OpenPositionView(
        instrument="GBP_USD",
        direction="long",
        entry_price=Decimal("1.3345"),
        stop_price=Decimal("1.3320"),
        opened_at_utc=NOW - dt.timedelta(minutes=20),
    )


def state(structure="break:asian_high", **extra) -> MarketStateObject:
    kwargs = state_kwargs(**extra)
    kwargs["technical_state"] = kwargs["technical_state"].model_copy(
        update={"structure_state": structure}
    )
    return MarketStateObject(**kwargs).identified()


class TestPlanValidation:
    def test_a_valid_plan_registers(self) -> None:
        assert plan().monitoring_plan_id == "plan-1"

    def test_an_invented_exit_rule_is_unregistrable(self) -> None:
        with pytest.raises(ValidationError, match="invent a new exit rule"):
            plan(hard_invalidation_conditions=["close if it feels wrong"])

    def test_an_order_touching_action_has_no_name(self) -> None:
        for rogue in ("close_position", "widen_stop", "resize"):
            with pytest.raises(ValidationError, match="§30.10"):
                plan(policy_actions=[rogue])
        assert "close_position" not in REGISTERED_POLICY_ACTIONS

    def test_expiry_past_the_flatten_boundary_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError, match="F-5"):
            plan(time_expiration_utc=FLATTEN + dt.timedelta(minutes=5))

    def test_a_quiet_hard_invalidation_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError, match="CRO or the owner"):
            PositionContradiction(
                contradiction_id="c-1",
                monitoring_plan_id="plan-1",
                observed_at_utc=NOW,
                classification=ContradictionClass.HARD_INVALIDATION,
                escalation=Escalation.NONE,
                market_state_id="ms-1",
                evidence=["structure:failed_break:asian_high"],
            )


class TestEvaluationPrecedence:
    def test_confirmation_when_the_thesis_tracks(self) -> None:
        finding = evaluate(plan(), position(), state("break:asian_high"), NOW)
        assert finding.classification is ContradictionClass.CONFIRMATION
        assert finding.escalation is Escalation.NONE

    def test_noise_when_nothing_registered_matches(self) -> None:
        finding = evaluate(plan(), position(), state("inside_reference_range"), NOW)
        assert finding.classification is ContradictionClass.NOISE

    def test_a_failed_break_is_a_hard_invalidation_to_the_cro(self) -> None:
        finding = evaluate(plan(), position(), state("failed_break:asian_high"), NOW)
        assert finding.classification is ContradictionClass.HARD_INVALIDATION
        assert finding.escalation is Escalation.CRO
        assert finding.evidence == ["structure:failed_break:asian_high"]

    def test_soft_contradiction_escalates_when_review_is_required(self) -> None:
        kwargs = state_kwargs()
        kwargs["market_regime"] = kwargs["market_regime"].model_copy(
            update={"intraday": SurveillanceRegime.TRANSITIONAL}
        )
        soft_state = MarketStateObject(**kwargs).identified()
        finding = evaluate(plan(), position(), soft_state, NOW)
        assert finding.classification is ContradictionClass.SOFT_CONTRADICTION
        assert finding.escalation is Escalation.SENIOR_TRADERS

    def test_past_the_flatten_boundary_pages_the_owner(self) -> None:
        finding = evaluate(
            plan(), position(), state(), FLATTEN + dt.timedelta(minutes=1)
        )
        assert finding.classification is ContradictionClass.TIME_EXPIRED
        assert finding.escalation is Escalation.OWNER
        assert "inviolate" in finding.evidence[0]

    def test_failed_data_quality_outranks_the_market_reading(self) -> None:
        kwargs = state_kwargs()
        kwargs["data_quality"] = DataQuality(
            overall_status=DataQualityStatus.FAILED,
            stale_components=[],
            missing_components=["prices"],
            conflicting_components=[],
        )
        failed_state = MarketStateObject(**kwargs).identified()
        finding = evaluate(plan(), position(), failed_state, NOW)
        assert finding.classification is ContradictionClass.DATA_HEALTH
        assert finding.escalation is Escalation.CRO

    def test_plan_expiry_before_flatten_goes_to_the_senior_traders(self) -> None:
        finding = evaluate(
            plan(), position(), state("inside_reference_range"),
            NOW + dt.timedelta(minutes=31),
        )
        assert finding.classification is ContradictionClass.TIME_EXPIRED
        assert finding.escalation is Escalation.SENIOR_TRADERS


class TestConditionMatcher:
    def test_matches_only_the_registered_vocabulary(self) -> None:
        s = state("break:asian_high")
        assert condition_holds("structure:break:asian_high", s)
        assert not condition_holds("structure:break:prior_high", s)
        assert not condition_holds("my_new_rule", s)

    def test_the_view_stays_narrow(self) -> None:
        view = position()
        for forbidden in ("equity", "pnl", "realized", "balance"):
            assert not any(forbidden in attr for attr in vars(view)), (
                "OpenPositionView must carry identity and protective structure "
                "only (§30.10)"
            )
