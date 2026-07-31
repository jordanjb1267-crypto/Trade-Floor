"""Deterministic technical surveillance (§30.3.B–E, §30.4, §30.17 unit rows:
freshness calculations, regime-label transitions, structure-event detection,
feature-registry enforcement, materiality thresholds)."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.market_data.spreads import SpreadSeries
from trading_firm.sessions import SessionClock
from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    load_surveillance_config,
)
from trading_firm.surveillance.freshness import (
    ComponentStatus,
    FreshnessThresholds,
    assess,
    component_status,
)
from trading_firm.surveillance.materiality import assess_change
from trading_firm.surveillance.schemas import (
    DataQualityStatus,
    EvidenceType,
    NewsPollState,
    SurveillanceRegime,
)
from trading_firm.surveillance.state_builder import build_market_state
from trading_firm.surveillance.technical.indicators import observe_indicators
from trading_firm.surveillance.technical.liquidity import observe_liquidity
from trading_firm.surveillance.technical.regime import classify
from trading_firm.surveillance.technical.structure import (
    StructureEventKind,
    key_levels,
    observe_structure,
)

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


@pytest.fixture(scope="module")
def sconfig():
    return load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)


def bar(hhmm: str, o: str, h: str, low: str, c: str, day: dt.date = DAY) -> Bar:
    return Bar(
        instrument="GBP_USD",
        ts=dt.datetime.combine(day, dt.time.fromisoformat(hhmm), tzinfo=LONDON),
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def series(*bars: Bar) -> BarSeries:
    return BarSeries(instrument="GBP_USD", granularity_minutes=15, bars=tuple(bars))


# The canonical fixture range: Asian high 1.3340, low 1.3300 (see
# test_features.py — same inputs, so golden numbers stay comparable).
ASIAN_BARS = (
    bar("00:00", "1.3320", "1.3335", "1.3310", "1.3330"),
    bar("02:00", "1.3330", "1.3340", "1.3305", "1.3315"),
    bar("04:00", "1.3315", "1.3325", "1.3300", "1.3320"),
    bar("06:45", "1.3320", "1.3330", "1.3312", "1.3326"),
    bar("07:15", "1.3326", "1.3332", "1.3318", "1.3328"),
)

AT = dt.datetime.combine(DAY, dt.time(8, 30), tzinfo=LONDON)
ACTIVATION = dt.datetime.combine(DAY, dt.time(8, 0), tzinfo=LONDON)


def permits(feature_id: str) -> bool:
    return feature_id.startswith(("session_features_v1.", "structure_features_v1."))


class TestFreshness:
    THRESHOLDS = FreshnessThresholds({"prices": 900, "calendar": 86400})

    def test_per_component_thresholds_not_one_global(self) -> None:
        now = AT
        two_hours_old = now - dt.timedelta(hours=2)
        # The same age is stale for prices and fresh for the calendar —
        # exactly the difference one global threshold cannot express (§30.4).
        assert (
            component_status(two_hours_old, "prices", self.THRESHOLDS, now)
            is ComponentStatus.STALE
        )
        assert (
            component_status(two_hours_old, "calendar", self.THRESHOLDS, now)
            is ComponentStatus.FRESH
        )

    def test_an_undeclared_component_cannot_be_evaluated(self) -> None:
        with pytest.raises(KeyError, match="own threshold"):
            component_status(AT, "news", self.THRESHOLDS, AT)

    def test_empty_or_nonpositive_thresholds_rejected(self) -> None:
        with pytest.raises(ValueError):
            FreshnessThresholds({})
        with pytest.raises(ValueError):
            FreshnessThresholds({"prices": 0})

    def test_all_required_unusable_is_failed(self) -> None:
        quality = assess(
            {"prices": None, "calendar": AT},
            self.THRESHOLDS,
            frozenset({"prices"}),
            AT,
        )
        assert quality.overall_status is DataQualityStatus.FAILED

    def test_any_problem_is_at_least_degraded(self) -> None:
        quality = assess(
            {"prices": AT, "calendar": None},
            self.THRESHOLDS,
            frozenset({"prices"}),
            AT,
        )
        assert quality.overall_status is DataQualityStatus.DEGRADED
        assert quality.missing_components == ["calendar"]

    def test_everything_fresh_is_healthy(self) -> None:
        quality = assess(
            {"prices": AT, "calendar": AT},
            self.THRESHOLDS,
            frozenset({"prices"}),
            AT,
        )
        assert quality.overall_status is DataQualityStatus.HEALTHY


class TestStructure:
    def _levels(self):
        return key_levels(Decimal("1.3340"), Decimal("1.3300"), None, None)

    def test_a_close_beyond_the_high_is_a_break(self) -> None:
        s = series(*ASIAN_BARS, bar("08:00", "1.3330", "1.3350", "1.3328", "1.3348"))
        events = observe_structure(s, self._levels(), ACTIVATION, AT)
        kinds = {(e.level_id, e.kind) for e in events}
        assert ("asian_high", StructureEventKind.BREAK) in kinds
        assert ("asian_high", StructureEventKind.FAILED_BREAK) not in kinds

    def test_a_break_that_closes_back_inside_is_a_failed_break(self) -> None:
        s = series(
            *ASIAN_BARS,
            bar("08:00", "1.3330", "1.3350", "1.3328", "1.3348"),
            bar("08:15", "1.3348", "1.3352", "1.3330", "1.3332"),
        )
        events = observe_structure(
            s, self._levels(), ACTIVATION, AT + dt.timedelta(minutes=15)
        )
        kinds = {(e.level_id, e.kind) for e in events}
        assert ("asian_high", StructureEventKind.FAILED_BREAK) in kinds

    def test_a_touch_without_a_close_beyond_is_only_reached(self) -> None:
        s = series(*ASIAN_BARS, bar("08:00", "1.3330", "1.3341", "1.3328", "1.3335"))
        events = observe_structure(s, self._levels(), ACTIVATION, AT)
        kinds = {(e.level_id, e.kind) for e in events}
        assert ("asian_high", StructureEventKind.LEVEL_REACHED) in kinds
        assert ("asian_high", StructureEventKind.BREAK) not in kinds

    def test_at_most_one_break_per_level_per_window(self) -> None:
        s = series(
            *ASIAN_BARS,
            bar("08:00", "1.3330", "1.3350", "1.3328", "1.3348"),
            bar("08:15", "1.3348", "1.3355", "1.3345", "1.3352"),
        )
        events = observe_structure(
            s, self._levels(), ACTIVATION, AT + dt.timedelta(minutes=15)
        )
        breaks = [e for e in events if e.kind is StructureEventKind.BREAK]
        assert len(breaks) == 1, "state-change-only starts at detection (§30.6)"


class TestIndicatorGate:
    def test_registered_features_observe(self) -> None:
        out = observe_indicators(
            {"session_features_v1.asian_width_pips": Decimal("40")}, permits, AT
        )
        assert out[0].feature_id == "session_features_v1.asian_width_pips"

    def test_an_unregistered_id_raises_rather_than_filters(self) -> None:
        with pytest.raises(ValueError, match="§30.7"):
            observe_indicators({"my_new_indicator.rsi": Decimal("70")}, permits, AT)


class TestLiquidity:
    def test_a_pierce_and_reclaim_is_a_sweep(self) -> None:
        # High 1.3340, range 40 pips: a 08:00 bar spiking to 1.3348 (8 pips
        # through, 20% of range) and closing back at 1.3330 sweeps the high.
        s = series(*ASIAN_BARS, bar("08:00", "1.3330", "1.3348", "1.3326", "1.3330"))
        state = observe_liquidity(
            s, None, Decimal("1.3340"), Decimal("1.3300"), ACTIVATION, AT
        )
        assert state.classification == "swept"
        by_name = {o.name: o for o in state.observations}
        sweep = by_name["asian_high_sweep_and_reclaim"]
        assert sweep.value == "True"
        assert sweep.evidence is EvidenceType.PRICE_ACTION_INFERENCE

    def test_no_spread_data_is_unavailable_not_normal(self) -> None:
        s = series(*ASIAN_BARS)
        state = observe_liquidity(
            s, None, Decimal("1.3340"), Decimal("1.3300"), ACTIVATION, AT
        )
        assert state.spread_state == "unknown"
        assert state.spread_evidence is EvidenceType.UNAVAILABLE

    def test_a_doubled_spread_reads_widened_and_observed(self) -> None:
        base = {
            dt.datetime.combine(DAY, dt.time(8, m), tzinfo=LONDON): Decimal("0.00020")
            for m in (0, 5, 10, 15)
        }
        base[dt.datetime.combine(DAY, dt.time(8, 20), tzinfo=LONDON)] = Decimal("0.00050")
        spreads = SpreadSeries(instrument="GBP_USD", by_ts=base)
        s = series(*ASIAN_BARS)
        state = observe_liquidity(
            s, spreads, Decimal("1.3340"), Decimal("1.3300"), ACTIVATION, AT
        )
        assert state.spread_state == "widened"
        assert state.spread_evidence is EvidenceType.OBSERVED


class TestRegimeTransitions:
    def test_compression_expansion_and_between(self) -> None:
        compressing = classify(Decimal("0.3"), None, None)
        transitional = classify(Decimal("1.0"), None, None)
        expanding = classify(Decimal("2.0"), None, None)
        assert compressing.intraday is SurveillanceRegime.COMPRESSING
        assert transitional.intraday is SurveillanceRegime.TRANSITIONAL
        assert expanding.intraday is SurveillanceRegime.EXPANDING

    def test_no_evidence_is_indeterminate_not_a_guess(self) -> None:
        state = classify(None, None, None)
        assert state.intraday is SurveillanceRegime.INDETERMINATE
        assert state.daily is SurveillanceRegime.INDETERMINATE
        assert state.evidence_feature_ids == []

    def test_daily_direction_needs_scale_not_just_sign(self) -> None:
        trending = classify(Decimal("1"), Decimal("-90"), Decimal("40"))
        balanced = classify(Decimal("1"), Decimal("-30"), Decimal("40"))
        assert trending.daily is SurveillanceRegime.TRENDING
        assert balanced.daily is SurveillanceRegime.MEAN_REVERTING

    def test_every_substantive_label_cites_features(self) -> None:
        state = classify(Decimal("0.3"), Decimal("-90"), Decimal("40"))
        assert "session_features_v1.compression_ratio" in state.evidence_feature_ids
        assert "structure_features_v1.net_move_pips" in state.evidence_feature_ids


class TestStateBuilder:
    def _build(self, sconfig, clock, extra=(), as_of=AT, prior=None):
        s = series(*ASIAN_BARS, *extra)
        return build_market_state(
            instrument="GBP_USD",
            session_date=DAY,
            clock=clock,
            series=s,
            spreads=None,
            permits=permits,
            config=sconfig,
            configuration_version="test-cfg",
            as_of=as_of,
            prior=prior,
        )

    def test_builds_an_identified_verifiable_object(self, sconfig, clock) -> None:
        state = self._build(sconfig, clock)
        state.verify(state.market_state_id)
        assert state.session_state.phase == "ACTIVE"
        assert state.news_state.poll_state is NewsPollState.UNKNOWN

    def test_determinism_same_inputs_same_identity(self, sconfig, clock) -> None:
        assert (
            self._build(sconfig, clock).market_state_id
            == self._build(sconfig, clock).market_state_id
        )

    def test_no_lookahead_bars_at_or_after_as_of_change_nothing(
        self, sconfig, clock
    ) -> None:
        """§30.17 replay row as a unit property: a bar timestamped at as_of
        (still forming, or from the future) must not alter the state."""
        with_future = self._build(
            sconfig,
            clock,
            extra=(
                bar("08:30", "1.3330", "1.3390", "1.3328", "1.3388"),
                bar("08:45", "1.3388", "1.3400", "1.3380", "1.3395"),
            ),
        )
        without = self._build(sconfig, clock)
        assert with_future.market_state_id == without.market_state_id

    def test_a_break_before_as_of_is_in_the_state(self, sconfig, clock) -> None:
        state = self._build(
            sconfig,
            clock,
            extra=(bar("08:00", "1.3330", "1.3350", "1.3328", "1.3348"),),
            as_of=dt.datetime.combine(DAY, dt.time(8, 15), tzinfo=LONDON),
        )
        assert state.technical_state.structure_state == "break:asian_high"

    def test_disabled_domains_read_missing_never_healthy(self, sconfig, clock) -> None:
        state = self._build(sconfig, clock)
        assert state.data_quality.overall_status is DataQualityStatus.DEGRADED
        assert {"calendar", "news", "cross_market"} <= set(
            state.data_quality.missing_components
        )

    def test_no_feature_coverage_fails_closed(self, sconfig, clock) -> None:
        state = build_market_state(
            instrument="GBP_USD",
            session_date=DAY,
            clock=clock,
            series=series(bar("08:00", "1.3330", "1.3335", "1.3328", "1.3332")),
            spreads=None,
            permits=permits,
            config=sconfig,
            configuration_version="test-cfg",
            as_of=AT,
        )
        assert state.technical_state.structure_state == "unavailable"
        assert state.market_regime.intraday is SurveillanceRegime.INDETERMINATE
        assert state.data_quality.overall_status is not DataQualityStatus.HEALTHY

    def test_change_summary_links_and_compares_to_the_prior(self, sconfig, clock) -> None:
        first = self._build(sconfig, clock)
        second = self._build(
            sconfig,
            clock,
            extra=(bar("08:00", "1.3330", "1.3350", "1.3328", "1.3348"),),
            as_of=dt.datetime.combine(DAY, dt.time(8, 15), tzinfo=LONDON),
            prior=first,
        )
        assert second.change_summary.prior_market_state_id == first.market_state_id
        assert any("structure" in c for c in second.change_summary.material_changes)


class TestMateriality:
    def test_first_state_is_material_by_definition(self, sconfig, clock) -> None:
        state = TestStateBuilder()._build(sconfig, clock)
        assert assess_change(None, state).is_material

    def test_unchanged_state_is_not_material(self, sconfig, clock) -> None:
        state = TestStateBuilder()._build(sconfig, clock)
        assert not assess_change(state, state).is_material
