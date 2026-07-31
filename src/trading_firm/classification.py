"""Deterministic evidence classification (§5.1, §5.2) under amendment A-2.

Two jobs, both of which the firm previously had no code for.

**Ceiling.** A senior trader claims a novelty and an evidence class in its
thesis (§6.7). Deterministic code decides the maximum evidence class the data
actually supports, so a persuasive claim cannot exceed what the packet shows.
That is §5.2's rule stated as code: "a score or evidence class does not
authorize size. It only determines the maximum tier the deterministic risk gate
may consider."

**Under-claim.** A-2 (§6.6) makes the mirror case visible for the first time.
Over-claiming was already impossible — the ceiling clamps it. Under-claiming
was invisible: an agent holding E5 evidence that filed E3 produced no error, no
audit anomaly, and no scored penalty, which made caution free and imposed a
systematic negative bias on expectancy that nothing detected. `Classification`
now records the gap so the Learning Director can score it post-session.

**Pressure invariance (§5.1).** Every function here takes `MarketSnapshot` and
never `FirmSnapshot`. Firm state — equity, elapsed time, session or cumulative
P&L, trades taken, progress toward any aspiration — cannot reach classification
because it is not in scope of any signature in this module. It reaches the risk
gate instead, where §3.3 lets it only reduce. `tests/unit/test_classification.py`
pins the property across firm states, per §21.
"""

from __future__ import annotations

from dataclasses import dataclass

from trading_firm.adaptive import AdaptiveThesis, EvidenceClass, NoveltyClass
from trading_firm.packet import MarketSnapshot
from trading_firm.policy import AdaptivePolicyManifest

# Ordered worst-to-best so `min` expresses "the strictest cap wins".
_ORDER: tuple[EvidenceClass, ...] = (
    EvidenceClass.E0,
    EvidenceClass.E1,
    EvidenceClass.E2,
    EvidenceClass.E3,
    EvidenceClass.E4,
    EvidenceClass.E5,
)
_RANK = {ev: i for i, ev in enumerate(_ORDER)}


def _cap(current: EvidenceClass, limit: EvidenceClass) -> EvidenceClass:
    return current if _RANK[current] <= _RANK[limit] else limit


@dataclass(frozen=True)
class Classification:
    """The deterministic verdict on one thesis's claimed classes.

    `effective` is what the risk gate may act on. `under_claim` is the A-2
    signal: the trader could have justified more from the same packet.
    """

    market_id: str
    ceiling: EvidenceClass
    claimed: EvidenceClass
    effective: EvidenceClass
    novelty: NoveltyClass
    reasons: tuple[str, ...]

    @property
    def over_claim(self) -> bool:
        """The claim exceeded the data. Clamped, never honored."""
        return _RANK[self.claimed] > _RANK[self.ceiling]

    @property
    def under_claim(self) -> bool:
        """A-2 (§6.6): the data supported more than the trader claimed."""
        return _RANK[self.claimed] < _RANK[self.ceiling]

    @property
    def max_edge_tier(self) -> int:
        """The tier ceiling this classification unlocks — the stricter of the
        effective evidence class and the novelty class (§5.2, §6.8)."""
        ceiling = self.effective.max_edge_tier
        if not self.novelty.may_receive_exceptional:
            ceiling = min(ceiling, 3)
        if not self.novelty.may_trade_live:
            ceiling = 0
        return ceiling


def evidence_ceiling(
    market: MarketSnapshot,
    policy: AdaptivePolicyManifest,
) -> tuple[EvidenceClass, tuple[str, ...]]:
    """Maximum evidence class the packet supports, with the reason for each cap.

    Takes the market half only. Adding a `FirmSnapshot` parameter here would
    violate §5.1 and break `test_classification.py`'s invariance property.
    """
    reasons: list[str] = []

    # §5.2 E0 and §0.10: missing, stale, or incomplete evidence rejects outright.
    if not market.data_fresh:
        return EvidenceClass.E0, ("market data not fresh: E0 (§5.2, §0.10)",)
    if not market.bars_complete:
        return EvidenceClass.E0, ("bar series incomplete: E0 (§5.2, §0.10)",)
    if not market.calendar_state_known:
        return EvidenceClass.E0, ("economic-calendar state unknown: E0 (§5.2, §0.10)",)

    ceiling = EvidenceClass.E5

    # §11 / §6A freedom boundary: a feature outside the approved registry is an
    # untested indicator, which is E1 by definition (§5.2).
    unapproved = sorted(f for f in market.features if not policy.permits_feature(f))
    if unapproved:
        ceiling = _cap(ceiling, EvidenceClass.E1)
        reasons.append(
            f"features outside the approved registry {unapproved}: capped at E1 (§11, §5.2)"
        )

    # §5.2 E2: "limited analog support". §11 carries the required sample size.
    required = policy.required_analog_sample_size
    if required is not None and market.analog_sample_size < required:
        ceiling = _cap(ceiling, EvidenceClass.E2)
        reasons.append(
            f"analog sample {market.analog_sample_size} below the required {required}: "
            f"capped at E2 (§5.2, §11)"
        )

    # §5.3 exceptional gate: spread and slippage within limits.
    if market.spread_pips > policy.max_spread_pips:
        ceiling = _cap(ceiling, EvidenceClass.E3)
        reasons.append(
            f"spread {market.spread_pips} pips above the {policy.max_spread_pips} limit: "
            f"capped at E3 (§5.3)"
        )

    # §5.3 exceptional gate: no disqualifying high-impact event present.
    if market.high_impact_event_active:
        ceiling = _cap(ceiling, EvidenceClass.E3)
        reasons.append("high-impact event active: capped at E3 (§5.3)")

    if not reasons:
        reasons.append("no deterministic cap applied: ceiling E5 (§5.2)")
    return ceiling, tuple(reasons)


def classify(
    thesis: AdaptiveThesis,
    market: MarketSnapshot,
    policy: AdaptivePolicyManifest,
) -> Classification:
    """Reconcile a trader's claimed classes against what the packet supports.

    The thesis is read for its *claims* only. No firm state participates, so
    the result is reproducible from `market` alone — which is what makes the
    §21 invariance test meaningful rather than circular.
    """
    ceiling, reasons = evidence_ceiling(market, policy)
    claimed = thesis.evidence_class
    effective = _cap(claimed, ceiling)

    notes = list(reasons)
    if _RANK[claimed] > _RANK[ceiling]:
        notes.append(
            f"claimed {claimed.value} exceeds the deterministic ceiling {ceiling.value}: "
            f"clamped to {effective.value} (§5.2)"
        )
    elif _RANK[claimed] < _RANK[ceiling]:
        # Not an error and not a clamp — a scored calibration signal (A-2).
        notes.append(
            f"claimed {claimed.value} below the supported ceiling {ceiling.value}: "
            f"under-claim recorded for post-session review (A-2, §6.6)"
        )

    return Classification(
        market_id=market.checksum,
        ceiling=ceiling,
        claimed=claimed,
        effective=effective,
        novelty=thesis.novelty_class,
        reasons=tuple(notes),
    )
