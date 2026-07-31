"""Specialist bench and context aggregation (§6.3, §6.4) and their §21 criterion.

The criterion this file exists for — "irrelevant specialists can return
`NOT_APPLICABLE` without causing workflow failure" — sounds like an
error-handling detail and is not one. §6.3 demoted three playbooks from the
firm's mandate to a consultable bench. A bench agent that is never consulted is
never scored and eventually retired, so unless abstention is free, cheap, and
non-penalised, every specialist learns to find its own pattern everywhere and
the firm is strategy-driven again with extra steps.

So the tests below assert three separate things about abstention: that it
constructs with nothing (no rationale demanded), that it flows through a round
without raising, and that it is scored as neither hit nor miss. And the
asymmetry tests assert the dangerous direction is *impossible* rather than
merely unused: no arrangement of SUPPORT verdicts produces a positive tier
delta, checked exhaustively over the verdict product rather than by inspection.
"""

import ast
import datetime as dt
import inspect
import itertools
import pathlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_firm.agents.bench import (
    ASIAN_RANGE_SWEEP_REVERSAL_DOMAIN,
    BENCH,
    LONDON_BREAKOUT_DOMAIN,
    LONDON_CONTINUATION_DOMAIN,
    CalendarEntry,
    ConsultationRound,
    ContextPacket,
    EventRiskReading,
    ExecutionConditions,
    RegimeReading,
    SpecialistConsultation,
    SpecialistDomain,
    SpecialistVerdict,
    StructuralLevelReading,
    assess_relevance,
    bench_domain,
    consult,
    relevant_specialists,
)
from trading_firm.agents.schemas import RegimeLabel
from trading_firm.packet import MarketSnapshot

UTC = dt.UTC
NOW = dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC)
THESIS = "t-001"

BREAKOUT = "london_breakout_specialist"
SWEEP = "asian_range_sweep_reversal_specialist"
CONTINUATION = "london_continuation_specialist"


