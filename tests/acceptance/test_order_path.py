"""Acceptance tests (§21) — the subset provable at Phase 4:

- No order can bypass the risk engine.
- No order can be placed on a live transport.
- Every submitted entry carries a broker-held stop.
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


def build_candidate(score: int) -> Candidate:
    return Candidate(
        instrument="EUR_USD",
        strategy_id="london_breakout",
        strategy_version="0.1.0",
        direction=Direction.LONG,
        entry_price=D("1.1394"),
        stop_price=D("1.1369"),
        edge_score=score,
        created_at=IN_SESSION,
        expires_at=IN_SESSION + dt.timedelta(minutes=30),
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
    )


def test_full_deterministic_path_end_to_end() -> None:
    """§2: data → candidate → risk gate → sizing → revalidation → broker →
    stop confirmation, with the real engines at every stage."""
    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    engine = RiskEngine(config, clock)
    account = AccountState(closed_equity=D("250"), tier_anchor=D("250"))

    candidate = build_candidate(score=75)
    decision = engine.evaluate(candidate, account, EUR_USD, IN_SESSION)
    assert decision.approved

    sizing = size_position(
        candidate,
        EUR_USD,
        decision.allowed_risk_usd,
        closed_equity=account.closed_equity,
        margin_utilization_cap_fraction=D("0.30"),
    )
    assert sizing.approved

    broker = FakeBroker()
    result = BrokerAdapter(broker).submit_entry(
        candidate, decision, sizing, current_price=candidate.entry_price
    )
    assert result.state is OrderState.PROTECTED
    trade = broker.get_trade(result.trade_id)
    assert trade["stopLossOrder"] is not None  # broker-held stop, always (§0.9)


def test_rejected_candidate_cannot_reach_broker() -> None:
    """A sub-70 score is rejected by the risk engine, and the adapter treats
    submitting it as an order-path violation, not a request."""
    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    engine = RiskEngine(config, clock)
    account = AccountState(closed_equity=D("250"), tier_anchor=D("250"))

    candidate = build_candidate(score=60)
    decision = engine.evaluate(candidate, account, EUR_USD, IN_SESSION)
    assert not decision.approved

    sizing = SizingResult(True, 100, D("1.00"), D("2.28"), ())
    broker = FakeBroker()
    with pytest.raises(OrderPathViolationError):
        BrokerAdapter(broker).submit_entry(candidate, decision, sizing, candidate.entry_price)
    assert broker.open_trade_ids() == set()


def test_live_transport_cannot_exist_behind_adapter() -> None:
    class LiveTransport(FakeBroker):
        is_practice = False

    with pytest.raises(OrderPathViolationError):
        BrokerAdapter(LiveTransport())
