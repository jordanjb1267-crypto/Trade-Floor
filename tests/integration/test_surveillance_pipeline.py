"""End-to-end surveillance pipelines (§30.17 integration rows): bars to
Market State, calendar to blackout, news to verification to alertability,
identical packets for Alpha and Beta, candidate references, and the durable
outbox on a migrated database."""

import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from tests.unit.test_replay import build_series
from trading_firm.agents import validate_agent_payload
from trading_firm.audit.db import apply_migrations, connect
from trading_firm.config import BASE_CONFIG_PATH, load_config
from trading_firm.models import Candidate, Direction
from trading_firm.sessions import SessionClock
from trading_firm.surveillance.config import (
    BASE_SURVEILLANCE_CONFIG_PATH,
    load_surveillance_config,
)
from trading_firm.surveillance.events import EventType, SurveillanceEvent, record_event
from trading_firm.surveillance.macro.blackout import blackout_active
from trading_firm.surveillance.news.normalization import normalize_item
from trading_firm.surveillance.news.verification import state_for_sources
from trading_firm.surveillance.packet import build_packet
from trading_firm.surveillance.schemas import DataQualityStatus, VerificationState
from trading_firm.surveillance.sources.fmp_calendar import normalize_calendar
from trading_firm.surveillance.state_builder import build_market_state

LONDON = ZoneInfo("Europe/London")
DAY = dt.date(2026, 7, 29)
AS_OF = dt.datetime.combine(DAY, dt.time(9, 0), tzinfo=LONDON)


@pytest.fixture(scope="module")
def clock() -> SessionClock:
    return SessionClock(load_config(BASE_CONFIG_PATH).session)


@pytest.fixture(scope="module")
def state(clock):
    return build_market_state(
        instrument="GBP_USD",
        session_date=DAY,
        clock=clock,
        series=build_series(),
        spreads=None,
        permits=lambda fid: fid.startswith("session_features_v1."),
        config=load_surveillance_config(BASE_SURVEILLANCE_CONFIG_PATH),
        configuration_version="integration-test",
        as_of=AS_OF,
    )


class TestBarsToMarketState:
    def test_the_full_chain_produces_a_verified_state(self, state) -> None:
        state.verify(state.market_state_id)
        assert state.session_state.phase == "ACTIVE"
        # The replay fixture's WIN day breaks the Asian high before 09:00.
        assert state.technical_state.structure_state.startswith("break:")


class TestIdenticalPacketsForAlphaAndBeta:
    def test_one_construction_per_trader_identical_ids(self, state) -> None:
        alpha = build_packet(
            market_state=state,
            prior_material_state_id=None,
            source_health={"oanda_practice": "HEALTHY"},
            created_at_utc=AS_OF,
        )
        beta = build_packet(
            market_state=state,
            prior_material_state_id=None,
            source_health={"oanda_practice": "HEALTHY"},
            created_at_utc=AS_OF,
        )
        assert alpha.packet_id == beta.packet_id
        beta.verify(alpha.packet_id)


class TestCandidateReferencesRoundTrip:
    def test_annotated_candidate_survives_the_db(self, state, tmp_path) -> None:
        packet = build_packet(
            market_state=state,
            prior_material_state_id=None,
            source_health={},
            created_at_utc=AS_OF,
        )
        candidate = Candidate(
            instrument="GBP_USD",
            strategy_id="london_breakout",
            strategy_version="1.0.0",
            direction=Direction.LONG,
            entry_price=Decimal("1.3342"),
            stop_price=Decimal("1.3302"),
            edge_score=75,
            created_at=AS_OF,
            expires_at=AS_OF + dt.timedelta(minutes=30),
            data_fresh=True,
            news_state_known=True,
            stop_broker_compatible=True,
            market_state_id=state.market_state_id,
            market_state_packet_id=packet.packet_id,
        )
        conn = connect(tmp_path / "db.sqlite")
        apply_migrations(conn)
        conn.execute(
            "INSERT INTO candidates (created_at, expires_at, instrument, strategy_id, "
            "strategy_version, direction, entry_price, stop_price, edge_score, "
            "payload_json, market_state_packet_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                candidate.created_at.isoformat(),
                candidate.expires_at.isoformat(),
                candidate.instrument,
                candidate.strategy_id,
                candidate.strategy_version,
                candidate.direction.value,
                str(candidate.entry_price),
                str(candidate.stop_price),
                candidate.edge_score,
                "{}",
                candidate.market_state_packet_id,
            ),
        )
        conn.commit()
        stored = conn.execute(
            "SELECT market_state_packet_id FROM candidates"
        ).fetchone()[0]
        assert stored == packet.packet_id
        conn.close()


class TestCalendarToBlackout:
    def test_a_high_impact_release_gates_its_currencies(self) -> None:
        events = normalize_calendar(
            [{"date": "2026-07-29 08:30:00", "currency": "GBP", "event": "BoE", "impact": "High"}],
            source_tz="UTC",
        )
        during = dt.datetime(2026, 7, 29, 8, 20, tzinfo=dt.UTC)
        assert blackout_active(events, "GBP_USD", during)
        assert not blackout_active(events, "EUR_USD", during)


class TestNewsToAlertability:
    def test_ingest_verify_and_gate(self) -> None:
        item = normalize_item(
            headline="BoE holds rates; statement cites persistent services inflation",
            source_id="fmp.news",
            publication_time_utc=dt.datetime(2026, 7, 29, 11, 5, tzinfo=dt.UTC),
            ingested_at_utc=dt.datetime(2026, 7, 29, 11, 6, tzinfo=dt.UTC),
        )
        single = state_for_sources(frozenset({"fmp.news"}), frozenset())
        assert single is VerificationState.SINGLE_SOURCE
        review = validate_agent_payload(
            "news_relevance_review",
            dict(
                review_id="rev-1",
                news_item_id=item.news_item_id,
                verification_state=single.value,
                event_time_utc=None,
                publication_time_utc=item.publication_time_utc,
                potentially_affected_instruments=["GBP_USD"],
                materiality="MEDIUM",
                already_known_or_recirculated=False,
                conflicting_facts=[],
                pricing_assessment="UNKNOWN",
                recommended_state="WATCH",
            ),
        )
        assert not review.can_support_material_alert, (
            "a single-provider item cannot drive a MATERIAL alert (§30.8)"
        )


class TestDurableOutboxOnAMigratedDatabase:
    def test_the_coordinator_shaped_event_persists(self, state, tmp_path) -> None:
        conn = connect(tmp_path / "db.sqlite")
        apply_migrations(conn)
        event = SurveillanceEvent(
            event_id="evt-integration-1",
            event_type=EventType.MARKET_STATE_PUBLISHED,
            schema_version="surveillance_event_v1",
            event_time_utc=state.as_of_utc,
            ingestion_time_utc=state.as_of_utc,
            producer="surveillance.coordinator",
            instrument_scope=[state.instrument_id],
            correlation_id=f"{DAY}.activation",
            configuration_version="integration-test",
            data_quality=DataQualityStatus.DEGRADED,
            payload={"market_state_id": state.market_state_id},
        )
        record_event(conn, event)
        row = conn.execute(
            "SELECT event_type, data_quality, payload_checksum FROM surveillance_events"
        ).fetchone()
        assert row == ("market_state.published", "DEGRADED", event.payload_checksum)
        conn.close()
