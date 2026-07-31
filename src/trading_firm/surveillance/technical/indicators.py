"""Registry-gated indicator observation (§30.3.C, §30.7).

The Indicator and Feature Monitor monitors only indicators present in the
approved registry. Here that is a hard gate, not a filter: handing this
module a feature id the gate does not permit raises, because a silently
dropped observation and a silently accepted one are both drift — the first
hides coverage loss, the second is the unregistered-indicator path §30.7
closes.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Mapping
from decimal import Decimal

from trading_firm.surveillance.schemas import IndicatorObservation

PermitsFeature = Callable[[str], bool]


def observe_indicators(
    features: Mapping[str, Decimal],
    permits: PermitsFeature,
    observed_at: dt.datetime,
) -> list[IndicatorObservation]:
    """Typed observations for every supplied feature value.

    `permits` is the adaptive policy manifest's `permits_feature` — the same
    gate classification consults (§30.7: one registry, no second one).
    """
    rejected = sorted(fid for fid in features if not permits(fid))
    if rejected:
        raise ValueError(
            f"unregistered feature ids {rejected}: the Indicator and Feature "
            f"Monitor observes only registry members (§30.7)"
        )
    return [
        IndicatorObservation(feature_id=fid, value=value, observed_at=observed_at)
        for fid, value in sorted(features.items())
    ]
