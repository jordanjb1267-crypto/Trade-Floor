"""Pressure invariance and evidence ceilings (§5.1, §5.2, §6.6 / A-2; §21).

§21 lists "pressure invariance of evidence classification" as a required unit
test and "evidence classification is bit-identical across firm states for the
same Market State Packet, including a state far behind any aspiration" as an
acceptance criterion. Both live here.

The point of the invariance test is not that the current code happens to pass
it — it does, trivially, because no classification signature admits a
FirmSnapshot. The point is that it FAILS the day someone widens one, which is
exactly the change A-2 exists to prevent.
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
from trading_firm.classification import classify, evidence_ceiling
from trading_firm.models import DrawdownState
from trading_firm.packet import FirmSnapshot, MarketSnapshot, MarketStatePacket
from trading_firm.policy import load_adaptive_policy

UTC = dt.UTC
POLICY_PATH = "config/research/adaptive_policy.yaml"
APPROVED_FEATURE = "session_features_v1.asian_width_pips"


@pytest.fixture(scope="module")
def policy():
    return load_adaptive_policy(POLICY_PATH)


def market(**overrides) -> MarketSnapshot:
    base = dict(
        instrument="GBP_USD",
        observed_at=dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC),
        session_date=dt.date(2026, 7, 30),
        session_phase="briefing",
        regime="compression",
        volatility_state="low",
        bid=Decimal("1.28450"),
        ask=Decimal("1.28462"),
        spread_pips=Decimal("1.2"),
        feature_version="session_features_v1",
        features={APPROVED_FEATURE: Decimal("38")},
        analog_sample_size=40,
    )
    base.update(overrides)
    return MarketSnapshot(**base)


def thesis(**overrides) -> AdaptiveThesis:
    base = dict(
        thesis_id="t-001",
        trader_id="alpha",
        timestamp_utc=dt.datetime(2026, 7, 30, 7, 40, tzinfo=UTC),
        instrument="GBP_USD",
        direction="long",
        market_state=MarketState(
            regime="compression", volatility_state="low", session_phase="briefing"
        ),
        selected_features=[
            SelectedFeature(
                feature_id=APPROVED_FEATURE,
                observed_value=Decimal("38"),
                relevance="inside the 15-60 tradeable band",
            )
        ],
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
        estimated_costs=Decimal("0.02"),
        expected_value_basis="validated playbook expectancy",
        confidence_calibration_reference="calibration_v1",
    )
    base.update(overrides)
    return AdaptiveThesis(**base)


# --- the firm states the invariance property is quantified over -------------
# Deliberately includes the state the owner's framing described: far behind an
# aspiration, late, and losing. If desperation could reach classification, this
# is the row that would move.
FIRM_STATES = {
    "flat and normal": FirmSnapshot(
        closed_equity=Decimal("250"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.NORMAL,
    ),
    "far ahead": FirmSnapshot(
        closed_equity=Decimal("1000"),
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
    "two losses today": FirmSnapshot(
        closed_equity=Decimal("232"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.CAUTION,
        session_realized_loss=Decimal("18.00"),
        trades_this_session=2,
    ),
    "degraded and unreconciled": FirmSnapshot(
        closed_equity=Decimal("250"),
        tier_anchor=Decimal("250"),
        drawdown_state=DrawdownState.SHADOW,
        reconciled=False,
        broker_healthy=False,
        open_positions=1,
    ),
}


class TestPressureInvariance:
    """§21 unit test: "pressure invariance of evidence classification"."""

    def test_classification_is_bit_identical_across_firm_states(self, policy) -> None:
        snapshot = market()
        t = thesis()
        baseline = classify(t, snapshot, policy)

        for label, firm in FIRM_STATES.items():
            packet = MarketStatePacket(market=snapshot, firm=firm)
            # The packet the trader received carries firm state; classification
            # reads the market half and only the market half.
            result = classify(t, packet.market, policy)
            assert result == baseline, f"classification moved under firm state: {label}"
            assert result.max_edge_tier == baseline.max_edge_tier, label

    def test_market_id_is_stable_while_packet_id_moves(self) -> None:
        # §6A: both traders must receive the same packet. A-2: the identity
        # classification is reproducible under is the MARKET half alone.
        snapshot = market()
        ids = {
            label: MarketStatePacket(market=snapshot, firm=firm)
            for label, firm in FIRM_STATES.items()
        }
        assert len({p.market_id for p in ids.values()}) == 1
        assert len({p.packet_id for p in ids.values()}) == len(FIRM_STATES)

    def test_classification_signature_admits_no_firm_state(self) -> None:
        """The structural guarantee, asserted rather than assumed.

        A-2 requires that reading firm state during classification be a type
        error, not a review finding. If someone widens either signature to take
        a FirmSnapshot, this fails immediately and names the amendment.
        """
        import inspect

        for fn in (classify, evidence_ceiling):
            annotations = [p.annotation for p in inspect.signature(fn).parameters.values()]
            rendered = " ".join(str(a) for a in annotations)
            assert "FirmSnapshot" not in rendered, (
                f"{fn.__name__} accepts firm state: classification must be a pure "
                f"function of the Market State Packet's market half (A-2, §5.1)"
            )

    def test_classification_module_never_references_firm_state(self) -> None:
        """Closes the aliased-import gap the signature check alone leaves open.

        `from ... import FirmSnapshot as FS` would render as 'FS' in a signature
        and slip past the check above. Requiring the module to not import or
        name the type at all is both stronger and simpler to reason about: the
        classifier cannot read what it cannot reach.
        """
        import ast
        import pathlib

        import trading_firm.classification as module

        source = pathlib.Path(module.__file__).read_text()
        tree = ast.parse(source)
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported |= {alias.name for alias in node.names}
            elif isinstance(node, ast.Import):
                imported |= {alias.name for alias in node.names}
        assert "FirmSnapshot" not in imported, (
            "classification imports FirmSnapshot: firm state must not be reachable "
            "from classification at all (A-2, §5.1)"
        )
        # Belt and braces — catches a fully-qualified `packet.FirmSnapshot(...)`
        # reference that no import statement would reveal.
        code_lines = [
            line for line in source.splitlines() if not line.lstrip().startswith("#")
        ]
        body = "\n".join(code_lines).split('"""')
        executable = "".join(body[::2])  # drop docstrings, keep code
        assert "FirmSnapshot" not in executable, (
            "classification code references FirmSnapshot (A-2, §5.1)"
        )


