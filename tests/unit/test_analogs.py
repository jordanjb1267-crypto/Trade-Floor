"""Historical analog and base-rate engine (§6.4 agent N; §12.4, §12.6, §12.7).

Three properties carry the weight here, and each is asserted as an
impossibility rather than a rejection:

1. **The analog set cannot be chosen after the direction is known (§6.4).** The
   query type has no direction field, the search function has no direction
   parameter, and a query edited after commitment cannot be run against the
   pre-registered hash. The cherry-pick is not caught — it has nowhere to
   happen.
2. **No research number can leave the research environment unreviewed
   (§12.7 / A-1).** The publication gate is shut by default, refuses to open on
   a bare boolean, and suppresses every §12.6 evidence claim while it is shut.
3. **Firm state never reaches a base rate (A-2, §5.1).** History is history.
   `FirmSnapshot` is unreachable from this module at source level.
"""

import ast
import dataclasses
import datetime as dt
import inspect
import pathlib
from decimal import Decimal

import pydantic
import pytest
from pydantic import ValidationError

import trading_firm.research.analogs as analogs
from trading_firm.models import Direction
from trading_firm.research.analogs import (
    FORBIDDEN_QUERY_FIELDS,
    MINIMUM_SAMPLE,
    PRIMARY_THRESHOLD_SCALE,
    REQUIRED_REVIEW_COVERAGE,
    AdversarialReview,
    AnalogQuery,
    AnalogReport,
    CommittedQuery,
    CostModel,
    DataLimitations,
    DirectionalOutcomes,
    EvidenceUse,
    FeatureTolerance,
    HistoricalObservation,
    OutcomeDistribution,
    PublicationGateError,
    QueryCommitmentError,
    SimilarityMethod,
    commit_query,
    search_analogs,
)

UTC = dt.UTC
AS_OF = dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC)
GENERATED_AT = dt.datetime(2026, 7, 30, 7, 41, tzinfo=UTC)
FEATURE = "session_features_v1.asian_width_pips"
COST = Decimal("1.5")  # 1.2 spread + 0.3 slippage


def query(**overrides) -> AnalogQuery:
    base = dict(
        query_label="compressed asian range before the London open",
        pre_registered_hypothesis=(
            "an asian range near 38 pips is followed by directional expansion"
        ),
        instrument="GBP_USD",
        data_source_id="oanda_m5_practice_2024_2026",
        similarity_method=SimilarityMethod.TOLERANCE_BOX,
        tolerances=(
            FeatureTolerance(
                feature_id=FEATURE, target=Decimal("38"), tolerance=Decimal("6")
            ),
        ),
        start_date=dt.date(2024, 1, 1),
        end_date=dt.date(2026, 6, 30),
        as_of_utc=AS_OF,
        horizon_minutes=180,
        embargo_days=2,
        threshold_scales=(Decimal("0.5"), Decimal("1"), Decimal("1.5")),
        cost_model=CostModel(
            spread_pips=Decimal("1.2"),
            slippage_pips=Decimal("0.3"),
            commission_pips=Decimal("0"),
        ),
        known_coverage_gaps=("2025-03 broker feed outage, 4 sessions",),
    )
    base.update(overrides)
    return AnalogQuery(**base)


def observation(
    index: int,
    *,
    move: Decimal,
    width: Decimal = Decimal("38"),
    regime: str = "compression",
    session_date: dt.date | None = None,
    **overrides,
) -> HistoricalObservation:
    day = session_date or dt.date(2025, 1, 6) + dt.timedelta(days=index)
    base = dict(
        observation_id=f"obs-{index}",
        instrument="GBP_USD",
        observed_at=dt.datetime.combine(day, dt.time(7, 40), tzinfo=UTC),
        session_date=day,
        regime=regime,
        horizon_minutes=180,
        forward_move_pips=move,
        outcome_observed_at=dt.datetime.combine(day, dt.time(10, 40), tzinfo=UTC),
        features={FEATURE: width},
        data_complete=True,
    )
    base.update(overrides)
    return HistoricalObservation(**base)


def corpus() -> list[HistoricalObservation]:
    """Six matching sessions, three up and three down, on six distinct dates.

    Widths fan out from the 38-pip target so the threshold sweep is not
    degenerate: at 0.5 tolerance units only the four tightest match, at 1.0 all
    six do. A corpus sitting exactly on target would make every sensitivity
    assertion true for the wrong reason.
    """
    # Ordered so the tightest matches are the winners: the tight box looks
    # excellent for longs and the committed box does not, which is exactly the
    # threshold-shopping case §6.4's sensitivity disclosure exists to expose.
    moves = [Decimal("12"), Decimal("20"), Decimal("8"), Decimal("6"), Decimal("-30"),
             Decimal("-24")]
    return [
        observation(
            i,
            move=move,
            width=Decimal(38 + i),
            regime="compression" if i % 2 else "balance",
        )
        for i, move in enumerate(moves)
    ]


