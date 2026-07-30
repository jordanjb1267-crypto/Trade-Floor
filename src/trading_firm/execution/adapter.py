"""Deterministic broker adapter (§2 order path stages 7–10, §8.1).

The ONLY component that may submit, modify, or cancel broker orders. It
refuses to act without an approved RiskDecision and SizingResult (no stage
may be skipped, §2), revalidates price immediately before submission
(N-13), attaches the broker-held stop on fill (§0.9), submits idempotently
via deterministic client order ids, and resolves UNKNOWN states by querying
the broker rather than blind resubmission.

No LLM ever calls this module (§0.3). Practice transport only until Phase 7.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol

from trading_firm.execution.states import OrderLifecycle, OrderState
from trading_firm.models import Candidate, Direction, RiskDecision, SizingResult


class BrokerTransport(Protocol):
    """Wire-level broker interface. Implementations: FakeBroker (tests/paper),
    OandaPracticeTransport (Phase 4 sandbox). A live transport may not exist
    before Phase 7 and never outside this execution package (§16, D-1)."""

    @property
    def is_practice(self) -> bool: ...

    def create_market_order(
        self,
        *,
        instrument: str,
        units: int,
        stop_loss_price: str,
        client_order_id: str,
    ) -> dict: ...

    def find_order_by_client_id(self, client_order_id: str) -> dict | None: ...

    def get_trade(self, trade_id: str) -> dict | None: ...

    def close_trade(self, trade_id: str) -> dict: ...


class OrderPathViolationError(RuntimeError):
    """A §2 order-path stage was skipped or a guard failed. Never rescued."""


@dataclass(frozen=True)
class OrderResult:
    state: OrderState
    client_order_id: str
    broker_order_id: str | None = None
    trade_id: str | None = None
    detail: str = ""
    resubmit_safe: bool = False  # only meaningful for UNKNOWN


def client_order_id_for(candidate: Candidate) -> str:
    """Deterministic idempotency key: same candidate → same id (§8.1)."""
    material = "|".join(
        [
            candidate.instrument,
            candidate.strategy_id,
            candidate.strategy_version,
            candidate.direction.value,
            candidate.created_at.date().isoformat(),
        ]
    )
    return "clltf-" + hashlib.sha256(material.encode()).hexdigest()[:16]


class BrokerAdapter:
    def __init__(
        self,
        transport: BrokerTransport,
        *,
        revalidation_tolerance_pips: Decimal = Decimal("2"),
        pip_size: Decimal = Decimal("0.0001"),
    ):
        if not transport.is_practice:
            raise OrderPathViolationError(
                "live transport refused: live execution requires Phase 7 owner activation "
                "(§13, §22); only practice transports may be constructed"
            )
        self._transport = transport
        self._tolerance = revalidation_tolerance_pips * pip_size

    def submit_entry(
        self,
        candidate: Candidate,
        decision: RiskDecision,
        sizing: SizingResult,
        current_price: Decimal,
    ) -> OrderResult:
        # --- §2: no stage may be skipped -------------------------------------
        if not decision.approved:
            raise OrderPathViolationError("risk decision not approved: order path violation (§2)")
        if not sizing.approved or sizing.units <= 0:
            raise OrderPathViolationError("sizing not approved: order path violation (§2)")

        client_id = client_order_id_for(candidate)
        lifecycle = OrderLifecycle(client_id)

        # --- idempotency: never submit the same candidate twice (§8.1) -------
        existing = self._transport.find_order_by_client_id(client_id)
        if existing is not None:
            return self._interpret_response(existing, lifecycle, candidate, duplicate=True)

        # --- price/spread revalidation immediately before submission (N-13) --
        drift = abs(current_price - candidate.entry_price)
        if drift > self._tolerance:
            lifecycle.transition(OrderState.REJECTED)
            return OrderResult(
                state=OrderState.REJECTED,
                client_order_id=client_id,
                detail=f"revalidation failed: price drifted {drift} > {self._tolerance} (N-13)",
            )

        signed_units = sizing.units if candidate.direction is Direction.LONG else -sizing.units
        try:
            response = self._transport.create_market_order(
                instrument=candidate.instrument,
                units=signed_units,
                stop_loss_price=str(candidate.stop_price),  # broker-held stop (§0.9)
                client_order_id=client_id,
            )
        except TimeoutError:
            lifecycle.transition(OrderState.UNKNOWN)
            return self._resolve_unknown(lifecycle, candidate)

        lifecycle.transition(OrderState.SUBMITTED)
        return self._interpret_response(response, lifecycle, candidate, duplicate=False)

    def _resolve_unknown(self, lifecycle: OrderLifecycle, candidate: Candidate) -> OrderResult:
        """§8.1 unknown-state handling: query by client id; never blind-resubmit."""
        found = self._transport.find_order_by_client_id(lifecycle.client_order_id)
        if found is None:
            return OrderResult(
                state=OrderState.UNKNOWN,
                client_order_id=lifecycle.client_order_id,
                detail="submit timed out and no order exists at broker: resubmission is safe",
                resubmit_safe=True,
            )
        lifecycle.transition(OrderState.SUBMITTED)
        return self._interpret_response(found, lifecycle, candidate, duplicate=True)

    def _interpret_response(
        self,
        response: dict,
        lifecycle: OrderLifecycle,
        candidate: Candidate,
        *,
        duplicate: bool,
    ) -> OrderResult:
        note = "duplicate submit adopted existing order; " if duplicate else ""
        if lifecycle.state is OrderState.PENDING_SUBMIT:
            lifecycle.transition(OrderState.SUBMITTED)

        if "orderRejectTransaction" in response:
            lifecycle.transition(OrderState.REJECTED)
            reason = response["orderRejectTransaction"].get("rejectReason", "unspecified")
            return OrderResult(
                state=OrderState.REJECTED,
                client_order_id=lifecycle.client_order_id,
                detail=note + f"broker rejected order: {reason}",
            )

        if "orderCancelTransaction" in response and "orderFillTransaction" not in response:
            lifecycle.transition(OrderState.CANCELLED)
            return OrderResult(
                state=OrderState.CANCELLED,
                client_order_id=lifecycle.client_order_id,
                detail=note + "order cancelled without fill",
            )

        fill = response.get("orderFillTransaction")
        if fill is None:
            lifecycle.transition(OrderState.UNKNOWN)
            return OrderResult(
                state=OrderState.UNKNOWN,
                client_order_id=lifecycle.client_order_id,
                detail=note + "unrecognized broker response shape",
            )

        trade_id = str(fill.get("tradeOpened", {}).get("tradeID", ""))
        lifecycle.transition(OrderState.FILLED_UNPROTECTED)

        # --- stop-loss confirmation is a pipeline stage, not an option (§2) ---
        trade = self._transport.get_trade(trade_id) if trade_id else None
        stop = (trade or {}).get("stopLossOrder")
        if stop and Decimal(str(stop.get("price", "0"))) == candidate.stop_price:
            lifecycle.transition(OrderState.PROTECTED)
            return OrderResult(
                state=OrderState.PROTECTED,
                client_order_id=lifecycle.client_order_id,
                broker_order_id=str(response.get("orderCreateTransaction", {}).get("id", "")),
                trade_id=trade_id,
                detail=note + "filled with broker-held stop confirmed active",
            )

        lifecycle.transition(OrderState.STOP_MISSING)
        return OrderResult(
            state=OrderState.STOP_MISSING,
            client_order_id=lifecycle.client_order_id,
            trade_id=trade_id,
            detail=note
            + "filled but broker-held stop NOT confirmed: kill-switch trigger, "
            "flatten immediately (§8.1 stop-loss failure policy)",
        )