class TestEvidenceCeiling:
    def test_clean_packet_supports_e5(self, policy) -> None:
        ceiling, _ = evidence_ceiling(market(), policy)
        assert ceiling is EvidenceClass.E5

    @pytest.mark.parametrize(
        "override",
        [
            {"data_fresh": False},
            {"bars_complete": False},
            {"calendar_state_known": False},
        ],
    )
    def test_missing_or_stale_data_is_e0(self, policy, override) -> None:
        # §5.2 E0 and §0.10 fail-closed.
        ceiling, reasons = evidence_ceiling(market(**override), policy)
        assert ceiling is EvidenceClass.E0
        assert any("E0" in r for r in reasons)

    def test_unapproved_feature_caps_at_e1(self, policy) -> None:
        snapshot = market(features={"made_up_v9.vibe_index": Decimal("7")})
        ceiling, reasons = evidence_ceiling(snapshot, policy)
        assert ceiling is EvidenceClass.E1
        assert any("outside the approved registry" in r for r in reasons)

    def test_thin_analog_sample_caps_at_e2(self, policy) -> None:
        ceiling, reasons = evidence_ceiling(market(analog_sample_size=4), policy)
        assert ceiling is EvidenceClass.E2
        assert any("analog sample" in r for r in reasons)

    def test_wide_spread_caps_at_e3(self, policy) -> None:
        # §5.3: execution conditions gate Exceptional.
        ceiling, _ = evidence_ceiling(market(spread_pips=Decimal("9.5")), policy)
        assert ceiling is EvidenceClass.E3

    def test_high_impact_event_caps_at_e3(self, policy) -> None:
        ceiling, _ = evidence_ceiling(market(high_impact_event_active=True), policy)
        assert ceiling is EvidenceClass.E3

    def test_strictest_cap_wins(self, policy) -> None:
        snapshot = market(
            analog_sample_size=1,  # E2
            spread_pips=Decimal("9.5"),  # E3
            high_impact_event_active=True,  # E3
        )
        ceiling, reasons = evidence_ceiling(snapshot, policy)
        assert ceiling is EvidenceClass.E2
        assert len(reasons) == 3, "every cap is reported, not just the binding one"