def run(q: AnalogQuery | None = None, observations=None) -> AnalogReport:
    q = q or query()
    committed = commit_query(q, at=dt.datetime(2026, 7, 30, 7, 0, tzinfo=UTC), by="agent-N")
    return search_analogs(
        committed,
        corpus() if observations is None else observations,
        expected_query_id=committed.query_id,
        generated_at=GENERATED_AT,
    )


# --------------------------------------------------------------------- §6.4 N


class TestTheQueryCannotKnowTheDirection:
    """§6.4: "must not cherry-pick a favorable analog set after seeing the
    desired trade direction." Removed as a possibility, not forbidden."""

    def test_analog_query_declares_no_direction_shaped_field(self) -> None:
        assert not FORBIDDEN_QUERY_FIELDS & set(AnalogQuery.model_fields)

    def test_the_import_time_guard_fails_if_a_direction_field_is_added(
        self, monkeypatch
    ) -> None:
        class Sneaky(AnalogQuery):
            side: str = "long"

        monkeypatch.setattr(analogs, "AnalogQuery", Sneaky)
        with pytest.raises(RuntimeError, match=r"§6.4"):
            analogs._reject_direction_fields()

    def test_search_analogs_takes_no_direction_argument(self) -> None:
        params = set(inspect.signature(search_analogs).parameters)
        assert not FORBIDDEN_QUERY_FIELDS & params

    def test_no_public_callable_in_the_module_accepts_a_direction(self) -> None:
        for name, obj in vars(analogs).items():
            if name.startswith("_") or not inspect.isfunction(obj):
                continue
            if obj.__module__ != analogs.__name__:
                continue
            params = set(inspect.signature(obj).parameters)
            assert not FORBIDDEN_QUERY_FIELDS & params, (
                f"{name} accepts a direction: an analog search conditioned on the "
                f"direction it justifies is the §6.4 cherry-pick"
            )

    def test_the_observation_record_stores_a_signed_move_not_a_pnl(self) -> None:
        # A stored "profit" would already encode a direction; a signed move does
        # not, which is what lets one set answer for both sides.
        names = {f.name for f in dataclasses.fields(HistoricalObservation)}
        assert "forward_move_pips" in names
        assert not FORBIDDEN_QUERY_FIELDS & names


class TestQueryCommitment:
    def test_the_same_definition_hashes_identically(self) -> None:
        assert query().content_hash == query().content_hash

    @pytest.mark.parametrize(
        "field,value",
        [
            ("start_date", dt.date(2025, 1, 1)),
            ("end_date", dt.date(2026, 5, 31)),
            ("horizon_minutes", 120),
            ("embargo_days", 5),
            ("pre_registered_hypothesis", "something else entirely"),
            ("regime_filter", ("compression",)),
            ("similarity_method", SimilarityMethod.NORMALIZED_L1),
        ],
    )
    def test_every_search_parameter_participates_in_the_hash(self, field, value) -> None:
        assert query().content_hash != query(**{field: value}).content_hash

    def test_widening_a_tolerance_produces_a_different_query(self) -> None:
        wider = query(
            tolerances=(
                FeatureTolerance(
                    feature_id=FEATURE, target=Decimal("38"), tolerance=Decimal("20")
                ),
            )
        )
        assert wider.content_hash != query().content_hash

    def test_a_query_altered_after_commitment_fails_verification(self) -> None:
        committed = commit_query(query(), at=AS_OF, by="agent-N")
        tampered = CommittedQuery(
            query=committed.query.model_copy(update={"embargo_days": 0}),
            query_id=committed.query_id,
            committed_at=committed.committed_at,
            committed_by=committed.committed_by,
        )
        with pytest.raises(QueryCommitmentError, match="altered after commitment"):
            tampered.verify()

    def test_the_engine_refuses_a_hash_the_caller_did_not_pre_register(self) -> None:
        """The headline anti-cherry-pick test, end to end.

        Run the committed query, dislike the answer, widen the box, re-commit,
        and try to pass the result off under the original pre-registration.
        """
        original = query()
        committed = commit_query(original, at=AS_OF, by="agent-N")
        friendlier = commit_query(
            original.model_copy(
                update={
                    "tolerances": (
                        FeatureTolerance(
                            feature_id=FEATURE,
                            target=Decimal("38"),
                            tolerance=Decimal("40"),
                        ),
                    )
                }
            ),
            at=AS_OF,
            by="agent-N",
        )
        assert friendlier.query_id != committed.query_id
        with pytest.raises(QueryCommitmentError, match="pre-registered"):
            search_analogs(
                friendlier,
                corpus(),
                expected_query_id=committed.query_id,
                generated_at=GENERATED_AT,
            )

    def test_a_report_cannot_cite_a_query_id_it_does_not_hash_to(self) -> None:
        report = run()
        with pytest.raises(QueryCommitmentError, match="do not belong to"):
            dataclasses.replace(report, query_id="0" * 64)

    def test_duplicate_observation_ids_are_refused(self) -> None:
        doubled = corpus() + [corpus()[0]]
        with pytest.raises(ValueError, match="appear more than once"):
            run(observations=doubled)


