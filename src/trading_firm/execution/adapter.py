"""Deterministic broker adapter (§2 order path stages 7–10, §8.1).

The ONLY component that may submit, modify, or cancel broker orders.
Hardened per the 2026-07-30 adversarial review (findings 0–21):

- Approvals are BOUND to their candidate: RiskDecision and SizingResult carry
  the candidate's content key, and submitting a mismatched pairing, an
  expired candidate, or sizing above the approved risk is an order-path
  violation (findings 8, 12).
- Client order ids derive from the candidate content hash, so distinct
  same-day candidates never collide and only true resubmissions dedupe
  (findings 1, 18).
- Broker lookups return a typed ClientOrderStatus — never a create-response
  envelope — so dedup and UNKNOWN resolution work against the real OANDA API
  shape (findings 0, 3).
- All transport failures (timeouts, connection loss, unparseable bodies)
  surface as TransportFailureError and route through UNKNOWN handling; a
  failure during stop verification yields STOP_MISSING, never an unhandled
  exception past a live fill (findings 2, 10, 15).
- resubmit_safe requires repeated confirmed-absent lookups; any lookup
  failure means "outcome undetermined — do NOT resubmit" (finding 0).
- PROTECTED requires the stop present, price-exact, AND in an active state;
  filled units must equal sized units (partial fill = kill-switch class)
  (findings 6, 9, 16).

No LLM ever calls this module (§0.3). Practice transport only until Phase 7,
re-asserted on every submission (finding 20).
"""

from __future__ import annotations

import datetime as dt
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, Protocol

from trading_firm.execution.states import OrderLifecycle, OrderState
from trading_firm.models import (
    Candidate,
    Direction,
    InstrumentSpec,
    RiskDecision,
    SizingResult,
)


class TransportFailureError(RuntimeError):
    """The transport could not determine the outcome (timeout, connection
    loss, unparseable response). The request MAY have reached the broker."""


class BrokerAuthError(TransportFailureError):
    """The broker rejected the credential itself (HTTP 401/403).

    Subclasses TransportFailureError deliberately: every existing handler
    keeps routing it through fail-closed UNKNOWN resolution, which stays
    correct here because a rejected credential also fails the confirmed-absent
    lookups resubmit_safe requires — so the path can never resubmit. The
    distinct type exists so operators get the real cause by name instead of a
    downstream symptom.
    """


class OrderPathViolationError(RuntimeError):
    """A §2 order-path stage was skipped or a guard failed. Never rescued."""


@dataclass(frozen=True)
class ClientOrderStatus:
    """Normalized broker answer for a client-order-id lookup."""

    state: Literal["PENDING", "FILLED", "CANCELLED"]
    trade_id: str | None = None


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

    def lookup_client_order(self, client_order_id: str) -> ClientOrderStatus | None: ...

    def get_trade(self, trade_id: str) -> dict | None: ...

    def close_trade(self, trade_id: str) -> dict: ...


@dataclass(frozen=True)
class OrderResult:
    state: OrderState
    client_order_id: str
    broker_order_id: str | None = None
    trade_id: str | None = None
    detail: str = ""
    resubmit_safe: bool = False  # only meaningful for UNKNOWN
    filled_units: int | None = None


def client_order_id_for(candidate: Candidate) -> str:
    """Idempotency key from the candidate CONTENT hash: identical resubmissions
    collide (by design); distinct candidates cannot (findings 1, 18)."""
    return "clltf-" + candidate.content_key()[:20]


ACTIVE_STOP_STATES = frozenset({"PENDING"})


