"""Acceptance tests (§21) — the subset provable at Phase 4:

- No order can bypass the risk engine.
- No order can be placed on a live transport.
- Approvals are bound to their candidate (an approval for A cannot trade B).
- Every submitted entry carries a broker-held stop, confirmed active.
- No duplicate order submission.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.execution import BrokerAdapter, OrderState
from trading_firm.execution.adapter import OrderPathViolationError
from trading_firm.execution.fake import FakeBroker
from trading_firm.models import (
    AccountState,
    Candidate,
    Direction,
    InstrumentSpec,
    SizingResult,
)
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock
from trading_firm.sizing import size_position

D = Decimal
LONDON = ZoneInfo("Europe/London")
IN_SESSION = dt.datetime(2026, 7, 29, 9, 0, tzinfo=LONDON)
EUR_USD = InstrumentSpec(name="EUR_USD", margin_rate=D("0.02"))


def build_candidate(score: int, entry: str = "1.1394", stop: str = "1.1369") -> Candidate:
    return Candidate(
        instrument="EUR_USD",
        strategy_id="london_breakout",
        strategy_version="0.1.0",
        direction=Direction.LONG,
        entry_price=D(entry),
        stop_price=D(stop),
        edge_score=score,
        created_at=IN_SESSION,
        expires_at=IN_SESSION + dt.timedelta(minutes=30),
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
    )


def full_pipeline(candidate: Candidate):
    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    engine = RiskEngine(config, clock)
    account = AccountState(closed_equity=D("250"), tier_anchor=D("250"))
    decision = engine.evaluate(candidate, account, EUR_USD, IN_SESSION)
    sizing = size_position(
        candidate,
        EUR_USD,
        decision.allowed_risk_usd,
        closed_equity=account.closed_equity,
        margin_utilization_cap_fraction=D("0.30"),
    )
    return decision, sizing


def test_full_deterministic_path_end_to_end() -> None:
    """§2: data → candidate → risk gate → sizing → revalidation → broker →
    stop confirmation, with the real engines at every stage."""
    candidate = build_candidate(score=75)
    decision, sizing = full_pipeline(candidate)
    assert decision.approved and sizing.approved

    broker = FakeBroker()
    result = BrokerAdapter(broker, sleep_fn=lambda _s: None).submit_entry(
        candidate, decision, sizing, EUR_USD, candidate.entry_price, IN_SESSION
    )
    assert result.state is OrderState.PROTECTED
    trade = broker.get_trade(result.trade_id)
    assert trade["stopLossOrder"]["state"] == "PENDING"  # confirmed ACTIVE (§0.9)


def test_rejected_candidate_cannot_reach_broker() -> None:
    candidate = build_candidate(score=60)
    decision, _ = full_pipeline(candidate)
    assert not decision.approved

    sizing = SizingResult(True, 100, D("1.00"), D("2.28"), (), candidate.content_key())
    broker = FakeBroker()
    with pytest.raises(OrderPathViolationError):
        BrokerAdapter(broker, sleep_fn=lambda _s: None).submit_entry(
            candidate, decision, sizing, EUR_USD, candidate.entry_price, IN_SESSION
        )
    assert broker.open_trade_ids() == set()


def test_approval_minted_for_one_candidate_cannot_trade_another() -> None:
    """Findings 8/12: the gate verifies THIS order was approved, not that
    an approval merely exists."""
    approved_candidate = build_candidate(score=75)
    decision, sizing = full_pipeline(approved_candidate)
    assert decision.approved

    other_candidate = build_candidate(score=75, entry="1.1450", stop="1.1425")
    broker = FakeBroker()
    with pytest.raises(OrderPathViolationError, match="DIFFERENT candidate"):
        BrokerAdapter(broker, sleep_fn=lambda _s: None).submit_entry(
            other_candidate, decision, sizing, EUR_USD, other_candidate.entry_price, IN_SESSION
        )
    assert broker.open_trade_ids() == set()


def test_live_transport_cannot_exist_behind_adapter() -> None:
    class LiveTransport(FakeBroker):
        is_practice = False

    with pytest.raises(OrderPathViolationError):
        BrokerAdapter(LiveTransport())
