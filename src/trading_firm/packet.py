"""Market State Packet (§6A) with the A-2 market/firm split.

§6A requires one immutable, deterministically generated packet delivered to
both senior traders under the same checksum. Its field list mixes two input
classes that A-2 (§5.1) requires be kept apart:

- **market-derived state** — bid/ask, bars, features, volatility, event state.
  A function of the market. May raise the tier ceiling the risk gate considers.
- **firm state** — positions, P&L, risk capacity. A function of us. Reaches the
  deterministic risk gate, where it may only *reduce* allowed risk (§3.3).

Both are needed: a trader that cannot see it has no capacity cannot correctly
decline. But they must not be interchangeable, because conviction-driven and
pressure-driven sizing produce the same action and differ only in which of
these two an implementation read. §5.1 therefore requires classification to be
a pure function of the market half.

That requirement is made structural rather than procedural here. `MarketSnapshot`
and `FirmSnapshot` are separate types, and every classification entry point
accepts only the former, so reading firm state during classification is a type
error rather than a review finding — the M-1 move that made tier-raising
unrepresentable rather than merely prohibited.

`FirmSnapshot` cannot carry a profit target, elapsed-day count, or progress
toward any goal. There are no such fields, and `config.profit_target` is
annotated `None` (§3.5), so there is nothing for one to be derived from.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal

from trading_firm.models import AccountState, DrawdownState

PACKET_VERSION = "market_state_packet_v1"


def _canonical(value: object) -> object:
    """Serialize deterministically: same inputs -> same bytes, across processes."""
    if isinstance(value, Decimal):
        # Normalized text, so Decimal("38") and Decimal("38.0") agree.
        return f"{value.normalize():f}"
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            raise ValueError("packet datetimes must be timezone-aware (§10.3)")
        return value.astimezone(dt.UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in value]
    if isinstance(value, DrawdownState):
        return value.value
    raise TypeError(f"packet field type is not canonically serializable: {type(value)!r}")


def _digest(payload: Mapping[str, object]) -> str:
    blob = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class MarketSnapshot:
    """The evidence-bearing half of the packet (§6A).

    Every field is a property of the market or of our data about the market.
    Nothing here describes the firm's position, performance, or ambitions —
    that separation is what makes §5.1 pressure invariance testable.
    """

    instrument: str
    observed_at: dt.datetime
    session_date: dt.date
    session_phase: str
    regime: str
    volatility_state: str
    bid: Decimal
    ask: Decimal
    spread_pips: Decimal
    feature_version: str
    features: Mapping[str, Decimal] = field(default_factory=dict)
    analog_sample_size: int = 0
    data_fresh: bool = True
    bars_complete: bool = True
    calendar_state_known: bool = True
    high_impact_event_active: bool = False

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware (§10.3)")
        if self.ask < self.bid:
            raise ValueError(f"ask {self.ask} below bid {self.bid}: malformed quote (§0.10)")
        if self.analog_sample_size < 0:
            raise ValueError("analog_sample_size cannot be negative")
        object.__setattr__(self, "features", dict(self.features))

    @property
    def checksum(self) -> str:
        """The value §6A requires both senior traders to receive identically."""
        return _digest(
            {
                "packet_version": PACKET_VERSION,
                "instrument": self.instrument,
                "observed_at": self.observed_at,
                "session_date": self.session_date,
                "session_phase": self.session_phase,
                "regime": self.regime,
                "volatility_state": self.volatility_state,
                "bid": self.bid,
                "ask": self.ask,
                "spread_pips": self.spread_pips,
                "feature_version": self.feature_version,
                "features": self.features,
                "analog_sample_size": self.analog_sample_size,
                "data_fresh": self.data_fresh,
                "bars_complete": self.bars_complete,
                "calendar_state_known": self.calendar_state_known,
                "high_impact_event_active": self.high_impact_event_active,
            }
        )


@dataclass(frozen=True)
class FirmSnapshot:
    """The capacity-bearing half of the packet (§6A).

    Reaches the deterministic risk gate, where §3.3 lets it only reduce allowed
    risk. It must never reach classification (§5.1), and no classification
    entry point in this package accepts it.

    There is deliberately no profit target, elapsed-day count, distance-to-goal,
    or cumulative-return field. §3.5 forbids the firm from having a target at
    all, and `config.profit_target` is typed `None`, so no such value exists to
    place here.
    """

    closed_equity: Decimal
    tier_anchor: Decimal
    drawdown_state: DrawdownState
    session_realized_loss: Decimal = Decimal("0")
    weekly_realized_loss: Decimal = Decimal("0")
    trades_this_session: int = 0
    exceptional_trades_this_session: int = 0
    open_positions: int = 0
    reconciled: bool = True
    broker_healthy: bool = True

    @classmethod
    def from_account(cls, account: AccountState, state: DrawdownState) -> FirmSnapshot:
        return cls(
            closed_equity=account.closed_equity,
            tier_anchor=account.tier_anchor,
            drawdown_state=state,
            session_realized_loss=account.session_realized_loss,
            weekly_realized_loss=account.weekly_realized_loss,
            trades_this_session=account.trades_this_session,
            exceptional_trades_this_session=account.exceptional_trades_this_session,
            open_positions=account.open_positions,
            reconciled=account.reconciled,
            broker_healthy=account.broker_healthy,
        )

    @property
    def checksum(self) -> str:
        return _digest(
            {
                "packet_version": PACKET_VERSION,
                "closed_equity": self.closed_equity,
                "tier_anchor": self.tier_anchor,
                "drawdown_state": self.drawdown_state,
                "session_realized_loss": self.session_realized_loss,
                "weekly_realized_loss": self.weekly_realized_loss,
                "trades_this_session": self.trades_this_session,
                "exceptional_trades_this_session": self.exceptional_trades_this_session,
                "open_positions": self.open_positions,
                "reconciled": self.reconciled,
                "broker_healthy": self.broker_healthy,
            }
        )


@dataclass(frozen=True)
class MarketStatePacket:
    """§6A: one immutable packet, one checksum, delivered to Alpha and Beta.

    `packet_id` covers both halves, so a trader that received a different firm
    state received a different packet and the audit trail shows it. `market_id`
    covers the market half alone: it is the identity under which classification
    must be reproducible, and the key the §5.1 invariance property is stated in
    terms of.
    """

    market: MarketSnapshot
    firm: FirmSnapshot

    @property
    def market_id(self) -> str:
        return self.market.checksum

    @property
    def packet_id(self) -> str:
        return _digest(
            {
                "packet_version": PACKET_VERSION,
                "market": self.market.checksum,
                "firm": self.firm.checksum,
            }
        )

    def verify(self, expected_packet_id: str) -> None:
        """Fail closed on a mutated packet (§0.10, §6A)."""
        actual = self.packet_id
        if actual != expected_packet_id:
            raise ValueError(
                f"market state packet checksum mismatch: expected {expected_packet_id}, "
                f"computed {actual} — the packet was mutated after issue (§6A, §0.10)"
            )
