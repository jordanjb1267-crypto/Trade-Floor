"""Per-component freshness (§30.4) — never one global threshold.

Each component must have its own freshness threshold. Do not use one global
threshold for all data (§30.4): broker prices age in seconds, the economic
calendar in hours, and a single number is either uselessly loose for prices
or absurdly tight for the calendar. The thresholds type therefore takes an
explicit per-component mapping and has no default-for-everything constructor.

Pure functions of (timestamps, thresholds, now); pressure-blind by content
and by guard.
"""

from __future__ import annotations

import datetime as dt
import enum
from collections.abc import Mapping
from dataclasses import dataclass

from trading_firm.surveillance.schemas import DataQuality, DataQualityStatus


class ComponentStatus(enum.StrEnum):
    FRESH = "fresh"
    STALE = "stale"
    MISSING = "missing"


@dataclass(frozen=True)
class FreshnessThresholds:
    """Explicit seconds-per-component. Constructing one threshold for
    everything is unrepresentable: the mapping is required, and a component
    absent from it cannot be evaluated at all (fail closed, §30.1 rule 8)."""

    seconds_by_component: Mapping[str, int]

    def __post_init__(self) -> None:
        if not self.seconds_by_component:
            raise ValueError("freshness thresholds require at least one component (§30.4)")
        bad = {k: v for k, v in self.seconds_by_component.items() if v <= 0}
        if bad:
            raise ValueError(f"non-positive freshness thresholds: {bad} (§30.4)")
        object.__setattr__(self, "seconds_by_component", dict(self.seconds_by_component))

    def for_component(self, component: str) -> int:
        try:
            return self.seconds_by_component[component]
        except KeyError:
            raise KeyError(
                f"no freshness threshold declared for component {component!r}: a "
                f"component without its own threshold cannot be called fresh (§30.4)"
            ) from None


def component_status(
    last_update: dt.datetime | None,
    component: str,
    thresholds: FreshnessThresholds,
    now: dt.datetime,
) -> ComponentStatus:
    if last_update is None:
        return ComponentStatus.MISSING
    if last_update.tzinfo is None or now.tzinfo is None:
        raise ValueError("freshness compares aware datetimes only (§30.4, C-2)")
    age = (now - last_update).total_seconds()
    limit = thresholds.for_component(component)
    return ComponentStatus.FRESH if age <= limit else ComponentStatus.STALE


def assess(
    last_updates: Mapping[str, dt.datetime | None],
    thresholds: FreshnessThresholds,
    required: frozenset[str],
    now: dt.datetime,
) -> DataQuality:
    """Synthesize component statuses into the §30.4 data-quality block.

    FAILED when every required component is unusable, DEGRADED when any
    component (required or not) is stale or missing, HEALTHY only when
    everything present is fresh. The HEALTHY-with-problems state is already
    unrepresentable at the schema layer; this function is where the honest
    statuses come from.
    """
    stale: list[str] = []
    missing: list[str] = []
    for component, last_update in sorted(last_updates.items()):
        status = component_status(last_update, component, thresholds, now)
        if status is ComponentStatus.STALE:
            stale.append(component)
        elif status is ComponentStatus.MISSING:
            missing.append(component)

    unusable = set(stale) | set(missing)
    required_unusable = required & unusable
    if required and required_unusable == required:
        overall = DataQualityStatus.FAILED
    elif unusable:
        overall = DataQualityStatus.DEGRADED
    else:
        overall = DataQualityStatus.HEALTHY
    return DataQuality(
        overall_status=overall,
        stale_components=stale,
        missing_components=missing,
        conflicting_components=[],
    )
