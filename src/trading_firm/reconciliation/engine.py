"""Order-state reconciler (§8.1, §18): broker state is authoritative.

Any mismatch between local records and broker reality disables new entries.
Position-level discrepancies HALT; equity-only discrepancies allow
manage-only operation; a clean pass restores normal mode (§18 restart
sequence steps 2–6).
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from decimal import Decimal

EQUITY_TOLERANCE = Decimal("0.01")


class StartupMode(enum.Enum):
    NORMAL = "NORMAL"
    MANAGE_ONLY = "MANAGE_ONLY"
    HALTED = "HALTED"


@dataclass(frozen=True)
class LocalBook:
    """What the runtime believes it holds."""

    open_trade_ids: frozenset[str] = frozenset()
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
    broker_open_trade_ids: set[str],
    broker_balance: Decimal,
) -> ReconciliationResult:
    position_issues: list[str] = []
    equity_issues: list[str] = []

    for trade_id in sorted(broker_open_trade_ids - set(local.open_trade_ids)):
        position_issues.append(
            f"broker holds trade {trade_id} unknown to local book (broker is authoritative)"
        )
    for trade_id in sorted(set(local.open_trade_ids) - broker_open_trade_ids):
        position_issues.append(
            f"local book holds trade {trade_id} that broker does not report"
        )
    if abs(broker_balance - local.closed_equity) > EQUITY_TOLERANCE:
        equity_issues.append(
            f"equity mismatch: broker {broker_balance} vs local {local.closed_equity}"
        )

    clean = not position_issues and not equity_issues
    return ReconciliationResult(
        clean=clean,
        entries_enabled=clean,  # fail closed (§0.10): any mismatch disables entries
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
