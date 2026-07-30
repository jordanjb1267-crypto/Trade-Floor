"""Failure-injection tests (§21) through the real adapter against the honest
fake broker. Regression coverage for 2026-07-30 review findings 0, 2, 9, 10,
11, 15, 17.
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
    InstrumentSpec,
    RiskDecision,
    SizingResult,
)
from trading_firm.reconciliation import (
    BrokerTradeRecord,
    LocalBook,
    StartupMode,
    reconcile,
    startup_mode,
)

D = Decimal
LONDON = ZoneInfo("Europe/London")
NOW = dt.datetime(2026, 7, 29, 8, 15, tzinfo=LONDON)
EUR_USD = InstrumentSpec(name="EUR_USD", margin_rate=D("0.02"))


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


def approvals(cand: Candidate) -> tuple[RiskDecision, SizingResult]:
    key = cand.content_key()
    return (
        RiskDecision(True, EdgeTier.STANDARD, D("2.50"), (), key),
        SizingResult(True, 595, D("2.49"), D("13.55"), (), key),
    )


def submit(adapter, broker_cand=None):
    cand = broker_cand or candidate()
    decision, sizing = approvals(cand)
    return adapter.submit_entry(cand, decision, sizing, EUR_USD, cand.entry_price, NOW)


def adapter_for(broker: FakeBroker) -> BrokerAdapter:
    return BrokerAdapter(broker, sleep_fn=lambda _s: None)


class TestTimeoutHandling:
    def test_timeout_before_landing_is_resubmit_safe_after_repeated_lookups(self) -> None:
        broker = FakeBroker()
        broker.inject_timeout()
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.UNKNOWN
        assert result.resubmit_safe
        assert broker.open_trade_ids() == set()

        retry = submit(adapter)
        assert retry.state is OrderState.PROTECTED
        assert len(broker.open_trade_ids()) == 1

    def test_timeout_after_landing_resolves_to_the_landed_order(self) -> None:
        # Finding 11: the genuinely dangerous timeout — the order filled but
        # the response was lost. The adapter must find it, never resubmit.
        broker = FakeBroker()
        broker.inject_timeout_after_landing()
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.PROTECTED
        assert "resolved at broker" in result.detail
        assert len(broker.open_trade_ids()) == 1

        # And an explicit retry still cannot double the position.
        retry = submit(adapter)
        assert retry.trade_id == result.trade_id
        assert len(broker.open_trade_ids()) == 1

    def test_lookup_failure_during_resolution_forbids_resubmit(self) -> None:
        # Finding 0: a failed lookup is NOT evidence of absence. skip=1 lets
        # the pre-submit lookup succeed so the failure hits the RESOLUTION
        # lookup after the timed-out create.
        broker = FakeBroker()
        broker.inject_timeout()
        broker.inject_lookup_failure(skip=1)
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.UNKNOWN
        assert not result.resubmit_safe
        assert "do NOT resubmit" in result.detail

    def test_presubmit_lookup_failure_blocks_submission(self) -> None:
        broker = FakeBroker()
        broker.inject_lookup_failure()
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.UNKNOWN
        assert broker.open_trade_ids() == set()


class TestStopFailureDrills:
    def test_transport_failure_during_stop_verification_is_stop_missing(self) -> None:
        # Finding 10: a live fill whose stop cannot be VERIFIED is treated as
        # a stop-loss failure — never an unhandled exception.
        broker = FakeBroker()
        broker.inject_get_trade_failure()
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.STOP_MISSING
        assert "verification unavailable" in result.detail

    def test_dropped_stop_then_emergency_flatten_reconciles(self) -> None:
        broker = FakeBroker()
        broker.inject_dropped_stop()
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.STOP_MISSING

        broker.close_trade(result.trade_id)  # §8.1: flatten immediately
        outcome = reconcile(
            LocalBook(closed_equity=D("250")),
            broker_trades=[BrokerTradeRecord.from_v20(t) for t in broker.open_trades()],
            broker_balance=D("250"),
        )
        assert outcome.clean
        assert startup_mode(outcome) is StartupMode.NORMAL


class TestFillIntegrity:
    def test_partial_fill_is_kill_switch_class(self) -> None:
        # Finding 9: §21 'Partial fill' — mismatch between sized and filled
        # units is surfaced, never reported as a clean PROTECTED position.
        broker = FakeBroker()
        broker.inject_partial_fill(300)
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.STOP_MISSING
        assert result.filled_units == 300
        assert "partial fill" in result.detail

    def test_margin_closeout_during_fill_pinned_to_stop_missing(self) -> None:
        # Finding 17: fill lands, broker closes the trade before verification.
        broker = FakeBroker()
        broker.inject_margin_closeout()
        adapter = adapter_for(broker)
        result = submit(adapter)
        assert result.state is OrderState.STOP_MISSING


class TestDesyncDrills:
    def test_hidden_broker_position_halts_startup(self) -> None:
        broker = FakeBroker()
        broker.inject_hidden_trade("9999", "GBP_USD", 100)
        outcome = reconcile(
            LocalBook(closed_equity=D("250")),
            broker_trades=[BrokerTradeRecord.from_v20(t) for t in broker.open_trades()],
            broker_balance=D("250"),
        )
        assert not outcome.entries_enabled
        assert startup_mode(outcome) is StartupMode.HALTED
