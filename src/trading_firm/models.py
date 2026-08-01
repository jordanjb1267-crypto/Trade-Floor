"""Domain models for the deterministic core (governing spec §8, §10.2).

Frozen dataclasses and Decimal money math throughout: risk-critical values
never pass through binary floats.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

CENT = Decimal("0.01")


def cents(value: Decimal) -> Decimal:
    """Quantize a dollar amount down to whole cents (never round risk up)."""
    return value.quantize(CENT, rounding=ROUND_DOWN)


class EdgeTier(enum.IntEnum):
    """§5.2 — score determines the MAXIMUM tier the risk gate may consider."""

    NONE = 0
    STANDARD = 1
    STRONG = 2
    HIGH = 3
    EXCEPTIONAL = 4


def tier_from_score(score: int) -> EdgeTier:
    """§5.2 classification thresholds. Scores are integers (§5.2, v1.1.0)."""
    if not 0 <= score <= 100:
        raise ValueError(f"edge score must be an integer in [0, 100], got {score}")
    if score < 70:
        return EdgeTier.NONE
    if score < 80:
        return EdgeTier.STANDARD
    if score < 90:
        return EdgeTier.STRONG
    if score < 95:
        return EdgeTier.HIGH
    return EdgeTier.EXCEPTIONAL


class DrawdownState(enum.Enum):
    """§4.5 drawdown-state machine states."""

    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    RESTRICTED = "RESTRICTED"
    SHADOW = "SHADOW"


class Direction(enum.Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(frozen=True)
class InstrumentSpec:
    """Broker-reported instrument facts. margin_rate is PER-INSTRUMENT (§3.2, F-1)."""

    name: str
    margin_rate: Decimal
    pip_location: int = -4
    minimum_trade_size: int = 1
    trade_units_precision: int = 0

    @property
    def pip_size(self) -> Decimal:
        return Decimal(10) ** self.pip_location


@dataclass(frozen=True)
class AccountState:
    """Reconciled account facts at decision time. Losses are positive numbers."""

    closed_equity: Decimal
    tier_anchor: Decimal
    session_realized_loss: Decimal = Decimal("0")
    weekly_realized_loss: Decimal = Decimal("0")
    trades_this_session: int = 0
    exceptional_trades_this_session: int = 0
    open_positions: int = 0
    reconciled: bool = True
    broker_healthy: bool = True


@dataclass(frozen=True)
class Candidate:
    """Schema-valid strategy candidate (§8.1). Candidates never carry size."""

    instrument: str
    strategy_id: str
    strategy_version: str
    direction: Direction
    entry_price: Decimal
    stop_price: Decimal
    edge_score: int
    created_at: datetime
    expires_at: datetime
    data_fresh: bool
    news_state_known: bool
    stop_broker_compatible: bool
    human_approval: bool = False
    # A-2 (§5.1, §6.6): the tier ceiling the thesis's own novelty x evidence
    # classification permits, from classification.Classification.max_edge_tier.
    # None for a candidate produced by a named strategy rather than an adaptive
    # thesis. The risk engine may only LOWER the tier with it — a thesis cannot
    # raise what the evidence score set (§5.2).
    thesis_ceiling: EdgeTier | None = None

    def stop_distance(self) -> Decimal:
        distance = abs(self.entry_price - self.stop_price)
        if distance <= 0:
            raise ValueError("stop must differ from entry (§3.3: stop is defined first)")
        return distance

    def stop_distance_pips(self, spec: InstrumentSpec) -> Decimal:
        return self.stop_distance() / spec.pip_size

    def content_key(self) -> str:
        """Content hash identifying THIS candidate exactly.

        Binds risk decisions and sizing results to the candidate they were
        issued for (review finding 8/12), and serves as the idempotency key
        material — distinct candidates never collide (finding 1/18) because
        entry, stop, and the full creation timestamp participate.
        """
        import hashlib

        material = "|".join(
            [
                self.instrument,
                self.strategy_id,
                self.strategy_version,
                self.direction.value,
                str(self.entry_price),
                str(self.stop_price),
                self.created_at.isoformat(),
            ]
        )
        return hashlib.sha256(material.encode()).hexdigest()


@dataclass(frozen=True)
class RiskDecision:
    """Immutable approval/rejection record (§8.1 Risk Engine).

    candidate_key binds the decision to exactly one candidate: the broker
    adapter refuses approvals minted for a different candidate (§2).
    """

    approved: bool
    tier: EdgeTier
    allowed_risk_usd: Decimal
    reasons: tuple[str, ...]
    candidate_key: str
    binding_constraint: str | None = None
    # A-2 / §25: the audit record must distinguish a GATE-bound decision from a
    # THESIS-bound one. `binding_constraint` already names which capacity bound
    # the dollar amount; these two name what bound the TIER. Without them a
    # trader that under-classified its own opportunity is indistinguishable from
    # one the risk engine correctly restrained, which is precisely the case A-2
    # exists to make visible.
    thesis_ceiling: EdgeTier | None = None
    tier_bound_by: str | None = None


@dataclass(frozen=True)
class SizingResult:
    """Deterministic sizing output (§8.1 Position Sizing Engine)."""

    approved: bool
    units: int
    effective_risk_usd: Decimal
    margin_required_usd: Decimal
    reasons: tuple[str, ...]
    candidate_key: str


@dataclass(frozen=True)
class PendingPromotion:
    """§4.2 (D-2): deterministic conditions ARM a promotion; only the owner applies it."""

    from_anchor: Decimal
    to_anchor: Decimal
    armed_at: datetime
    expires_at: datetime
