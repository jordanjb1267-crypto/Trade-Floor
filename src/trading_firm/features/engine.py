"""Deterministic session feature engine (§8.1): versioned, no future leakage.

Features for a session are computed at the Asian-range-final boundary using
ONLY bars that opened strictly before it. Reproducing a historical session
and computing it live must give identical values (§8.1 Feature Engine).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from zoneinfo import ZoneInfo

from trading_firm.market_data.bars import BarSeries
from trading_firm.sessions.clock import SessionClock

FEATURES_VERSION = "session_features_v1"
LONDON = ZoneInfo("Europe/London")

ASIAN_WINDOW_START_LONDON = dt.time(0, 0)
PRE_LONDON_WINDOW = dt.timedelta(hours=1)


@dataclass(frozen=True)
class SessionFeatures:
    """Versioned deterministic features for one session date."""

    feature_version: str
    session_date: dt.date
    computed_at: dt.datetime  # the boundary; no bar at/after it contributed
    asian_high: Decimal
    asian_low: Decimal
    asian_width_pips: Decimal
    asian_bar_count: int
    pre_london_range_pips: Decimal
    compression_ratio: Decimal  # pre-London range / Asian width (0 if width 0)


def session_features(
    series: BarSeries,
    session_date: dt.date,
    clock: SessionClock,
    pip_size: Decimal = Decimal("0.0001"),
) -> SessionFeatures | None:
    """Compute features at the Asian-range-final boundary. None if data missing.

    Fail closed (§0.10): a session with no Asian-window bars produces no
    features and therefore no candidates.
    """
    boundary = clock.boundaries(session_date)["asian_range_final"]
    window_start = dt.datetime.combine(session_date, ASIAN_WINDOW_START_LONDON, tzinfo=LONDON)

    asian_bars = series.between(window_start, boundary)
    if not asian_bars:
        return None

    asian_high = max(bar.high for bar in asian_bars)
    asian_low = min(bar.low for bar in asian_bars)
    width_pips = (asian_high - asian_low) / pip_size

    pre_bars = series.between(boundary - PRE_LONDON_WINDOW, boundary)
    if pre_bars:
        pre_range = (max(b.high for b in pre_bars) - min(b.low for b in pre_bars)) / pip_size
    else:
        pre_range = Decimal("0")

    compression = pre_range / width_pips if width_pips > 0 else Decimal("0")

    return SessionFeatures(
        feature_version=FEATURES_VERSION,
        session_date=session_date,
        computed_at=boundary,
        asian_high=asian_high,
        asian_low=asian_low,
        asian_width_pips=width_pips,
        asian_bar_count=len(asian_bars),
        pre_london_range_pips=pre_range,
        compression_ratio=compression.quantize(Decimal("0.01")),
    )
