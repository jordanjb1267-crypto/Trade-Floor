"""Versioned regime classification (§30.3.E) over the controlled labels.

Version 1 classifies from the two feature families the registry carries:
compression (Asian range vs pre-London range) and prior-session direction.
The classifier is deliberately conservative — INDETERMINATE whenever the
evidence is absent — because a wrong regime label with a confident name is
worse than an honest unknown (§30.1 rule 8), and the labels feed briefings,
never the risk gate.

Every label cites the feature ids it was computed from; the schema refuses a
substantive label with no evidence.
"""

from __future__ import annotations

from decimal import Decimal

from trading_firm.surveillance.schemas import RegimeState, SurveillanceRegime

REGIME_CLASSIFIER_VERSION = "surveillance_regime_v1"

# Compression-ratio bands: pre-London range as a fraction of the Asian range.
# Below the floor the pre-London hour is coiling inside the Asian range;
# above the ceiling it is already moving more than the whole Asian session.
COMPRESSION_FLOOR = Decimal("0.5")
EXPANSION_CEILING = Decimal("1.5")


def classify_intraday(
    compression_ratio: Decimal | None,
) -> tuple[SurveillanceRegime, list[str]]:
    if compression_ratio is None:
        return SurveillanceRegime.INDETERMINATE, []
    evidence = ["session_features_v1.compression_ratio"]
    if compression_ratio <= COMPRESSION_FLOOR:
        return SurveillanceRegime.COMPRESSING, evidence
    if compression_ratio >= EXPANSION_CEILING:
        return SurveillanceRegime.EXPANDING, evidence
    return SurveillanceRegime.TRANSITIONAL, evidence


def classify_daily(
    net_move_pips: Decimal | None,
    asian_width_pips: Decimal | None,
) -> tuple[SurveillanceRegime, list[str]]:
    """Prior-session direction vs the current Asian range: a prior move that
    dwarfs today's range reads as trending context; comparable sizes read as
    mean-reverting balance."""
    if net_move_pips is None or asian_width_pips is None or asian_width_pips <= 0:
        return SurveillanceRegime.INDETERMINATE, []
    evidence = [
        "structure_features_v1.net_move_pips",
        "session_features_v1.asian_width_pips",
    ]
    if abs(net_move_pips) >= asian_width_pips * 2:
        return SurveillanceRegime.TRENDING, evidence
    return SurveillanceRegime.MEAN_REVERTING, evidence


def classify(
    compression_ratio: Decimal | None,
    net_move_pips: Decimal | None,
    asian_width_pips: Decimal | None,
) -> RegimeState:
    intraday, intraday_evidence = classify_intraday(compression_ratio)
    daily, daily_evidence = classify_daily(net_move_pips, asian_width_pips)
    # The session horizon needs intra-session bars v1 does not consume;
    # claiming a label without them would be prose in a vocabulary.
    return RegimeState(
        intraday=intraday,
        session=SurveillanceRegime.INDETERMINATE,
        daily=daily,
        evidence_feature_ids=sorted({*intraday_evidence, *daily_evidence}),
        classifier_version=REGIME_CLASSIFIER_VERSION,
    )
