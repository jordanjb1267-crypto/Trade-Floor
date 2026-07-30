"""Failure-injection tests (§21): broker timeout, duplicate response,
rejected stop, broker/local position mismatch — driven through the real
adapter against the fake broker.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_firm.execution import BrokerAdapter, OrderState
from trading_firm.execution.fake import FakeBroker
from trading_firm.models import (
    Candidate,
    Direction,
    EdgeTier,
    RiskDecision,
    SizingResult,
)
from trading_firm.reconciliation import LocalBook, StartupMode, reconcile, startup_mode

D = Decimal
LONDON = ZoneInfo("Europe/London")
NOW = dt.datetime(2026, 7, 29, 8, 15, tzinfo=LONDON)

DECISION = RiskDecision(
    approved=True, tier=EdgeTier.STANDARD, allowed_risk_usd=D("2.50"), reasons=()
)
SIZING = SizingResult(
    approved=True,
    units=595,
    effective_risk_usd=D("2.49"),
    margin_required_usd=D("13.55"),
    reasons=(),
)


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


class TestTimeoutHandling:
    def test_timeout_before_landing_is_unknown_and_resubmit_safe(self) -> None:
        broker = FakeBroker()
        broker.inject_timeout()
        adapter = BrokerAdapter(broker)
        result = adapter.submit_entry(candidate(), DECISION, SIZING, D("1.1394"))
        assert result.state is OrderState.UNKNOWN
        assert result.resubmit_safe
        assert broker.open_trade_ids() == set()  # nothing landed

        # The documented recovery: one explicit resubmission, still one position.
        retry = adapter.submit_entry(candidate(), DECISION, SIZING, D("1.1394"))
        assert retry.state is OrderState.PROTECTED
        assert len(broker.open_trade_ids()) == 1

    def test_timeout_after_landing_adopts_existing_order(self) -> None:
        broker = FakeBroker()
        adapter = BrokerAdapter(broker)
        first = adapter.submit_entry(candidate(), DECISION, SIZING, D("1.1394"))
        assert first.state is OrderState.PROTECTED

        # The response was lost in transit the second time; the order already
        # exists at the broker. Adapter must adopt it, never double-submit.
        broker.inject_timeout()
        retry = adapter.submit_entry(candidate(), DECISION, SIZING, D("1.1394"))
        assert retry.state is OrderState.PROTECTED
        assert retry.trade_id == first.trade_id
        assert len(broker.open_trade_ids()) == 1


class TestStopFailureDrill:
    def test_dropped_stop_detected_then_emergency_flatten_reconciles(self) -> None:
        broker = FakeBroker()
        broker.inject_dropped_stop()
        adapter = BrokerAdapter(broker)
        result = adapter.submit_entry(candidate(), DECISION, SIZING, D("1.1394"))
        assert result.state is OrderState.STOP_MISSING

        # §8.1 stop-loss failure policy: flatten immediately at market.
        broker.close_trade(result.trade_id)
        reconciliation = reconcile(
            LocalBook(closed_equity=D("250")),
            broker_open_trade_ids=broker.open_trade_ids(),
            broker_balance=D("250"),
        )
        assert reconciliation.clean
        assert startup_mode(reconciliation) is StartupMode.NORMAL


class TestDesyncDrill:
    def test_position_appearing_at_broker_halts_startup(self) -> None:
        broker = FakeBroker()
        broker.inject_hidden_trade("9999", "GBP_USD", 100)
        reconciliation = reconcile(
            LocalBook(closed_equity=D("250")),
            broker_open_trade_ids=broker.open_trade_ids(),
            broker_balance=D("250"),
        )
        assert not reconciliation.entries_enabled
        assert startup_mode(reconciliation) is StartupMode.HALTED
