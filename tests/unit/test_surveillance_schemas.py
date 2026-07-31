"""Market State Object and event envelope (§30.4, §30.6).

Covers the §30.17 unit rows: schema validation, the Market State checksum,
and asset-class-neutral instrument handling. The checksum tests mirror
test_packet.py's contract: determinism across constructions, and mutation
trips verify().
"""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_firm.surveillance.events import (
    EVENT_SCHEMA_VERSION,
    EventType,
    SurveillanceEvent,
)
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
    MarketStateObject,
    NewsPollState,
    NewsState,
    RegimeState,
    SessionState,
    SurveillanceRegime,
    TechnicalState,
)

AS_OF = dt.datetime(2026, 7, 29, 7, 30, tzinfo=dt.UTC)


def state_kwargs(**overrides) -> dict:
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


@pytest.fixture()
def state() -> MarketStateObject:
    return MarketStateObject(**state_kwargs()).identified()


class TestChecksumIdentity:
    def test_identity_is_deterministic_across_constructions(self, state) -> None:
        again = MarketStateObject(**state_kwargs()).identified()
        assert again.market_state_id == state.market_state_id

    def test_verify_accepts_the_identified_object(self, state) -> None:
        state.verify(state.market_state_id)  # does not raise

    def test_a_mutated_copy_fails_verification(self, state) -> None:
        tampered = state.model_copy(
            update={
                "technical_state": state.technical_state.model_copy(
                    update={"momentum_state": "strongly_bullish"}
                )
            }
        )
        with pytest.raises(ValueError, match="append-only"):
            tampered.verify(state.market_state_id)

    def test_the_id_does_not_feed_its_own_checksum(self, state) -> None:
        relabeled = state.model_copy(update={"market_state_id": "someone-else"})
        assert relabeled.content_checksum == state.content_checksum


class TestFailClosedShapes:
    def test_healthy_with_missing_components_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError, match="never be treated as\\s+confirmation"):
            DataQuality(
                overall_status=DataQualityStatus.HEALTHY,
                stale_components=[],
                missing_components=["news"],
                conflicting_components=[],
            )

    def test_naive_datetimes_rejected(self) -> None:
        with pytest.raises(ValidationError, match="naive"):
            MarketStateObject(**state_kwargs(as_of_utc=AS_OF.replace(tzinfo=None)))

    def test_backward_validity_window_rejected(self) -> None:
        with pytest.raises(ValidationError, match="expires"):
            MarketStateObject(**state_kwargs(valid_until_utc=AS_OF - dt.timedelta(minutes=1)))

    def test_a_regime_claim_without_evidence_is_prose(self) -> None:
        with pytest.raises(ValidationError, match="prose"):
            RegimeState(
                intraday=SurveillanceRegime.TRENDING,
                session=SurveillanceRegime.INDETERMINATE,
                daily=SurveillanceRegime.INDETERMINATE,
                evidence_feature_ids=[],
                classifier_version="v1",
            )

    def test_indeterminate_everywhere_needs_no_evidence(self) -> None:
        RegimeState(
            intraday=SurveillanceRegime.INDETERMINATE,
            session=SurveillanceRegime.INDETERMINATE,
            daily=SurveillanceRegime.INDETERMINATE,
            evidence_feature_ids=[],
            classifier_version="v1",
        )

    def test_an_unregistered_indicator_shape_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="registry"):
            IndicatorObservation(
                feature_id="the chart looks tight",
                value=Decimal("1"),
                observed_at=AS_OF,
            )

    def test_only_healthy_no_news_states_confirm(self) -> None:
        confirming = {s for s in NewsPollState if s.is_confirming}
        assert confirming == {
            NewsPollState.NO_MATERIAL_ITEMS_FOUND,
            NewsPollState.SOURCE_HEALTHY_NO_ITEMS,
        }, "SOURCE_UNAVAILABLE/POLL_FAILED/VERIFICATION_PENDING/UNKNOWN never confirm"


class TestAssetClassNeutrality:
    """§30.11: no pip semantics baked into the surveillance domain — an
    equity-shaped instrument validates without FX-specific fields."""

    def test_a_non_fx_instrument_id_validates(self) -> None:
        obj = MarketStateObject(**state_kwargs(instrument_id="SPX500_USD", asset_class="INDEX_CFD"))
        assert obj.identified().market_state_id

    def test_prose_is_not_an_instrument(self) -> None:
        with pytest.raises(ValidationError, match="instrument"):
            MarketStateObject(**state_kwargs(instrument_id="the S&P"))


class TestEventEnvelope:
    def _event(self, **overrides) -> SurveillanceEvent:
        base = dict(
            event_id="evt-1",
            event_type=EventType.MARKET_STATE_PUBLISHED,
            schema_version=EVENT_SCHEMA_VERSION,
            event_time_utc=AS_OF,
            ingestion_time_utc=AS_OF,
            producer="state_builder",
            instrument_scope=["GBP_USD"],
            correlation_id="corr-1",
            configuration_version="test-config-v1",
            data_quality=DataQualityStatus.HEALTHY,
            payload={"market_state_id": "abc", "width_pips": Decimal("38.0")},
        )
        base.update(overrides)
        return SurveillanceEvent(**base)

    def test_the_family_set_is_exactly_the_spec_list(self) -> None:
        assert len(EventType) == 22

    def test_an_unregistered_event_type_is_unrepresentable(self) -> None:
        with pytest.raises(ValidationError):
            self._event(event_type="surveillance.buy_signal")

    def test_payload_checksum_is_deterministic(self) -> None:
        assert self._event().payload_checksum == self._event().payload_checksum

    def test_an_unserializable_payload_fails_at_construction(self) -> None:
        with pytest.raises(ValidationError, match="canonically"):
            self._event(payload={"handle": object()})

    def test_to_row_carries_every_envelope_field(self) -> None:
        row = self._event().to_row()
        assert row["event_type"] == "market_state.published"
        assert row["payload_checksum"]
        assert "T" in row["event_time_utc"]  # ISO-8601 UTC text, DB convention
