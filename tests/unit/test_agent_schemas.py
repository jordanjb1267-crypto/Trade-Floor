"""Agent-output schema tests (§6.5 machine validation; M-1 as a type constraint)."""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from trading_firm.agents import validate_agent_payload
from trading_firm.agents.schemas import ApprovalCard, RegimeLabel

D = Decimal
AWARE = dt.datetime(2026, 7, 29, 9, 0, tzinfo=dt.UTC)


def strategist_payload(**overrides) -> dict:
    payload = {
        "strategy_id": "london_breakout",
        "strategy_version": "0.1.0",
        "instrument": "GBP_USD",
        "direction": "LONG",
        "entry_price": "1.3342",
        "stop_price": "1.3302",
        "target_price": "1.3402",
        "expiration_utc": AWARE.isoformat(),
        "tier_adjustments": [],
    }
    payload.update(overrides)
    return payload


class TestM1TypeConstraint:
    def test_lowering_adjustment_accepted(self) -> None:
        payload = strategist_payload(
            tier_adjustments=[
                {"component": "regime_match", "adjustment": -1, "evidence": "regime mixed"}
            ]
        )
        assessment = validate_agent_payload("strategist_assessment", payload)
        assert assessment.tier_adjustments[0].adjustment == -1

    def test_raising_adjustment_is_unrepresentable(self) -> None:
        # The M-1 rule as a type: an LLM payload that tries to RAISE a tier
        # fails validation before any deterministic code sees it.
        payload = strategist_payload(
            tier_adjustments=[
                {"component": "regime_match", "adjustment": 1, "evidence": "looks great!"}
            ]
        )
        with pytest.raises(ValidationError):
            validate_agent_payload("strategist_assessment", payload)

    def test_unknown_component_rejected(self) -> None:
        payload = strategist_payload(
            tier_adjustments=[
                {"component": "vibes", "adjustment": -1, "evidence": "?"}
            ]
        )
        with pytest.raises(ValidationError):
            validate_agent_payload("strategist_assessment", payload)


class TestStrategistInvariants:
    def test_directional_assessment_requires_stop(self) -> None:
        payload = strategist_payload(stop_price=None)
        with pytest.raises(ValidationError, match="stop"):
            validate_agent_payload("strategist_assessment", payload)

    def test_no_setup_requires_reason(self) -> None:
        payload = strategist_payload(
            direction=None, entry_price=None, stop_price=None, expiration_utc=None
        )
        with pytest.raises(ValidationError, match="reason"):
            validate_agent_payload("strategist_assessment", payload)

    def test_no_setup_with_reason_valid(self) -> None:
        payload = strategist_payload(
            direction=None,
            entry_price=None,
            stop_price=None,
            expiration_utc=None,
            no_setup_reason="Asian range outside filter bounds",
        )
        assessment = validate_agent_payload("strategist_assessment", payload)
        assert assessment.direction is None


class TestContextReport:
    def test_stale_calendar_fails_closed(self) -> None:
        report = validate_agent_payload(
            "context_report",
            {
                "regime": "compression",
                "regime_evidence": "overlapping balance",
                "calendar_state": "stale",
                "events": [],
                "levels": [],
            },
        )
        assert not report.news_state_known

    def test_freshness_doubt_fails_closed(self) -> None:
        report = validate_agent_payload(
            "context_report",
            {
                "regime": "trend",
                "regime_evidence": "impulsive legs",
                "calendar_state": "fresh",
                "events": [],
                "levels": [],
                "data_freshness_doubts": ["calendar older than 6h"],
            },
        )
        assert not report.news_state_known

    def test_naive_event_time_rejected(self) -> None:
        with pytest.raises(ValidationError):
            validate_agent_payload(
                "context_report",
                {
                    "regime": "trend",
                    "regime_evidence": "x",
                    "calendar_state": "fresh",
                    "events": [
                        {
                            "time_utc": "2026-07-30T12:30:00",  # naive
                            "currency": "USD",
                            "impact": "High",
                            "name": "GDP",
                            "blackout": True,
                        }
                    ],
                    "levels": [],
                },
            )


class TestCroVerdict:
    def test_verdict_requires_citations(self) -> None:
        with pytest.raises(ValidationError):
            validate_agent_payload(
                "cro_verdict",
                {"verdict": "NO_OBJECTION", "rule_citations": [], "reasoning": "fine"},
            )


class TestApprovalCard:
    def _card(self) -> ApprovalCard:
        return ApprovalCard(
            instrument="GBP_USD",
            strategy_id="london_breakout",
            strategy_version="0.1.0",
            direction="LONG",
            proposed_entry=D("1.3342"),
            technical_stop=D("1.3302"),
            target=D("1.3402"),
            exit_method="fixed 1.5R or flatten boundary",
            maximum_dollar_loss=D("2.50"),
            position_size_units=595,
            estimated_spread_pips=D("1.9"),
            estimated_commission_usd=D("0"),
            estimated_slippage_pips=D("1.0"),
            expected_net_reward_to_risk=D("1.38"),
            edge_tier="STANDARD",
            edge_components={"expectancy": "baseline research prior"},
            regime=RegimeLabel.COMPRESSION,
            economic_event_status="no high-impact events in window",
            candidate_expiration_utc=AWARE,
            risk_engine_status="approved; binding: tier dollar cap",
            session_loss_capacity_usd=D("25.00"),
            weekly_loss_capacity_usd=D("37.50"),
        )

    def test_card_renders_all_owner_facts(self) -> None:
        rendered = self._card().render_markdown()
        for fragment in ("1.3302", "595 units", "$2.50", "STANDARD", "flatten boundary"):
            assert fragment in rendered

    def test_missing_field_rejected(self) -> None:
        payload = self._card().model_dump()
        del payload["maximum_dollar_loss"]
        with pytest.raises(ValidationError):
            validate_agent_payload("approval_card", payload)


class TestGate:
    def test_unknown_kind_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown agent payload kind"):
            validate_agent_payload("mystery", {})

    def test_post_session_report_taxonomy(self) -> None:
        report = validate_agent_payload(
            "post_session_report",
            {
                "session_date": "2026-07-29",
                "classifications": [
                    {"reference": "trade-1", "label": "lucky_win", "reasoning": "late entry"}
                ],
                "process_findings": [],
                "drift_observations": [],
                "challenger_hypotheses": [
                    {
                        "hypothesis": "wider buffer reduces false breaks",
                        "evidence_required": "50 replay sessions per §12.6",
                    }
                ],
            },
        )
        assert report.classifications[0].label.value == "lucky_win"
