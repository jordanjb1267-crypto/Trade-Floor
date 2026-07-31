"""Senior-trader independence protocol (§6.2) and its §21 acceptance criterion.

The criterion — "Alpha cannot access Beta's first-pass report before submitting
its own, and vice versa" — is the reason the pair is worth having at all. Two
traders fed each other's conclusions are one trader with extra latency.
"""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.adaptive import (
    AdaptiveThesis,
    EvidenceClass,
    HistoricalAnalogs,
    MarketState,
    NoveltyClass,
    SelectedFeature,
    Thesis,
    TradePlan,
)
from trading_firm.independence import IndependenceLedger

UTC = dt.UTC
PACKET = "a" * 64
MARKET_ID = "m" * 64
NOW = dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC)

WIDTH = "session_features_v1.asian_width_pips"
COMPRESSION = "session_features_v1.compression_ratio"
PRE_LONDON = "session_features_v1.pre_london_range_pips"


def feature(feature_id: str, value: str = "38") -> SelectedFeature:
    return SelectedFeature(
        feature_id=feature_id, observed_value=Decimal(value), relevance="in band"
    )


def thesis(trader: str, **overrides) -> AdaptiveThesis:
    base = dict(
        thesis_id=f"t-{trader}",
        trader_id=trader,
        timestamp_utc=NOW,
        instrument="GBP_USD",
        direction="long",
        market_state=MarketState(
            regime="compression", volatility_state="low", session_phase="briefing"
        ),
        selected_features=[feature(WIDTH)],
        historical_analogs=HistoricalAnalogs(sample_size=40),
        thesis=Thesis(
            causal_or_behavioral_rationale="overnight balance",
            expected_path="expansion beyond the range edge",
            failure_scenario="rotation back inside within two bars",
        ),
        trade_plan=TradePlan(
            entry_rule="first print beyond the range + buffer",
            invalidation_rule="opposite range side",
            exit_rule="1.5R or flatten",
            expiration_rule="entry cutoff",
        ),
        novelty_class=NoveltyClass.N0,
        evidence_class=EvidenceClass.E3,
        estimated_costs=Decimal("0.02"),
        expected_value_basis="validated playbook expectancy",
        confidence_calibration_reference="calibration_v1",
    )
    base.update(overrides)
    return AdaptiveThesis(**base)


@pytest.fixture
def ledger() -> IndependenceLedger:
    return IndependenceLedger(packet_id=PACKET, market_id=MARKET_ID)


