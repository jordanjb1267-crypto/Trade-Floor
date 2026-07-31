"""Experiment and multiple-testing ledger (§12.4; §22 Phase 3 deliverable).

Three things are being pinned here.

1. **The count is computed, not remembered.** The seeded fixture reproduces the
   GBP sample's real history from `governance/decision-log.md` — a breakout
   baseline, a three-variant exit challenger, and one first look each for
   sweep-reversal and continuation. Six tests. The ledger must arrive at six
   without anybody telling it six.
2. **The dangerous move is impossible, not merely discouraged.** A post-hoc
   hypothesis cannot be filed as pre-registered, a spent test cannot be
   refunded, and a research number cannot be formatted for publication without
   §12.7 clearance. Those are argued from signatures and raised exceptions, not
   from convention.
3. **A-2 pressure invariance.** Statistical significance is a property of the
   data and the number of times it has been asked. The source-level guard fails
   the day someone lets firm state near a threshold computation.
"""

import ast
import dataclasses
import datetime as dt
import inspect
import pathlib
from decimal import Decimal

import pytest
from pydantic import ValidationError

import trading_firm.research.experiments as experiments_module
from trading_firm.research.experiments import (
    DEFAULT_ALPHA,
    BHDecision,
    Experiment,
    ExperimentLedger,
    ExperimentOutcome,
    Registration,
    Sample,
    SampleRole,
)

UTC = dt.UTC

# ---------------------------------------------------------------------------
# The GBP sample as the firm actually spent it (governance/decision-log.md,
# 2026-07-30). Six weeks of M5 GBP_USD, 31 completed London sessions.
# ---------------------------------------------------------------------------

GBP_SAMPLE_ID = "gbp_usd_london_m5_2026-06-04_2026-07-15"
DECISION_LOG = "governance/decision-log.md 2026-07-30"


def gbp_sample(role: SampleRole = SampleRole.DISCOVERY) -> Sample:
    return Sample(
        sample_id=GBP_SAMPLE_ID,
        description="Six weeks of M5 GBP_USD via the licensed FMP connector, London sessions",
        instrument="GBP_USD",
        role=role,
        first_session=dt.date(2026, 6, 4),
        last_session=dt.date(2026, 7, 15),
        sessions=30,
        known_coverage_holes=("feed timestamps pinned empirically to America/New_York",),
    )


def spent_gbp_ledger(**kwargs) -> ExperimentLedger:
    """The ledger as of 2026-07-30: six tests already spent on one sample."""
    ledger = ExperimentLedger(**kwargs)
    ledger.add_sample(gbp_sample())

    # 1. Champion baseline replay — a single pre-declared parameter set, no
    #    selection event. 30 trades, below every §12.6 threshold.
    ledger.add(
        Experiment(
            hypothesis_id="london_breakout_v0.1.0_baseline",
            description="v0.1.0 breakout parameters, untouched, over the canonical feed",
            sample_id=GBP_SAMPLE_ID,
            metric="profit_factor",
            registration=Registration.PRE_REGISTERED,
            registered_at=dt.datetime(2026, 7, 30, 8, 0, tzinfo=UTC),
            outcome=ExperimentOutcome.INCONCLUSIVE,
            tested_at=dt.datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
            variants_tested=1,
            report_reference="reports/validation/2026-07-30-london-breakout-v0.1.0-replay.md",
            provenance=DECISION_LOG,
            notes=("19 GBP trades, net -$3.97, PF 0.73 — below §12.6 thresholds",),
        )
    )

    # 2. Exit-logic challenger — three variants fixed in advance, discovery /
    #    confirmation split declared before any replay, mechanical selection.
    #    A selection event over three variants: three tests, not one.
    ledger.add(
        Experiment(
            hypothesis_id="exit_logic_challenger",
            description="Flatten-dominated exits imply exit logic is the binding constraint",
            sample_id=GBP_SAMPLE_ID,
            metric="net_expectancy_after_costs",
            registration=Registration.PRE_REGISTERED,
            registered_at=dt.datetime(2026, 7, 30, 9, 30, tzinfo=UTC),
            outcome=ExperimentOutcome.REFUTED,
            tested_at=dt.datetime(2026, 7, 30, 11, 0, tzinfo=UTC),
            variants_tested=3,
            report_reference="reports/validation/2026-07-30-exit-challenger-eval.md",
            provenance=DECISION_LOG,
            notes=("V2 passed discovery PF 1.03 then failed confirmation PF 0.66",),
        )
    )

    # 3. Sweep-reversal first look — single pre-declared parameter set.
    ledger.add(
        Experiment(
            hypothesis_id="sweep_reversal_v0.1.0_first_look",
            description="Liquidity-sweep reversals price a distinct edge from breakouts",
            sample_id=GBP_SAMPLE_ID,
            metric="profit_factor",
            registration=Registration.PRE_REGISTERED,
            registered_at=dt.datetime(2026, 7, 30, 12, 0, tzinfo=UTC),
            outcome=ExperimentOutcome.INCONCLUSIVE,
            tested_at=dt.datetime(2026, 7, 30, 12, 30, tzinfo=UTC),
            variants_tested=1,
            report_reference="reports/validation/2026-07-30-sweep-reversal-v0.1.0-baseline.md",
            provenance=DECISION_LOG,
            notes=("27 GBP trades, net +$1.48, PF 1.11",),
        )
    )

    # 4. Continuation first look — one trend-alignment variable, declared first.
    ledger.add(
        Experiment(
            hypothesis_id="continuation_trend_alignment_first_look",
            description="Trend-aligned breakouts may be the good breakouts",
            sample_id=GBP_SAMPLE_ID,
            metric="profit_factor",
            registration=Registration.PRE_REGISTERED,
            registered_at=dt.datetime(2026, 7, 30, 13, 0, tzinfo=UTC),
            outcome=ExperimentOutcome.INCONCLUSIVE,
            tested_at=dt.datetime(2026, 7, 30, 13, 30, tzinfo=UTC),
            variants_tested=1,
            report_reference="reports/validation/2026-07-30-london-continuation-v0.1.0-baseline.md",
            provenance=DECISION_LOG,
            notes=("9 GBP trades — decides nothing",),
        )
    )
    return ledger