class TestQueryValidation:
    def test_a_single_threshold_cannot_satisfy_the_sensitivity_requirement(self) -> None:
        with pytest.raises(ValidationError, match="sensitivity to similarity thresholds"):
            query(threshold_scales=(Decimal("1"),))

    def test_the_sweep_must_contain_the_primary_scale(self) -> None:
        with pytest.raises(ValidationError, match="must include the primary scale"):
            query(threshold_scales=(Decimal("0.5"), Decimal("0.8"), Decimal("1.2")))

    def test_the_sweep_must_be_ascending_and_distinct(self) -> None:
        with pytest.raises(ValidationError, match="strictly ascending"):
            query(threshold_scales=(Decimal("1.5"), Decimal("1"), Decimal("0.5")))

    def test_a_repeated_feature_cannot_double_weight_the_metric(self) -> None:
        tol = FeatureTolerance(feature_id=FEATURE, target=Decimal("38"), tolerance=Decimal("6"))
        with pytest.raises(ValidationError, match="appear twice in the search box"):
            query(tolerances=(tol, tol))

    def test_a_costless_round_trip_is_not_an_explicit_cost_model(self) -> None:
        with pytest.raises(ValidationError, match="EXPLICIT transaction-cost"):
            CostModel(
                spread_pips=Decimal("0"),
                slippage_pips=Decimal("0"),
                commission_pips=Decimal("0"),
            )

    def test_a_window_reaching_past_the_as_of_date_is_leakage_by_construction(self) -> None:
        with pytest.raises(ValidationError, match="future leakage by construction"):
            query(end_date=dt.date(2026, 8, 31))

    def test_floats_are_refused_at_the_edge(self) -> None:
        with pytest.raises(ValidationError, match="is a float"):
            FeatureTolerance(feature_id=FEATURE, target=38.0, tolerance=Decimal("6"))

    def test_a_naive_as_of_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            query(as_of_utc=dt.datetime(2026, 7, 30, 7, 40))

    def test_coverage_gaps_must_be_stated_even_when_empty(self) -> None:
        fields = dict(query().model_dump())
        fields.pop("known_coverage_gaps")
        with pytest.raises(ValidationError):
            AnalogQuery(**fields)


class TestBothDirectionsAlways:
    """§6.4 item 4, reported for both sides of one analog set — always."""

    def test_every_report_carries_both_sides_over_the_same_set(self) -> None:
        d = run().outcome_distribution
        assert d.long_outcomes.direction is Direction.LONG
        assert d.short_outcomes.direction is Direction.SHORT
        assert d.long_outcomes.count == d.short_outcomes.count == 6

    def test_the_two_sides_sum_to_exactly_twice_the_cost(self) -> None:
        """The identity that makes a direction-selective set detectable.

        Both sides are the same analogs charged the same costs, so the totals
        must sum to -2 * cost * n. Filtering one side breaks it exactly.
        """
        d = run().outcome_distribution
        total = d.long_outcomes.sum_net_pips + d.short_outcomes.sum_net_pips
        assert total == -2 * COST * 6

    def test_a_set_cannot_be_favorable_to_both_directions(self) -> None:
        d = run().outcome_distribution
        assert d.long_outcomes.mean_net_pips + d.short_outcomes.mean_net_pips == -2 * COST
        assert not (
            d.long_outcomes.mean_net_pips > 0 and d.short_outcomes.mean_net_pips > 0
        )

    def test_a_distribution_built_from_two_different_sets_is_rejected(self) -> None:
        d = run().outcome_distribution
        trimmed = dataclasses.replace(
            d.short_outcomes, count=d.short_outcomes.count - 1
        )
        with pytest.raises(ValueError, match="the SAME analog set"):
            OutcomeDistribution(
                long_outcomes=d.long_outcomes,
                short_outcomes=trimmed,
                cost_pips_per_trade=COST,
            )

    def test_a_short_side_quietly_recomputed_without_costs_is_rejected(self) -> None:
        d = run().outcome_distribution
        flattering = dataclasses.replace(
            d.short_outcomes,
            sum_net_pips=d.short_outcomes.sum_net_pips + 2 * COST * 6,
        )
        with pytest.raises(ValueError, match="not the same analogs charged the same costs"):
            OutcomeDistribution(
                long_outcomes=d.long_outcomes,
                short_outcomes=flattering,
                cost_pips_per_trade=COST,
            )

    def test_costs_are_charged_to_both_sides_not_netted(self) -> None:
        one = [observation(0, move=Decimal("10"))]
        d = run(observations=one).outcome_distribution
        assert d.long_outcomes.sum_net_pips == Decimal("10") - COST
        assert d.short_outcomes.sum_net_pips == Decimal("-10") - COST