def market(**overrides) -> MarketSnapshot:
    base = dict(
        instrument="GBP_USD",
        observed_at=NOW,
        session_date=dt.date(2026, 7, 30),
        session_phase="briefing",
        regime="compression",
        volatility_state="low",
        bid=Decimal("1.28450"),
        ask=Decimal("1.28462"),
        spread_pips=Decimal("1.2"),
        feature_version="session_features_v1",
        features={"session_features_v1.asian_width_pips": Decimal("38")},
        analog_sample_size=40,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def consultation(
    specialist_id: str,
    verdict: SpecialistVerdict,
    **overrides,
) -> SpecialistConsultation:
    base = dict(
        specialist_id=specialist_id,
        thesis_id=THESIS,
        verdict=verdict,
    )
    if verdict.requires_rationale:
        base["rationale"] = "range width 38 pips, inside the validated band"
    if verdict is SpecialistVerdict.QUALIFY:
        base["qualification"] = "only above the 07:00 high with a 2-pip buffer"
    base.update(overrides)
    return SpecialistConsultation(**base)


# --------------------------------------------------------------------- verdicts


class TestSpecialistVerdict:
    def test_the_four_verdicts_are_exactly_the_spec_list(self) -> None:
        assert {v.value for v in SpecialistVerdict} == {
            "SUPPORT",
            "QUALIFY",
            "REJECT",
            "NOT_APPLICABLE",
        }

    def test_only_claims_require_a_rationale(self) -> None:
        # §6.3: silence needs no justification. Demanding one is how a bench
        # learns to manufacture signals.
        assert SpecialistVerdict.NOT_APPLICABLE.requires_rationale is False
        for verdict in (
            SpecialistVerdict.SUPPORT,
            SpecialistVerdict.QUALIFY,
            SpecialistVerdict.REJECT,
        ):
            assert verdict.requires_rationale is True

    def test_only_support_counts_as_support(self) -> None:
        assert SpecialistVerdict.SUPPORT.counts_as_support is True
        for verdict in (
            SpecialistVerdict.QUALIFY,
            SpecialistVerdict.REJECT,
            SpecialistVerdict.NOT_APPLICABLE,
        ):
            assert verdict.counts_as_support is False, (
                f"{verdict.value} must not read as support (§6.3)"
            )

    def test_only_risk_reducing_verdicts_surface(self) -> None:
        assert SpecialistVerdict.REJECT.surfaces is True
        assert SpecialistVerdict.QUALIFY.surfaces is True
        assert SpecialistVerdict.SUPPORT.surfaces is False
        assert SpecialistVerdict.NOT_APPLICABLE.surfaces is False


# ---------------------------------------------------------------- consultation


class TestConsultationValidation:
    def test_not_applicable_constructs_with_no_rationale_at_all(self) -> None:
        # The §21 criterion begins here: abstention must be free to express.
        record = SpecialistConsultation(
            specialist_id=CONTINUATION,
            thesis_id=THESIS,
            verdict=SpecialistVerdict.NOT_APPLICABLE,
        )
        assert record.rationale == ""
        assert record.qualification is None

    @pytest.mark.parametrize(
        "verdict", [SpecialistVerdict.SUPPORT, SpecialistVerdict.REJECT]
    )
    def test_a_claim_without_a_rationale_is_rejected(self, verdict) -> None:
        with pytest.raises(ValidationError, match="no rationale"):
            SpecialistConsultation(
                specialist_id=BREAKOUT,
                thesis_id=THESIS,
                verdict=verdict,
            )

    def test_whitespace_is_not_a_rationale(self) -> None:
        with pytest.raises(ValidationError, match="no rationale"):
            consultation(BREAKOUT, SpecialistVerdict.SUPPORT, rationale="   ")

    def test_qualify_without_a_qualification_is_a_support_in_disguise(self) -> None:
        with pytest.raises(ValidationError, match="no qualification"):
            consultation(BREAKOUT, SpecialistVerdict.QUALIFY, qualification=None)

    def test_a_support_may_not_smuggle_a_qualification(self) -> None:
        with pytest.raises(ValidationError, match="conditions travel with QUALIFY only"):
            consultation(
                BREAKOUT, SpecialistVerdict.SUPPORT, qualification="only above the high"
            )

    def test_consultation_has_no_score_size_or_tier_field(self) -> None:
        """§6.3 bullet 2 as a type: a specialist has no vocabulary for risk."""
        fields = set(SpecialistConsultation.model_fields)
        for forbidden in ("score", "confidence", "size", "units", "tier", "evidence_class"):
            assert forbidden not in fields, (
                f"a specialist may not express {forbidden}: it may not force the firm to "
                f"trade its playbook (§6.3, §5.1)"
            )

    def test_unknown_fields_are_refused(self) -> None:
        with pytest.raises(ValidationError):
            consultation(BREAKOUT, SpecialistVerdict.SUPPORT, edge_tier="EXCEPTIONAL")

    def test_a_consultation_is_frozen(self) -> None:
        record = consultation(BREAKOUT, SpecialistVerdict.SUPPORT)
        with pytest.raises(ValidationError):
            record.verdict = SpecialistVerdict.REJECT


# --------------------------------------------------------------------- domains


class TestSpecialistDomain:
    def test_the_bench_is_the_three_named_playbooks(self) -> None:
        assert set(BENCH) == {BREAKOUT, SWEEP, CONTINUATION}
        assert {d.domain_id for d in BENCH.values()} == {
            "london_breakout",
            "asian_range_sweep_reversal",
            "london_continuation",
        }

    def test_the_bench_cannot_be_extended_at_runtime(self) -> None:
        # §11 puts the registry under promotion control; a session may not add
        # a specialist to it mid-flight.
        with pytest.raises(TypeError):
            BENCH["invented_specialist"] = LONDON_BREAKOUT_DOMAIN

    def test_unknown_specialist_names_the_bench(self) -> None:
        with pytest.raises(ValueError, match="unknown bench specialist"):
            bench_domain("scalping_specialist")

    def test_a_domain_may_not_claim_event_distorted_tape(self) -> None:
        with pytest.raises(ValidationError, match="event_distorted"):
            SpecialistDomain(
                domain_id="london_breakout",
                regimes=(RegimeLabel.COMPRESSION, RegimeLabel.EVENT_DISTORTED),
                description="breakouts, including through the news",
            )

    def test_a_domain_that_covers_everything_is_not_a_domain(self) -> None:
        # Otherwise §6.3 bullet 4 ("evaluated only on opportunities within its
        # declared domain") scores the specialist everywhere.
        everything = tuple(r for r in RegimeLabel if r is not RegimeLabel.EVENT_DISTORTED)
        with pytest.raises(ValidationError, match="every assessable regime"):
            SpecialistDomain(
                domain_id="universal_specialist",
                regimes=everything,
                description="always relevant",
            )

    def test_an_empty_domain_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpecialistDomain(domain_id="empty", regimes=(), description="nothing")

    def test_a_domain_id_must_be_an_identifier_not_prose(self) -> None:
        with pytest.raises(ValidationError, match="is not an identifier"):
            SpecialistDomain(
                domain_id="the breakout thing we do",
                regimes=(RegimeLabel.COMPRESSION,),
                description="prose",
            )


# ------------------------------------------------------------------- relevance


class TestRelevanceClassifier:
    def test_compression_is_the_breakout_domain_not_the_continuation_domain(self) -> None:
        snapshot = market(regime="compression")
        assert assess_relevance(LONDON_BREAKOUT_DOMAIN, snapshot).relevant is True
        assert assess_relevance(ASIAN_RANGE_SWEEP_REVERSAL_DOMAIN, snapshot).relevant is True
        assert assess_relevance(LONDON_CONTINUATION_DOMAIN, snapshot).relevant is False

    def test_trend_is_the_continuation_domain_only(self) -> None:
        snapshot = market(regime="trend")
        assert relevant_specialists(snapshot) == (CONTINUATION,)

    def test_balance_is_the_sweep_domain_only(self) -> None:
        assert relevant_specialists(market(regime="balance")) == (SWEEP,)

    def test_event_distorted_tape_makes_the_whole_bench_irrelevant(self) -> None:
        snapshot = market(regime="event_distorted")
        assert relevant_specialists(snapshot) == ()
        finding = assess_relevance(LONDON_BREAKOUT_DOMAIN, snapshot)
        assert "event_distorted" in finding.reason and "§5.3" in finding.reason

    def test_an_unknown_regime_label_is_not_relevance(self) -> None:
        # An agent-invented regime word cannot make a specialist relevant.
        finding = assess_relevance(LONDON_BREAKOUT_DOMAIN, market(regime="coiled_and_ready"))
        assert finding.relevant is False
        assert "outside the deterministic regime vocabulary" in finding.reason

    @pytest.mark.parametrize(
        "override,fragment",
        [
            ({"data_fresh": False}, "not fresh"),
            ({"bars_complete": False}, "incomplete"),
            ({"calendar_state_known": False}, "calendar state unknown"),
        ],
    )
    def test_relevance_fails_closed_on_degraded_data(self, override, fragment) -> None:
        # §0.10. The regime label computed from bad data cannot establish a
        # validated domain, and removing a voice can never add risk.
        snapshot = market(**override)
        finding = assess_relevance(LONDON_BREAKOUT_DOMAIN, snapshot)
        assert finding.relevant is False
        assert fragment in finding.reason
        assert relevant_specialists(snapshot) == ()

    def test_relevance_is_a_pure_function_of_the_market(self) -> None:
        snapshot = market()
        first = assess_relevance(LONDON_BREAKOUT_DOMAIN, snapshot)
        second = assess_relevance(LONDON_BREAKOUT_DOMAIN, market())
        assert first == second


# ------------------------------------------------------------ consultation round


class TestConsultationRound:
    def test_two_of_three_abstentions_complete_the_round_normally(self) -> None:
        """§21 acceptance criterion, stated as directly as it can be.

        Compression tape: the breakout specialist has something to say, the
        continuation specialist does not, and the sweep specialist — in domain
        but with no read — also does not. The round completes, the abstentions
        are visible, and neither abstainer is counted for or against.
        """
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [
                consultation(BREAKOUT, SpecialistVerdict.SUPPORT),
                consultation(CONTINUATION, SpecialistVerdict.NOT_APPLICABLE),
                consultation(SWEEP, SpecialistVerdict.NOT_APPLICABLE),
            ],
        )
        assert len(round_.records) == 3
        assert len(round_.abstentions) == 2
        assert round_.any_rejection is False
        assert round_.tier_delta == 0
        assert round_.requires_arbiter_response is False
        assert round_.surfaced_concerns == ()

    def test_an_empty_round_completes(self) -> None:
        # Nobody was relevant, nobody was consulted. That is a valid session.
        round_ = consult(THESIS, market(regime="event_distorted"), [])
        assert round_.records == ()
        assert round_.any_rejection is False
        assert round_.in_domain_support is False
        assert round_.tier_delta == 0

    def test_a_round_of_nothing_but_abstentions_completes(self) -> None:
        round_ = consult(
            THESIS,
            market(regime="trend"),
            [consultation(sid, SpecialistVerdict.NOT_APPLICABLE) for sid in BENCH],
        )
        assert len(round_.abstentions) == 3
        assert round_.tier_delta == 0

    def test_a_rejection_surfaces_and_must_be_answered(self) -> None:
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [
                consultation(
                    BREAKOUT,
                    SpecialistVerdict.REJECT,
                    rationale="range width 38 pips but no displacement on the retest",
                )
            ],
        )
        assert round_.any_rejection is True
        assert round_.requires_arbiter_response is True
        assert len(round_.surfaced_concerns) == 1
        assert "REJECT (in-domain) london_breakout_specialist" in round_.surfaced_concerns[0]
        assert round_.tier_delta == -1

    def test_a_qualification_becomes_a_condition_on_the_plan(self) -> None:
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [consultation(BREAKOUT, SpecialistVerdict.QUALIFY)],
        )
        assert round_.conditions == ("only above the 07:00 high with a 2-pip buffer",)
        assert round_.requires_arbiter_response is True
        assert round_.tier_delta == 0, "a qualification restricts; it does not reduce the tier"

    def test_support_from_inside_the_domain_is_distinguished_from_outside(self) -> None:
        snapshot = market(regime="trend")  # continuation's domain, not breakout's
        in_domain = consult(
            THESIS, snapshot, [consultation(CONTINUATION, SpecialistVerdict.SUPPORT)]
        )
        out_of_domain = consult(
            THESIS, snapshot, [consultation(BREAKOUT, SpecialistVerdict.SUPPORT)]
        )
        assert in_domain.in_domain_support is True
        assert out_of_domain.in_domain_support is False
        # Both are still recorded — the distinction is informational, not a filter.
        assert len(out_of_domain.supports) == 1

    def test_out_of_domain_support_is_flagged_as_a_manufactured_signal(self) -> None:
        # §6.3 bullet 3's named failure: a specialist finding its pattern in a
        # market its domain does not cover.
        round_ = consult(
            THESIS, market(regime="trend"), [consultation(BREAKOUT, SpecialistVerdict.SUPPORT)]
        )
        assert len(round_.manufactured_signals) == 1
        assert round_.scored_records == ()

    def test_out_of_domain_rejection_is_not_a_manufactured_signal(self) -> None:
        # §0.6: the risk-reducing direction is always available to anyone.
        round_ = consult(
            THESIS, market(regime="trend"), [consultation(BREAKOUT, SpecialistVerdict.REJECT)]
        )
        assert round_.manufactured_signals == ()
        assert round_.any_rejection is True
        assert "out-of-domain" in round_.surfaced_concerns[0]

    def test_a_specialist_speaks_once_per_round(self) -> None:
        with pytest.raises(ValueError, match="appears twice"):
            consult(
                THESIS,
                market(),
                [
                    consultation(BREAKOUT, SpecialistVerdict.SUPPORT),
                    consultation(BREAKOUT, SpecialistVerdict.SUPPORT),
                ],
            )

    def test_a_consultation_is_bound_to_the_thesis_it_assessed(self) -> None:
        with pytest.raises(ValueError, match="answered thesis"):
            consult(
                THESIS,
                market(),
                [consultation(BREAKOUT, SpecialistVerdict.SUPPORT, thesis_id="t-999")],
            )

    def test_the_round_records_the_market_it_was_run_against(self) -> None:
        snapshot = market()
        assert consult(THESIS, snapshot, []).market_id == snapshot.checksum