@pytest.fixture
def spent() -> ExperimentLedger:
    return spent_gbp_ledger()


class TestSampleRecord:
    def test_a_sample_ending_before_it_begins_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match=r"§12\.7"):
            Sample(
                sample_id="broken",
                description="reversed range",
                instrument="GBP_USD",
                role=SampleRole.DISCOVERY,
                first_session=dt.date(2026, 7, 15),
                last_session=dt.date(2026, 6, 4),
                sessions=30,
            )

    def test_sample_records_are_frozen(self) -> None:
        sample = gbp_sample()
        with pytest.raises(ValidationError):
            sample.sessions = 999

    def test_sample_rejects_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            Sample(
                sample_id="s",
                description="d",
                instrument="GBP_USD",
                role=SampleRole.DISCOVERY,
                first_session=dt.date(2026, 6, 4),
                last_session=dt.date(2026, 7, 15),
                sessions=30,
                favourable=True,
            )


class TestExperimentRecord:
    def _base(self, **overrides) -> dict:
        base = dict(
            hypothesis_id="h",
            description="d",
            sample_id=GBP_SAMPLE_ID,
            metric="profit_factor",
            registration=Registration.POST_HOC,
            registered_at=dt.datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
        )
        base.update(overrides)
        return base

    def test_naive_registration_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            Experiment(**self._base(registered_at=dt.datetime(2026, 7, 30, 9, 0)))

    def test_naive_test_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="timezone-aware"):
            Experiment(**self._base(tested_at=dt.datetime(2026, 7, 30, 10, 0)))

    def test_a_registration_recorded_after_its_own_result_is_rejected(self) -> None:
        """The entire value of a pre-registration is its position in time."""
        with pytest.raises(ValidationError, match=r"post-hoc by definition"):
            Experiment(
                **self._base(
                    registered_at=dt.datetime(2026, 7, 30, 11, 0, tzinfo=UTC),
                    tested_at=dt.datetime(2026, 7, 30, 10, 0, tzinfo=UTC),
                )
            )

    def test_a_result_without_a_test_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="never run to produce"):
            Experiment(**self._base(tested_at=None))

    def test_a_pending_experiment_carrying_a_p_value_is_rejected(self) -> None:
        """Otherwise a test could be run, scored, and still counted as unspent."""
        with pytest.raises(ValidationError, match="understates the trial count"):
            Experiment(
                **self._base(
                    outcome=ExperimentOutcome.PENDING,
                    tested_at=None,
                    p_value=Decimal("0.01"),
                )
            )

    def test_an_abandoned_experiment_carrying_a_test_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="understates the trial count"):
            Experiment(**self._base(outcome=ExperimentOutcome.ABANDONED))

    def test_p_values_outside_the_unit_interval_are_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Experiment(**self._base(p_value=Decimal("1.5")))
        with pytest.raises(ValidationError):
            Experiment(**self._base(p_value=Decimal("-0.01")))

    def test_a_pending_registration_has_spent_no_test(self) -> None:
        exp = Experiment(**self._base(outcome=ExperimentOutcome.PENDING, tested_at=None))
        assert exp.tests_spent == 0
        assert not exp.is_selection_event

    def test_a_refuted_test_costs_exactly_as_much_multiplicity_as_a_supported_one(self) -> None:
        supported = Experiment(**self._base(outcome=ExperimentOutcome.SUPPORTED))
        refuted = Experiment(**self._base(outcome=ExperimentOutcome.REFUTED))
        inconclusive = Experiment(**self._base(outcome=ExperimentOutcome.INCONCLUSIVE))
        assert supported.tests_spent == refuted.tests_spent == inconclusive.tests_spent == 1

    def test_a_variant_sweep_spends_one_test_per_variant(self) -> None:
        exp = Experiment(**self._base(variants_tested=3))
        assert exp.tests_spent == 3
        assert exp.is_selection_event

    def test_experiment_records_are_frozen(self) -> None:
        exp = Experiment(**self._base())
        with pytest.raises(ValidationError):
            exp.variants_tested = 0


class TestSpentGbpSample:
    """The historical state: six tests already against one six-week sample."""

    def test_the_ledger_counts_six_spent_tests_without_being_told(self, spent) -> None:
        assert spent.tests_recorded(GBP_SAMPLE_ID) == 6

    def test_the_three_variant_exit_sweep_registers_as_one_selection_event(self, spent) -> None:
        assert spent.selection_events(GBP_SAMPLE_ID) == 1
        assert len(spent.experiments(GBP_SAMPLE_ID)) == 4

    def test_nothing_is_left_pending_against_the_gbp_sample(self, spent) -> None:
        assert spent.pending_registrations(GBP_SAMPLE_ID) == 0

    def test_the_seventh_test_must_clear_alpha_over_seven(self, spent) -> None:
        required = spent.required_p_value(GBP_SAMPLE_ID)
        assert required == DEFAULT_ALPHA / Decimal(7)
        assert Decimal("0.007") < required < Decimal("0.0072")

    def test_a_nominally_significant_new_result_fails_the_corrected_bar(self, spent) -> None:
        """The exact failure the ledger exists to prevent, stated as a claim."""
        claimed = Decimal("0.03")
        assert claimed < DEFAULT_ALPHA  # would read as "significant" uncorrected
        assert claimed > spent.required_p_value(GBP_SAMPLE_ID)

    def test_bonferroni_over_the_recorded_family_is_alpha_over_six(self, spent) -> None:
        assert spent.bonferroni_threshold(GBP_SAMPLE_ID) == DEFAULT_ALPHA / Decimal(6)

    def test_six_tests_have_not_yet_exhausted_the_sample(self, spent) -> None:
        state = spent.status(GBP_SAMPLE_ID)
        assert not state.exhausted
        assert state.headroom
        assert state.reasons == ()
        assert state.expected_false_positives == Decimal("0.30")

    def test_experiments_are_returned_in_registration_order(self, spent) -> None:
        ids = [e.hypothesis_id for e in spent.experiments(GBP_SAMPLE_ID)]
        assert ids == [
            "london_breakout_v0.1.0_baseline",
            "exit_logic_challenger",
            "sweep_reversal_v0.1.0_first_look",
            "continuation_trend_alignment_first_look",
        ]

    def test_a_second_sample_carries_its_own_independent_count(self, spent) -> None:
        spent.add_sample(
            Sample(
                sample_id="gbp_usd_london_m5_post_2026-07-29",
                description="clean data after the spent window",
                instrument="GBP_USD",
                role=SampleRole.CONFIRMATION,
                first_session=dt.date(2026, 7, 30),
                last_session=dt.date(2026, 8, 28),
                sessions=22,
            )
        )
        assert spent.tests_recorded("gbp_usd_london_m5_post_2026-07-29") == 0
        assert spent.required_p_value("gbp_usd_london_m5_post_2026-07-29") == DEFAULT_ALPHA
        assert spent.tests_recorded(GBP_SAMPLE_ID) == 6


