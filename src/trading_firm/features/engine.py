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
    # Coverage guard (§0.10): a partially-covered Asian window yields a
    # truncated range — too narrow, so the breakout triggers early and the
    # stop sits in the wrong place. A fixture that simply starts mid-window
    # must fail closed like missing data, not silently emit phantom trades.
    if asian_bars[0].ts > window_start + dt.timedelta(minutes=series.granularity_minutes):
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


STRUCTURE_FEATURES_VERSION = "structure_features_v1"
MAX_PRIOR_LOOKBACK_DAYS = 5


@dataclass(frozen=True)
class PriorSessionStructure:
    """Prior London trading-window structure serving a CURRENT session.

    No-lookahead by construction: only bars from a prior day's
    activation->flatten window contribute, all of which close before the
    current session's activation boundary (recorded as computed_at)."""

    feature_version: str
    session_date: dt.date  # the current session these features serve
    prior_session_date: dt.date  # the prior session actually used
    computed_at: dt.datetime
    prior_window_open: Decimal
    prior_window_close: Decimal
    net_move_pips: Decimal  # signed: positive = bullish prior session


def prior_session_structure(
    series: BarSeries,
    session_date: dt.date,
    clock: SessionClock,
    pip_size: Decimal = Decimal("0.0001"),
) -> PriorSessionStructure | None:
    """London-window direction of the nearest prior day with data.

    Walks back at most MAX_PRIOR_LOOKBACK_DAYS calendar days (weekends and
    holidays have no bars and are skipped). Fail closed (§0.10): no prior
    data — or only a PARTIALLY covered prior window — yields None, hence no
    candidates.
    """
    current_activation = clock.boundaries(session_date)["activation"]
    step = dt.timedelta(minutes=series.granularity_minutes)
    for back in range(1, MAX_PRIOR_LOOKBACK_DAYS + 1):
        prior_date = session_date - dt.timedelta(days=back)
        prior = clock.boundaries(prior_date)
        bars = series.between(prior["activation"], prior["flatten"])
        if not bars:
            continue
        # A partially-covered prior window is not "validated structure": a
        # single bar's open-to-close would gate live entries on almost no
        # evidence. Treat it as no data and keep walking back (§0.10).
        if bars[0].ts > prior["activation"] + step or bars[-1].ts < prior["flatten"] - step:
            continue
        return PriorSessionStructure(
            feature_version=STRUCTURE_FEATURES_VERSION,
            session_date=session_date,
            prior_session_date=prior_date,
            computed_at=current_activation,
            prior_window_open=bars[0].open,
            prior_window_close=bars[-1].close,
            net_move_pips=(bars[-1].close - bars[0].open) / pip_size,
        )
    return None