class TestSevenRequiredDisclosures:
    """§6.4 names seven outputs. A report missing one is misleading, not short."""

    REQUIRED = (
        "query",  # search definition
        "analog_count",  # number of analogs
        "similarity_method",  # similarity method
        "outcome_distribution",  # outcome distribution after costs
        "regime_breakdown",  # regime breakdown
        "threshold_sensitivity",  # sensitivity to similarity thresholds
        "data_limitations",  # data limitations
    )

    def test_all_seven_are_required_constructor_fields(self) -> None:
        by_name = {f.name: f for f in dataclasses.fields(AnalogReport)}
        for name in self.REQUIRED:
            field = by_name[name]
            assert field.default is dataclasses.MISSING, f"{name} has a default"
            assert field.default_factory is dataclasses.MISSING, f"{name} is optional"

    def test_sensitivity_covers_every_committed_threshold(self) -> None:
        report = run()
        assert tuple(p.threshold_scale for p in report.threshold_sensitivity) == (
            Decimal("0.5"),
            Decimal("1"),
            Decimal("1.5"),
        )

    def test_a_sweep_truncated_after_the_results_were_seen_is_rejected(self) -> None:
        report = run()
        with pytest.raises(ValueError, match="not a subset chosen after"):
            dataclasses.replace(
                report, threshold_sensitivity=report.threshold_sensitivity[:1]
            )

    def test_the_headline_count_is_the_primary_scale(self) -> None:
        report = run()
        primary = next(
            p
            for p in report.threshold_sensitivity
            if p.threshold_scale == PRIMARY_THRESHOLD_SCALE
        )
        assert report.analog_count == primary.analog_count

    def test_the_regime_breakdown_partitions_the_analogs(self) -> None:
        report = run()
        assert sum(s.analog_count for s in report.regime_breakdown) == report.analog_count
        assert {s.regime for s in report.regime_breakdown} == {"compression", "balance"}

    def test_data_limitations_can_never_be_empty(self) -> None:
        assert run().data_limitations.notes

    def test_a_limitations_block_asserting_nothing_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="asserting the data is"):
            DataLimitations(
                observations_supplied=6,
                excluded_wrong_instrument=0,
                excluded_outside_date_range=0,
                excluded_horizon_mismatch=0,
                excluded_lookahead=0,
                excluded_by_embargo=0,
                excluded_incomplete_data=0,
                excluded_missing_features=0,
                excluded_by_regime_filter=0,
                eligible_population=6,
                distinct_session_dates_eligible=6,
                known_coverage_gaps=(),
                notes=(),
            )

    def test_the_declared_method_must_match_the_committed_one(self) -> None:
        report = run()
        with pytest.raises(ValueError, match="but the query committed"):
            dataclasses.replace(report, similarity_method=SimilarityMethod.NORMALIZED_L1)