class TestFirstPassIsolation:
    """§21: neither trader may read the other before locking its own."""

    def test_beta_cannot_read_alpha_before_locking(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        with pytest.raises(PermissionError, match="before first-pass submission"):
            ledger.read("beta", "alpha")

    def test_alpha_cannot_read_beta_before_locking(self, ledger) -> None:
        ledger.submit(thesis("beta"), PACKET, NOW)
        with pytest.raises(PermissionError, match="before first-pass submission"):
            ledger.read("alpha", "beta")

    def test_reading_is_permitted_once_both_are_locked(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        ledger.submit(thesis("beta"), PACKET, NOW)
        assert ledger.read("beta", "alpha").trader_id == "alpha"
        assert ledger.read("alpha", "beta").trader_id == "beta"

    def test_a_trader_may_always_read_its_own(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        assert ledger.read("alpha", "alpha").trader_id == "alpha"


class TestPacketBinding:
    def test_a_different_packet_is_rejected(self, ledger) -> None:
        # §6.2 rule 1 / §6A: both traders receive the SAME packet. A thesis
        # built on different data is not an independent second opinion.
        with pytest.raises(ValueError, match="same packet"):
            ledger.submit(thesis("alpha"), "b" * 64, NOW)

    def test_naive_timestamp_rejected(self, ledger) -> None:
        with pytest.raises(ValueError, match="timezone-aware"):
            ledger.submit(thesis("alpha"), PACKET, dt.datetime(2026, 7, 30, 7, 40))


class TestImmutability:
    def test_first_pass_cannot_be_resubmitted(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        with pytest.raises(ValueError, match="immutable"):
            ledger.submit(thesis("alpha", direction="short"), PACKET, NOW)

    def test_content_hash_detects_tampering(self, ledger) -> None:
        report = ledger.submit(thesis("alpha"), PACKET, NOW)
        report.verify()  # clean
        tampered = type(report)(
            trader_id=report.trader_id,
            packet_id=report.packet_id,
            thesis=thesis("alpha", direction="short"),
            locked_at=report.locked_at,
            content_hash=report.content_hash,
        )
        with pytest.raises(ValueError, match="altered after locking"):
            tampered.verify()


class TestArbiterGate:
    def test_arbiter_blocked_until_both_complete(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        with pytest.raises(PermissionError, match="only after both are complete"):
            ledger.for_arbiter()

    def test_arbiter_receives_both(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        ledger.submit(thesis("beta"), PACKET, NOW)
        alpha, beta = ledger.for_arbiter()
        assert (alpha.trader_id, beta.trader_id) == ("alpha", "beta")


class TestRevisions:
    def test_revision_requires_both_first_passes(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        with pytest.raises(PermissionError, match="both first passes"):
            ledger.revise(thesis("alpha", direction="short"), ["flipped"], NOW)

    def test_revision_requires_a_first_pass_of_its_own(self, ledger) -> None:
        # Only Beta locked. Alpha trying to revise has skipped the commitment
        # step entirely — it would be responding to Beta without ever having
        # staked a position of its own, which is the anchoring §6.2 prevents.
        ledger.submit(thesis("beta"), PACKET, NOW)
        with pytest.raises(PermissionError, match="cannot revise before locking"):
            ledger.revise(thesis("alpha", direction="short"), ["saw beta"], NOW)

    def test_silent_convergence_is_rejected(self, ledger) -> None:
        # §6.2 rule 6: the thesis moved but the account of why did not. That is
        # precisely the anchoring the rule exists to surface.
        ledger.submit(thesis("alpha"), PACKET, NOW)
        ledger.submit(thesis("beta", direction="short"), PACKET, NOW)
        with pytest.raises(ValueError, match="lists nothing changed"):
            ledger.revise(thesis("alpha", direction="short"), ["   "], NOW)

    def test_declared_change_is_accepted(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        ledger.submit(thesis("beta", direction="short"), PACKET, NOW)
        revision = ledger.revise(
            thesis("alpha", direction="none"),
            ["Beta's sweep evidence invalidates the continuation read"],
            NOW,
        )
        assert revision.changed[0].startswith("Beta's sweep")

    def test_holding_position_needs_no_changelist(self, ledger) -> None:
        # A trader that reads the opposing thesis and does not move has nothing
        # to declare. Independence does not mean churn.
        ledger.submit(thesis("alpha"), PACKET, NOW)
        ledger.submit(thesis("beta", direction="short"), PACKET, NOW)
        assert ledger.revise(thesis("alpha"), [], NOW).changed == ()


class TestAgreementQuality:
    """§6.2 rule 7 and §6.1.D: agreement counts only when independently reached."""

    def test_identical_evidence_is_not_independent_agreement(self, ledger) -> None:
        ledger.submit(thesis("alpha"), PACKET, NOW)
        ledger.submit(thesis("beta"), PACKET, NOW)
        agreement = ledger.agreement()
        assert agreement.same_direction is True
        assert agreement.materially_independent is False
        assert agreement.independent_agreement is False, (
            "two theses on one feature are one thesis counted twice"
        )

    def test_disjoint_evidence_is_independent_agreement(self, ledger) -> None:
        ledger.submit(thesis("alpha", selected_features=[feature(WIDTH)]), PACKET, NOW)
        ledger.submit(
            thesis("beta", selected_features=[feature(COMPRESSION, "0.4")]), PACKET, NOW
        )
        agreement = ledger.agreement()
        assert agreement.independent_agreement is True
        assert agreement.shared_features == ()

    def test_partial_overlap_still_counts_as_independent(self, ledger) -> None:
        ledger.submit(
            thesis("alpha", selected_features=[feature(WIDTH), feature(PRE_LONDON, "9")]),
            PACKET,
            NOW,
        )
        ledger.submit(
            thesis("beta", selected_features=[feature(WIDTH), feature(COMPRESSION, "0.4")]),
            PACKET,
            NOW,
        )
        agreement = ledger.agreement()
        assert agreement.shared_features == (WIDTH,)
        assert agreement.independent_agreement is True

    def test_opposed_directions_are_not_agreement(self, ledger) -> None:
        ledger.submit(thesis("alpha", selected_features=[feature(WIDTH)]), PACKET, NOW)
        ledger.submit(
            thesis("beta", direction="short", selected_features=[feature(COMPRESSION, "0.4")]),
            PACKET,
            NOW,
        )
        assert ledger.agreement().independent_agreement is False


class TestIndependenceRequiresBothSides:
    """§6.2 rule 7 / §6.1: found by mutation — changing `and` to `or` in
    `materially_independent` survived the entire 837-test suite.

    That is not cosmetic. `Agreement.materially_independent` is the only gate
    between E4 and E5 in the Arbiter, so under `or` a thesis whose evidence is a
    strict SUBSET of the other's would count as independent corroboration and
    unlock Exceptional — precisely the "averaging two weak theses into one
    apparently strong thesis" §6.1 forbids.
    """

    def test_a_subset_thesis_is_not_independent_corroboration(self, ledger) -> None:
        # Alpha cites two features; Beta cites one of Alpha's and nothing else.
        # Beta has contributed no evidence Alpha did not already have.
        ledger.submit(
            thesis("alpha", selected_features=[feature(WIDTH), feature(COMPRESSION, "0.4")]),
            PACKET, NOW,
        )
        ledger.submit(thesis("beta", selected_features=[feature(WIDTH)]), PACKET, NOW)

        agreement = ledger.agreement()
        assert agreement.same_direction is True
        assert agreement.alpha_only == (COMPRESSION,)
        assert agreement.beta_only == ()
        assert agreement.materially_independent is False, (
            "Beta added nothing Alpha did not already hold; that is one thesis "
            "counted twice, not two agreeing traders"
        )
        assert agreement.independent_agreement is False

    def test_the_mirror_case_is_also_not_independent(self, ledger) -> None:
        ledger.submit(thesis("alpha", selected_features=[feature(WIDTH)]), PACKET, NOW)
        ledger.submit(
            thesis("beta", selected_features=[feature(WIDTH), feature(COMPRESSION, "0.4")]),
            PACKET, NOW,
        )
        assert ledger.agreement().materially_independent is False

    def test_both_contributing_is_independent(self, ledger) -> None:
        # The control: without it, a rule that always returned False would pass.
        ledger.submit(thesis("alpha", selected_features=[feature(WIDTH)]), PACKET, NOW)
        ledger.submit(
            thesis("beta", selected_features=[feature(COMPRESSION, "0.4")]), PACKET, NOW
        )
        assert ledger.agreement().materially_independent is True
