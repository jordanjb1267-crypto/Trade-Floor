"""§21 acceptance tests for the adaptive layer, end to end (§6A).

Every criterion below is already covered by a unit test somewhere. That is not
the same thing as being covered here. Each Pass 2 module was built and tested in
isolation, so what has never been checked is that the §6A chain *composes* —
that a classification clamped in `classification.py` actually arrives at
`risk/engine.py` as a lowered ceiling rather than being dropped by the layer in
between. A gate that holds in a unit test and is bypassed by the wiring is
indistinguishable from a gate that works, right up until it matters.

The chain under test, which is §6A's workflow minus the LLM steps:

    MarketSnapshot + FirmSnapshot -> MarketStatePacket (one checksum)
      -> Alpha and Beta lock independent theses (IndependenceLedger)
      -> Arbiter compares only after both lock
      -> deterministic classification clamps the surviving claim
      -> Candidate carries thesis_ceiling
      -> RiskEngine authorizes, or does not

The last step is the one that matters: no §21 criterion is satisfied by a
component refusing something. It is satisfied when the *risk engine* refuses.
"""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

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
from trading_firm.agents.bench import (
    ConsultationRound,
    SpecialistConsultation,
    SpecialistVerdict,
    consult,
)
from trading_firm.arbiter import arbitrate
from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.independence import IndependenceLedger
from trading_firm.models import (
    AccountState,
    Candidate,
    Direction,
    DrawdownState,
    EdgeTier,
    InstrumentSpec,
)
from trading_firm.packet import FirmSnapshot, MarketSnapshot, MarketStatePacket
from trading_firm.policy import load_adaptive_policy
from trading_firm.risk import RiskEngine
from trading_firm.sessions import SessionClock

D = Decimal
UTC = dt.UTC
LONDON = ZoneInfo("Europe/London")
IN_SESSION = dt.datetime(2026, 7, 29, 9, 0, tzinfo=LONDON)
GBP_USD = InstrumentSpec(name="GBP_USD", margin_rate=D("0.05"))  # F-1
WIDTH = "session_features_v1.asian_width_pips"
COMPRESSION = "session_features_v1.compression_ratio"


@pytest.fixture(scope="module")
def policy():
    return load_adaptive_policy("config/research/adaptive_policy.yaml")


@pytest.fixture(scope="module")
def engine() -> RiskEngine:
    config = load_config(BASE_CONFIG_PATH)
    return RiskEngine(config, SessionClock(config.session))