class TestPreRegistrationIntegrity:
    def test_register_offers_no_way_to_supply_a_result(self) -> None:
        """A post-hoc hypothesis must not be able to enter through this door."""
        params = set(inspect.signature(ExperimentLedger.register).parameters)
        assert "p_value" not in params
        assert "outcome" not in params
        assert "tested_at" not in params
        assert "registration" not in params

    def test_record_post_hoc_offers_no_way_to_claim_pre_registration(self) -> None:
        params = set(inspect.signature(ExperimentLedger.record_post_hoc).parameters)
        assert "registration" not in params
        assert "registered_at" not in params
        assert "provenance" not in params

    def test_a_recorded_result_keeps_the_registration_class_it_was_filed_under(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        ledger.register(
            "h1", "d", GBP_SAMPLE_ID, "profit_factor", dt.datetime(2026, 8, 1, tzinfo=UTC)
        )
        done = ledger.record_result(
            "h1",
            ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 8, 2, tzinfo=UTC),
            p_value=Decimal("0.004"),
        )
        assert done.registration is Registration.PRE_REGISTERED
        assert done.registration.may_support_confirmation

    def test_a_post_hoc_record_can_never_support_confirmation(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        exp = ledger.record_post_hoc(
            "h2",
            "noticed after the fact that Tuesdays looked good",
            GBP_SAMPLE_ID,
            "win_rate",
            ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 8, 2, tzinfo=UTC),
            p_value=Decimal("0.01"),
        )
        assert exp.registration is Registration.POST_HOC
        assert not exp.registration.may_support_confirmation

    def test_a_completed_pre_registered_record_added_directly_must_cite_its_proof(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        unproven = Experiment(
            hypothesis_id="claims_prior_registration",
            description="asserts it was written down first",
            sample_id=GBP_SAMPLE_ID,
            metric="profit_factor",
            registration=Registration.PRE_REGISTERED,
            registered_at=dt.datetime(2026, 8, 1, tzinfo=UTC),
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 8, 2, tzinfo=UTC),
            p_value=Decimal("0.002"),
        )
        with pytest.raises(ValueError, match=r"never witnessed"):
            ledger.add(unproven)
        stored = ledger.add(unproven, provenance=DECISION_LOG)
        assert stored.provenance == DECISION_LOG

    def test_a_pending_registration_needs_no_provenance(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        pending = ledger.register(
            "h3", "d", GBP_SAMPLE_ID, "profit_factor", dt.datetime(2026, 8, 1, tzinfo=UTC)
        )
        assert pending.outcome is ExperimentOutcome.PENDING
        assert pending.provenance is None


class TestLedgerBookkeeping:
    def test_a_spent_test_can_never_be_overwritten(self, spent) -> None:
        with pytest.raises(ValueError, match=r"never overwritten"):
            spent.record_result(
                "exit_logic_challenger",
                ExperimentOutcome.SUPPORTED,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
                p_value=Decimal("0.001"),
            )
        assert spent.tests_recorded(GBP_SAMPLE_ID) == 6

    def test_reusing_a_hypothesis_id_is_rejected(self, spent) -> None:
        with pytest.raises(ValueError, match=r"understate the trial count"):
            spent.record_post_hoc(
                "exit_logic_challenger",
                "same id, new claim",
                GBP_SAMPLE_ID,
                "profit_factor",
                ExperimentOutcome.SUPPORTED,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
            )

    def test_redeclaring_a_sample_would_reset_its_count_and_is_rejected(self, spent) -> None:
        with pytest.raises(ValueError, match=r"reset its trial count"):
            spent.add_sample(gbp_sample())

    def test_an_experiment_against_an_undeclared_sample_is_rejected(self) -> None:
        ledger = ExperimentLedger()
        with pytest.raises(KeyError, match=r"never declared"):
            ledger.record_post_hoc(
                "orphan",
                "which data?",
                "nobody_declared_this",
                "profit_factor",
                ExperimentOutcome.SUPPORTED,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
            )

    def test_recording_a_result_for_an_unknown_hypothesis_is_rejected(self) -> None:
        ledger = ExperimentLedger()
        with pytest.raises(KeyError, match=r"not in the ledger"):
            ledger.record_result(
                "never_registered",
                ExperimentOutcome.SUPPORTED,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
            )

    def test_record_result_refuses_to_move_a_hypothesis_back_to_pending(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        ledger.register(
            "h4", "d", GBP_SAMPLE_ID, "profit_factor", dt.datetime(2026, 8, 1, tzinfo=UTC)
        )
        with pytest.raises(ValueError, match=r"reflects a run test"):
            ledger.record_result(
                "h4", ExperimentOutcome.PENDING, dt.datetime(2026, 8, 2, tzinfo=UTC)
            )

    def test_an_abandoned_registration_spends_no_test(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        ledger.register(
            "h5", "d", GBP_SAMPLE_ID, "profit_factor", dt.datetime(2026, 8, 1, tzinfo=UTC)
        )
        dropped = ledger.record_result(
            "h5", ExperimentOutcome.ABANDONED, dt.datetime(2026, 8, 2, tzinfo=UTC)
        )
        assert dropped.tested_at is None
        assert ledger.tests_recorded(GBP_SAMPLE_ID) == 0

    def test_pending_registrations_do_not_raise_the_bar_for_a_new_result(self) -> None:
        """Writing a hypothesis down is free; running it is what costs."""
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        for i in range(5):
            ledger.register(
                f"pending_{i}",
                "d",
                GBP_SAMPLE_ID,
                "profit_factor",
                dt.datetime(2026, 8, 1, tzinfo=UTC),
            )
        assert ledger.pending_registrations(GBP_SAMPLE_ID) == 5
        assert ledger.tests_recorded(GBP_SAMPLE_ID) == 0
        assert ledger.required_p_value(GBP_SAMPLE_ID) == DEFAULT_ALPHA

    def test_a_ledger_rejects_a_significance_level_that_corrects_nothing(self) -> None:
        with pytest.raises(ValueError, match=r"§12\.4"):
            ExperimentLedger(alpha=Decimal("0"))
        with pytest.raises(ValueError, match=r"§12\.4"):
            ExperimentLedger(alpha=Decimal("1"))

    def test_a_resolution_floor_at_or_above_alpha_is_rejected(self) -> None:
        with pytest.raises(ValueError, match=r"before its first test"):
            ExperimentLedger(alpha=Decimal("0.05"), resolution_floor=Decimal("0.05"))


class TestBonferroni:
    def test_the_first_test_faces_the_uncorrected_level(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        assert ledger.bonferroni_threshold(GBP_SAMPLE_ID) == DEFAULT_ALPHA
        assert ledger.required_p_value(GBP_SAMPLE_ID) == DEFAULT_ALPHA

    def test_the_required_p_value_falls_monotonically_as_tests_are_spent(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        seen = [ledger.required_p_value(GBP_SAMPLE_ID)]
        for i in range(6):
            ledger.record_post_hoc(
                f"t{i}",
                "d",
                GBP_SAMPLE_ID,
                "profit_factor",
                ExperimentOutcome.INCONCLUSIVE,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
            )
            seen.append(ledger.required_p_value(GBP_SAMPLE_ID))
        assert seen == sorted(seen, reverse=True)
        assert all(a > b for a, b in zip(seen[:-1], seen[1:], strict=True))
        assert seen[-1] == DEFAULT_ALPHA / Decimal(7)

    def test_a_stricter_alpha_can_be_supplied_per_call(self, spent) -> None:
        strict = spent.required_p_value(GBP_SAMPLE_ID, alpha=Decimal("0.01"))
        assert strict == Decimal("0.01") / Decimal(7)
        assert strict < spent.required_p_value(GBP_SAMPLE_ID)

    def test_an_out_of_range_alpha_override_is_rejected(self, spent) -> None:
        with pytest.raises(ValueError, match=r"§12\.4"):
            spent.required_p_value(GBP_SAMPLE_ID, alpha=Decimal("2"))


class TestBenjaminiHochberg:
    def _ledger_with(self, p_values: list[str]) -> ExperimentLedger:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        for i, p in enumerate(p_values):
            ledger.record_post_hoc(
                f"feature_{i:02d}",
                "screening candidate",
                GBP_SAMPLE_ID,
                "net_expectancy_after_costs",
                ExperimentOutcome.SUPPORTED,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
                p_value=Decimal(p),
            )
        return ledger

    def test_no_scored_experiments_yields_no_decisions(self, spent) -> None:
        # The seeded history recorded outcomes but no p-values.
        assert spent.benjamini_hochberg(GBP_SAMPLE_ID) == ()
        assert spent.tests_recorded(GBP_SAMPLE_ID) == 6

    def test_the_benjamini_hochberg_1995_worked_example_rejects_the_first_four(self) -> None:
        """Textbook fixture: m=15, alpha=0.05, four discoveries."""
        ledger = self._ledger_with(
            [
                "0.0001", "0.0004", "0.0019", "0.0095", "0.0201",
                "0.0278", "0.0298", "0.0344", "0.0459", "0.3240",
                "0.4262", "0.5719", "0.6528", "0.7590", "1.0000",
            ]
        )
        decisions = ledger.benjamini_hochberg(GBP_SAMPLE_ID)
        assert len(decisions) == 15
        assert [d.rank for d in decisions] == list(range(1, 16))
        assert sum(1 for d in decisions if d.significant) == 4
        assert all(d.significant for d in decisions[:4])
        assert not any(d.significant for d in decisions[4:])
        assert decisions[3].p_value == Decimal("0.0095")
        assert decisions[3].critical_value == Decimal("4") / Decimal("15") * DEFAULT_ALPHA

    def test_the_step_up_carries_smaller_ranks_that_individually_fail(self) -> None:
        """The classic BH implementation bug: rejecting only ranks that pass.

        With m=2 and alpha=0.05 the critical values are 0.025 and 0.05. Rank 1
        (p=0.03) fails its own threshold; rank 2 (p=0.04) clears its own. A
        correct step-up declares BOTH significant.
        """
        decisions = self._ledger_with(["0.03", "0.04"]).benjamini_hochberg(GBP_SAMPLE_ID)
        assert decisions[0].p_value == Decimal("0.03")
        assert decisions[0].critical_value == Decimal("0.025")
        assert decisions[0].p_value > decisions[0].critical_value
        assert decisions[0].significant
        assert decisions[1].significant

    def test_benjamini_hochberg_is_never_stricter_than_bonferroni(self) -> None:
        ledger = self._ledger_with(["0.001", "0.012", "0.020", "0.031", "0.048"])
        bonferroni = ledger.bonferroni_threshold(GBP_SAMPLE_ID)
        decisions = ledger.benjamini_hochberg(GBP_SAMPLE_ID)
        bonferroni_hits = sum(1 for d in decisions if d.p_value <= bonferroni)
        fdr_hits = sum(1 for d in decisions if d.significant)
        assert fdr_hits >= bonferroni_hits
        assert bonferroni == DEFAULT_ALPHA / Decimal(5)

    def test_nothing_is_significant_when_every_p_value_is_large(self) -> None:
        decisions = self._ledger_with(["0.4", "0.6", "0.9"]).benjamini_hochberg(GBP_SAMPLE_ID)
        assert len(decisions) == 3
        assert not any(d.significant for d in decisions)

    def test_unscored_experiments_are_excluded_from_fdr_but_still_cost_a_test(self) -> None:
        ledger = self._ledger_with(["0.001", "0.002"])
        ledger.record_post_hoc(
            "unscored",
            "replay with no p-value reported",
            GBP_SAMPLE_ID,
            "profit_factor",
            ExperimentOutcome.INCONCLUSIVE,
            dt.datetime(2026, 8, 1, tzinfo=UTC),
        )
        assert len(ledger.benjamini_hochberg(GBP_SAMPLE_ID)) == 2
        assert ledger.tests_recorded(GBP_SAMPLE_ID) == 3

    def test_decisions_are_frozen_records(self) -> None:
        decision = self._ledger_with(["0.01"]).benjamini_hochberg(GBP_SAMPLE_ID)[0]
        assert isinstance(decision, BHDecision)
        with pytest.raises(dataclasses.FrozenInstanceError):
            decision.significant = False


class TestExhaustion:
    def test_twenty_tests_at_alpha_five_percent_exhaust_the_sample(self) -> None:
        """At that point one 'significant' result is expected from noise alone."""
        ledger = spent_gbp_ledger()
        ledger.record_post_hoc(
            "sweep_of_fourteen_parameter_sets",
            "grid over entry buffer",
            GBP_SAMPLE_ID,
            "profit_factor",
            ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 8, 1, tzinfo=UTC),
            p_value=Decimal("0.04"),
            variants_tested=14,
        )
        state = ledger.status(GBP_SAMPLE_ID)
        assert state.tests_recorded == 20
        assert state.expected_false_positives == Decimal("1.00")
        assert state.exhausted
        assert not state.headroom
        assert any("chance alone" in reason for reason in state.reasons)

    def test_assert_not_exhausted_fails_closed_and_names_the_honest_path(self) -> None:
        ledger = spent_gbp_ledger()
        ledger.record_post_hoc(
            "grid",
            "grid",
            GBP_SAMPLE_ID,
            "profit_factor",
            ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 8, 1, tzinfo=UTC),
            variants_tested=14,
        )
        with pytest.raises(ValueError, match=r"the honest path is new data"):
            ledger.assert_not_exhausted(GBP_SAMPLE_ID)

    def test_assert_not_exhausted_returns_the_status_while_headroom_remains(self, spent) -> None:
        state = spent.assert_not_exhausted(GBP_SAMPLE_ID)
        assert state.tests_recorded == 6
        assert not state.exhausted

    def test_an_immutable_holdout_is_exhausted_by_its_first_inspection(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample(role=SampleRole.HOLDOUT))
        assert not ledger.status(GBP_SAMPLE_ID).exhausted
        ledger.record_post_hoc(
            "holdout_check",
            "the one question the holdout answers",
            GBP_SAMPLE_ID,
            "net_expectancy_after_costs",
            ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 8, 1, tzinfo=UTC),
            p_value=Decimal("0.002"),
        )
        state = ledger.status(GBP_SAMPLE_ID)
        assert state.exhausted
        assert state.role is SampleRole.HOLDOUT
        assert any("holdout" in reason for reason in state.reasons)
        with pytest.raises(ValueError, match=r"once"):
            ledger.assert_not_exhausted(GBP_SAMPLE_ID)

    def test_a_threshold_below_the_resolution_floor_exhausts_the_sample(self) -> None:
        """A p-value the sample cannot measure is not a result."""
        ledger = ExperimentLedger(alpha=Decimal("0.05"), resolution_floor=Decimal("0.02"))
        ledger.add_sample(gbp_sample())
        for i in range(2):
            ledger.record_post_hoc(
                f"t{i}",
                "d",
                GBP_SAMPLE_ID,
                "profit_factor",
                ExperimentOutcome.INCONCLUSIVE,
                dt.datetime(2026, 8, 1, tzinfo=UTC),
            )
        state = ledger.status(GBP_SAMPLE_ID)
        assert state.next_test_threshold == Decimal("0.05") / Decimal(3)
        assert state.exhausted
        assert state.reasons == tuple(r for r in state.reasons if "resolution floor" in r)


class TestPublicationGate:
    """§12.7 / A-1: research code may not publish before adversarial review."""

    def test_publication_is_blocked_by_default(self, spent) -> None:
        assert spent.publication_cleared is False
        with pytest.raises(ValueError, match=r"§12\.7"):
            spent.publication_table(GBP_SAMPLE_ID)

    def test_the_block_names_the_uses_it_forbids(self, spent) -> None:
        with pytest.raises(ValueError, match=r"minimum evidence"):
            spent.publication_table(GBP_SAMPLE_ID)

    def test_arithmetic_stays_available_to_reviewers_while_the_report_is_blocked(
        self, spent
    ) -> None:
        """The gate is on the formatter; a reviewer can still see the counts."""
        assert spent.tests_recorded(GBP_SAMPLE_ID) == 6
        assert spent.required_p_value(GBP_SAMPLE_ID) > 0
        assert spent.status(GBP_SAMPLE_ID).tests_recorded == 6

    def test_clearance_without_a_review_reference_is_not_a_clearance(self) -> None:
        # Rejected at CONSTRUCTION, not at publication: a ledger that believes
        # it is cleared while pointing at no review should never exist to be
        # asked. §12.7 requirement 7 makes the review outcome an audit entry.
        with pytest.raises(ValueError, match=r"not a clearance"):
            spent_gbp_ledger(publication_cleared=True)

    def test_the_gate_cannot_be_flipped_after_construction(self) -> None:
        # The defect this test exists for: a plain writable attribute would let
        # any caller clear the gate at runtime and publish an unreviewed number.
        ledger = spent_gbp_ledger()
        assert ledger.publication_cleared is False
        with pytest.raises(AttributeError):
            ledger.publication_cleared = True
        with pytest.raises(AttributeError):
            ledger.review_reference = "docs/reviews/fabricated.md"
        with pytest.raises(ValueError, match=r"publication_cleared is False"):
            ledger.publication_table(GBP_SAMPLE_ID)

    def test_a_cleared_table_states_its_own_denominator_and_trial_count(self) -> None:
        # Test-only clearance with a fabricated review reference: this exercises
        # the far side of the gate. No code path in src/ sets this flag.
        ledger = spent_gbp_ledger(
            publication_cleared=True,
            review_reference="docs/reviews/TEST-ONLY-not-a-real-review.md",
        )
        table = ledger.publication_table(GBP_SAMPLE_ID)
        assert "§12.4" in table
        assert "tests recorded: 6" in table
        assert "selection events: 1" in table
        assert "sessions capable of producing features: 30" in table
        assert "America/New_York" in table  # disclosed coverage hole (§12.7 rule 6)
        assert "exit_logic_challenger" in table
        assert "pre_registered" in table
        assert str(DEFAULT_ALPHA / Decimal(7)) in table

    def test_no_source_line_in_the_module_clears_publication(self) -> None:
        source = pathlib.Path(experiments_module.__file__).read_text()
        assert "publication_cleared = True" not in source
        assert "publication_cleared=True" not in source
        assert "publication_cleared: bool = False" in source


class TestPressureInvariance:
    """A-2 (§5.1, §6.6): firm state may not reach a significance threshold."""

    def test_the_module_never_imports_or_references_firm_state(self) -> None:
        source = pathlib.Path(experiments_module.__file__).read_text()
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {alias.name for alias in node.names}
                imported.add(node.module or "")
            elif isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
        assert "FirmSnapshot" not in imported, (
            "experiments imports FirmSnapshot: a multiple-testing correction must not be "
            "reachable from firm state (A-2, §5.1)"
        )
        assert not any("packet" in name for name in imported), (
            "experiments imports from the packet module, which carries FirmSnapshot (A-2)"
        )
        # Belt and braces: catches a fully-qualified `packet.FirmSnapshot(...)`.
        code_lines = [line for line in source.splitlines() if not line.lstrip().startswith("#")]
        executable = "".join("\n".join(code_lines).split('"""')[::2])
        assert "FirmSnapshot" not in executable, (
            "experiments code references FirmSnapshot (A-2, §5.1)"
        )

    def test_no_public_signature_admits_firm_state_or_a_proxy_for_it(self) -> None:
        """Equity, session P&L, and days elapsed do not move a p-value."""
        forbidden = {
            "firm",
            "firm_snapshot",
            "equity",
            "account",
            "session_pnl",
            "cumulative_return",
            "days_elapsed",
            "trades_taken",
            "goal_progress",
        }
        for name, member in vars(ExperimentLedger).items():
            if name.startswith("_") or not callable(member):
                continue
            signature = inspect.signature(member)
            assert not (set(signature.parameters) & forbidden), (
                f"ExperimentLedger.{name} accepts firm state: statistical significance is a "
                f"property of the data and the number of times it has been asked, not of the "
                f"firm's need for a win (A-2, §5.1)"
            )
            rendered = " ".join(str(p.annotation) for p in signature.parameters.values())
            assert "FirmSnapshot" not in rendered

    def test_the_correction_depends_only_on_the_trial_count(self) -> None:
        """Two ledgers built the same way agree exactly, whatever else differs."""
        a = spent_gbp_ledger()
        b = spent_gbp_ledger()
        assert a.required_p_value(GBP_SAMPLE_ID) == b.required_p_value(GBP_SAMPLE_ID)
        assert a.status(GBP_SAMPLE_ID) == b.status(GBP_SAMPLE_ID)


def test_module_is_pressure_blind_under_the_shared_guard() -> None:
    """A-2 (§5.1) via `tests/a2_guard.py`.

    The local guards in this file check the single name `FirmSnapshot`. An
    adversarial review defeated that by importing `AccountState` instead, so
    the shared guard checks the whole firm-state vocabulary. Both run: the
    local one gives a module-specific message, this one is the real check.
    """
    import importlib

    from a2_guard import assert_pressure_blind

    assert_pressure_blind(importlib.import_module("trading_firm.research.experiments"))


class TestBackdatedRegistration:
    """§12.4: a pre-registration made after the fact is not a pre-registration.

    The escape an adversarial review demonstrated: a researcher who has already
    seen p=0.002 calls register() with a date a month earlier, then
    record_result(). Two ordinary calls, no provenance cited, and the ledger
    reports the hypothesis as pre-registered.
    """

    def test_a_registration_behind_the_witness_clock_is_refused(self) -> None:
        ledger = spent_gbp_ledger()
        latest = max(
            e.tested_at for e in ledger.experiments() if e.tested_at is not None
        )
        with pytest.raises(ValueError, match="not a pre-registration"):
            ledger.register(
                "backdated",
                "invented after seeing the result",
                GBP_SAMPLE_ID,
                "profit_factor",
                latest - dt.timedelta(days=30),
            )

    def test_a_registration_after_the_witness_clock_is_accepted(self) -> None:
        ledger = spent_gbp_ledger()
        latest = max(
            e.tested_at for e in ledger.experiments() if e.tested_at is not None
        )
        e = ledger.register(
            "honest", "written down first", GBP_SAMPLE_ID, "profit_factor",
            latest + dt.timedelta(days=1),
        )
        assert e.registration is Registration.PRE_REGISTERED

    def test_the_limit_of_the_guarantee_is_real(self) -> None:
        """Documented honestly rather than glossed: a fresh ledger has witnessed
        nothing, so it cannot detect backdating. Closing this needs an external
        witness (a commit hash, a signed timestamp), which is outside this
        module. The test exists so the limitation is visible rather than
        discovered later by someone relying on a guarantee that isn't there."""
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        e = ledger.register(
            "unwitnessed", "nothing to check against", GBP_SAMPLE_ID, "profit_factor",
            dt.datetime(2020, 1, 1, tzinfo=UTC),
        )
        assert e.registration is Registration.PRE_REGISTERED


class TestRegistrationClassIsImmutable:
    def test_a_result_cannot_upgrade_a_post_hoc_registration(self) -> None:
        """Mutating `registration=existing.registration` to PRE_REGISTERED in
        record_result left all 65 tests green. This is the test that kills it."""
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        ledger.record_post_hoc(
            "fitted", "noticed after the fact", GBP_SAMPLE_ID, "profit_factor",
            outcome=ExperimentOutcome.PENDING,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC),
        )
        updated = ledger.record_result(
            "fitted", ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 7, 21, tzinfo=UTC), p_value=Decimal("0.001"),
        )
        assert updated.registration is Registration.POST_HOC, (
            "a result must not promote its own hypothesis to pre-registered (§12.4)"
        )