class TestLeakageAndHonestDenominators:
    """§12.4 anti-overfitting and §12.7 rule 6 honest denominators."""

    def test_an_outcome_that_completes_after_the_as_of_moment_is_discarded(self) -> None:
        future = observation(
            9,
            move=Decimal("99"),
            session_date=dt.date(2026, 6, 29),
            outcome_observed_at=dt.datetime(2026, 7, 31, 10, 40, tzinfo=UTC),
        )
        report = run(observations=corpus() + [future])
        assert report.data_limitations.excluded_lookahead == 1
        assert report.analog_count == 6
        assert any("not knowable at decision time" in n for n in report.data_limitations.notes)

    def test_the_embargo_excludes_outcomes_overlapping_the_decision_window(self) -> None:
        recent = observation(
            9,
            move=Decimal("99"),
            session_date=dt.date(2026, 6, 29),
            observed_at=dt.datetime(2026, 7, 29, 7, 40, tzinfo=UTC),
            outcome_observed_at=dt.datetime(2026, 7, 29, 10, 40, tzinfo=UTC),
        )
        report = run(observations=corpus() + [recent])
        assert report.data_limitations.excluded_by_embargo == 1
        assert report.analog_count == 6

    def test_an_outcome_stamped_before_its_own_observation_cannot_be_built(self) -> None:
        with pytest.raises(ValueError, match="look-ahead data, not history"):
            observation(
                1,
                move=Decimal("5"),
                outcome_observed_at=dt.datetime(2025, 1, 7, 6, 0, tzinfo=UTC),
            )

    def test_incomplete_and_featureless_observations_are_excluded_and_disclosed(
        self,
    ) -> None:
        broken = [
            observation(20, move=Decimal("30"), data_complete=False),
            observation(21, move=Decimal("30"), features={}),
        ]
        report = run(observations=corpus() + broken)
        limits = report.data_limitations
        assert limits.excluded_incomplete_data == 1
        assert limits.excluded_missing_features == 1
        assert limits.eligible_population == 6
        assert limits.observations_supplied == 8
        assert any("coverage hole" in n for n in limits.notes)

    def test_the_wrong_instrument_horizon_or_date_never_enters_the_population(self) -> None:
        strays = [
            observation(30, move=Decimal("30"), instrument="EUR_USD"),
            observation(31, move=Decimal("30"), horizon_minutes=60),
            observation(32, move=Decimal("30"), session_date=dt.date(2023, 5, 1)),
        ]
        limits = run(observations=corpus() + strays).data_limitations
        assert limits.excluded_wrong_instrument == 1
        assert limits.excluded_horizon_mismatch == 1
        assert limits.excluded_outside_date_range == 1
        assert limits.eligible_population == 6

    def test_the_regime_filter_is_disclosed_as_a_conditioning_choice(self) -> None:
        report = run(query(regime_filter=("compression",)))
        assert report.analog_count == 3
        assert report.data_limitations.excluded_by_regime_filter == 3
        assert any("conditional on that filter" in n for n in report.data_limitations.notes)

    def test_known_coverage_gaps_are_carried_into_the_report(self) -> None:
        gaps = run().data_limitations.known_coverage_gaps
        assert gaps == ("2025-03 broker feed outage, 4 sessions",)

    def test_a_borderline_similarity_distance_excludes_rather_than_admits(self) -> None:
        """Ambiguity must shrink claimed evidence, never inflate it (§12.4).

        A width of 39 against a tolerance of 3 sits at 1/3 of a tolerance unit —
        a non-terminating decimal. Rounding it down would admit the observation
        at a threshold of exactly 0.333333; rounding up excludes it.
        """
        q = query(
            tolerances=(
                FeatureTolerance(
                    feature_id=FEATURE, target=Decimal("38"), tolerance=Decimal("3")
                ),
            ),
            threshold_scales=(Decimal("0.333333"), Decimal("1"), Decimal("2")),
        )
        report = run(q, observations=[observation(0, move=Decimal("5"), width=Decimal("39"))])
        tight = report.threshold_sensitivity[0]
        assert tight.analog_count == 0
        assert report.analog_count == 1

    def test_widening_the_threshold_can_only_add_analogs(self) -> None:
        counts = [p.analog_count for p in run().threshold_sensitivity]
        assert counts == [4, 6, 6]  # non-degenerate: the sweep actually moves
        assert counts == sorted(counts)

    def test_the_sweep_shows_when_a_result_survives_only_at_one_threshold(self) -> None:
        """The disclosure that makes threshold-shopping visible (§6.4).

        The tight box here is favorable to longs and the committed box is not.
        Publishing the tight number alone would be a defensible-looking lie; the
        report forces both onto the same page.
        """
        sweep = {p.threshold_scale: p for p in run().threshold_sensitivity}
        tight = sweep[Decimal("0.5")].distribution.long_outcomes.mean_net_pips
        committed = sweep[Decimal("1")].distribution.long_outcomes.mean_net_pips
        assert tight > 0 > committed

    def test_an_empty_result_says_so_instead_of_implying_a_base_rate(self) -> None:
        far = [observation(0, move=Decimal("5"), width=Decimal("500"))]
        report = run(observations=far)
        assert report.analog_count == 0
        assert report.outcome_distribution.long_outcomes.mean_net_pips is None
        assert any("establishes no base rate" in n for n in report.data_limitations.notes)


