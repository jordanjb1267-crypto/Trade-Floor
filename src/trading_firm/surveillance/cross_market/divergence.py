"""Cross-market divergence detection (§30.3.G, §30.6).

A divergence is a measured breakdown of a registered expectation: a
co-moving pair whose sign-agreement went negative, or an inverse pair whose
agreement went positive, past the threshold. Under-observed windows return
no verdict at all — an absent measurement is not a confirmation and not a
divergence (§30.1 rule 8).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from trading_firm.surveillance.cross_market.relationships import (
    RegisteredRelationship,
    rolling_agreement,
)

DIVERGENCE_THRESHOLD = Decimal("0.4")


@dataclass(frozen=True)
class DivergenceFinding:
    relationship_id: str
    agreement: Decimal
    diverging: bool
    logic_version: str


def evaluate(
    relationship: RegisteredRelationship,
    returns_a: list[Decimal],
    returns_b: list[Decimal],
    threshold: Decimal = DIVERGENCE_THRESHOLD,
) -> DivergenceFinding | None:
    agreement = rolling_agreement(returns_a, returns_b)
    if agreement is None:
        return None
    if relationship.expected == "co_moving":
        diverging = agreement < -threshold
    else:
        diverging = agreement > threshold
    return DivergenceFinding(
        relationship_id=relationship.relationship_id,
        agreement=agreement,
        diverging=diverging,
        logic_version=relationship.version,
    )
