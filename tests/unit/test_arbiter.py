"""Market Opportunity Arbiter (§6.1 agent D) and its no-averaging invariant.

§6.1 gives agent D four rules. Three are already mechanisms elsewhere and are
tested here only where the Arbiter must be shown to *use* them rather than
route around them: the first-pass gate is `IndependenceLedger.for_arbiter()`
(§6.2 rule 5), the independence judgment is `Agreement.materially_independent`
(§6.2 rule 7), and the E1/E2 ceiling is `EvidenceClass.max_edge_tier` (§5.2).

The fourth — "must not average two weak theses into one apparently strong
thesis" — has no prior mechanism, so it gets a property test rather than a spot
check: over every combination of the two traders' evidence classes, and under
both independent and duplicated evidence, the arbitrated class must never
exceed the better of the two inputs.
"""

import ast
import datetime as dt
import inspect
import itertools
import pathlib
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
from trading_firm.arbiter import ArbiterDecision, arbitrate, compare
from trading_firm.classification import classify
from trading_firm.independence import IndependenceLedger
from trading_firm.models import DrawdownState
from trading_firm.packet import FirmSnapshot, MarketSnapshot, MarketStatePacket
from trading_firm.policy import load_adaptive_policy

UTC = dt.UTC
NOW = dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC)
PACKET = "p" * 64
POLICY_PATH = "config/research/adaptive_policy.yaml"

WIDTH = "session_features_v1.asian_width_pips"
COMPRESSION = "session_features_v1.compression_ratio"
PRE_LONDON = "session_features_v1.pre_london_range_pips"
ASIAN_HIGH = "session_features_v1.asian_high"

# Disjoint evidence -> materially independent; identical evidence -> duplicated.
ALPHA_OWN = [WIDTH, PRE_LONDON]
BETA_OWN = [COMPRESSION, ASIAN_HIGH]

EVERY_EVIDENCE_CLASS = tuple(EvidenceClass)


@pytest.fixture(scope="module")
def policy():
    return load_adaptive_policy(POLICY_PATH)


def feature(feature_id: str, value: str = "38") -> SelectedFeature:
    return SelectedFeature(
        feature_id=feature_id, observed_value=Decimal(value), relevance="in band"
    )


