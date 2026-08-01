"""Registered cross-market relationships (§30.3.G) — versioned expectations.

A relationship is a REGISTERED expectation (this pair usually co-moves, that
pair usually inverts), never a discovered one: the Cross-Market Monitor
tracks approved contextual instruments only, and an expectation enters the
registry with a version, not a hunch. The rolling statistic here is the
deterministic measurement an expectation is checked against.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

RELATIONSHIP_LOGIC_VERSION = "surveillance_relationships_v1"


@dataclass(frozen=True)
class RegisteredRelationship:
    relationship_id: str
    instrument_a: str
    instrument_b: str
    expected: Literal["co_moving", "inverse"]
    version: str = RELATIONSHIP_LOGIC_VERSION


def rolling_agreement(
    returns_a: list[Decimal], returns_b: list[Decimal]
) -> Decimal | None:
    """Fraction of aligned observation pairs moving the same direction, in
    [-1, 1] (sign-agreement, not Pearson — robust on short FX windows and
    exactly reproducible in Decimal). None when under-observed."""
    if len(returns_a) != len(returns_b):
        raise ValueError("return series must be aligned (§30.4)")
    pairs = [
        (a, b)
        for a, b in zip(returns_a, returns_b, strict=True)
        if a != 0 and b != 0
    ]
    if len(pairs) < 5:
        return None
    same = sum(1 for a, b in pairs if (a > 0) == (b > 0))
    return (Decimal(2 * same) / Decimal(len(pairs))) - Decimal(1)
