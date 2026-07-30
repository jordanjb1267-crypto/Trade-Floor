"""Broker adapter tests (§2 order path, §8.1): guards, approval binding,
idempotency without collisions, revalidation, strict stop confirmation.
Regression coverage for 2026-07-30 review findings 1, 6, 7, 8, 12, 16, 18, 20.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.execution import BrokerAdapter, OrderState
from trading_firm.execution.adapter import OrderPathViolationError, client_order_id_for
from trading_firm.execution.fake import FakeBroker
from trading_firm.models import (
    Candidate,
    Direction,
    EdgeTier,
    InstrumentSpec,
    RiskDecision,
    SizingResult,
)

D = Decimal
LONDON = ZoneInfo("Europe/London")
NOW = dt.datetime(2026, 7, 29, 8, 15, tzinfo=LONDON)
EUR_USD = InstrumentSpec(name="EUR_USD", margin_rate=D("0.02"))
USD_JPY = InstrumentSpec(name="USD_JPY", margin_rate=D("0.04"), pip_location=-2)


def candidate(**overrides) -> Candidate:
    fields = {
        "instrument": "EUR_USD",
        "strategy_id": "london_breakout",
        "strategy_version": "0.1.0",
        "direction": Direction.LONG,
        "entry_price": D("1.1394"),
        "stop_price": D("1.1369"),
        "edge_score": 75,
        "created_at": NOW,
        "expires_at": NOW + dt.timedelta(hours=2),
        "data_fresh": True,
        "news_state_known": True,
        "stop_broker_compatible": True,
    }
    fields.update(overrides)
    return Candidate(**fields)


def approvals(cand: Candidate, units: int = 595) -> tuple[RiskDecision, SizingResult]:
    key = cand.content_key()
    decision = RiskDecision(
        approved=True, tier=EdgeTier.STANDARD, allowed_risk_usd=D("2.50"),
        reasons=(), candidate_key=key,
    )
    sizing = SizingResult(
        approved=True, units=units, effective_risk_usd=D("2.49"),
        margin_required_usd=D("13.55"), reasons=(), candidate_key=key,
    )
    return decision, sizing


def adapter_for(broker: FakeBroker) -> BrokerAdapter:
    return BrokerAdapter(broker, sleep_fn=lambda _s: None)


def submit(adapter, cand, decision, sizing, spec=EUR_USD, price=None, now=NOW):
    return adapter.submit_entry(cand, decision, sizing, spec, price or cand.entry_price, now)


class TestOrderPathGuards:
    def test_unapproved_risk_decision_is_a_violation(self) -> None:
        cand = candidate()
        decision, sizing = approvals(cand)
        rejected = RiskDecision(
            approved=False, tier=EdgeTier.NONE, allowed_risk_usd=D("0"),
            reasons=("nope",), candidate_key=cand.content_key(),
        )
        with pytest.raises(OrderPathViolationError, match="risk decision"):
            submit(adapter_for(FakeBroker()), cand, rejected, sizing)

    def test_unapproved_sizing_is_a_violation(self) -> None:
        cand = candidate()
        decision, _ = approvals(cand)
        bad = SizingResult(False, 0, D("0"), D("0"), ("no",), cand.content_key())
        with pytest.raises(OrderPathViolationError, match="sizing"):
            submit(adapter_for(FakeBroker()), cand, decision, bad)

    def test_approval_for_different_candidate_is_a_violation(self) -> None:
        # Findings 8/12: approvals are BOUND to their candidate.
        cand_a = candidate()
        cand_b = candidate(entry_price=D("1.1450"), stop_price=D("1.1425"))
        decision_a, sizing_a = approvals(cand_a)
        with pytest.raises(OrderPathViolationError, match="DIFFERENT candidate"):
            submit(adapter_for(FakeBroker()), cand_b, decision_a, sizing_a)

    def test_expired_candidate_is_a_violation(self) -> None:
        cand = candidate()
        decision, sizing = approvals(cand)
        late = cand.expires_at + dt.timedelta(minutes=1)
        with pytest.raises(OrderPathViolationError, match="expired"):
            submit(adapter_for(FakeBroker()), cand, decision, sizing, now=late)

    def test_sizing_above_approved_risk_is_a_violation(self) -> None:
        cand = candidate()
        decision, _ = approvals(cand)
        oversized = SizingResult(
            approved=True, units=50_000, effective_risk_usd=D("125.00"),
            margin_required_usd=D("1139.40"), reasons=(), candidate_key=cand.content_key(),
        )
        with pytest.raises(OrderPathViolationError, match="exceeds approved"):
            submit(adapter_for(FakeBroker()), cand, decision, oversized)

    def test_live_transport_refused_at_construction(self) -> None:
        class LiveBroker(FakeBroker):
            is_practice = False

        with pytest.raises(OrderPathViolationError, match="live transport refused"):
            BrokerAdapter(LiveBroker())

    def test_transport_turning_live_refused_at_submit(self) -> None:
        # Finding 20: is_practice is re-asserted on every call.
        broker = FakeBroker()
        adapter = adapter_for(broker)
        cand = candidate()
        decision, sizing = approvals(cand)
        broker.is_practice = False
        with pytest.raises(OrderPathViolationError):
            submit(adapter, cand, decision, sizing)


class TestSubmission:
    def test_happy_path_fills_and_confirms_stop(self) -> None:
        broker = FakeBroker()
        cand = candidate()
        decision, sizing = approvals(cand)
        result = submit(adapter_for(broker), cand, decision, sizing)
        assert result.state is OrderState.PROTECTED
        assert result.filled_units == 595
        trade = broker.get_trade(result.trade_id)
        assert trade["stopLossOrder"] == {"price": "1.1369", "state": "PENDING"}

    def test_short_direction_sends_negative_units(self) -> None:
        broker = FakeBroker()
        cand = candidate(direction=Direction.SHORT, stop_price=D("1.1419"))
        decision, sizing = approvals(cand)
        result = submit(adapter_for(broker), cand, decision, sizing)
        assert broker.get_trade(result.trade_id)["currentUnits"] == "-595"

    def test_revalidation_aborts_on_price_drift(self) -> None:
        broker = FakeBroker()
        cand = candidate()
        decision, sizing = approvals(cand)
        result = submit(
            adapter_for(broker), cand, decision, sizing, price=D("1.1394") + D("0.0003")
        )
        assert result.state is OrderState.REJECTED
        assert "revalidation" in result.detail
        assert broker.open_trade_ids() == set()

    def test_revalidation_tolerance_scales_with_instrument_pips(self) -> None:
        # Finding 7: 0.01 on USD_JPY is one pip — inside a 2-pip tolerance.
        broker = FakeBroker()
        cand = candidate(
            instrument="USD_JPY", entry_price=D("155.00"), stop_price=D("154.50")
        )
        decision, sizing = approvals(cand)
        result = submit(
            adapter_for(broker), cand, decision, sizing, spec=USD_JPY, price=D("155.01")
        )
        assert result.state is OrderState.PROTECTED

    def test_broker_rejection_reported(self) -> None:
        broker = FakeBroker()
        broker.inject_reject("INSUFFICIENT_MARGIN")
        cand = candidate()
        decision, sizing = approvals(cand)
        result = submit(adapter_for(broker), cand, decision, sizing)
        assert result.state is OrderState.REJECTED
        assert "INSUFFICIENT_MARGIN" in result.detail


class TestStopConfirmation:
    def test_dropped_stop_is_stop_missing(self) -> None:
        broker = FakeBroker()
        broker.inject_dropped_stop()
        cand = candidate()
        decision, sizing = approvals(cand)
        result = submit(adapter_for(broker), cand, decision, sizing)
        assert result.state is OrderState.STOP_MISSING
        assert "kill-switch" in result.detail

    def test_inactive_stop_state_is_stop_missing(self) -> None:
        # Finding 16: price match alone is not confirmation.
        broker = FakeBroker()
        broker.inject_stop_state("CANCELLED")
        cand = candidate()
        decision, sizing = approvals(cand)
        result = submit(adapter_for(broker), cand, decision, sizing)
        assert result.state is OrderState.STOP_MISSING
        assert "not active" in result.detail

    def test_wrong_stop_price_is_stop_missing(self) -> None:
        broker = FakeBroker()
        broker.inject_stop_price("1.1300")
        cand = candidate()
        decision, sizing = approvals(cand)
        result = submit(adapter_for(broker), cand, decision, sizing)
        assert result.state is OrderState.STOP_MISSING
        assert "1.1300" in result.detail


class TestIdempotencyWithoutCollisions:
    def test_same_candidate_never_creates_two_positions(self) -> None:
        broker = FakeBroker()
        adapter = adapter_for(broker)
        cand = candidate()
        decision, sizing = approvals(cand)
        first = submit(adapter, cand, decision, sizing)
        second = submit(adapter, cand, decision, sizing)
        assert first.trade_id == second.trade_id
        assert "duplicate" in second.detail
        assert len(broker.open_trade_ids()) == 1

    def test_distinct_same_day_candidates_do_not_collide(self) -> None:
        # Finding 1/18: a revised re-entry the same day is a DIFFERENT order.
        broker = FakeBroker()
        adapter = adapter_for(broker)
        cand_a = candidate()
        cand_b = candidate(
            entry_price=D("1.1450"),
            stop_price=D("1.1425"),
            created_at=NOW + dt.timedelta(hours=1),
        )
        result_a = submit(adapter, cand_a, *approvals(cand_a))
        result_b = submit(
            adapter, cand_b, *approvals(cand_b), price=cand_b.entry_price
        )
        assert client_order_id_for(cand_a) != client_order_id_for(cand_b)
        assert result_a.state is OrderState.PROTECTED
        assert result_b.state is OrderState.PROTECTED
        assert result_a.trade_id != result_b.trade_id
        assert len(broker.open_trade_ids()) == 2

    def test_client_id_deterministic(self) -> None:
        assert client_order_id_for(candidate()) == client_order_id_for(candidate())