def market(**overrides) -> MarketSnapshot:
    """A clean packet: ceiling E5, so each trader's effective class is its claim."""
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
        features={WIDTH: Decimal("38"), COMPRESSION: Decimal("0.4")},
        analog_sample_size=40,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def thesis(trader: str, features: list[str] | None = None, **overrides) -> AdaptiveThesis:
    chosen = features if features is not None else (ALPHA_OWN if trader == "alpha" else BETA_OWN)
    base = dict(
        thesis_id=f"t-{trader}",
        trader_id=trader,
        timestamp_utc=NOW,
        instrument="GBP_USD",
        direction="long",
        market_state=MarketState(
            regime="compression", volatility_state="low", session_phase="briefing"
        ),
        selected_features=[feature(f) for f in chosen],
        historical_analogs=HistoricalAnalogs(sample_size=40),
        thesis=Thesis(
            causal_or_behavioral_rationale="overnight balance, London seeks liquidity",
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


def ledger_of(
    alpha: AdaptiveThesis, beta: AdaptiveThesis, snapshot: MarketSnapshot | None = None
) -> IndependenceLedger:
    snapshot = snapshot if snapshot is not None else market()
    led = IndependenceLedger(packet_id=PACKET, market_id=snapshot.checksum)
    led.submit(alpha, PACKET, NOW)
    led.submit(beta, PACKET, NOW)
    return led


def decide(alpha: AdaptiveThesis, beta: AdaptiveThesis, policy, snapshot=None):
    snapshot = snapshot if snapshot is not None else market()
    return arbitrate(ledger_of(alpha, beta, snapshot), snapshot, policy)


class TestArbiterWaitsForBothLocks:
    """§6.1: the Arbiter must not see either analysis before both lock."""

    def test_arbitration_is_impossible_until_both_first_passes_exist(self, policy) -> None:
        led = IndependenceLedger(packet_id=PACKET, market_id=market().checksum)
        led.submit(thesis("alpha"), PACKET, NOW)
        with pytest.raises(PermissionError, match="only after both are complete"):
            arbitrate(led, market(), policy)

    def test_arbitration_reuses_the_ledger_gate_rather_than_its_own(self, policy) -> None:
        # An empty ledger must fail in exactly the same place: the §6.2 rule 5
        # release, not some second ordering check inside the Arbiter that could
        # be relaxed independently.
        with pytest.raises(PermissionError, match=r"outstanding: \['alpha', 'beta'\]"):
            arbitrate(
                IndependenceLedger(packet_id=PACKET, market_id=market().checksum),
                market(),
                policy,
            )


class TestNoAveraging:
    """§6.1: "must not average two weak theses into one apparently strong thesis"."""

    def test_two_agreeing_e2_theses_do_not_become_e3_or_e4(self, policy) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E2),
            thesis("beta", evidence_class=EvidenceClass.E2),
            policy,
        )
        assert result.materially_independent is True, "the fixture is disjoint evidence"
        assert result.arbitrated is EvidenceClass.E2
        assert result.arbitrated not in (EvidenceClass.E3, EvidenceClass.E4, EvidenceClass.E5)
        assert result.max_edge_tier == 0, "E2 authorizes no live tier (§5.2)"

    @pytest.mark.parametrize("independent", [True, False])
    @pytest.mark.parametrize(
        ("alpha_class", "beta_class"),
        list(itertools.product(EVERY_EVIDENCE_CLASS, EVERY_EVIDENCE_CLASS)),
    )
    def test_arbitrated_class_never_exceeds_the_better_input(
        self, policy, alpha_class, beta_class, independent
    ) -> None:
        """The invariant, quantified over all 36 pairings twice.

        A spot check would pass on an implementation that averages ranks, sums
        them, or promotes on agreement, because for many pairings those agree
        with selection. Sweeping the grid is what separates them.
        """
        beta_features = BETA_OWN if independent else ALPHA_OWN
        result = decide(
            thesis("alpha", evidence_class=alpha_class),
            thesis("beta", features=beta_features, evidence_class=beta_class),
            policy,
        )
        rank = {ev: i for i, ev in enumerate(EVERY_EVIDENCE_CLASS)}
        assert rank[result.arbitrated] <= max(rank[alpha_class], rank[beta_class]), (
            f"alpha {alpha_class} + beta {beta_class} arbitrated to {result.arbitrated}"
        )

    def test_an_inflated_decision_cannot_be_constructed_at_all(self) -> None:
        # Not merely "the selection path never produces this": the value itself
        # is unrepresentable, so a future caller assembling a decision by hand
        # fails at construction (§6.1).
        with pytest.raises(ValueError, match="must not average two weak theses"):
            ArbiterDecision(
                market_id="m",
                selected=thesis("alpha", evidence_class=EvidenceClass.E2),
                arbitrated=EvidenceClass.E4,
                alpha_evidence=EvidenceClass.E2,
                beta_evidence=EvidenceClass.E2,
                materially_independent=True,
                unresolved=(),
                reasons=("two E2s agreed, so surely E4",),
            )

    def test_a_thesis_cannot_be_upgraded_by_the_other_traders_class(self) -> None:
        # Passes the max-of-both invariant (E5 is one of the inputs) but is
        # still an average: alpha proceeds carrying beta's evidence.
        with pytest.raises(ValueError, match="exceeds alpha's own"):
            ArbiterDecision(
                market_id="m",
                selected=thesis("alpha", evidence_class=EvidenceClass.E2),
                arbitrated=EvidenceClass.E5,
                alpha_evidence=EvidenceClass.E2,
                beta_evidence=EvidenceClass.E5,
                materially_independent=True,
                unresolved=(),
                reasons=("borrowed beta's class",),
            )

    def test_the_stronger_thesis_is_selected_not_blended(self, policy) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E2),
            thesis("beta", evidence_class=EvidenceClass.E4),
            policy,
        )
        assert result.selected_trader == "beta"
        assert result.arbitrated is EvidenceClass.E4
        assert result.selected is not None and result.selected.thesis_id == "t-beta"

    def test_arbitration_weighs_clamped_evidence_not_the_claim(self, policy) -> None:
        # Both traders file E5 on a packet whose analog support only reaches E2.
        # The Arbiter compares what §5.2 left of each claim, so a persuasive
        # pair is worth exactly what a persuasive single is: nothing.
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E5),
            thesis("beta", evidence_class=EvidenceClass.E5),
            policy,
            snapshot=market(analog_sample_size=3),
        )
        assert result.alpha_evidence is result.beta_evidence is EvidenceClass.E2
        assert result.arbitrated is EvidenceClass.E2
        assert result.max_edge_tier == 0

    def test_the_weaker_thesis_contributes_nothing_to_the_class(self, policy) -> None:
        strong_alone = decide(
            thesis("alpha", evidence_class=EvidenceClass.E4),
            thesis("beta", evidence_class=EvidenceClass.E1),
            policy,
        )
        strong_pair = decide(
            thesis("alpha", evidence_class=EvidenceClass.E4),
            thesis("beta", evidence_class=EvidenceClass.E4),
            policy,
        )
        assert strong_alone.arbitrated is strong_pair.arbitrated is EvidenceClass.E4