class TestCorrectionParametersAreFixed:
    """A correction that can be loosened after the fact corrects nothing."""

    def test_alpha_cannot_be_widened_after_construction(self) -> None:
        ledger = spent_gbp_ledger()
        before = ledger.required_p_value(GBP_SAMPLE_ID)
        with pytest.raises(AttributeError):
            ledger.alpha = Decimal("0.9")
        assert ledger.required_p_value(GBP_SAMPLE_ID) == before

    def test_the_resolution_floor_cannot_be_disabled(self) -> None:
        ledger = spent_gbp_ledger()
        with pytest.raises(AttributeError):
            ledger.resolution_floor = Decimal("0")
        assert ledger.resolution_floor > 0


class TestVariantMultiplicityReachesBH:
    """§12.4: a variant sweep is the multiplicity BH exists to price.

    The reviewer's scenario: a 19-variant sweep reporting only its best p-value
    counted as ONE family member, so `m=2` and both results were declared
    significant, while Bonferroni over the same ledger correctly counted 20.
    """

    @staticmethod
    def _swept_ledger() -> ExperimentLedger:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        ledger.record_post_hoc(
            "sweep", "19 exit variants, best reported", GBP_SAMPLE_ID, "profit_factor",
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC),
            p_value=Decimal("0.02"), variants_tested=19,
        )
        ledger.record_post_hoc(
            "other", "one further test", GBP_SAMPLE_ID, "profit_factor",
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 21, tzinfo=UTC),
            p_value=Decimal("0.04"),
        )
        return ledger

    def test_the_sweep_is_not_called_a_discovery(self) -> None:
        decisions = self._swept_ledger().benjamini_hochberg(GBP_SAMPLE_ID)
        assert not any(d.significant for d in decisions), (
            "a 19-variant sweep at p=0.02 is not a discovery; counting it as one "
            "family member is the exact multiplicity BH is for (§12.4)"
        )

    def test_bh_family_size_agrees_with_the_trial_count(self) -> None:
        ledger = self._swept_ledger()
        assert ledger.tests_recorded(GBP_SAMPLE_ID) == 20
        # critical = rank/m * alpha, so the rank-1 value pins m.
        rank_one = min(ledger.benjamini_hochberg(GBP_SAMPLE_ID), key=lambda d: d.p_value)
        assert rank_one.critical_value == DEFAULT_ALPHA / Decimal(20), (
            "BH and Bonferroni must not disagree about how many tests were run"
        )

    def test_family_is_never_smaller_than_the_results_drawn_from_it(self) -> None:
        ledger = ExperimentLedger()
        ledger.add_sample(gbp_sample())
        for i in range(3):
            ledger.record_post_hoc(
                f"h{i}", "d", GBP_SAMPLE_ID, "profit_factor",
                outcome=ExperimentOutcome.SUPPORTED,
                tested_at=dt.datetime(2026, 7, 20 + i, tzinfo=UTC),
                p_value=Decimal("0.001"),
            )
        assert len(ledger.benjamini_hochberg(GBP_SAMPLE_ID)) == 3