class TestPublicationGate:
    """§12.7 / amendment A-1: the gate is shut and cannot be nudged open."""

    def test_a_fresh_report_is_not_cleared(self) -> None:
        report = run()
        assert report.publication_cleared is False
        assert report.review is None

    def test_formatting_for_publication_raises_and_cites_the_section(self) -> None:
        with pytest.raises(PublicationGateError, match=r"§12.7 rule 1"):
            run().format_for_publication()

    def test_preview_works_and_stamps_what_it_may_not_be_used_for(self) -> None:
        text = run().preview()
        assert "NOT PUBLISHABLE" in text
        assert "§12.7" in text
        # The seven §6.4 disclosures must all be legible in the rendering.
        for heading in (
            "Search definition",
            "Number of analogs",
            "Similarity method",
            "Outcome distribution after costs",
            "Regime breakdown",
            "Sensitivity to similarity threshold",
            "Data limitations",
        ):
            assert heading in text

    def test_an_empty_report_still_renders_all_seven_disclosures(self) -> None:
        far = [observation(0, move=Decimal("5"), width=Decimal("500"))]
        text = run(query(known_coverage_gaps=()), observations=far).preview()
        assert "Number of analogs   : 0" in text
        assert "(no analogs)" in text
        assert "establishes no base rate" in text
        assert "no additional coverage gaps were declared" in text

    def test_flipping_the_boolean_alone_is_refused(self) -> None:
        with pytest.raises(PublicationGateError, match="no adversarial review attached"):
            dataclasses.replace(run(), publication_cleared=True)

    def test_a_self_review_is_not_a_review(self) -> None:
        with pytest.raises(ValueError, match="independent of the code's author"):
            AdversarialReview(
                review_record_id="AR-1",
                reviewer_id="agent-N",
                author_id="agent-N",
                reviewed_at=AS_OF,
                covered_areas=frozenset(REQUIRED_REVIEW_COVERAGE),
                findings_confirmed=(),
                findings_refuted=(),
                decision_log_ref="governance/decision-log.md#ar-1",
            )

    def test_a_review_may_extend_the_required_coverage_but_never_shorten_it(self) -> None:
        with pytest.raises(ValueError, match="minimum coverage"):
            AdversarialReview(
                review_record_id="AR-2",
                reviewer_id="chief-quant",
                author_id="agent-N",
                reviewed_at=AS_OF,
                covered_areas=frozenset({"fill_and_cost_model"}),
                findings_confirmed=(),
                findings_refuted=(),
                decision_log_ref="governance/decision-log.md#ar-2",
            )

    def test_a_review_without_an_audit_trail_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="decision-log"):
            AdversarialReview(
                review_record_id="AR-3",
                reviewer_id="chief-quant",
                author_id="agent-N",
                reviewed_at=AS_OF,
                covered_areas=frozenset(REQUIRED_REVIEW_COVERAGE),
                findings_confirmed=("fill model overstated",),
                findings_refuted=("claimed off-by-one in the embargo",),
                decision_log_ref="   ",
            )

    def test_the_module_never_clears_its_own_gate(self) -> None:
        """No code path in the engine sets `publication_cleared` True.

        Clearance comes from a human-run §12.7 review recorded in the decision
        log. A helper that flipped the flag would make the whole gate cosmetic,
        so its absence is pinned rather than assumed.
        """
        code = _executable_source(analogs)
        assert "publication_cleared=True" not in code.replace(" ", "")