class BrokerAdapter:
    def __init__(
        self,
        transport: BrokerTransport,
        *,
        revalidation_tolerance_pips: Decimal = Decimal("2"),
        lookup_attempts: int = 2,
        lookup_retry_seconds: float = 1.0,
        sleep_fn: Callable[[float], None] = time.sleep,
    ):
        if not transport.is_practice:
            raise OrderPathViolationError(
                "live transport refused: live execution requires Phase 7 owner activation "
                "(§13, §22); only practice transports may be constructed"
            )
        self._transport = transport
        self._tolerance_pips = revalidation_tolerance_pips
        self._lookup_attempts = max(1, lookup_attempts)
        self._lookup_retry_seconds = lookup_retry_seconds
        self._sleep = sleep_fn

    # ------------------------------------------------------------------ entry

    def submit_entry(
        self,
        candidate: Candidate,
        decision: RiskDecision,
        sizing: SizingResult,
        spec: InstrumentSpec,
        current_price: Decimal,
        now: dt.datetime,
    ) -> OrderResult:
        self._assert_order_path(candidate, decision, sizing, spec, now)
        client_id = client_order_id_for(candidate)
        lifecycle = OrderLifecycle(client_id)

        # --- idempotency: never submit the same candidate twice (§8.1) -------
        try:
            existing = self._transport.lookup_client_order(client_id)
        except (TimeoutError, TransportFailureError) as err:
            return OrderResult(
                state=OrderState.UNKNOWN,
                client_order_id=client_id,
                detail=f"pre-submit lookup failed ({err}): outcome undeterminable, "
                "do NOT submit until the broker is reachable",
            )
        if existing is not None:
            return self._result_from_lookup(
                existing, lifecycle, candidate, note="duplicate submit adopted existing order; "
            )

        # --- price revalidation immediately before submission (N-13) ---------
        tolerance = self._tolerance_pips * spec.pip_size  # per-instrument (finding 7)
        drift = abs(current_price - candidate.entry_price)
        if drift > tolerance:
            lifecycle.transition(OrderState.REJECTED)
            return OrderResult(
                state=OrderState.REJECTED,
                client_order_id=client_id,
                detail=f"revalidation failed: price drifted {drift} > {tolerance} (N-13)",
            )

        signed_units = sizing.units if candidate.direction is Direction.LONG else -sizing.units
        try:
            response = self._transport.create_market_order(
                instrument=candidate.instrument,
                units=signed_units,
                stop_loss_price=str(candidate.stop_price),  # broker-held stop (§0.9)
                client_order_id=client_id,
            )
        except (TimeoutError, TransportFailureError):
            lifecycle.transition(OrderState.UNKNOWN)
            return self._resolve_unknown(lifecycle, candidate)

        lifecycle.transition(OrderState.SUBMITTED)
        return self._interpret_create_response(response, lifecycle, candidate, sizing)

    # ----------------------------------------------------------------- guards

    def _assert_order_path(
        self,
        candidate: Candidate,
        decision: RiskDecision,
        sizing: SizingResult,
        spec: InstrumentSpec,
        now: dt.datetime,
    ) -> None:
        if not self._transport.is_practice:  # re-assert every call (finding 20)
            raise OrderPathViolationError("transport is no longer practice-scoped")
        if not decision.approved:
            raise OrderPathViolationError("risk decision not approved: order path violation (§2)")
        if not sizing.approved or sizing.units <= 0:
            raise OrderPathViolationError("sizing not approved: order path violation (§2)")
        key = candidate.content_key()
        if decision.candidate_key != key or sizing.candidate_key != key:
            raise OrderPathViolationError(
                "approval/sizing were minted for a DIFFERENT candidate: order path "
                "violation (§2; review findings 8/12)"
            )
        if now >= candidate.expires_at:
            raise OrderPathViolationError("candidate expired before submission (§13)")
        if sizing.effective_risk_usd > decision.allowed_risk_usd:
            raise OrderPathViolationError(
                f"sizing risk {sizing.effective_risk_usd} exceeds approved "
                f"{decision.allowed_risk_usd} (§21 acceptance)"
            )
        if candidate.instrument != spec.name:
            raise OrderPathViolationError("instrument spec mismatch")

    # ------------------------------------------------------ unknown resolution

    def _resolve_unknown(self, lifecycle: OrderLifecycle, candidate: Candidate) -> OrderResult:
        """§8.1 unknown-state handling: repeated broker queries, never blind
        resubmission. resubmit_safe only after every query confirms absence."""
        for attempt in range(self._lookup_attempts):
            if attempt > 0:
                self._sleep(self._lookup_retry_seconds)
            try:
                found = self._transport.lookup_client_order(lifecycle.client_order_id)
            except (TimeoutError, TransportFailureError) as err:
                return OrderResult(
                    state=OrderState.UNKNOWN,
                    client_order_id=lifecycle.client_order_id,
                    detail=f"lookup failed during unknown-state resolution ({err}): "
                    "outcome undetermined — do NOT resubmit (finding 0)",
                )
            if found is not None:
                lifecycle.transition(OrderState.SUBMITTED)
                return self._result_from_lookup(
                    found, lifecycle, candidate, note="timed-out submit resolved at broker; "
                )
        return OrderResult(
            state=OrderState.UNKNOWN,
            client_order_id=lifecycle.client_order_id,
            detail=f"submit outcome unknown; {self._lookup_attempts} spaced lookups found "
            "no order at the broker: one explicit resubmission is safe",
            resubmit_safe=True,
        )

    # ------------------------------------------------------- response handling

    def _result_from_lookup(
        self,
        status: ClientOrderStatus,
        lifecycle: OrderLifecycle,
        candidate: Candidate,
        note: str,
    ) -> OrderResult:
        if lifecycle.state is OrderState.PENDING_SUBMIT:
            lifecycle.transition(OrderState.SUBMITTED)
        if status.state == "CANCELLED":
            lifecycle.transition(OrderState.CANCELLED)
            return OrderResult(
                state=OrderState.CANCELLED,
                client_order_id=lifecycle.client_order_id,
                detail=note + "existing order was cancelled without fill",
            )
        if status.state == "PENDING":
            return OrderResult(
                state=OrderState.UNKNOWN,
                client_order_id=lifecycle.client_order_id,
                detail=note + "order still pending at broker: do not resubmit",
            )
        lifecycle.transition(OrderState.FILLED_UNPROTECTED)
        return self._verify_stop(status.trade_id, lifecycle, candidate, note, filled_units=None)

    def _interpret_create_response(
        self,
        response: dict,
        lifecycle: OrderLifecycle,
        candidate: Candidate,
        sizing: SizingResult,
    ) -> OrderResult:
        if "orderRejectTransaction" in response:
            lifecycle.transition(OrderState.REJECTED)
            reason = response["orderRejectTransaction"].get("rejectReason", "unspecified")
            return OrderResult(
                state=OrderState.REJECTED,
                client_order_id=lifecycle.client_order_id,
                detail=f"broker rejected order: {reason}",
            )

        if "orderCancelTransaction" in response and "orderFillTransaction" not in response:
            lifecycle.transition(OrderState.CANCELLED)
            return OrderResult(
                state=OrderState.CANCELLED,
                client_order_id=lifecycle.client_order_id,
                detail="order cancelled without fill",
            )

        fill = response.get("orderFillTransaction")
        if fill is None:
            lifecycle.transition(OrderState.UNKNOWN)
            return OrderResult(
                state=OrderState.UNKNOWN,
                client_order_id=lifecycle.client_order_id,
                detail="unrecognized create-response shape: resolve via lookup before "
                "any further action",
            )

        broker_order_id = str(response.get("orderCreateTransaction", {}).get("id", ""))

        # --- partial-fill guard (§8.1, §21; finding 9) ------------------------
        filled_units = abs(int(Decimal(str(fill.get("units", "0")))))
        opened = fill.get("tradeOpened")
        if filled_units and filled_units != sizing.units:
            trade_id = str(opened.get("tradeID", "")) if opened else None
            lifecycle.transition(OrderState.FILLED_UNPROTECTED)
            lifecycle.transition(OrderState.STOP_MISSING)
            return OrderResult(
                state=OrderState.STOP_MISSING,
                client_order_id=lifecycle.client_order_id,
                broker_order_id=broker_order_id,
                trade_id=trade_id,
                filled_units=filled_units,
                detail=f"filled units {filled_units} != sized units {sizing.units} "
                "(partial fill): kill-switch class, flatten immediately (§8.1)",
            )

        if opened is None:
            # Netted/reduced fill shape (finding 6): our one-position invariant
            # was violated upstream — reconcile before anything else.
            lifecycle.transition(OrderState.UNKNOWN)
            return OrderResult(
                state=OrderState.UNKNOWN,
                client_order_id=lifecycle.client_order_id,
                broker_order_id=broker_order_id,
                filled_units=filled_units or None,
                detail="fill netted against existing exposure (no tradeOpened): "
                "halt and reconcile before proceeding (§8.1)",
            )

        trade_id = str(opened["tradeID"])
        lifecycle.transition(OrderState.FILLED_UNPROTECTED)
        return self._verify_stop(
            trade_id, lifecycle, candidate, note="", filled_units=filled_units or None,
            broker_order_id=broker_order_id,
        )

    def _verify_stop(
        self,
        trade_id: str | None,
        lifecycle: OrderLifecycle,
        candidate: Candidate,
        note: str,
        filled_units: int | None,
        broker_order_id: str | None = None,
    ) -> OrderResult:
        """Stop confirmation is a pipeline stage (§2). Any failure to CONFIRM
        is treated as stop-loss failure: STOP_MISSING, flatten immediately."""

        def stop_missing(detail: str) -> OrderResult:
            lifecycle.transition(OrderState.STOP_MISSING)
            return OrderResult(
                state=OrderState.STOP_MISSING,
                client_order_id=lifecycle.client_order_id,
                broker_order_id=broker_order_id,
                trade_id=trade_id,
                filled_units=filled_units,
                detail=note + detail + " — kill-switch trigger, flatten immediately (§8.1)",
            )

        if not trade_id:
            return stop_missing("fill carried no trade id; stop unverifiable")
        try:
            trade = self._transport.get_trade(trade_id)
        except (TimeoutError, TransportFailureError) as err:  # finding 10
            return stop_missing(f"stop verification unavailable ({err})")

        stop = (trade or {}).get("stopLossOrder")
        if stop is None:
            return stop_missing("filled but broker-held stop NOT present")
        state = str(stop.get("state", ""))
        if state not in ACTIVE_STOP_STATES:  # finding 6/16
            return stop_missing(f"stop present but state '{state}' is not active")
        if Decimal(str(stop.get("price", "0"))) != candidate.stop_price:
            return stop_missing(
                f"stop price {stop.get('price')} != required {candidate.stop_price}"
            )

        lifecycle.transition(OrderState.PROTECTED)
        return OrderResult(
            state=OrderState.PROTECTED,
            client_order_id=lifecycle.client_order_id,
            broker_order_id=broker_order_id,
            trade_id=trade_id,
            filled_units=filled_units,
            detail=note + "filled with broker-held stop confirmed active",
        )