class TestSupportRejectAsymmetry:
    """§6.3 bullet 2 and §5.1: support is advisory, and advice cannot raise."""

    def test_no_arrangement_of_verdicts_produces_a_positive_tier_delta(self) -> None:
        # Exhaustive over the whole verdict product for the whole bench, on
        # tape where every specialist is in domain if the domain allows it.
        # The claim is that the dangerous value is unreachable, not unused.
        snapshot = market(regime="compression")
        for combo in itertools.product(SpecialistVerdict, repeat=len(BENCH)):
            round_ = consult(
                THESIS,
                snapshot,
                [consultation(sid, verdict) for sid, verdict in zip(BENCH, combo, strict=True)],
            )
            assert round_.tier_delta <= 0, f"{combo} produced a positive delta (§5.1, §6.3)"

    def test_three_supports_move_nothing(self) -> None:
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [consultation(sid, SpecialistVerdict.SUPPORT) for sid in BENCH],
        )
        assert round_.tier_delta == 0
        assert round_.surfaced_concerns == ()
        assert round_.requires_arbiter_response is False

    def test_supports_cannot_outvote_a_rejection(self) -> None:
        # The bench is not a vote. One in-domain rejection surfaces and reduces
        # regardless of how many colleagues disagree.
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [
                consultation(BREAKOUT, SpecialistVerdict.REJECT),
                consultation(SWEEP, SpecialistVerdict.SUPPORT),
                consultation(CONTINUATION, SpecialistVerdict.SUPPORT),
            ],
        )
        assert round_.tier_delta == -1
        assert round_.requires_arbiter_response is True

    def test_rejections_do_not_stack_into_arbitrary_arithmetic(self) -> None:
        one = consult(
            THESIS,
            market(regime="compression"),
            [consultation(BREAKOUT, SpecialistVerdict.REJECT)],
        )
        two = consult(
            THESIS,
            market(regime="compression"),
            [
                consultation(BREAKOUT, SpecialistVerdict.REJECT),
                consultation(SWEEP, SpecialistVerdict.REJECT),
            ],
        )
        assert one.tier_delta == two.tier_delta == -1
        assert len(two.surfaced_concerns) == 2, "both rejections are still shown"

    def test_out_of_domain_rejection_surfaces_but_does_not_move_the_tier(self) -> None:
        round_ = consult(
            THESIS, market(regime="trend"), [consultation(BREAKOUT, SpecialistVerdict.REJECT)]
        )
        assert round_.tier_delta == 0
        assert round_.requires_arbiter_response is True


