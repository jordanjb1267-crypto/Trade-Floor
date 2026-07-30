"""Order-state reconciler (§8.1, §18): broker state is authoritative.

Implements the full §18 restart checklist, hardened per the 2026-07-30
adversarial review (findings 4, 13, 14, 19):

- per-trade field comparison (instrument, signed units), not just id sets;
- §18 step 4: every open broker trade must carry a broker-held stop in an
  active state — and at the locally-expected price where known; anything
  else is a STOP_MISSING-class position discrepancy;
- pending orders unknown to the local book are position-class discrepancies;
- any position-class discrepancy HALTs; equity-only mismatch is manage-only.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal

EQUITY_TOLERANCE = Decimal("0.01")
ACTIVE_STOP_STATES = frozenset({"PENDING"})


class StartupMode(enum.Enum):
    NORMAL = "NORMAL"
    MANAGE_ONLY = "MANAGE_ONLY"
    HALTED = "HALTED"


@dataclass(frozen=True)
class LocalTradeRecord:
    """What the runtime believes about one open trade."""

    trade_id: str
    instrument: str
    units: int  # signed
    stop_price: Decimal


@dataclass(frozen=True)
class BrokerTradeRecord:
    """One open trade as reported by the broker."""

    trade_id: str
    instrument: str
    units: int  # signed
    stop_price: Decimal | None
    stop_state: str | None

    @classmethod
    def from_v20(cls, trade: dict) -> BrokerTradeRecord:
        stop = trade.get("stopLossOrder")
        return cls(
            trade_id=str(trade["id"]),
            instrument=str(trade.get("instrument", "")),
            units=int(Decimal(str(trade.get("currentUnits", "0")))),
            stop_price=Decimal(str(stop["price"])) if stop and "price" in stop else None,
            stop_state=str(stop.get("state")) if stop else None,
        )


@dataclass(frozen=True)
class LocalBook:
    """What the runtime believes it holds."""

    trades: tuple[LocalTradeRecord, ...] = ()
    pending_order_ids: frozenset[str] = frozenset()
    closed_equity: Decimal = Decimal("0")


@dataclass(frozen=True)
class ReconciliationResult:
    clean: bool
    entries_enabled: bool
    position_discrepancies: tuple[str, ...] = field(default_factory=tuple)
    equity_discrepancies: tuple[str, ...] = field(default_factory=tuple)

    @property
    def discrepancies(self) -> tuple[str, ...]:
        return self.position_discrepancies + self.equity_discrepancies


def reconcile(
    local: LocalBook,
    *,
    broker_trades: list[BrokerTradeRecord],
    broker_balance: Decimal,
    broker_pending_order_ids: set[str] | frozenset[str] = frozenset(),
) -> ReconciliationResult:
    position_issues: list[str] = []
    equity_issues: list[str] = []

    local_by_id = {trade.trade_id: trade for trade in local.trades}
    broker_by_id = {trade.trade_id: trade for trade in broker_trades}

    for trade_id in sorted(set(broker_by_id) - set(local_by_id)):
        position_issues.append(
            f"broker holds trade {trade_id} unknown to local book (broker is authoritative)"
        )
    for trade_id in sorted(set(local_by_id) - set(broker_by_id)):
        position_issues.append(
            f"local book holds trade {trade_id} that broker does not report"
        )

    for trade_id in sorted(set(local_by_id) & set(broker_by_id)):
        local_trade, broker_trade = local_by_id[trade_id], broker_by_id[trade_id]
        if broker_trade.instrument != local_trade.instrument:
            position_issues.append(
                f"trade {trade_id}: instrument mismatch "
                f"({broker_trade.instrument} vs local {local_trade.instrument})"
            )
        if broker_trade.units != local_trade.units:  # finding 13
            position_issues.append(
                f"trade {trade_id}: units mismatch "
                f"(broker {broker_trade.units} vs local {local_trade.units})"
            )

    # --- §18 step 4: verify protective stops (findings 4, 14) ----------------
    for broker_trade in sorted(broker_trades, key=lambda t: t.trade_id):
        if broker_trade.stop_price is None or broker_trade.stop_state not in ACTIVE_STOP_STATES:
            position_issues.append(
                f"trade {broker_trade.trade_id}: broker-held stop not confirmed active "
                f"(price={broker_trade.stop_price}, state={broker_trade.stop_state}) — "
                "STOP_MISSING class (§0.9, §8.1)"
            )
            continue
        expected = local_by_id.get(broker_trade.trade_id)
        if expected is not None and broker_trade.stop_price != expected.stop_price:
            position_issues.append(
                f"trade {broker_trade.trade_id}: stop price {broker_trade.stop_price} "
                f"!= expected {expected.stop_price} — STOP_MISSING class (§0.9)"
            )

    # --- pending orders (§18 step 2 includes orders; finding 19) -------------
    for order_id in sorted(set(broker_pending_order_ids) - set(local.pending_order_ids)):
        position_issues.append(
            f"broker holds pending order {order_id} unknown to local book"
        )
    for order_id in sorted(set(local.pending_order_ids) - set(broker_pending_order_ids)):
        position_issues.append(
            f"local book expects pending order {order_id} that broker does not report"
        )

    if abs(broker_balance - local.closed_equity) > EQUITY_TOLERANCE:
        equity_issues.append(
            f"equity mismatch: broker {broker_balance} vs local {local.closed_equity}"
        )

    clean = not position_issues and not equity_issues
    return ReconciliationResult(
        clean=clean,
        entries_enabled=clean,  # fail closed (§0.10)
        position_discrepancies=tuple(position_issues),
        equity_discrepancies=tuple(equity_issues),
    )


def startup_mode(result: ReconciliationResult) -> StartupMode:
    """§18: reconcile before anything; halt on position uncertainty."""
    if result.position_discrepancies:
        return StartupMode.HALTED
    if result.equity_discrepancies:
        return StartupMode.MANAGE_ONLY
    return StartupMode.NORMAL
