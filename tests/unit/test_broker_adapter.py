"""Broker adapter tests (§2 order path, §8.1): guards, idempotency,
revalidation, stop confirmation."""

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
    RiskDecision,
    SizingResult,
)

D = Decimal
LONDON = ZoneInfo("Europe/London")
NOW = dt.datetime(2026, 7, 29, 8, 15, tzinfo=LONDON)


def candidate() -> Candidate:
    return Candidate(
        instrument="EUR_USD",
        strategy_id="london_breakout",
        strategy_version="0.1.0",
        direction=Direction.LONG,
        entry_price=D("1.1394"),
        stop_price=D("1.1369"),
        edge_score=75,
        created_at=NOW,
        expires_at=NOW + dt.timedelta(hours=2),
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
    )


APPROVED_DECISION = RiskDecision(
    approved=True, tier=EdgeTier.STANDARD, allowed_risk_usd=D("2.50"), reasons=()
)
APPROVED_SIZING = SizingResult(
    approved=True,
    units=595,
    effective_risk_usd=D("2.49"),
    margin_required_usd=D("13.55"),
    reasons=(),
)
REJECTED_DECISION = RiskDecision(
    approved=False, tier=EdgeTier.NONE, allowed_risk_usd=D("0"), reasons=("nope",)
)


class TestOrderPathGuards:
    def test_unapproved_risk_decision_is_a_violation(self) -> None:
        adapter = BrokerAdapter(FakeBroker())
        with pytest.raises(OrderPathViolationError, match="risk decision"):
            adapter.submit_entry(candidate(), REJECTED_DECISION, APPROVED_SIZING, D("1.1394"))

    def test_unapproved_sizing_is_a_violation(self) -> None:
        adapter = BrokerAdapter(FakeBroker())
        bad_sizing = SizingResult(False, 0, D("0"), D("0"), ("no",))
        with pytest.raises(OrderPathViolationError, match="sizing"):
            adapter.submit_entry(candidate(), APPROVED_DECISION, bad_sizing, D("1.1394"))

    def test_live_transport_refused_at_construction(self) -> None:
        class LiveBroker(FakeBroker):
            is_practice = False

        with pytest.raises(OrderPathViolationError, match="live transport refused"):
            BrokerAdapter(LiveBroker())


class TestSubmission:
    def test_happy_path_fills_and_confirms_stop(self) -> None:
        broker = FakeBroker()
        adapter = BrokerAdapter(broker)
        result = adapter.submit_entry(candidate(), APPROVED_DECISION, APPROVED_SIZING, D("1.1394"))
        assert result.state is OrderState.PROTECTED
        assert result.trade_id is not None
        trade = broker.get_trade(result.trade_id)
        assert trade["stopLossOrder"]["price"] == "1.1369"  # broker-held stop (§0.9)
        assert trade["currentUnits"] == "595"

    def test_short_direction_sends_negative_units(self) -> None:
        broker = FakeBroker()
        adapter = BrokerAdapter(broker)
        short = Candidate(
            **{
                **candidate().__dict__,
                "direction": Direction.SHORT,
                "stop_price": D("1.1419"),
            }
        )
        result = adapter.submit_entry(short, APPROVED_DECISION, APPROVED_SIZING, D("1.1394"))
        assert broker.get_trade(result.trade_id)["currentUnits"] == "-595"

    def test_revalidation_aborts_on_price_drift(self) -> None:
        broker = FakeBroker()
        adapter = BrokerAdapter(broker)
        drifted = D("1.1394") + D("0.0003")  # 3 pips > 2-pip tolerance (N-13)
        result = adapter.submit_entry(candidate(), APPROVED_DECISION, APPROVED_SIZING, drifted)
        assert result.state is OrderState.REJECTED
        assert "revalidation" in result.detail
        assert broker.open_trade_ids() == set()  # nothing reached the broker

    def test_broker_rejection_reported(self) -> None:
        broker = FakeBroker()
        broker.inject_reject("INSUFFICIENT_MARGIN")
        adapter = BrokerAdapter(broker)
        result = adapter.submit_entry(candidate(), APPROVED_DECISION, APPROVED_SIZING, D("1.1394"))
        assert result.state is OrderState.REJECTED
        assert "INSUFFICIENT_MARGIN" in result.detail

    def test_dropped_stop_is_stop_missing_alarm(self) -> None:
        broker = FakeBroker()
        broker.inject_dropped_stop()
        adapter = BrokerAdapter(broker)
        result = adapter.submit_entry(candidate(), APPROVED_DECISION, APPROVED_SIZING, D("1.1394"))
        assert result.state is OrderState.STOP_MISSING
        assert "kill-switch" in result.detail


class TestIdempotency:
    def test_same_candidate_never_creates_two_positions(self) -> None:
        broker = FakeBroker()
        adapter = BrokerAdapter(broker)
        first = adapter.submit_entry(candidate(), APPROVED_DECISION, APPROVED_SIZING, D("1.1394"))
        second = adapter.submit_entry(candidate(), APPROVED_DECISION, APPROVED_SIZING, D("1.1394"))
        assert first.trade_id == second.trade_id
        assert "duplicate" in second.detail
        assert len(broker.open_trade_ids()) == 1

    def test_client_id_deterministic(self) -> None:
        assert client_order_id_for(candidate()) == client_order_id_for(candidate())
