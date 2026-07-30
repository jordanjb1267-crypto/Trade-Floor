"""Deterministic fake broker: OANDA-v20-shaped transport for tests and,
later, paper execution (§13). Supports failure injection for the §21
failure-injection suite: rejections, dropped stops, timeouts, and hidden
positions for reconciliation drills.
"""

from __future__ import annotations

import itertools
from decimal import Decimal


class FakeBroker:
    is_practice = True

    def __init__(self, balance: Decimal = Decimal("250")):
        self.balance = balance
        self._ids = itertools.count(1000)
        self._orders_by_client_id: dict[str, dict] = {}
        self._trades: dict[str, dict] = {}
        # failure injection switches (one-shot)
        self._reject_next: str | None = None
        self._drop_stop_next = False
        self._timeout_next = False

    # ------------------------------------------------------------ injection
    def inject_reject(self, reason: str = "INSUFFICIENT_MARGIN") -> None:
        self._reject_next = reason

    def inject_dropped_stop(self) -> None:
        self._drop_stop_next = True

    def inject_timeout(self) -> None:
        self._timeout_next = True

    def inject_hidden_trade(self, trade_id: str, instrument: str, units: int) -> None:
        """A position the local book does not know about (desync drill)."""
        self._trades[trade_id] = {
            "id": trade_id,
            "instrument": instrument,
            "currentUnits": str(units),
            "stopLossOrder": None,
        }

    # ------------------------------------------------------------ transport
    def create_market_order(
        self, *, instrument: str, units: int, stop_loss_price: str, client_order_id: str
    ) -> dict:
        if self._timeout_next:
            self._timeout_next = False
            raise TimeoutError("simulated transport timeout")

        if client_order_id in self._orders_by_client_id:
            return self._orders_by_client_id[client_order_id]  # idempotent replay

        order_id = str(next(self._ids))
        if self._reject_next is not None:
            reason, self._reject_next = self._reject_next, None
            response = {
                "orderCreateTransaction": {"id": order_id},
                "orderRejectTransaction": {"rejectReason": reason},
            }
            self._orders_by_client_id[client_order_id] = response
            return response

        trade_id = str(next(self._ids))
        stop = None if self._drop_stop_next else {"price": stop_loss_price, "state": "PENDING"}
        self._drop_stop_next = False
        self._trades[trade_id] = {
            "id": trade_id,
            "instrument": instrument,
            "currentUnits": str(units),
            "stopLossOrder": stop,
        }
        response = {
            "orderCreateTransaction": {"id": order_id},
            "orderFillTransaction": {"id": order_id, "tradeOpened": {"tradeID": trade_id}},
        }
        self._orders_by_client_id[client_order_id] = response
        return response

    def find_order_by_client_id(self, client_order_id: str) -> dict | None:
        return self._orders_by_client_id.get(client_order_id)

    def get_trade(self, trade_id: str) -> dict | None:
        return self._trades.get(trade_id)

    def close_trade(self, trade_id: str) -> dict:
        trade = self._trades.pop(trade_id, None)
        if trade is None:
            return {"errorMessage": "trade not found"}
        return {"orderFillTransaction": {"tradesClosed": [{"tradeID": trade_id}]}}

    # ------------------------------------------------------- reconciliation
    def open_trade_ids(self) -> set[str]:
        return set(self._trades)

    def account_summary(self) -> dict:
        return {"account": {"balance": str(self.balance), "openTradeCount": len(self._trades)}}
