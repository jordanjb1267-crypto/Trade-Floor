"""Broker execution package (§2, §8.1).

Re-exports are LAZY (PEP 562), and that is a §12.1 control, not a style
choice. This package also holds the shared §17 credential preflight
(`credentials.py`), which the read-only notify transport imports — and in
Python, importing any submodule executes this file first. With eager
re-exports, merely validating a Telegram token loaded the order-placing
adapter into the process; the shadow supervisor's acceptance test
(`tests/acceptance/test_supervisor_no_order_path.py`) requires that a process
which cannot place orders does not have the order path in memory at all.

`from trading_firm.execution import BrokerAdapter` still works everywhere it
is meant to — the attribute resolves on first touch. What changed is that
nobody gets the adapter without asking for it by name.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover — for type checkers only, never at runtime
    from trading_firm.execution.adapter import (
        BrokerAdapter,
        ClientOrderStatus,
        OrderPathViolationError,
        OrderResult,
        TransportFailureError,
    )
    from trading_firm.execution.states import OrderLifecycle, OrderState

__all__ = [
    "BrokerAdapter",
    "ClientOrderStatus",
    "OrderLifecycle",
    "OrderPathViolationError",
    "OrderResult",
    "OrderState",
    "TransportFailureError",
]

_ADAPTER_EXPORTS = {
    "BrokerAdapter",
    "ClientOrderStatus",
    "OrderPathViolationError",
    "OrderResult",
    "TransportFailureError",
}
_STATES_EXPORTS = {"OrderLifecycle", "OrderState"}


def __getattr__(name: str):
    if name in _ADAPTER_EXPORTS:
        from trading_firm.execution import adapter

        return getattr(adapter, name)
    if name in _STATES_EXPORTS:
        from trading_firm.execution import states

        return getattr(states, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
