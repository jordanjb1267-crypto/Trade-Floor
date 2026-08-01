"""The three §30.13 agent output kinds, through the one gate (§6.5).

The load-bearing test is the type-level direction ban: §30.13 says
trade_direction must remain null at the surveillance-alert layer, and the
§30.17 acceptance row says no alert contains an executable direction. Here
that is a validation error, the TierAdjustment le=0 move."""

import datetime as dt

import pytest
from pydantic import ValidationError

from trading_firm.agents import validate_agent_payload

NOW = dt.datetime(2026, 7, 29, 8, 0, tzinfo=dt.UTC)


def alert_payload(**overrides) -> dict:
    base = dict(
        alert_id="alert-1",
        market_state_id="ms-1",
        severity="MATERIAL",
        instrument_ids=["GBP_USD"],
        change_type="structure.break_detected",
        what_changed="Asian high broken and accepted above",
        supporting_observation_ids=["obs-1"],
        conflicting_observation_ids=[],
        data_quality_status="HEALTHY",
        suggested_recipients=["senior_traders"],
        trade_direction=None,
        expires_at_utc=NOW + dt.timedelta(minutes=30),
    )
    base.update(overrides)
    return base


class TestOpportunityAlert:
    def test_a_valid_alert_passes_the_gate(self) -> None:
        alert = validate_agent_payload("opportunity_alert", alert_payload())
        assert alert.trade_direction is None

    @pytest.mark.parametrize("direction", ["BUY", "SELL", "long", "short", 1, -1])
    def test_an_executable_direction_is_a_type_error(self, direction) -> None:
        with pytest.raises(ValidationError):
            validate_agent_payload("opportunity_alert", alert_payload(trade_direction=direction))

    def test_an_unknown_severity_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_agent_payload("opportunity_alert", alert_payload(severity="URGENT_BUY"))

    def test_naive_expiry_rejected(self) -> None:
        with pytest.raises(ValidationError, match="naive"):
            validate_agent_payload(
                "opportunity_alert",
                alert_payload(expires_at_utc=NOW.replace(tzinfo=None)),
            )


class TestSituationReport:
    def test_round_trips_the_gate(self) -> None:
        report = validate_agent_payload(
            "surveillance_situation_report",
            dict(
                report_id="rep-1",
                market_state_id="ms-1",
                agent_id="technical-surveillance-lead",
                agent_version="1.0.0",
                generated_at_utc=NOW,
                overall_state="NORMAL",
                material_changes=[],
                active_market_drivers=[],
                technical_observations=["compression persists"],
                macro_observations=[],
                news_observations=[],
                cross_market_observations=[],
                contradictions=[],
                data_limitations=["news domain disabled"],
                specialists_to_consult=[],
                escalation_required=False,
                expiration_utc=NOW + dt.timedelta(hours=1),
            ),
        )
        assert report.overall_state == "NORMAL"

    def test_extra_fields_rejected_everywhere(self) -> None:
        with pytest.raises(ValidationError):
            validate_agent_payload(
                "surveillance_situation_report",
                {"report_id": "rep-1", "recommended_position_size": 2},
            )


class TestNewsRelevanceReview:
    def _payload(self, **overrides) -> dict:
        base = dict(
            review_id="rev-1",
            news_item_id="news-1",
            verification_state="SINGLE_SOURCE",
            event_time_utc=None,
            publication_time_utc=NOW,
            potentially_affected_instruments=["GBP_USD"],
            materiality="MEDIUM",
            already_known_or_recirculated=False,
            conflicting_facts=[],
            pricing_assessment="UNKNOWN",
            recommended_state="WATCH",
        )
        base.update(overrides)
        return base

    def test_round_trips_the_gate(self) -> None:
        review = validate_agent_payload("news_relevance_review", self._payload())
        assert review.recommended_state == "WATCH"

    def test_single_source_cannot_support_a_material_alert(self) -> None:
        review = validate_agent_payload("news_relevance_review", self._payload())
        assert not review.can_support_material_alert

    @pytest.mark.parametrize("state", ["CORROBORATED", "OFFICIAL_SOURCE"])
    def test_verified_states_can(self, state) -> None:
        review = validate_agent_payload(
            "news_relevance_review", self._payload(verification_state=state)
        )
        assert review.can_support_material_alert

    def test_there_is_no_trade_this_news_state(self) -> None:
        with pytest.raises(ValidationError):
            validate_agent_payload(
                "news_relevance_review", self._payload(recommended_state="ENTER_LONG")
            )
