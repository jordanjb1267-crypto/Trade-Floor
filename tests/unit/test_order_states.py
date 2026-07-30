"""Order state machine tests (§8.1)."""

import pytest

from trading_firm.execution.states import IllegalTransitionError, OrderLifecycle, OrderState


class TestLifecycle:
    def test_happy_path_to_protected(self) -> None:
        order = OrderLifecycle("clltf-test")
        for state in (
            OrderState.SUBMITTED,
            OrderState.FILLED_UNPROTECTED,
            OrderState.PROTECTED,
            OrderState.CLOSED,
        ):
            order.transition(state)
        assert order.is_terminal
        assert [s for s, _ in order.history] == [
            OrderState.PENDING_SUBMIT,
            OrderState.SUBMITTED,
            OrderState.FILLED_UNPROTECTED,
            OrderState.PROTECTED,
            OrderState.CLOSED,
        ]

    def test_fill_requires_stop_resolution(self) -> None:
        # FILLED_UNPROTECTED can only become PROTECTED or STOP_MISSING —
        # a filled position cannot close without the stop question answered.
        order = OrderLifecycle("clltf-test")
        order.transition(OrderState.SUBMITTED)
        order.transition(OrderState.FILLED_UNPROTECTED)
        with pytest.raises(IllegalTransitionError):
            order.transition(OrderState.CLOSED)

    def test_stop_missing_recovery_paths(self) -> None:
        order = OrderLifecycle("clltf-test")
        order.transition(OrderState.SUBMITTED)
        order.transition(OrderState.FILLED_UNPROTECTED)
        order.transition(OrderState.STOP_MISSING)
        order.transition(OrderState.CLOSED)  # emergency flatten (§8.1)
        assert order.is_terminal

    def test_terminal_states_are_final(self) -> None:
        order = OrderLifecycle("clltf-test")
        order.transition(OrderState.REJECTED)
        with pytest.raises(IllegalTransitionError):
            order.transition(OrderState.SUBMITTED)

    def test_unknown_resolves_only_to_broker_truth(self) -> None:
        order = OrderLifecycle("clltf-test")
        order.transition(OrderState.UNKNOWN)
        with pytest.raises(IllegalTransitionError):
            order.transition(OrderState.PROTECTED)  # must pass through a fill state
        order.transition(OrderState.FILLED_UNPROTECTED)
        order.transition(OrderState.PROTECTED)
