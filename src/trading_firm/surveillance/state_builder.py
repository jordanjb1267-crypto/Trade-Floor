"""Market State Object builder (§30.4) — Phase C's deterministic core.

Builds one identified, checksummed `MarketStateObject` from the data the
firm already computes: `BarSeries`, the session/structure feature engine,
and the measured spread series. No look-ahead by construction: every window
this module reads ends at `as_of`, and `between()` is half-open, so a bar
timestamped at or after the build moment cannot contribute (§30.17 replay
row: no look-ahead information enters a Market State).

Domains the configuration has off (macro, news, cross-market in this build)
are recorded as missing components with honest placeholder states — UNKNOWN
news never confirms anything (§30.8), and overall data quality cannot read
HEALTHY while components are missing (§30.4). Observe-only: this module
returns objects; persistence and events belong to the coordinator.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from trading_firm.features.engine import (
    prior_session_structure,
    session_features,
)
from trading_firm.market_data.bars import BarSeries
from trading_firm.market_data.spreads import SpreadSeries
from trading_firm.packet import _digest
from trading_firm.sessions import SessionClock
from trading_firm.surveillance.config import SurveillanceConfig
from trading_firm.surveillance.freshness import FreshnessThresholds, assess
from trading_firm.surveillance.materiality import assess_change
from trading_firm.surveillance.schemas import (
    MARKET_STATE_SCHEMA_VERSION,
    ChangeSummary,
    CrossMarketState,
    ExecutionState,
    MacroState,
    MarketStateObject,
    NewsPollState,
    NewsState,
    SessionState,
    TechnicalState,
)
from trading_firm.surveillance.technical.indicators import PermitsFeature, observe_indicators
from trading_firm.surveillance.technical.liquidity import observe_liquidity
from trading_firm.surveillance.technical.regime import classify
from trading_firm.surveillance.technical.structure import key_levels, observe_structure

STATE_VALIDITY = dt.timedelta(minutes=5)

# Per-component freshness (§30.4: never one global threshold). Prices age in
# bar-lengths; the technical block per session; disabled domains have
# thresholds so enabling them later is a config change, not a code change.
DEFAULT_THRESHOLDS = FreshnessThresholds(
    {
        "prices": 15 * 60,
        "technical": 8 * 3600,
        "calendar": 24 * 3600,
        "news": 30 * 60,
        "cross_market": 30 * 60,
    }
)
REQUIRED_COMPONENTS = frozenset({"prices", "technical"})


def _session_phase(clock: SessionClock, moment: dt.datetime, day: dt.date) -> str:
    b = clock.boundaries(day)
    if moment < b["activation"]:
        return "PRE_SESSION"
    if moment < b["entry_cutoff"]:
        return "ACTIVE"
    if moment < b["flatten"]:
        return "POST_CUTOFF"
    return "CLOSED"


def build_market_state(
    *,
    instrument: str,
    session_date: dt.date,
    clock: SessionClock,
    series: BarSeries,
    spreads: SpreadSeries | None,
    permits: PermitsFeature,
    config: SurveillanceConfig,
    configuration_version: str,
    as_of: dt.datetime,
    prior: MarketStateObject | None = None,
    thresholds: FreshnessThresholds = DEFAULT_THRESHOLDS,
) -> MarketStateObject:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware (§30.4, C-2)")

    boundaries = clock.boundaries(session_date)
    feats = session_features(series, session_date, clock)
    structure_feats = prior_session_structure(series, session_date, clock)

    # ------------------------------------------------------------- technical
    if feats is not None:
        feature_values: dict[str, Decimal] = {
            "session_features_v1.asian_high": feats.asian_high,
            "session_features_v1.asian_low": feats.asian_low,
            "session_features_v1.asian_width_pips": feats.asian_width_pips,
            "session_features_v1.pre_london_range_pips": feats.pre_london_range_pips,
            "session_features_v1.compression_ratio": feats.compression_ratio,
        }
        observations = observe_indicators(feature_values, permits, feats.computed_at)
        # v1 tracks the Asian extremes only: the feature engine does not yet
        # compute prior-session HIGH/LOW (its structure family carries the
        # prior window's open/close/net-move), and mislabeling those as
        # extremes would be a false level with an honest-sounding name.
        levels = key_levels(feats.asian_high, feats.asian_low, None, None)
        structure_events = observe_structure(
            series, levels, boundaries["activation"], as_of
        )
        broke = [o for o in structure_events if o.kind.value == "break"]
        failed = [o for o in structure_events if o.kind.value == "failed_break"]
        if failed:
            structure_state = f"failed_break:{failed[-1].level_id}"
        elif broke:
            structure_state = f"break:{broke[-1].level_id}"
        else:
            structure_state = "inside_reference_range"
        technical = TechnicalState(
            structure_state=structure_state,
            momentum_state="not_classified",
            volatility_percentile=None,
            session_range_fraction_of_atr=None,
            key_levels=[sided.level for sided in levels],
            active_indicator_observations=observations,
        )
        liquidity = observe_liquidity(
            series, spreads, feats.asian_high, feats.asian_low,
            boundaries["activation"], as_of,
        )
        regime = classify(
            feats.compression_ratio,
            structure_feats.net_move_pips if structure_feats else None,
            feats.asian_width_pips,
        )
        technical_updated: dt.datetime | None = feats.computed_at
        feature_snapshot_id = _digest(
            {"feature_version": feats.feature_version, **feature_values}
        )
    else:
        technical = TechnicalState(
            structure_state="unavailable",
            momentum_state="unavailable",
            volatility_percentile=None,
            session_range_fraction_of_atr=None,
            key_levels=[],
            active_indicator_observations=[],
        )
        liquidity = observe_liquidity(
            series, spreads, Decimal("0"), Decimal("0"),
            boundaries["activation"], as_of,
        )
        regime = classify(None, None, None)
        technical_updated = None
        feature_snapshot_id = None

    # ------------------------------------------- disabled or absent domains
    macro = MacroState(
        active_drivers=[],
        upcoming_events=[],
        blackout_active=False,
        uncertainty_state=(
            "macro_domain_disabled" if not config.macro_active else "not_loaded"
        ),
    )
    news = NewsState(
        material_item_ids=[],
        poll_state=NewsPollState.UNKNOWN,
        unresolved_conflict=False,
        last_successful_poll_utc=None,
    )
    cross_market = CrossMarketState(
        confirmations=[], divergences=[], relationship_versions=[]
    )

    # ------------------------------------------------------------ freshness
    window_bars = series.between(boundaries["startup"] - dt.timedelta(hours=8), as_of)
    last_price = window_bars[-1].ts if window_bars else None
    data_quality = assess(
        {
            "prices": last_price,
            "technical": technical_updated,
            "calendar": None,
            "news": None,
            "cross_market": None,
        },
        thresholds,
        REQUIRED_COMPONENTS,
        as_of,
    )

    execution = ExecutionState(
        broker_health="not_probed_by_builder",
        market_data_health="fresh" if "prices" not in (
            data_quality.stale_components + data_quality.missing_components
        ) else "stale_or_missing",
        expected_slippage_state=liquidity.spread_state,
        tradability_state="observe_only",
    )

    draft = MarketStateObject(
        market_state_id="unidentified",
        schema_version=MARKET_STATE_SCHEMA_VERSION,
        instrument_id=instrument,
        asset_class="FX_SPOT",
        as_of_utc=as_of.astimezone(dt.UTC),
        valid_until_utc=(as_of + STATE_VALIDITY).astimezone(dt.UTC),
        source_snapshot_ids=[f"oanda_practice.bars.{instrument}.{session_date.isoformat()}"],
        feature_snapshot_id=feature_snapshot_id,
        configuration_version=configuration_version,
        session_state=SessionState(
            named_session="LONDON",
            phase=_session_phase(clock, as_of, session_date),
            session_date=session_date,
            anchor_timezone="Europe/London",
        ),
        market_regime=regime,
        technical_state=technical,
        liquidity_state=liquidity,
        macro_state=macro,
        news_state=news,
        cross_market_state=cross_market,
        execution_state=execution,
        data_quality=data_quality,
        change_summary=ChangeSummary(
            prior_market_state_id=prior.market_state_id if prior else None,
            material_changes=[],
            non_material_changes_suppressed=0,
        ),
    )

    # Two-phase identification: the change summary compares against the prior
    # PUBLISHED object, so it is computed on the draft and folded in before
    # the content is identified (§30.4).
    assessment = assess_change(prior, draft)
    final = draft.model_copy(
        update={
            "change_summary": ChangeSummary(
                prior_market_state_id=prior.market_state_id if prior else None,
                material_changes=list(assessment.material_changes),
                non_material_changes_suppressed=0,
            )
        }
    )
    return final.identified()
