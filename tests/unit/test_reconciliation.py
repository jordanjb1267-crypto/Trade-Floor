"""Reconciler tests (§8.1, §18): broker authoritative, fail closed on every
mismatch class — including §18 step 4 stop verification.
Regression coverage for 2026-07-30 review findings 4, 13, 14, 19.
"""

from decimal import Decimal

from trading_firm.reconciliation import (
    BrokerTradeRecord,
    LocalBook,
    LocalTradeRecord,
    StartupMode,
    reconcile,
    startup_mode,
)

D = Decimal

LOCAL_TRADE = LocalTradeRecord(
    trade_id="101", instrument="EUR_USD", units=595, stop_price=D("1.1369")
)


def broker_trade(**overrides) -> BrokerTradeRecord:
    fields = {
        "trade_id": "101",
        "instrument": "EUR_USD",
        "units": 595,
        "stop_price": D("1.1369"),
        "stop_state": "PENDING",
    }
    fields.update(overrides)
    return BrokerTradeRecord(**fields)


def run(local_trades=(LOCAL_TRADE,), broker_trades=None, balance="250.00", pending=frozenset()):
    return reconcile(
        LocalBook(trades=tuple(local_trades), closed_equity=D("250.00")),
        broker_trades=list(broker_trades if broker_trades is not None else [broker_trade()]),
        broker_balance=D(balance),
        broker_pending_order_ids=pending,
    )


class TestCleanBook:
    def test_matching_protected_position_is_normal(self) -> None:
        result = run()
        assert result.clean and result.entries_enabled
        assert startup_mode(result) is StartupMode.NORMAL

    def test_flat_books_are_normal(self) -> None:
        result = run(local_trades=(), broker_trades=[])
        assert result.clean


class TestPositionDiscrepancies:
    def test_hidden_broker_trade_halts(self) -> None:
        result = run(local_trades=(), broker_trades=[broker_trade()])
        assert startup_mode(result) is StartupMode.HALTED

    def test_local_ghost_trade_halts(self) -> None:
        result = run(broker_trades=[])
        assert startup_mode(result) is StartupMode.HALTED

    def test_units_mismatch_halts(self) -> None:
        # Finding 13: same trade id, diverged size (e.g. partial closeout).
        result = run(broker_trades=[broker_trade(units=300)])
        assert startup_mode(result) is StartupMode.HALTED
        assert any("units mismatch" in issue for issue in result.discrepancies)

    def test_instrument_mismatch_halts(self) -> None:
        result = run(broker_trades=[broker_trade(instrument="GBP_USD")])
        assert startup_mode(result) is StartupMode.HALTED


class TestStopVerification:
    """§18 step 4 (findings 4/14): stops verified during reconciliation."""

    def test_missing_stop_halts(self) -> None:
        result = run(broker_trades=[broker_trade(stop_price=None, stop_state=None)])
        assert startup_mode(result) is StartupMode.HALTED
        assert any("STOP_MISSING" in issue for issue in result.discrepancies)

    def test_inactive_stop_state_halts(self) -> None:
        result = run(broker_trades=[broker_trade(stop_state="CANCELLED")])
        assert startup_mode(result) is StartupMode.HALTED

    def test_wrong_stop_price_halts(self) -> None:
        result = run(broker_trades=[broker_trade(stop_price=D("1.1300"))])
        assert startup_mode(result) is StartupMode.HALTED

    def test_from_v20_parses_fake_broker_shape(self) -> None:
        record = BrokerTradeRecord.from_v20(
            {
                "id": "42",
                "instrument": "EUR_USD",
                "currentUnits": "-595",
                "stopLossOrder": {"price": "1.1419", "state": "PENDING"},
            }
        )
        assert record.units == -595
        assert record.stop_price == D("1.1419")
        assert record.stop_state == "PENDING"


class TestPendingOrders:
    def test_unknown_pending_order_halts(self) -> None:
        # Finding 19: §18 step 2 includes orders, not just positions.
        result = run(pending={"777"})
        assert startup_mode(result) is StartupMode.HALTED

    def test_expected_pending_order_missing_at_broker_halts(self) -> None:
        outcome = reconcile(
            LocalBook(
                trades=(LOCAL_TRADE,),
                pending_order_ids=frozenset({"888"}),
                closed_equity=D("250.00"),
            ),
            broker_trades=[broker_trade()],
            broker_balance=D("250.00"),
        )
        assert startup_mode(outcome) is StartupMode.HALTED


class TestEquity:
    def test_equity_mismatch_is_manage_only(self) -> None:
        result = run(balance="248.00")
        assert not result.entries_enabled
        assert startup_mode(result) is StartupMode.MANAGE_ONLY

    def test_equity_tolerance_boundary(self) -> None:
        assert run(balance="250.01").clean
        assert not run(balance="250.02").clean
