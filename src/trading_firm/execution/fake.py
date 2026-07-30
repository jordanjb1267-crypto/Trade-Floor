"""Deterministic fake broker: OANDA-v20-shaped transport for tests and,
later, paper execution (§13).

Honesty rules from the 2026-07-30 adversarial review: this fake mirrors the
REAL broker's semantics, including the inconvenient ones —

- create_market_order does NOT dedupe by client id (OANDA doesn't for market
  orders); duplicate prevention is the adapter's job (finding 3).
- Rejected creates leave no order record, so lookups return None for them.
- lookup_client_order returns a typed ClientOrderStatus, the same shape the
  real transport produces — never a create-response envelope.

Failure injection covers the §21 classes: rejection, dropped/inactive/
wrong-price stop, timeout before AND after landing, lookup failure,
get_trade failure, partial fill, margin closeout, hidden trades, and
mutated units for reconciliation drills.
"""

from __future__ import annotations

import itertools
from decimal import Decimal

from trading_firm.execution.adapter import ClientOrderStatus, TransportFailureError


class FakeBroker:
    is_practice = True

    def __init__(self, balance: Decimal = Decimal("250")):
        self.balance = balance
        self._ids = itertools.count(1000)
        self._client_index: dict[str, ClientOrderStatus] = {}
        self._trades: dict[str, dict] = {}
        # one-shot failure injection switches
        self._reject_next: str | None = None
        self._drop_stop_next = False
        self._stop_state_next: str | None = None
        self._stop_price_next: str | None = None
        self._timeout_next = False
        self._timeout_after_landing_next = False
        self._lookup_failure_next = False
        self._lookup_failure_skip = 0
        self._get_trade_failure_next = False
        self._partial_fill_next: int | None = None
        self._margin_closeout_next = False

    # ------------------------------------------------------------ injection
    def inject_reject(self, reason: str = "INSUFFICIENT_MARGIN") -> None:
        self._reject_next = reason

    def inject_dropped_stop(self) -> None:
        self._drop_stop_next = True

    def inject_stop_state(self, state: str) -> None:
        self._stop_state_next = state

    def inject_stop_price(self, price: str) -> None:
        self._stop_price_next = price

    def inject_timeout(self) -> None:
        """Request-leg failure: nothing reaches the broker."""
        self._timeout_next = True

    def inject_timeout_after_landing(self) -> None:
        """Response-leg failure: the order lands and fills, the response is
        lost (review finding 11 — the genuinely dangerous timeout)."""
        self._timeout_after_landing_next = True

    def inject_lookup_failure(self, skip: int = 0) -> None:
        """Fail one lookup after letting `skip` lookups succeed first."""
        self._lookup_failure_next = True
        self._lookup_failure_skip = skip

    def inject_get_trade_failure(self) -> None:
        self._get_trade_failure_next = True

    def inject_partial_fill(self, units: int) -> None:
        self._partial_fill_next = units

    def inject_margin_closeout(self) -> None:
        """Fill succeeds, then the broker closes the trade out before the
        stop-verification query (margin closeout during fill, §21)."""
        self._margin_closeout_next = True

    def inject_hidden_trade(self, trade_id: str, instrument: str, units: int) -> None:
        """A position the local book does not know about (desync drill)."""
        self._trades[trade_id] = {
            "id": trade_id,
            "instrument": instrument,
            "currentUnits": str(units),
            "stopLossOrder": None,
        }

    def corrupt_trade_units(self, trade_id: str, units: int) -> None:
        self._trades[trade_id]["currentUnits"] = str(units)

    def strip_stop(self, trade_id: str) -> None:
        self._trades[trade_id]["stopLossOrder"] = None

    # ------------------------------------------------------------ transport
    def create_market_order(
        self, *, instrument: str, units: int, stop_loss_price: str, client_order_id: str
    ) -> dict:
        if self._timeout_next:
            self._timeout_next = False
            raise TransportFailureError("simulated transport failure before the order landed")

        order_id = str(next(self._ids))
        if self._reject_next is not None:
            reason, self._reject_next = self._reject_next, None
            # OANDA: a rejected create produces NO order record; lookups miss.
            return {
                "orderCreateTransaction": {"id": order_id},
                "orderRejectTransaction": {"rejectReason": reason},
            }

        filled_units = self._partial_fill_next or units
        self._partial_fill_next = None
        trade_id = str(next(self._ids))
        if self._drop_stop_next:
            stop = None
            self._drop_stop_next = False
        else:
            stop = {
                "price": self._stop_price_next or stop_loss_price,
                "state": self._stop_state_next or "PENDING",
            }
            self._stop_state_next = None
            self._stop_price_next = None
        self._trades[trade_id] = {
            "id": trade_id,
            "instrument": instrument,
            "currentUnits": str(filled_units if units > 0 else -abs(filled_units)),
            "stopLossOrder": stop,
        }
        self._client_index[client_order_id] = ClientOrderStatus(state="FILLED", trade_id=trade_id)

        if self._margin_closeout_next:
            self._margin_closeout_next = False
            del self._trades[trade_id]
            self.balance -= Decimal("10")

        response = {
            "orderCreateTransaction": {"id": order_id},
            "orderFillTransaction": {
                "id": order_id,
                "units": str(filled_units if units > 0 else -abs(filled_units)),
                "tradeOpened": {"tradeID": trade_id},
            },
        }
        if self._timeout_after_landing_next:
            self._timeout_after_landing_next = False
            raise TransportFailureError("simulated transport failure after the order landed")
        return response

    def lookup_client_order(self, client_order_id: str) -> ClientOrderStatus | None:
        if self._lookup_failure_next:
            if self._lookup_failure_skip > 0:
                self._lookup_failure_skip -= 1
            else:
                self._lookup_failure_next = False
                raise TransportFailureError("simulated lookup failure")
        return self._client_index.get(client_order_id)

    def get_trade(self, trade_id: str) -> dict | None:
        if self._get_trade_failure_next:
            self._get_trade_failure_next = False
            raise TransportFailureError("simulated get_trade failure")
        return self._trades.get(trade_id)

    def close_trade(self, trade_id: str) -> dict:
        trade = self._trades.pop(trade_id, None)
        if trade is None:
            return {"errorMessage": "trade not found"}
        return {"orderFillTransaction": {"tradesClosed": [{"tradeID": trade_id}]}}

    # ------------------------------------------------------- reconciliation
    def open_trade_ids(self) -> set[str]:
        return set(self._trades)

    def open_trades(self) -> list[dict]:
        return list(self._trades.values())

    def account_summary(self) -> dict:
        return {"account": {"balance": str(self.balance), "openTradeCount": len(self._trades)}}