class TestSpecialistScoring:
    """§6.3 bullet 4 and the §6.6 / A-2 bounds on what counts as a miss."""

    def test_a_correct_abstention_outside_the_domain_is_never_a_miss(self) -> None:
        round_ = consult(
            THESIS,
            market(regime="trend"),
            [consultation(BREAKOUT, SpecialistVerdict.NOT_APPLICABLE)],
        )
        record = round_.records[0]
        assert record.correct_abstention is True
        assert record.scored is False
        assert record.manufactured_signal is False
        assert record.in_domain_abstention is False

    def test_abstaining_inside_the_domain_is_a_post_session_signal_only(self) -> None:
        # A-2's under-claim, bench edition: recorded, never consumed in session.
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [consultation(BREAKOUT, SpecialistVerdict.NOT_APPLICABLE)],
        )
        assert len(round_.in_domain_abstentions) == 1
        assert round_.records[0].correct_abstention is False
        assert round_.tier_delta == 0, (
            "an in-session consequence for abstaining would make claiming evidence a "
            "pressure response rather than a market read (§6.6)"
        )

    def test_only_in_domain_consultations_are_scored(self) -> None:
        round_ = consult(
            THESIS,
            market(regime="compression"),
            [
                consultation(BREAKOUT, SpecialistVerdict.SUPPORT),  # in domain
                consultation(SWEEP, SpecialistVerdict.REJECT),  # in domain
                consultation(CONTINUATION, SpecialistVerdict.SUPPORT),  # out of domain
            ],
        )
        assert {r.specialist_id for r in round_.scored_records} == {BREAKOUT, SWEEP}


