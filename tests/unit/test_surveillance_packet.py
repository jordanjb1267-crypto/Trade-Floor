"""Surveillance packet, candidate references, and unwired preconditions
(§30.5, §30.14). The load-bearing claims: identical checksums for Alpha and
Beta, no field a contradiction packet could travel in, candidate reference
fields excluded from the idempotency hash, and preconditions that can only
refuse."""

import copy
import datetime as dt
from decimal import Decimal

import pytest
import yaml

# Shared canonical state fixture (bare module via pytest pythonpath).
from surveillance_fixtures import state_kwargs

from trading_firm.models import Candidate, Direction
from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    SurveillanceConfig,
    load_surveillance_config,
)
from trading_firm.surveillance.packet import SurveillancePacket, build_packet
from trading_firm.surveillance.preconditions import evaluate_preconditions
from trading_firm.surveillance.schemas import (  # noqa: E402
    MarketStateObject,
)

NOW = dt.datetime(2026, 7, 29, 7, 31, tzinfo=dt.UTC)


def state(**overrides) -> MarketStateObject:
    return MarketStateObject(**state_kwargs(**overrides)).identified()


def packet(market_state: MarketStateObject | None = None, **overrides) -> SurveillancePacket:
    base = dict(
        market_state=market_state or state(),
        prior_material_state_id=None,
        source_health={"oanda_practice": "HEALTHY", "fmp": "UNKNOWN"},
        created_at_utc=NOW,
    )
    base.update(overrides)
    return build_packet(**base)


class TestIdenticalChecksums:
    def test_two_constructions_one_identity(self) -> None:
        # §30.5: provided identically to both senior traders — the checksum
        # IS that property.
        assert packet().packet_id == packet().packet_id

    def test_verify_accepts_the_honest_packet(self) -> None:
        p = packet()
        p.verify(p.packet_id)

    def test_an_altered_packet_is_refused(self) -> None:
        p = packet()
        tampered = p.model_copy(update={"verified_news_item_ids": ("planted-item",)})
        with pytest.raises(ValueError, match="§30.5"):
            tampered.verify(p.packet_id)

    def test_limitations_are_derived_from_data_quality(self) -> None:
        p = packet()
        assert "missing:news" in p.data_limitations
        assert "missing:cross_market" in p.data_limitations


class TestTheContradictionPacketHasNoWhereToTravel:
    def test_no_field_could_carry_position_material(self) -> None:
        """A-3's tightening of the uploaded §30.5 list: firm state in
        classification input is a type error (§5.1), so the packet type has
        no position or contradiction field at all."""
        fields = set(SurveillancePacket.model_fields)
        offending = {
            f
            for f in fields
            if any(word in f for word in ("position", "contradiction", "equity", "pnl"))
        }
        assert offending == set()

    def test_no_narrative_field_exists_either(self) -> None:
        # Do not include another agent's narrative thesis in the first-pass
        # packet (§30.5): there is no thesis/narrative/report field.
        fields = set(SurveillancePacket.model_fields)
        assert not {f for f in fields if "thesis" in f or "narrative" in f}


class TestCandidateReferences:
    def _candidate(self, **overrides) -> Candidate:
        base = dict(
            instrument="GBP_USD",
            strategy_id="london_breakout",
            strategy_version="1.0.0",
            direction=Direction.LONG,
            entry_price=Decimal("1.28500"),
            stop_price=Decimal("1.28250"),
            edge_score=75,
            created_at=NOW,
            expires_at=NOW + dt.timedelta(minutes=30),
            data_fresh=True,
            news_state_known=True,
            stop_broker_compatible=True,
        )
        base.update(overrides)
        return Candidate(**base)

    def test_references_default_to_absent_old_candidates_valid(self) -> None:
        candidate = self._candidate()
        assert candidate.market_state_packet_id is None
        assert candidate.surveillance_report_ids == ()

    def test_references_do_not_move_the_idempotency_hash(self) -> None:
        """§30.14: references, not payload. The same trade idea observed
        under two packets is one candidate — golden-hash regression."""
        bare = self._candidate()
        annotated = self._candidate(
            market_state_id="ms-1",
            market_state_packet_id="pkt-1",
            surveillance_report_ids=("rep-1",),
            material_news_item_ids=("news-1",),
            source_health_snapshot_id="health-1",
            thesis_monitoring_plan_id="plan-1",
        )
        assert bare.content_key() == annotated.content_key()


class TestPreconditionsRefuseOnly:
    @pytest.fixture()
    def enabled(self) -> SurveillanceConfig:
        raw = copy.deepcopy(
            yaml.safe_load(BASE_SURVEILLANCE_CONFIG_PATH.read_text())
        )["surveillance"]
        raw["enabled"] = True
        return SurveillanceConfig.model_validate(raw)

    def test_disabled_division_asserts_nothing(self) -> None:
        config = load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH)
        assert evaluate_preconditions(None, {}, config, NOW) == ()

    def test_a_missing_packet_is_a_refusal_when_enabled(self, enabled) -> None:
        refusals = evaluate_preconditions(None, {}, enabled, NOW)
        assert refusals and "no surveillance packet" in refusals[0]

    def test_an_expired_packet_is_a_refusal(self, enabled) -> None:
        p = packet()
        late = p.market_state.valid_until_utc + dt.timedelta(seconds=1)
        refusals = evaluate_preconditions(p, p.source_health, enabled, late)
        assert any("expired" in r for r in refusals)

    def test_a_failed_source_is_a_refusal(self, enabled) -> None:
        p = packet(source_health={"fmp": "FAILED"})
        refusals = evaluate_preconditions(p, p.source_health, enabled, NOW)
        assert any("FAILED" in r or "failed" in r for r in refusals)

    def test_a_healthy_packet_yields_no_refusals(self, enabled) -> None:
        p = packet()
        assert evaluate_preconditions(p, p.source_health, enabled, NOW) == ()

    def test_the_risk_engine_is_not_wired_to_this_module(self) -> None:
        """§30.14: disabled until paper validation and owner approval — the
        honest form of which is an integration that does not exist. This
        pins it so wiring is a reviewed decision, not a drive-by import."""
        import ast
        from pathlib import Path

        source = Path("src/trading_firm/risk/engine.py").read_text()
        imports = {
            node.module
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert not any("surveillance" in module for module in imports)
