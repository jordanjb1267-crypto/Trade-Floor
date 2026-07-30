"""Reconciler tests (§8.1, §18): broker authoritative, fail closed on mismatch."""

from decimal import Decimal

from trading_firm.reconciliation import LocalBook, StartupMode, reconcile, startup_mode

D = Decimal


class TestReconcile:
    def test_clean_book_enables_entries(self) -> None:
        result = reconcile(
            LocalBook(open_trade_ids=frozenset({"101"}), closed_equity=D("250.00")),
            broker_open_trade_ids={"101"},
            broker_balance=D("250.00"),
        )
        assert result.clean and result.entries_enabled
        assert startup_mode(result) is StartupMode.NORMAL

    def test_hidden_broker_trade_halts(self) -> None:
        result = reconcile(
            LocalBook(closed_equity=D("250.00")),
            broker_open_trade_ids={"666"},
            broker_balance=D("250.00"),
        )
        assert not result.entries_enabled
        assert any("unknown to local book" in issue for issue in result.discrepancies)
        assert startup_mode(result) is StartupMode.HALTED

    def test_local_ghost_trade_halts(self) -> None:
        result = reconcile(
            LocalBook(open_trade_ids=frozenset({"777"}), closed_equity=D("250.00")),
            broker_open_trade_ids=set(),
            broker_balance=D("250.00"),
        )
        assert startup_mode(result) is StartupMode.HALTED

    def test_equity_mismatch_is_manage_only(self) -> None:
        result = reconcile(
            LocalBook(closed_equity=D("250.00")),
            broker_open_trade_ids=set(),
            broker_balance=D("248.00"),
        )
        assert not result.entries_enabled
        assert startup_mode(result) is StartupMode.MANAGE_ONLY

    def test_equity_tolerance_boundary(self) -> None:
        within = reconcile(
            LocalBook(closed_equity=D("250.00")),
            broker_open_trade_ids=set(),
            broker_balance=D("250.01"),
        )
        beyond = reconcile(
            LocalBook(closed_equity=D("250.00")),
            broker_open_trade_ids=set(),
            broker_balance=D("250.02"),
        )
        assert within.clean
        assert not beyond.clean