# ------------------------------------------------------ §6.4 context aggregation


def regime_reading(**overrides) -> RegimeReading:
    base = dict(
        regime=RegimeLabel.COMPRESSION,
        feature_version="session_features_v1",
        measures={"session_features_v1.asian_width_pips": Decimal("38")},
    )
    base.update(overrides)
    return RegimeReading(**base)


def event_risk(**overrides) -> EventRiskReading:
    base = dict(calendar_state="fresh", as_of_utc=NOW, entries=(), blackout_active=False)
    base.update(overrides)
    return EventRiskReading(**base)


def execution(**overrides) -> ExecutionConditions:
    base = dict(
        spread_pips=Decimal("1.2"),
        max_spread_pips=Decimal("2.5"),
        expected_slippage_pips=Decimal("0.4"),
        commission_usd=Decimal("0.06"),
        liquidity_state="normal",
        expected_gross_r=Decimal("1.5"),
        expected_cost_r=Decimal("0.3"),
    )
    base.update(overrides)
    return ExecutionConditions(**base)


def context(**overrides) -> ContextPacket:
    base = dict(
        market_id=market().checksum,
        observed_at=NOW,
        regime=regime_reading(),
        event_risk=event_risk(),
        structure=(
            StructuralLevelReading(
                level_id="asian_range_high",
                price=Decimal("1.28610"),
                level_type="range_extreme",
                timeframe="m5",
                derivation_id="asian_session.range_high",
                sample_bars=96,
            ),
        ),
        execution=execution(),
        analog_sample_size=40,
    )
    base.update(overrides)
    return ContextPacket(**base)


class TestRegimeAnalyst:
    def test_a_regime_call_must_be_grounded_in_a_measure(self) -> None:
        # §6.4 wants a "deterministic-data-grounded regime packet"; a bare label
        # is chart prose with an enum attached.
        with pytest.raises(ValidationError, match="no deterministic measure"):
            regime_reading(measures={})

    def test_measures_must_name_features_not_describe_them(self) -> None:
        with pytest.raises(ValidationError, match="not feature identifiers"):
            regime_reading(measures={"looks really tight to me": Decimal("1")})