class TestHonestDenominator:
    """§12.7 requirement 6: the denominator must be arithmetically possible.

    Nothing related `sessions` to the range it described, and the seeded GBP
    exemplar claimed 31 sessions over a range containing 30 weekdays. That
    number reached `publication_table()` as the denominator a §12.6 evidence
    count is judged against, so an impossible sample size sat one clearance
    away from a promotion record.
    """

    def test_a_denominator_larger_than_its_range_is_refused(self) -> None:
        with pytest.raises(ValidationError, match="contains only .* weekdays"):
            Sample(
                sample_id="impossible",
                description="two days, five hundred sessions",
                instrument="GBP_USD",
                role=SampleRole.DISCOVERY,
                first_session=dt.date(2026, 6, 4),
                last_session=dt.date(2026, 6, 5),
                sessions=500,
            )

    def test_the_exemplar_now_states_a_possible_denominator(self) -> None:
        sample = gbp_sample()
        span = (sample.last_session - sample.first_session).days + 1
        weekdays = sum(
            1
            for offset in range(span)
            if (sample.first_session + dt.timedelta(days=offset)).weekday() < 5
        )
        assert sample.sessions <= weekdays
        assert weekdays == 30

    def test_fewer_sessions_than_weekdays_is_fine(self) -> None:
        # Holidays and outages only reduce the count; that is what
        # known_coverage_holes records.
        sample = Sample(
            sample_id="holed",
            description="range with a holiday",
            instrument="GBP_USD",
            role=SampleRole.DISCOVERY,
            first_session=dt.date(2026, 6, 4),
            last_session=dt.date(2026, 7, 15),
            sessions=27,
            known_coverage_holes=("three UK bank holidays",),
        )
        assert sample.sessions == 27