class TestClaimReconciliation:
    def test_over_claim_is_clamped_not_honored(self, policy) -> None:
        # A persuasive E5 claim on a thin analog sample buys nothing.
        result = classify(thesis(), market(analog_sample_size=2), policy)
        assert result.claimed is EvidenceClass.E5
        assert result.ceiling is EvidenceClass.E2
        assert result.effective is EvidenceClass.E2
        assert result.over_claim is True
        assert result.under_claim is False
        assert result.max_edge_tier == 0, "E2 authorizes no live tier (§5.2)"

    def test_under_claim_is_recorded_not_penalized_in_session(self, policy) -> None:
        # A-2: the whole point. E5 evidence, E3 filed — previously invisible.
        result = classify(thesis(evidence_class=EvidenceClass.E3), market(), policy)
        assert result.ceiling is EvidenceClass.E5
        assert result.under_claim is True
        assert result.effective is EvidenceClass.E3, (
            "the under-claim is recorded for post-session scoring; it must NOT be "
            "silently upgraded in-session (A-2 bound: scoring is post-session only)"
        )
        assert any("under-claim recorded" in r for r in result.reasons)

    def test_exact_claim_is_neither(self, policy) -> None:
        result = classify(thesis(evidence_class=EvidenceClass.E5), market(), policy)
        assert result.over_claim is False and result.under_claim is False
        assert result.max_edge_tier == 4

    def test_novelty_still_binds_below_evidence(self, policy) -> None:
        # §6.8 survives A-2 untouched: N1 cannot reach Exceptional at any evidence.
        result = classify(thesis(novelty_class=NoveltyClass.N1), market(), policy)
        assert result.effective is EvidenceClass.E5
        assert result.max_edge_tier == 3

    def test_n2_cannot_trade_live_however_clean_the_packet(self, policy) -> None:
        result = classify(thesis(novelty_class=NoveltyClass.N2), market(), policy)
        assert result.ceiling is EvidenceClass.E5
        assert result.max_edge_tier == 0

    def test_result_carries_the_market_id_it_was_computed_from(self, policy) -> None:
        snapshot = market()
        assert classify(thesis(), snapshot, policy).market_id == snapshot.checksum


def test_module_is_pressure_blind_under_the_shared_guard() -> None:
    """A-2 (§5.1) via `tests/a2_guard.py`.

    The local guards in this file check the single name `FirmSnapshot`. An
    adversarial review defeated that by importing `AccountState` instead, so
    the shared guard checks the whole firm-state vocabulary. Both run: the
    local one gives a module-specific message, this one is the real check.
    """
    import importlib

    from a2_guard import assert_pressure_blind

    assert_pressure_blind(importlib.import_module("trading_firm.classification"))


class TestCeilingBoundaries:
    """Exact boundaries, found by mutation: `>` -> `>=` and `<` -> `<=` both
    survived the whole 837-test suite, so neither limit was pinned anywhere.

    Both directions matter. Capping one pip early is a silent, permanent
    down-bias on every tier the firm can reach — the invisible under-sizing A-2
    exists to make visible — and capping one pip late admits a spread §5.3
    excludes.
    """

    def test_a_spread_exactly_at_the_limit_is_within_limits(self, policy) -> None:
        # §5.3 says spread must be "within limits". At the limit is within it.
        at_limit = market(spread_pips=policy.max_spread_pips)
        ceiling, _ = evidence_ceiling(at_limit, policy)
        assert ceiling is EvidenceClass.E5, (
            "a spread exactly at the configured limit is inside it; capping here "
            "under-classifies every session that lands on the boundary"
        )

    def test_a_spread_one_step_above_the_limit_caps(self, policy) -> None:
        over = market(spread_pips=policy.max_spread_pips + Decimal("0.01"))
        ceiling, _ = evidence_ceiling(over, policy)
        assert ceiling is EvidenceClass.E3

    def test_an_analog_sample_exactly_at_the_minimum_is_sufficient(self, policy) -> None:
        # §12.6 states a MINIMUM sample. Meeting the minimum satisfies it.
        exact = market(analog_sample_size=policy.required_analog_sample_size)
        ceiling, _ = evidence_ceiling(exact, policy)
        assert ceiling is EvidenceClass.E5, (
            "requiring one more than the ratified minimum silently raises the §12.6 "
            "threshold this firm ratified"
        )

    def test_one_below_the_minimum_caps(self, policy) -> None:
        short = market(analog_sample_size=policy.required_analog_sample_size - 1)
        ceiling, reasons = evidence_ceiling(short, policy)
        assert ceiling is EvidenceClass.E2
        assert any("analog sample" in r for r in reasons)