class TestEventRiskAnalystFailsClosed:
    def test_a_missing_calendar_permits_no_entries(self) -> None:
        reading = EventRiskReading.unavailable("calendar provider returned 503")
        assert reading.calendar_state == "missing"
        assert reading.entries_permitted is False

    def test_a_stale_calendar_permits_no_entries(self) -> None:
        reading = event_risk(calendar_state="stale", unavailable_reason="last refresh 6h ago")
        assert reading.entries_permitted is False

    def test_a_fresh_calendar_inside_a_blackout_permits_no_entries(self) -> None:
        assert event_risk(blackout_active=True).entries_permitted is False

    def test_freshness_without_a_timestamp_cannot_be_claimed(self) -> None:
        with pytest.raises(ValidationError, match="no as_of_utc"):
            EventRiskReading(calendar_state="fresh")

    def test_a_failure_must_say_what_failed(self) -> None:
        with pytest.raises(ValidationError, match="no unavailable_reason"):
            EventRiskReading(calendar_state="stale", as_of_utc=NOW)

    def test_naive_timestamps_are_refused(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware|naive"):
            EventRiskReading(
                calendar_state="fresh", as_of_utc=dt.datetime(2026, 7, 30, 7, 40)
            )

    def test_age_is_reportable_for_a_callers_own_staleness_limit(self) -> None:
        reading = event_risk()
        assert reading.age_at(NOW + dt.timedelta(minutes=90)) == dt.timedelta(minutes=90)
        assert EventRiskReading.unavailable("no data").age_at(NOW) is None

    def test_high_impact_entries_are_isolable(self) -> None:
        reading = event_risk(
            entries=(
                CalendarEntry(
                    time_utc=NOW + dt.timedelta(hours=1),
                    currency="GBP",
                    impact="High",
                    name="BoE Bank Rate",
                    blackout=True,
                ),
                CalendarEntry(
                    time_utc=NOW + dt.timedelta(hours=3),
                    currency="USD",
                    impact="Low",
                    name="Redbook",
                    blackout=False,
                ),
            )
        )
        assert len(reading.high_impact_entries) == 1


class TestStructureAnalystReproducibility:
    def test_chart_prose_cannot_be_a_derivation(self) -> None:
        # §6.4: "reproducible data where possible rather than subjective chart prose".
        with pytest.raises(ValidationError, match="chart prose"):
            StructuralLevelReading(
                level_id="asian_range_high",
                price=Decimal("1.28610"),
                level_type="range_extreme",
                timeframe="m5",
                derivation_id="the obvious level everyone is watching",
                sample_bars=96,
            )

    def test_prose_may_accompany_the_data_in_a_note(self) -> None:
        level = StructuralLevelReading(
            level_id="asian_range_high",
            price=Decimal("1.28610"),
            level_type="range_extreme",
            timeframe="m5",
            derivation_id="asian_session.range_high",
            sample_bars=96,
            note="twice rejected overnight",
        )
        assert level.note == "twice rejected overnight"

    def test_a_level_must_say_how_many_bars_it_was_computed_from(self) -> None:
        with pytest.raises(ValidationError):
            StructuralLevelReading(
                level_id="asian_range_high",
                price=Decimal("1.28610"),
                level_type="range_extreme",
                timeframe="m5",
                derivation_id="asian_session.range_high",
                sample_bars=0,
            )


class TestExecutionConditions:
    def test_edge_surviving_costs_is_a_subtraction_not_an_opinion(self) -> None:
        conditions = execution(expected_gross_r=Decimal("1.5"), expected_cost_r=Decimal("0.3"))
        assert conditions.expected_net_r == Decimal("1.2")
        assert conditions.survives_costs is True

    def test_break_even_after_costs_does_not_survive(self) -> None:
        conditions = execution(expected_gross_r=Decimal("0.8"), expected_cost_r=Decimal("0.8"))
        assert conditions.expected_net_r == Decimal("0")
        assert conditions.survives_costs is False

    def test_spread_limits_are_checked_against_the_configured_maximum(self) -> None:
        assert execution(spread_pips=Decimal("2.5")).spread_within_limits is True
        assert execution(spread_pips=Decimal("2.6")).spread_within_limits is False


class TestContextPacket:
    def test_a_clean_context_permits_entries(self) -> None:
        packet = context()
        assert packet.blocking_conditions == ()
        assert packet.entries_permitted is True

    @pytest.mark.parametrize(
        "override,fragment",
        [
            ({"event_risk": EventRiskReading.unavailable("provider down")}, "calendar state"),
            ({"event_risk": event_risk(blackout_active=True)}, "blackout"),
            ({"execution": execution(broker_healthy=False)}, "broker connection"),
            ({"execution": execution(spread_pips=Decimal("9.5"))}, "exceeds"),
            ({"execution": execution(liquidity_state="disorderly")}, "disorderly"),
            (
                {"execution": execution(expected_gross_r=Decimal("0.1"))},
                "does not survive",
            ),
        ],
    )
    def test_every_degraded_condition_blocks_new_entries(self, override, fragment) -> None:
        packet = context(**override)
        assert packet.entries_permitted is False
        assert any(fragment in reason for reason in packet.blocking_conditions)

    def test_every_blocking_cause_is_reported_not_just_the_first(self) -> None:
        # A second cause hiding behind the first is how a system looks recovered
        # while still broken.
        packet = context(
            event_risk=EventRiskReading.unavailable("provider down"),
            execution=execution(broker_healthy=False, liquidity_state="disorderly"),
        )
        assert len(packet.blocking_conditions) == 3

    def test_a_duplicated_level_cannot_double_count_as_confirmation(self) -> None:
        level = StructuralLevelReading(
            level_id="asian_range_high",
            price=Decimal("1.28610"),
            level_type="range_extreme",
            timeframe="m5",
            derivation_id="asian_session.range_high",
            sample_bars=96,
        )
        with pytest.raises(ValidationError, match="reported twice"):
            context(structure=(level, level))

    def test_context_must_be_bound_to_the_packet_the_traders_received(self) -> None:
        snapshot = market()
        context().verify_against(snapshot)  # matching: no raise
        with pytest.raises(ValueError, match="checksum|describes market"):
            context(market_id="0" * 64).verify_against(snapshot)

    def test_an_analyst_may_not_restate_the_computed_regime_as_something_else(self) -> None:
        with pytest.raises(ValueError, match="may not restate a computed value"):
            context(regime=regime_reading(regime=RegimeLabel.TREND)).verify_against(market())

    def test_context_carries_the_analog_sample_size_as_an_input(self) -> None:
        # Agent N builds it elsewhere; the packet records it so the evidence
        # basis of a session is legible in one place (§6.4).
        assert context(analog_sample_size=0).analog_sample_size == 0
        with pytest.raises(ValidationError):
            context(analog_sample_size=-1)

    def test_context_holds_no_firm_state_field(self) -> None:
        fields = set(ContextPacket.model_fields)
        for forbidden in (
            "closed_equity",
            "session_realized_loss",
            "trades_this_session",
            "drawdown_state",
            "firm",
        ):
            assert forbidden not in fields, (
                f"context carries {forbidden}: context is what the market is, not what the "
                f"firm needs from it (A-2, §5.1)"
            )


# --------------------------------------------------------------- A-2 guardrails


class TestPressureInvarianceGuards:
    """A-2 at source level, mirroring `test_classification.py`.

    A specialist that could see the firm was behind would be a pressure input
    with an expert's badge on it, and a context packet that carried equity would
    let a regime call drift with the P&L. Neither is currently possible; these
    tests are what fail on the day someone widens a signature.
    """

    def _source(self) -> str:
        import trading_firm.agents.bench as module

        return pathlib.Path(module.__file__).read_text()

    def test_bench_never_imports_firm_state(self) -> None:
        tree = ast.parse(self._source())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                imported |= {alias.name for alias in node.names}
        assert "FirmSnapshot" not in imported, (
            "bench imports FirmSnapshot: specialists and context agents assess the market, "
            "never the firm's need (A-2, §5.1)"
        )

    def test_bench_code_never_names_firm_state(self) -> None:
        # Catches an aliased import or a fully-qualified `packet.FirmSnapshot`.
        source = self._source()
        code_lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
        executable = "".join("\n".join(code_lines).split('"""')[::2])
        assert "FirmSnapshot" not in executable, (
            "bench code references FirmSnapshot (A-2, §5.1)"
        )

    def test_no_public_callable_accepts_firm_state(self) -> None:
        for fn in (assess_relevance, relevant_specialists, consult, bench_domain):
            rendered = " ".join(
                str(p.annotation) for p in inspect.signature(fn).parameters.values()
            )
            assert "FirmSnapshot" not in rendered, (
                f"{fn.__name__} accepts firm state (A-2, §5.1)"
            )

    def test_bench_never_reaches_the_execution_package(self) -> None:
        # Iron rule §0.3 / §2: no LLM-facing module may touch the order path.
        source = self._source()
        assert "trading_firm.execution" not in source, (
            "bench references the execution package: no agent-facing module may reach the "
            "broker adapter (§0.3, §2)"
        )

    def test_a_round_is_reproducible_from_the_market_alone(self) -> None:
        # The bench analogue of the classification invariance property: the same
        # market and the same verdicts give the same round, every time.
        snapshot = market()
        calls = [consultation(BREAKOUT, SpecialistVerdict.SUPPORT)]
        first = consult(THESIS, snapshot, calls)
        second = consult(THESIS, market(), calls)
        assert first == second
        assert isinstance(first, ConsultationRound)


def test_module_is_pressure_blind_under_the_shared_guard() -> None:
    """A-2 (§5.1) via `tests/a2_guard.py`.

    The local guards in this file check the single name `FirmSnapshot`. An
    adversarial review defeated that by importing `AccountState` instead, so
    the shared guard checks the whole firm-state vocabulary. Both run: the
    local one gives a module-specific message, this one is the real check.
    """
    import importlib

    from a2_guard import assert_pressure_blind

    assert_pressure_blind(importlib.import_module("trading_firm.agents.bench"))


class TestRegimeMeasuresCannotBeMutatedPastTheValidator:
    """§6.4: a regime call must stay grounded in what the validator checked.

    Pydantic's frozen flag blocks attribute rebinding but not in-place
    mutation, so a plain `dict` field left the grounding rule bypassable in one
    line after construction.
    """

    def test_measures_reject_prose_at_construction(self) -> None:
        with pytest.raises(ValidationError, match="not feature identifiers"):
            RegimeReading(
                regime=RegimeLabel.COMPRESSION,
                feature_version="session_features_v1",
                measures={"the tape just looks tight to me": Decimal("1")},
            )

    def test_measures_cannot_be_mutated_after_construction(self) -> None:
        reading = RegimeReading(
            regime=RegimeLabel.COMPRESSION,
            feature_version="session_features_v1",
            measures={"session_features_v1.asian_width_pips": Decimal("38")},
        )
        with pytest.raises(TypeError):
            reading.measures["the tape just looks tight to me"] = Decimal("1")

    def test_the_caller_s_dict_is_copied_not_captured(self) -> None:
        supplied = {"session_features_v1.asian_width_pips": Decimal("38")}
        reading = RegimeReading(
            regime=RegimeLabel.COMPRESSION,
            feature_version="session_features_v1",
            measures=supplied,
        )
        supplied["session_features_v1.compression_ratio"] = Decimal("0.4")
        assert "session_features_v1.compression_ratio" not in reading.measures, (
            "holding the caller's dict lets it be edited from outside the record"
        )


class TestContextCannotContradictThePacketItCites:
    """§6A/§6.4: a context report may restate the packet, never revise it.

    Binding only the checksum and the regime left a report free to contradict
    the packet on spread, event state, analog depth, and observation time — the
    four values that set the evidence ceiling in classification.py — while
    verify_against reported it healthy. A report that disagrees with its own
    source is worse than one that omits the value: it looks corroborating.
    """

    def test_the_honest_packet_verifies(self) -> None:
        context().verify_against(market())  # does not raise

    def test_a_narrower_reported_spread_is_caught(self) -> None:
        wide = market(spread_pips=Decimal("9.0"))
        # Claims a tradeable 1.2-pip spread over a 9-pip tape: §5.3 caps E3 on
        # spread, so this is the difference between Exceptional and not.
        packet = context(market_id=wide.checksum, execution=execution(spread_pips=Decimal("1.2")))
        with pytest.raises(ValueError, match="spread_pips"):
            packet.verify_against(wide)

    def test_a_suppressed_event_blackout_is_caught(self) -> None:
        eventful = market(high_impact_event_active=True)
        packet = context(market_id=eventful.checksum, event_risk=event_risk(blackout_active=False))
        with pytest.raises(ValueError, match="blackout_active"):
            packet.verify_against(eventful)

    def test_an_inflated_analog_depth_is_caught(self) -> None:
        thin = market(analog_sample_size=3)
        packet = context(market_id=thin.checksum, analog_sample_size=40)
        with pytest.raises(ValueError, match="analog_sample_size"):
            packet.verify_against(thin)

    def test_a_stale_observation_time_is_caught(self) -> None:
        snapshot = market()
        packet = context(observed_at=NOW - dt.timedelta(days=1))
        with pytest.raises(ValueError, match="observed_at"):
            packet.verify_against(snapshot)

    def test_every_disagreement_is_reported_not_just_the_first(self) -> None:
        bad = market(spread_pips=Decimal("9.0"), high_impact_event_active=True,
                     analog_sample_size=3)
        packet = context(market_id=bad.checksum)
        with pytest.raises(ValueError) as excinfo:
            packet.verify_against(bad)
        message = str(excinfo.value)
        for field in ("spread_pips", "blackout_active", "analog_sample_size"):
            assert field in message, f"{field} silently omitted from the disagreement list"
