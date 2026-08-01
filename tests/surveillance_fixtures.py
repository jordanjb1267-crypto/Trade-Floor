"""Shared surveillance test fixtures, importable as a bare module.

Lives at tests/ root because pyproject pins pytest's pythonpath there (the
`a2_guard` mechanism) — a `from tests.unit...` import resolves in some local
invocations and not on the CI runner, which is exactly the split-brain this
module removes.
"""

import datetime as dt
from decimal import Decimal

from trading_firm.surveillance.schemas import (
    ChangeSummary,
    CrossMarketState,
    DataQuality,
    DataQualityStatus,
    EvidenceType,
    ExecutionState,
    IndicatorObservation,
    LiquidityState,
    MacroState,
    NewsPollState,
    NewsState,
    RegimeState,
    SessionState,
    SurveillanceRegime,
    TechnicalState,
)

AS_OF = dt.datetime(2026, 7, 29, 7, 30, tzinfo=dt.UTC)


def state_kwargs(**overrides) -> dict:
    """Canonical MarketStateObject constructor kwargs (unidentified)."""
    base = dict(
        market_state_id="unidentified",
        schema_version="market_state_object_v1",
        instrument_id="GBP_USD",
        asset_class="FX_SPOT",
        as_of_utc=AS_OF,
        valid_until_utc=AS_OF + dt.timedelta(minutes=5),
        source_snapshot_ids=["oanda_practice.candles.2026-07-29T0730"],
        feature_snapshot_id=None,
        configuration_version="test-config-v1",
        session_state=SessionState(
            named_session="LONDON",
            phase="PRE_SESSION",
            session_date=dt.date(2026, 7, 29),
            anchor_timezone="Europe/London",
        ),
        market_regime=RegimeState(
            intraday=SurveillanceRegime.COMPRESSING,
            session=SurveillanceRegime.INDETERMINATE,
            daily=SurveillanceRegime.INDETERMINATE,
            evidence_feature_ids=["session_features_v1.compression_ratio"],
            classifier_version="surveillance_regime_v1",
        ),
        technical_state=TechnicalState(
            structure_state="inside_asian_range",
            momentum_state="flat",
            volatility_percentile=Decimal("35"),
            session_range_fraction_of_atr=None,
            key_levels=[],
            active_indicator_observations=[
                IndicatorObservation(
                    feature_id="session_features_v1.asian_width_pips",
                    value=Decimal("38.0"),
                    observed_at=AS_OF,
                )
            ],
        ),
        liquidity_state=LiquidityState(
            classification="normal",
            evidence=EvidenceType.BROKER_PROXY,
            observations=[],
            spread_state="normal",
            spread_evidence=EvidenceType.OBSERVED,
            spread_percentile=Decimal("40"),
        ),
        macro_state=MacroState(
            active_drivers=[],
            upcoming_events=[],
            blackout_active=False,
            uncertainty_state="calendar_loaded",
        ),
        news_state=NewsState(
            material_item_ids=[],
            poll_state=NewsPollState.UNKNOWN,
            unresolved_conflict=False,
        ),
        cross_market_state=CrossMarketState(
            confirmations=[], divergences=[], relationship_versions=[]
        ),
        execution_state=ExecutionState(
            broker_health="reachable",
            market_data_health="fresh",
            expected_slippage_state="normal",
            tradability_state="tradable",
        ),
        data_quality=DataQuality(
            overall_status=DataQualityStatus.DEGRADED,
            stale_components=[],
            missing_components=["news", "cross_market"],
            conflicting_components=[],
        ),
        change_summary=ChangeSummary(material_changes=[], non_material_changes_suppressed=0),
    )
    base.update(overrides)
    return base