class TestMinimumEvidence:
    """§12.6: a sample below the threshold is not evidence of edge."""

    def test_the_ratified_thresholds_are_encoded_verbatim(self) -> None:
        assert MINIMUM_SAMPLE[EvidenceUse.PROBATION_EXIT_REVIEW] == 30
        assert MINIMUM_SAMPLE[EvidenceUse.TIER_QUALIFICATION_ABOVE_STANDARD] == 50
        assert MINIMUM_SAMPLE[EvidenceUse.EDGE_SCORE_RECALIBRATION] == 100
        assert MINIMUM_SAMPLE[EvidenceUse.CHALLENGER_PROMOTION] is None

    @pytest.mark.parametrize("use", list(EvidenceUse))
    def test_nothing_is_sufficient_while_the_publication_gate_is_shut(self, use) -> None:
        verdict = run().supports(use)
        assert verdict.sufficient is False
        assert any("§12.7" in r for r in verdict.reasons)

    def test_challenger_promotion_can_never_be_satisfied_by_one_report(self) -> None:
        verdict = run().supports(EvidenceUse.CHALLENGER_PROMOTION)
        assert verdict.required is None
        assert any("separate confirmation sample" in r for r in verdict.reasons)

    def test_a_short_sample_is_named_as_short(self) -> None:
        verdict = run().supports(EvidenceUse.PROBATION_EXIT_REVIEW)
        assert verdict.actual == 6
        assert any("not evidence of edge regardless" in r for r in verdict.reasons)

    def test_overlapping_observations_cannot_inflate_the_evidence_count(self) -> None:
        """Forty samples of three sessions are three sessions of evidence.

        Sampling one session repeatedly is the cheapest way to manufacture a
        §12.6 pass, so §12.6 is measured against distinct sessions.
        """
        crowded = [
            observation(
                i,
                move=Decimal("4") if i % 2 else Decimal("-4"),
                session_date=dt.date(2025, 2, 3) + dt.timedelta(days=i % 3),
                observed_at=dt.datetime(2025, 2, 3, 7, 40, tzinfo=UTC)
                + dt.timedelta(days=i % 3, minutes=i),
                outcome_observed_at=dt.datetime(2025, 2, 3, 10, 40, tzinfo=UTC)
                + dt.timedelta(days=i % 3, minutes=i),
            )
            for i in range(40)
        ]
        report = run(observations=crowded)
        assert report.analog_count == 40
        assert report.independent_sample == 3
        assert report.evidence_sample_size == 3
        assert report.supports(EvidenceUse.PROBATION_EXIT_REVIEW).actual == 3
        assert any("effective sample is the session count" in n
                   for n in report.data_limitations.notes)

    def test_an_independent_sample_larger_than_the_analog_count_is_impossible(self) -> None:
        with pytest.raises(ValueError, match="is a subset by definition"):
            dataclasses.replace(run(), independent_sample=99)


class TestAmendmentA2:
    """A-2 (§5.1, §6.6): a base rate is a property of history, never of us."""

    def test_the_module_does_not_import_firm_state(self) -> None:
        tree = ast.parse(pathlib.Path(analogs.__file__).read_text())
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom | ast.Import):
                imported |= {alias.name for alias in node.names}
        assert "FirmSnapshot" not in imported
        # `trading_firm.packet` defines FirmSnapshot; not importing the module at
        # all keeps firm state more than one attribute access away.
        assert not any(name.startswith("trading_firm.packet") for name in imported)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module != "trading_firm.packet"

    def test_the_module_never_references_firm_state_in_code(self) -> None:
        assert "FirmSnapshot" not in _executable_source(analogs), (
            "the base-rate engine references firm state: equity, session P&L, and "
            "trade count may never reach a historical base rate (A-2, §5.1)"
        )

    def test_no_entry_point_admits_firm_state(self) -> None:
        for fn in (search_analogs, commit_query):
            rendered = " ".join(
                str(p.annotation) for p in inspect.signature(fn).parameters.values()
            )
            assert "FirmSnapshot" not in rendered
            assert "Account" not in rendered

    def test_base_rates_are_identical_no_matter_what_the_firm_is_doing(self) -> None:
        # There is no firm-state parameter to vary, so the property is stated
        # the only way it can be: the same inputs give a bit-identical report.
        first, second = run(), run()
        assert first.query_id == second.query_id
        assert first.outcome_distribution == second.outcome_distribution
        assert first.data_limitations == second.data_limitations