def market(**overrides) -> MarketSnapshot:
    base = dict(
        instrument="GBP_USD",
        observed_at=IN_SESSION.astimezone(UTC),
        session_date=dt.date(2026, 7, 29),
        session_phase="active",
        regime="compression",
        volatility_state="low",
        bid=D("1.32974"),
        ask=D("1.32986"),
        spread_pips=D("1.2"),
        feature_version="session_features_v1",
        features={WIDTH: D("38"), COMPRESSION: D("0.4")},
        analog_sample_size=40,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def firm(**overrides) -> FirmSnapshot:
    base = dict(
        closed_equity=D("250"),
        tier_anchor=D("250"),
        drawdown_state=DrawdownState.NORMAL,
    )
    base.update(overrides)
    return FirmSnapshot(**base)


def feature(feature_id: str, value: str = "38") -> SelectedFeature:
    return SelectedFeature(feature_id=feature_id, observed_value=D(value), relevance="in band")


def thesis(trader: str, **overrides) -> AdaptiveThesis:
    base = dict(
        thesis_id=f"t-{trader}",
        trader_id=trader,
        timestamp_utc=IN_SESSION.astimezone(UTC),
        instrument="GBP_USD",
        direction="long",
        market_state=MarketState(
            regime="compression", volatility_state="low", session_phase="active"
        ),
        selected_features=[feature(WIDTH)],
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
        evidence_class=EvidenceClass.E5,
        estimated_costs=D("0.02"),
        expected_value_basis="validated playbook expectancy",
        confidence_calibration_reference="calibration_v1",
    )
    base.update(overrides)
    return AdaptiveThesis(**base)


def run_workflow(alpha, beta, policy, snapshot=None, firm_state=None):
    """§6A from packet to arbitration, exactly as an orchestrator would."""
    snapshot = snapshot if snapshot is not None else market()
    packet = MarketStatePacket(market=snapshot, firm=firm_state or firm())
    ledger = IndependenceLedger.for_packet(packet)
    ledger.submit(alpha, packet.packet_id, IN_SESSION.astimezone(UTC))
    ledger.submit(beta, packet.packet_id, IN_SESSION.astimezone(UTC))
    return packet, ledger, arbitrate(ledger, packet.market, policy)


def candidate_from(decision, score: int = 97) -> Candidate:
    """The hand-off §6A makes between the adaptive layer and the risk gate.

    `thesis_ceiling` is where the whole chain either survives or is lost: it is
    the single value carrying the arbitrated classification into deterministic
    code.
    """
    return Candidate(
        instrument="GBP_USD",
        strategy_id="adaptive_thesis",
        strategy_version="1.0.0",
        direction=Direction.LONG,
        entry_price=D("1.3298"),
        stop_price=D("1.3273"),
        edge_score=score,
        created_at=IN_SESSION.astimezone(UTC),
        expires_at=IN_SESSION.astimezone(UTC) + dt.timedelta(minutes=10),
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
        human_approval=True,
        thesis_ceiling=EdgeTier(decision.max_edge_tier),
    )


class TestUnvalidatedIdeasCannotReachTheBroker:
    """§21: "N2/N3 theses cannot place live orders"."""

    @pytest.mark.parametrize("novelty", [NoveltyClass.N2, NoveltyClass.N3])
    def test_the_risk_engine_refuses_them_end_to_end(self, policy, engine, novelty) -> None:
        # Both traders agree, on independent evidence, at the best possible
        # evidence class. The ONLY disqualifying fact is novelty.
        _, _, decision = run_workflow(
            thesis("alpha", novelty_class=novelty),
            thesis("beta", novelty_class=novelty, selected_features=[feature(COMPRESSION, "0.4")]),
            policy,
        )
        assert decision.max_edge_tier == 0

        result = engine.evaluate(
            candidate_from(decision), AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        assert result.approved is False, "an N2/N3 thesis reached an approval"
        assert result.allowed_risk_usd == D("0")
        assert any("no live tier" in r for r in result.reasons)

    def test_a_perfect_edge_score_does_not_rescue_them(self, policy, engine) -> None:
        # The deterministic score says EXCEPTIONAL; novelty still wins.
        _, _, decision = run_workflow(
            thesis("alpha", novelty_class=NoveltyClass.N2),
            thesis("beta", novelty_class=NoveltyClass.N2),
            policy,
        )
        result = engine.evaluate(
            candidate_from(decision, score=100),
            AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        assert result.approved is False


class TestN1CannotReceiveExceptional:
    """§21: "N1 theses cannot receive Exceptional risk"."""

    def test_the_tier_lands_below_exceptional(self, policy, engine) -> None:
        _, _, decision = run_workflow(
            thesis("alpha", novelty_class=NoveltyClass.N1),
            thesis("beta", novelty_class=NoveltyClass.N1,
                   selected_features=[feature(COMPRESSION, "0.4")]),
            policy,
        )
        assert decision.max_edge_tier == EdgeTier.HIGH

        result = engine.evaluate(
            candidate_from(decision), AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        assert result.approved is True
        assert result.tier is EdgeTier.HIGH
        assert result.tier is not EdgeTier.EXCEPTIONAL
        assert "thesis classification" in result.tier_bound_by

    def test_an_n0_thesis_on_the_same_evidence_does_reach_exceptional(
        self, policy, engine
    ) -> None:
        """The control. Without this the test above passes for any reason at all
        — a chain that rejected everything would satisfy it."""
        _, _, decision = run_workflow(
            thesis("alpha", novelty_class=NoveltyClass.N0),
            thesis("beta", novelty_class=NoveltyClass.N0,
                   selected_features=[feature(COMPRESSION, "0.4")]),
            policy,
        )
        assert decision.max_edge_tier == EdgeTier.EXCEPTIONAL
        result = engine.evaluate(
            candidate_from(decision), AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        assert result.approved is True
        assert result.tier is EdgeTier.EXCEPTIONAL


class TestNarrativeOnlyIsRejected:
    """§21: "a narrative-only thesis with no deterministic evidence is rejected"."""

    def test_it_cannot_even_be_constructed(self) -> None:
        with pytest.raises(Exception, match="narrative-only"):
            thesis("alpha", selected_features=[])

    def test_no_trade_needs_no_features(self) -> None:
        # §0.6: declining must stay the cheapest thing to express.
        assert thesis("alpha", direction="none", selected_features=[]).direction == "none"


class TestSpecialistAbstentionDoesNotBreakTheWorkflow:
    """§21: "irrelevant specialists can return NOT_APPLICABLE without causing
    workflow failure"."""

    def test_a_round_of_mostly_abstentions_completes(self, policy) -> None:
        snapshot = market()
        consultations = [
            SpecialistConsultation(
                specialist_id="london_breakout_specialist",
                thesis_id="t-alpha",
                verdict=SpecialistVerdict.SUPPORT,
                rationale="compression into the London open is the validated setup",
            ),
            SpecialistConsultation(
                specialist_id="asian_range_sweep_reversal_specialist",
                thesis_id="t-alpha",
                verdict=SpecialistVerdict.NOT_APPLICABLE,
            ),
            SpecialistConsultation(
                specialist_id="london_continuation_specialist",
                thesis_id="t-alpha",
                verdict=SpecialistVerdict.NOT_APPLICABLE,
            ),
        ]
        round_ = consult("t-alpha", snapshot, consultations)
        assert isinstance(round_, ConsultationRound)
        assert len(round_.records) == 3
        assert round_.tier_delta <= 0, "a consultation round may never raise the tier"

    def test_abstention_requires_no_rationale(self) -> None:
        # Demanding a justification for silence is how a bench learns to
        # manufacture signals (§6.3).
        SpecialistConsultation(
            specialist_id="london_continuation_specialist",
            thesis_id="t-alpha",
            verdict=SpecialistVerdict.NOT_APPLICABLE,
        )

    def test_unanimous_abstention_still_completes(self, policy) -> None:
        round_ = consult(
            "t-alpha",
            market(),
            [
                SpecialistConsultation(
                    specialist_id=sid, thesis_id="t-alpha",
                    verdict=SpecialistVerdict.NOT_APPLICABLE,
                )
                for sid in (
                    "london_breakout_specialist",
                    "asian_range_sweep_reversal_specialist",
                    "london_continuation_specialist",
                )
            ],
        )
        assert round_.tier_delta == 0


class TestIndependenceHoldsAcrossTheWorkflow:
    """§21: "Alpha cannot access Beta's first-pass report before submitting its
    own, and vice versa"."""

    def test_neither_trader_can_read_the_other_early(self, policy) -> None:
        packet = MarketStatePacket(market=market(), firm=firm())
        ledger = IndependenceLedger.for_packet(packet)
        ledger.submit(thesis("alpha"), packet.packet_id, IN_SESSION.astimezone(UTC))

        with pytest.raises(PermissionError):
            ledger.read("beta", "alpha")
        with pytest.raises(PermissionError):
            ledger.for_arbiter()

        ledger.submit(thesis("beta"), packet.packet_id, IN_SESSION.astimezone(UTC))
        assert ledger.read("beta", "alpha").trader_id == "alpha"

    def test_arbitration_is_impossible_before_both_lock(self, policy) -> None:
        packet = MarketStatePacket(market=market(), firm=firm())
        ledger = IndependenceLedger.for_packet(packet)
        ledger.submit(thesis("alpha"), packet.packet_id, IN_SESSION.astimezone(UTC))
        with pytest.raises(PermissionError):
            arbitrate(ledger, packet.market, policy)


class TestPressureInvarianceEndToEnd:
    """§21 [A-2]: "evidence classification is bit-identical across firm states
    for the same Market State Packet, including a state far behind any
    aspiration".

    The unit test proves classification does not move. This proves the whole
    §6A chain does not move — including the Arbiter, which sees both theses and
    could in principle be handed firm state by a future orchestrator.
    """

    FIRM_STATES = {
        "flat": dict(),
        "far ahead": dict(closed_equity=D("1000")),
        "far behind, late, and losing": dict(
            closed_equity=D("212"),
            drawdown_state=DrawdownState.RESTRICTED,
            session_realized_loss=D("18.00"),
            weekly_realized_loss=D("31.50"),
            trades_this_session=1,
        ),
        "one trade left": dict(trades_this_session=1),
    }

    def test_the_whole_chain_is_bit_identical(self, policy) -> None:
        snapshot = market()
        baseline = None
        for label, overrides in self.FIRM_STATES.items():
            _, _, decision = run_workflow(
                thesis("alpha"),
                thesis("beta", selected_features=[feature(COMPRESSION, "0.4")]),
                policy,
                snapshot,
                firm(**overrides),
            )
            if baseline is None:
                baseline = decision
                continue
            assert decision == baseline, f"arbitration moved under firm state: {label}"

    def test_the_risk_gate_still_reduces_under_pressure(self, policy, engine) -> None:
        """The other half, and the one that makes the test above meaningful:
        firm state MUST still bite — just at the gate, never at classification.
        A chain that ignored firm state everywhere would pass the invariance
        test and be catastrophically wrong."""
        _, _, decision = run_workflow(
            thesis("alpha"),
            thesis("beta", selected_features=[feature(COMPRESSION, "0.4")]),
            policy,
        )
        candidate = candidate_from(decision)

        calm = engine.evaluate(
            candidate, AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        after_a_loss = engine.evaluate(
            candidate,
            AccountState(
                closed_equity=D("250"), tier_anchor=D("250"), session_realized_loss=D("5.00")
            ),
            GBP_USD, IN_SESSION,
        )
        assert calm.tier is EdgeTier.EXCEPTIONAL
        assert after_a_loss.tier is EdgeTier.HIGH, "§3.4: a session loss disables Exceptional"
        assert after_a_loss.tier_bound_by == "session loss disables Exceptional (§3.4)"


class TestTheClampSurvivesTheHandoff:
    """The wiring question no unit test asks: does a clamped classification
    actually arrive at the risk gate, or is it dropped in between?"""

    def test_a_thin_analog_sample_reaches_the_gate_as_a_refusal(
        self, policy, engine
    ) -> None:
        # Both traders claim E5. The packet supports E2. Nothing about the
        # traders' confidence should survive to the gate.
        thin = market(analog_sample_size=2)
        _, _, decision = run_workflow(
            thesis("alpha"),
            thesis("beta", selected_features=[feature(COMPRESSION, "0.4")]),
            policy,
            thin,
        )
        assert decision.arbitrated is EvidenceClass.E2
        assert decision.selected is not None
        assert decision.selected.evidence_class is EvidenceClass.E5, (
            "the thesis still carries its claim; the record is what was clamped"
        )

        result = engine.evaluate(
            candidate_from(decision), AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        assert result.approved is False
        assert result.thesis_ceiling is EdgeTier.NONE

    def test_a_wide_spread_caps_the_tier_through_the_whole_chain(
        self, policy, engine
    ) -> None:
        # §5.3 gates Exceptional on execution conditions. E5 -> E3 -> STRONG.
        wide = market(spread_pips=D("9.5"))
        _, _, decision = run_workflow(
            thesis("alpha"),
            thesis("beta", selected_features=[feature(COMPRESSION, "0.4")]),
            policy,
            wide,
        )
        assert decision.arbitrated is EvidenceClass.E3
        result = engine.evaluate(
            candidate_from(decision), AccountState(closed_equity=D("250"), tier_anchor=D("250")),
            GBP_USD, IN_SESSION,
        )
        assert result.tier is EdgeTier.STRONG
        assert "thesis classification" in result.tier_bound_by


class TestNoOrderPathFromTheAdaptiveLayer:
    """§0.3 / §2: the adaptive layer recommends; it never executes."""

    def test_no_adaptive_module_reaches_execution(self) -> None:
        import ast
        import pathlib

        offenders = {}
        for name in (
            "adaptive", "packet", "policy", "classification", "independence",
            "arbiter", "agents/bench", "research/analogs", "research/experiments",
        ):
            path = pathlib.Path("src/trading_firm") / f"{name}.py"
            tree = ast.parse(path.read_text())
            reached = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and "execution" in (node.module or ""):
                    reached.add(node.module)
                elif isinstance(node, ast.Import):
                    reached |= {a.name for a in node.names if "execution" in a.name}
            if reached:
                offenders[name] = sorted(reached)
        assert not offenders, (
            f"adaptive-layer modules import the execution package: {offenders}. "
            f"No agent, schema, or classification path may reach the broker (§0.3, §2)"
        )