class TestIndependentAgreementVersusDuplicatedEvidence:
    """§6.2 rule 7 and §5.3: only independent confirmation can reach Exceptional."""

    def test_duplicated_evidence_is_reported_as_not_independent(self, policy) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E5),
            thesis("beta", features=ALPHA_OWN, evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.materially_independent is False
        assert result.arbitrated is EvidenceClass.E4, (
            "two theses on one feature set are one thesis counted twice, so §5.3's "
            "independent structural confirmation is absent"
        )
        assert result.max_edge_tier == 3, "HIGH, not EXCEPTIONAL"
        assert any("§5.3 requires independent" in r for r in result.reasons)

    def test_independent_agreement_permits_the_full_class_but_never_raises_it(
        self, policy
    ) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E5),
            thesis("beta", evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.materially_independent is True
        assert result.arbitrated is EvidenceClass.E5
        assert result.max_edge_tier == 4
        assert any("does not raise" in r for r in result.reasons)

    def test_partial_overlap_still_counts_as_independent(self, policy) -> None:
        result = decide(
            thesis("alpha", features=[WIDTH, PRE_LONDON], evidence_class=EvidenceClass.E5),
            thesis("beta", features=[WIDTH, COMPRESSION], evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.materially_independent is True
        assert result.arbitrated is EvidenceClass.E5

    def test_a_counterpart_that_cannot_advance_is_not_a_confirmation(self, policy) -> None:
        # Beta agrees on direction from disjoint evidence, so `Agreement` alone
        # reports independent agreement — but beta classified its own evidence
        # E0, which rejects outright (§5.2). An agreeing party that cannot itself
        # advance is not the independent structural confirmation §5.3 requires.
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E5),
            thesis("beta", evidence_class=EvidenceClass.E0),
            policy,
        )
        assert result.materially_independent is True
        assert result.selected_trader == "alpha"
        assert result.arbitrated is EvidenceClass.E4
        assert result.max_edge_tier == 3

    def test_a_declining_counterpart_is_not_a_confirmation_either(self, policy) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E5),
            thesis("beta", direction="none"),
            policy,
        )
        assert result.selected_trader == "alpha"
        assert result.arbitrated is EvidenceClass.E4
        assert result.max_edge_tier == 3


