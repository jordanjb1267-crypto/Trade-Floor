"""Order state machine (§8.1 Broker Adapter / Order State Reconciler).

Every order tracks an explicit lifecycle; illegal transitions raise instead
of silently corrupting state. A filled position without a confirmed
broker-held stop is a distinct, alarming state — STOP_MISSING is a
kill-switch trigger class (§8.1: stop-loss failure → flatten immediately).
"""

from __future__ import annotations

import datetime as dt
import enum


class OrderState(enum.Enum):
    PENDING_SUBMIT = "PENDING_SUBMIT"
    SUBMITTED = "SUBMITTED"
    FILLED_UNPROTECTED = "FILLED_UNPROTECTED"  # filled, stop not yet confirmed
    PROTECTED = "PROTECTED"  # broker-held stop confirmed active (§0.9)
    STOP_MISSING = "STOP_MISSING"  # kill-switch trigger: flatten immediately
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"  # transport failure; resolve before anything else
    CLOSED = "CLOSED"


_ALLOWED: dict[OrderState, frozenset[OrderState]] = {
    OrderState.PENDING_SUBMIT: frozenset(
        {OrderState.SUBMITTED, OrderState.REJECTED, OrderState.UNKNOWN}
    ),
    OrderState.SUBMITTED: frozenset(
        {
            OrderState.FILLED_UNPROTECTED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
            OrderState.UNKNOWN,
        }
    ),
    OrderState.FILLED_UNPROTECTED: frozenset({OrderState.PROTECTED, OrderState.STOP_MISSING}),
    OrderState.PROTECTED: frozenset({OrderState.CLOSED}),
    OrderState.STOP_MISSING: frozenset({OrderState.PROTECTED, OrderState.CLOSED}),
    OrderState.UNKNOWN: frozenset(
        {
            OrderState.SUBMITTED,
            OrderState.FILLED_UNPROTECTED,
            OrderState.REJECTED,
            OrderState.CANCELLED,
        }
    ),
    OrderState.REJECTED: frozenset(),
    OrderState.CANCELLED: frozenset(),
    OrderState.CLOSED: frozenset(),
}

TERMINAL_STATES = frozenset(
    {OrderState.REJECTED, OrderState.CANCELLED, OrderState.CLOSED}
)


class IllegalTransitionError(RuntimeError):
    pass


class OrderLifecycle:
    """Mutable lifecycle for one order: enforced transitions, full history."""

    def __init__(self, client_order_id: str):
        self.client_order_id = client_order_id
        self.state = OrderState.PENDING_SUBMIT
        self.history: list[tuple[OrderState, dt.datetime]] = [
            (self.state, dt.datetime.now(dt.UTC))
        ]

    def transition(self, new_state: OrderState) -> None:
        if new_state not in _ALLOWED[self.state]:
            raise IllegalTransitionError(
                f"{self.client_order_id}: {self.state.value} -> {new_state.value} is illegal"
            )
        self.state = new_state
        self.history.append((new_state, dt.datetime.now(dt.UTC)))

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