def _sample(sample_id: str, role: SampleRole) -> Sample:
    return Sample(
        sample_id=sample_id,
        description=f"{role.value} sample",
        instrument="GBP_USD",
        role=role,
        first_session=dt.date(2026, 6, 4),
        last_session=dt.date(2026, 7, 15),
        sessions=30,
    )


class TestHoldoutIsInspectedOnceEver:
    """§12.4: "immutable holdout periods". Documented in SampleRole, enforced
    by nothing — five successive writes were accepted, which is mining the
    holdout until something clears."""

    @staticmethod
    def _ledger() -> ExperimentLedger:
        ledger = ExperimentLedger()
        ledger.add_sample(_sample("holdout", SampleRole.HOLDOUT))
        return ledger

    def test_the_first_inspection_is_allowed(self) -> None:
        ledger = self._ledger()
        ledger.record_post_hoc(
            "first", "one look", "holdout", "profit_factor",
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC), p_value=Decimal("0.20"),
        )
        assert ledger.tests_recorded("holdout") == 1

    def test_a_second_inspection_is_refused(self) -> None:
        ledger = self._ledger()
        ledger.record_post_hoc(
            "first", "one look", "holdout", "profit_factor",
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC), p_value=Decimal("0.20"),
        )
        with pytest.raises(ValueError, match="inspected once, ever"):
            ledger.record_post_hoc(
                "second", "another look", "holdout", "profit_factor",
                outcome=ExperimentOutcome.SUPPORTED,
                tested_at=dt.datetime(2026, 7, 21, tzinfo=UTC), p_value=Decimal("0.04"),
            )

    def test_the_refusal_names_what_already_spent_it(self) -> None:
        ledger = self._ledger()
        ledger.record_post_hoc(
            "first", "one look", "holdout", "profit_factor",
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC), p_value=Decimal("0.20"),
        )
        with pytest.raises(ValueError, match="first"):
            ledger.record_post_hoc(
                "second", "another look", "holdout", "profit_factor",
                outcome=ExperimentOutcome.SUPPORTED,
                tested_at=dt.datetime(2026, 7, 21, tzinfo=UTC), p_value=Decimal("0.04"),
            )