class TestOpposedDirections:
    """§6.1: "may reject both traders and declare no trade"."""

    def test_independent_opposition_is_a_no_trade(self, policy) -> None:
        result = decide(
            thesis("alpha", direction="long", evidence_class=EvidenceClass.E5),
            thesis("beta", direction="short", evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.is_no_trade is True
        assert result.selected is None
        assert result.arbitrated is EvidenceClass.E0
        assert result.max_edge_tier == 0
        assert any("sign is undetermined" in r for r in result.reasons)

    def test_duplicated_opposition_is_a_no_trade_for_a_different_reason(self, policy) -> None:
        result = decide(
            thesis("alpha", direction="long", evidence_class=EvidenceClass.E5),
            thesis("beta", features=ALPHA_OWN, direction="short",
                   evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.is_no_trade is True
        assert any("not reproducible" in r for r in result.reasons)
        assert not any("sign is undetermined" in r for r in result.reasons), (
            "identical evidence reaching opposite conclusions is unstable interpretation, "
            "not a genuinely two-sided market; post-session review must tell them apart"
        )

    def test_opposition_never_resolves_to_the_higher_evidence_class(self, policy) -> None:
        # The tempting shortcut: E5 beats E2, so take the E5 side. §6.1 permits
        # rejecting both, and a contested sign is exactly when it is owed.
        result = decide(
            thesis("alpha", direction="long", evidence_class=EvidenceClass.E5),
            thesis("beta", direction="short", evidence_class=EvidenceClass.E2),
            policy,
        )
        assert result.is_no_trade is True

    def test_direction_conflict_is_recorded_as_unresolved(self, policy) -> None:
        result = decide(
            thesis("alpha", direction="long"), thesis("beta", direction="short"), policy
        )
        assert any(u.startswith("direction:") for u in result.unresolved)

    def test_both_declining_is_a_no_trade(self, policy) -> None:
        result = decide(
            thesis("alpha", direction="none", selected_features=[]),
            thesis("beta", direction="none", selected_features=[]),
            policy,
        )
        assert result.is_no_trade is True
        assert result.max_edge_tier == 0


class TestWeakHypothesesStayWeak:
    """§6.1: "cannot transform an E1 or E2 hypothesis into a high-risk live trade"."""

    @pytest.mark.parametrize(
        ("alpha_class", "beta_class"),
        list(itertools.product([EvidenceClass.E1, EvidenceClass.E2], repeat=2)),
    )
    def test_no_pairing_of_weak_hypotheses_unlocks_a_live_tier(
        self, policy, alpha_class, beta_class
    ) -> None:
        result = decide(
            thesis("alpha", evidence_class=alpha_class),
            thesis("beta", evidence_class=beta_class),
            policy,
        )
        assert result.max_edge_tier == 0

    def test_the_ceiling_comes_from_the_existing_evidence_table(self, policy) -> None:
        # Asserted against `EvidenceClass.max_edge_tier` rather than a second
        # copy of the §5.2 table living in the Arbiter.
        for claimed in EVERY_EVIDENCE_CLASS:
            result = decide(
                thesis("alpha", evidence_class=claimed),
                thesis("beta", evidence_class=claimed),
                policy,
            )
            assert result.max_edge_tier == result.arbitrated.max_edge_tier


class TestNoveltyStillBinds:
    """§6.8 survives arbitration: evidence never buys back a novelty permission."""

    def test_an_n2_thesis_reaches_no_live_tier_however_strong_the_agreement(
        self, policy
    ) -> None:
        result = decide(
            thesis("alpha", novelty_class=NoveltyClass.N2, evidence_class=EvidenceClass.E5),
            thesis("beta", novelty_class=NoveltyClass.N2, evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.arbitrated is EvidenceClass.E5
        assert result.max_edge_tier == 0, "N2 may never place live orders (§6.8)"

    def test_an_n1_thesis_cannot_reach_exceptional(self, policy) -> None:
        result = decide(
            thesis("alpha", novelty_class=NoveltyClass.N1, evidence_class=EvidenceClass.E5),
            thesis("beta", novelty_class=NoveltyClass.N1, evidence_class=EvidenceClass.E5),
            policy,
        )
        assert result.max_edge_tier == 3

    def test_the_more_validated_thesis_wins_an_evidence_tie(self, policy) -> None:
        result = decide(
            thesis("alpha", novelty_class=NoveltyClass.N2),
            thesis("beta", novelty_class=NoveltyClass.N0),
            policy,
        )
        assert result.selected_trader == "beta"


class TestNoTradeIsAlwaysAvailable:
    """§6.1 and §0.6: declining must be the cheapest branch, not the hardest."""

    def test_declining_needs_only_an_identity_and_a_reason(self) -> None:
        result = ArbiterDecision.no_trade(
            market_id="m", reasons=("nothing worth reviewing today",)
        )
        assert result.is_no_trade is True
        assert result.selected is None
        assert result.selected_trader is None
        assert result.arbitrated is EvidenceClass.E0
        assert result.max_edge_tier == 0

    def test_a_no_trade_carrying_live_evidence_cannot_be_constructed(self) -> None:
        with pytest.raises(ValueError, match="no-trade arbitration carries evidence"):
            ArbiterDecision(
                market_id="m",
                selected=None,
                arbitrated=EvidenceClass.E4,
                alpha_evidence=EvidenceClass.E4,
                beta_evidence=EvidenceClass.E4,
                materially_independent=True,
                unresolved=(),
                reasons=("declined but kept the class",),
            )

    def test_an_unexplained_arbitration_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="no stated reason"):
            ArbiterDecision.no_trade(market_id="m", reasons=())

    def test_stale_data_rejects_both_traders(self, policy) -> None:
        # §5.2 E0 / §0.10: the ceiling is E0 for both, so neither is advanceable.
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E5),
            thesis("beta", evidence_class=EvidenceClass.E5),
            policy,
            snapshot=market(data_fresh=False),
        )
        assert result.is_no_trade is True
        assert result.alpha_evidence is EvidenceClass.E0
        assert any("classifies E0" in r for r in result.reasons)


class TestOneTraderDeclines:
    def test_a_lone_directional_thesis_may_still_proceed(self, policy) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E4),
            thesis("beta", direction="none", selected_features=[]),
            policy,
        )
        assert result.selected_trader == "alpha"
        assert result.arbitrated is EvidenceClass.E4
        assert any("recommends no trade" in r for r in result.reasons)

    def test_the_decline_is_carried_forward_as_unresolved(self, policy) -> None:
        result = decide(
            thesis("alpha"), thesis("beta", direction="none", selected_features=[]), policy
        )
        assert any("direction: alpha long vs beta none" in u for u in result.unresolved)


class TestUnresolvedDisagreements:
    def test_evidence_and_novelty_disputes_are_recorded(self, policy) -> None:
        result = decide(
            thesis("alpha", evidence_class=EvidenceClass.E4, novelty_class=NoveltyClass.N0),
            thesis("beta", evidence_class=EvidenceClass.E2, novelty_class=NoveltyClass.N1),
            policy,
        )
        joined = " | ".join(result.unresolved)
        assert "evidence class: alpha E4 vs beta E2" in joined
        assert "novelty class: alpha N0 vs beta N1" in joined

    def test_full_agreement_leaves_nothing_unresolved(self, policy) -> None:
        assert decide(thesis("alpha"), thesis("beta"), policy).unresolved == ()

    def test_two_instruments_are_not_a_comparison(self, policy) -> None:
        result = compare(
            thesis("alpha"),
            classify(thesis("alpha"), market(), policy),
            thesis("beta", instrument="EUR_USD"),
            classify(thesis("beta", instrument="EUR_USD"), market(), policy),
            ledger_of(thesis("alpha"), thesis("beta", instrument="EUR_USD")).agreement(),
        )
        assert result.is_no_trade is True
        assert any("did not review the same opportunity" in r for r in result.reasons)

    def test_a_thesis_about_another_instrument_is_rejected(self, policy) -> None:
        result = decide(
            thesis("alpha", instrument="EUR_USD"), thesis("beta", instrument="EUR_USD"), policy
        )
        assert result.is_no_trade is True
        assert any("was not built from the evidence" in r for r in result.reasons)


class TestMarketIdentity:
    def test_the_decision_names_the_market_it_was_computed_from(self, policy) -> None:
        snapshot = market()
        assert decide(thesis("alpha"), thesis("beta"), policy, snapshot).market_id == (
            snapshot.checksum
        )

    def test_theses_classified_against_different_markets_are_incomparable(
        self, policy
    ) -> None:
        # §6A: both senior traders receive the exact same packet checksum.
        alpha_t, beta_t = thesis("alpha"), thesis("beta")
        with pytest.raises(ValueError, match="exact same packet checksum"):
            compare(
                alpha_t,
                classify(alpha_t, market(), policy),
                beta_t,
                classify(beta_t, market(spread_pips=Decimal("1.9")), policy),
                ledger_of(alpha_t, beta_t).agreement(),
            )

    def test_the_pair_cannot_be_supplied_in_the_wrong_order(self, policy) -> None:
        alpha_t, beta_t = thesis("alpha"), thesis("beta")
        with pytest.raises(ValueError, match="in that order"):
            compare(
                beta_t,
                classify(beta_t, market(), policy),
                alpha_t,
                classify(alpha_t, market(), policy),
                ledger_of(alpha_t, beta_t).agreement(),
            )


# --- the firm states the A-2 invariance property is quantified over ----------
FIRM_STATES = {
    "flat and normal": FirmSnapshot(
        closed_equity=Decimal("250"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.NORMAL,
    ),
    "far behind, late, and losing": FirmSnapshot(
        closed_equity=Decimal("212"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.RESTRICTED,
        session_realized_loss=Decimal("18.00"),
        weekly_realized_loss=Decimal("31.50"),
        trades_this_session=1,
    ),
    "far ahead": FirmSnapshot(
        closed_equity=Decimal("1000"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.NORMAL,
    ),
}


class TestPressureInvariance:
    """A-2 / §5.1: arbitration is a function of the market half of the packet."""

    def test_arbitration_is_identical_across_firm_states(self, policy) -> None:
        snapshot = market()
        baseline = decide(thesis("alpha"), thesis("beta"), policy, snapshot)
        for label, firm in FIRM_STATES.items():
            packet = MarketStatePacket(market=snapshot, firm=firm)
            result = decide(thesis("alpha"), thesis("beta"), policy, packet.market)
            assert result == baseline, f"arbitration moved under firm state: {label}"
            assert result.max_edge_tier == baseline.max_edge_tier, label

    def test_arbiter_signatures_admit_no_firm_state(self) -> None:
        for fn in (arbitrate, compare):
            rendered = " ".join(
                str(p.annotation) for p in inspect.signature(fn).parameters.values()
            )
            assert "FirmSnapshot" not in rendered, (
                f"{fn.__name__} accepts firm state: which thesis proceeds, and the class it "
                f"carries, must be a pure function of the market half (A-2, §5.1)"
            )

    def test_arbiter_module_never_references_firm_state(self) -> None:
        """Mirrors `test_classification.py`: an aliased import would slip past a
        signature check, so the module must not name the type at all."""
        import trading_firm.arbiter as module

        source = pathlib.Path(module.__file__).read_text()
        imported: set[str] = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.ImportFrom | ast.Import):
                imported |= {alias.name for alias in node.names}
        assert "FirmSnapshot" not in imported, (
            "arbiter imports FirmSnapshot: firm state must not be reachable from "
            "arbitration at all (A-2, §5.1)"
        )
        code_lines = [ln for ln in source.splitlines() if not ln.lstrip().startswith("#")]
        executable = "".join("\n".join(code_lines).split('"""')[::2])
        assert "FirmSnapshot" not in executable, (
            "arbiter code references FirmSnapshot (A-2, §5.1)"
        )
        for banned in ("closed_equity", "session_realized_loss", "trades_this_session",
                       "drawdown_state", "tier_anchor"):
            assert banned not in executable, (
                f"arbiter reads {banned}: firm state may only reduce risk at the gate, and "
                f"must not reach the decision about which thesis proceeds (A-2, §5.1, §3.3)"
            )


class TestEvidenceOrderIntegrity:
    """The Arbiter derives its ladder from the enum; pin that it stays a ladder."""

    def test_declaration_order_is_monotone_in_the_tier_it_unlocks(self) -> None:
        tiers = [ev.max_edge_tier for ev in EVERY_EVIDENCE_CLASS]
        assert tiers == sorted(tiers), (
            "EvidenceClass is declared worst-to-best and the Arbiter ranks by that order; "
            "a reordering would silently invert every comparison (§5.2)"
        )

    def test_novelty_declaration_order_narrows_permissions(self) -> None:
        live = [nv.may_trade_live for nv in NoveltyClass]
        assert live == sorted(live, reverse=True), "N0..N3 must narrow, never widen (§6.8)"


def test_module_is_pressure_blind_under_the_shared_guard() -> None:
    """A-2 (§5.1) via `tests/a2_guard.py`.

    The local guards in this file check the single name `FirmSnapshot`. An
    adversarial review defeated that by importing `AccountState` instead, so
    the shared guard checks the whole firm-state vocabulary. Both run: the
    local one gives a module-specific message, this one is the real check.
    """
    import importlib

    from a2_guard import assert_pressure_blind

    assert_pressure_blind(importlib.import_module("trading_firm.arbiter"))


class TestArbitratedEvidenceIsThePacketTheTradersAnalysed:
    """§6A: both traders receiving the same packet is only half the requirement.

    An adversarial review showed the Arbiter re-classifying both locked theses
    against an entirely unrelated MarketSnapshot while every §6.2 gate reported
    healthy — independence between the traders held perfectly, and the evidence
    being arbitrated was simply not the evidence anyone analysed.
    """

    def test_an_unrelated_snapshot_is_refused(self, policy) -> None:
        analysed = market()
        unrelated = market(
            session_date=dt.date(2026, 7, 29),
            regime="expansion",
            bid=Decimal("1.31000"),
            ask=Decimal("1.31014"),
        )
        assert unrelated.checksum != analysed.checksum

        led = ledger_of(thesis("alpha"), thesis("beta"), analysed)
        with pytest.raises(ValueError, match="not the packet the senior traders analysed"):
            arbitrate(led, unrelated, policy)

    def test_the_analysed_snapshot_is_accepted(self, policy) -> None:
        analysed = market()
        led = ledger_of(thesis("alpha"), thesis("beta"), analysed)
        assert arbitrate(led, analysed, policy).market_id == analysed.checksum

    def test_a_single_changed_field_is_enough_to_refuse(self, policy) -> None:
        # The realistic version: not a wholly different day, just a snapshot
        # rebuilt a moment later with a different spread. Re-classifying against
        # it would silently move the evidence ceiling (§5.3 caps E3 on spread).
        analysed = market(spread_pips=Decimal("1.2"))
        refreshed = market(spread_pips=Decimal("1.3"))
        led = ledger_of(thesis("alpha"), thesis("beta"), analysed)
        with pytest.raises(ValueError, match="not the packet"):
            arbitrate(led, refreshed, policy)

    def test_for_packet_cannot_produce_inconsistent_identities(self) -> None:
        from trading_firm.models import DrawdownState
        from trading_firm.packet import FirmSnapshot, MarketStatePacket

        snapshot = market()
        packet = MarketStatePacket(
            market=snapshot,
            firm=FirmSnapshot(
                closed_equity=Decimal("250"),
                tier_anchor=Decimal("250"),
                drawdown_state=DrawdownState.NORMAL,
            ),
        )
        led = IndependenceLedger.for_packet(packet)
        assert led.packet_id == packet.packet_id
        assert led.market_id == packet.market_id
        led.verify_market(snapshot)  # does not raise