class TestStatistics:
    def test_a_negative_mean_is_not_rounded_toward_zero(self) -> None:
        """ROUND_DOWN would flatter every losing base rate (§0.5).

        -1.015 is a tie. `models.cents`-style ROUND_DOWN would report -1.01 —
        a smaller loss than the data shows. Half-even reports -1.02.
        """
        nets = [Decimal("-1.015"), Decimal("-1.015")]
        summary = analogs._summarize(Direction.LONG, nets)
        assert summary.mean_net_pips == Decimal("-1.02")
        assert summary.sum_net_pips == Decimal("-2.030")

    def test_win_rate_counts_scratches_as_neither(self) -> None:
        nets = [Decimal("2"), Decimal("0"), Decimal("-2"), Decimal("4")]
        summary = analogs._summarize(Direction.SHORT, nets)
        assert (summary.wins, summary.losses, summary.scratches) == (2, 1, 1)
        assert summary.win_rate == Decimal("0.5000")

    def test_an_empty_set_reports_none_rather_than_zero(self) -> None:
        summary = analogs._summarize(Direction.LONG, [])
        assert summary.mean_net_pips is None
        assert summary.win_rate is None
        assert summary.sum_net_pips == Decimal("0")

    def test_normalized_l1_admits_a_trade_off_the_box_would_reject(self) -> None:
        two_features = (
            FeatureTolerance(feature_id=FEATURE, target=Decimal("38"), tolerance=Decimal("6")),
            FeatureTolerance(
                feature_id="session_features_v1.overnight_gap_pips",
                target=Decimal("0"),
                tolerance=Decimal("4"),
            ),
        )
        obs = [
            observation(
                0,
                move=Decimal("7"),
                features={
                    FEATURE: Decimal("38"),
                    "session_features_v1.overnight_gap_pips": Decimal("6"),
                },
            )
        ]
        box = run(query(tolerances=two_features), observations=obs)
        l1 = run(
            query(tolerances=two_features, similarity_method=SimilarityMethod.NORMALIZED_L1),
            observations=obs,
        )
        assert box.analog_count == 0  # 1.5 tolerance units on one axis
        assert l1.analog_count == 1  # mean deviation 0.75


class TestDirectionalOutcomesShape:
    def test_a_directional_summary_names_its_side(self) -> None:
        report = run()
        assert isinstance(report.outcome_distribution.long_outcomes, DirectionalOutcomes)
        assert report.outcome_distribution.long_outcomes.direction is Direction.LONG

    def test_best_and_worst_are_reported_so_the_tails_are_visible(self) -> None:
        d = run().outcome_distribution
        assert d.long_outcomes.best_net_pips == Decimal("20") - COST
        assert d.long_outcomes.worst_net_pips == Decimal("-30") - COST
        assert d.short_outcomes.best_net_pips == Decimal("30") - COST


def _executable_source(module) -> str:
    """Module source with comments and docstrings removed.

    Same technique as tests/unit/test_classification.py: a prose mention of a
    forbidden name in a docstring is documentation, not a reference.
    """
    source = pathlib.Path(module.__file__).read_text()
    lines = [line for line in source.splitlines() if not line.lstrip().startswith("#")]
    parts = "\n".join(lines).split('"""')
    return "".join(parts[::2])


class TestQueryFieldRegistration:
    """§6.4: the cherry-pick prohibition is only structural while the query
    cannot encode the answer it is meant to justify.

    The denylist alone did not deliver that — a field named `favourable_only`
    passed it, confirmed by probe. These tests pin the stronger guarantee and,
    more importantly, would fail if someone reverted to a denylist-only guard.
    """

    def test_the_guard_passes_on_the_real_model(self) -> None:
        analogs._reject_direction_fields()  # does not raise

    def test_a_denylisted_direction_field_is_caught(self) -> None:
        self._assert_guard_trips_on(side=(str, pydantic.Field(default="long")))

    def test_a_direction_field_the_denylist_never_heard_of_is_caught(self) -> None:
        """The actual gap. `favourable_only` is not in FORBIDDEN_QUERY_FIELDS and
        never would be — the field that defeats this control will not be named
        something a denylist author thought of."""
        assert "favourable_only" not in analogs.FORBIDDEN_QUERY_FIELDS
        self._assert_guard_trips_on(favourable_only=(bool, pydantic.Field(default=True)))

    def test_an_innocuous_addition_also_trips_it(self) -> None:
        """Deliberate: the guard cannot judge intent, so it stops every change
        and makes a human state that the new field is not a direction in
        disguise. A guard that only stops fields it recognizes as dangerous is
        the denylist again."""
        self._assert_guard_trips_on(notes=(str, pydantic.Field(default="")))

    def test_removing_a_field_is_caught_too(self) -> None:
        # Dropping `known_coverage_gaps` would silently undisclose the coverage
        # holes §12.7 rule 6 requires a report to state.
        reduced = {
            name: (info.annotation, info)
            for name, info in analogs.AnalogQuery.model_fields.items()
            if name != "regime_filter"
        }
        shrunk = pydantic.create_model("AnalogQuery", **reduced)
        self._assert_guard_trips_on(_model=shrunk)

    @staticmethod
    def _assert_guard_trips_on(_model=None, **extra_fields):
        real = analogs.AnalogQuery
        model = _model or pydantic.create_model(
            "AnalogQuery", __base__=real, **extra_fields
        )
        try:
            analogs.AnalogQuery = model
            with pytest.raises(RuntimeError, match=r"§6\.4|field set changed"):
                analogs._reject_direction_fields()
        finally:
            analogs.AnalogQuery = real