class TestConfirmationRequiresPreRegistration:
    """§12.4: `may_support_confirmation` had no caller in src/, so a post-hoc
    hypothesis could be recorded as its own passing confirmation."""

    @staticmethod
    def _ledger() -> ExperimentLedger:
        ledger = ExperimentLedger()
        ledger.add_sample(_sample("confirm", SampleRole.CONFIRMATION))
        return ledger

    def test_a_post_hoc_hypothesis_cannot_be_confirmed(self) -> None:
        with pytest.raises(ValueError, match="confirmation of itself"):
            self._ledger().record_post_hoc(
                "fitted", "noticed in the data", "confirm", "profit_factor",
                outcome=ExperimentOutcome.SUPPORTED,
                tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC), p_value=Decimal("0.001"),
            )

    def test_a_pre_registered_hypothesis_can_be(self) -> None:
        ledger = self._ledger()
        ledger.register(
            "planned", "written down first", "confirm", "profit_factor",
            dt.datetime(2026, 7, 1, tzinfo=UTC),
        )
        result = ledger.record_result(
            "planned", ExperimentOutcome.SUPPORTED,
            dt.datetime(2026, 7, 20, tzinfo=UTC), p_value=Decimal("0.001"),
        )
        assert result.registration is Registration.PRE_REGISTERED

    def test_discovery_samples_still_accept_post_hoc_work(self) -> None:
        # §12.4 separates the samples precisely so discovery stays free.
        ledger = ExperimentLedger()
        ledger.add_sample(_sample("discover", SampleRole.DISCOVERY))
        e = ledger.record_post_hoc(
            "noticed", "found while looking", "discover", "profit_factor",
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC), p_value=Decimal("0.03"),
        )
        assert e.registration is Registration.POST_HOC


class TestExactArithmetic:
    def test_a_float_p_value_is_refused(self) -> None:
        # 0.1 + 0.2 stores as Decimal('0.30000000000000004'); at a BH boundary
        # that decides significance by 1e-17.
        with pytest.raises(ValidationError, match="supplied as the float"):
            Experiment(
                hypothesis_id="h",
                description="d",
                sample_id=GBP_SAMPLE_ID,
                metric="profit_factor",
                registration=Registration.POST_HOC,
                outcome=ExperimentOutcome.SUPPORTED,
                tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC),
                p_value=0.1 + 0.2,
            )

    def test_a_string_or_decimal_p_value_is_exact(self) -> None:
        e = Experiment(
            hypothesis_id="h",
            description="d",
            sample_id=GBP_SAMPLE_ID,
            metric="profit_factor",
            registration=Registration.POST_HOC,
            registered_at=dt.datetime(2026, 7, 20, tzinfo=UTC),
            outcome=ExperimentOutcome.SUPPORTED,
            tested_at=dt.datetime(2026, 7, 20, tzinfo=UTC),
            p_value="0.3",
        )
        assert e.p_value == Decimal("0.3")
