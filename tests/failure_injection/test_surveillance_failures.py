"""Surveillance failure injection (§30.17 rows: one source fails, all
sources fail, conflicting headlines, calendar revision, duplicate news
storm, clock drift). Each scenario asserts the fail-closed shape — the
failure is representable, named, and never reads as confirmation."""

import datetime as dt
from decimal import Decimal

import pytest

from trading_firm.surveillance.cross_market.divergence import evaluate
from trading_firm.surveillance.cross_market.relationships import RegisteredRelationship
from trading_firm.surveillance.freshness import (
    ComponentStatus,
    FreshnessThresholds,
    component_status,
)
from trading_firm.surveillance.macro.blackout import blackout_active
from trading_firm.surveillance.macro.calendar import overdue
from trading_firm.surveillance.news.normalization import (
    is_recirculation,
    normalize_item,
)
from trading_firm.surveillance.news.relevance import potentially_affected
from trading_firm.surveillance.news.verification import (
    state_for_sources,
    transition,
)
from trading_firm.surveillance.schemas import NewsPollState, VerificationState
from trading_firm.surveillance.source_health import (
    FAILURES_TO_FAIL,
    PollOutcome,
    SourceHealth,
    SourceHealthState,
    advance,
    news_poll_state,
)
from trading_firm.surveillance.sources.fmp_calendar import (
    normalize_calendar,
    revision_rows,
)

NOW = dt.datetime(2026, 7, 29, 8, 0, tzinfo=dt.UTC)


class TestOneSourceFails:
    def test_a_single_timeout_degrades_and_reads_poll_failed(self) -> None:
        health = advance(SourceHealth("fmp.news"), PollOutcome.TIMEOUT, NOW)
        assert health.state is SourceHealthState.DEGRADED
        assert news_poll_state(health, items_found=0) is NewsPollState.POLL_FAILED

    def test_recovery_is_one_good_poll(self) -> None:
        health = advance(SourceHealth("fmp.news"), PollOutcome.TIMEOUT, NOW)
        health = advance(health, PollOutcome.OK_EMPTY, NOW)
        assert health.state is SourceHealthState.HEALTHY
        assert health.consecutive_failures == 0


class TestAllSourcesFail:
    def test_consecutive_failures_reach_failed_and_source_unavailable(self) -> None:
        health = SourceHealth("fmp.news")
        for _ in range(FAILURES_TO_FAIL):
            health = advance(health, PollOutcome.ERROR, NOW)
        assert health.state is SourceHealthState.FAILED
        assert news_poll_state(health, items_found=0) is NewsPollState.SOURCE_UNAVAILABLE

    def test_unavailable_is_never_confirming(self) -> None:
        health = SourceHealth("fmp.news")
        for _ in range(FAILURES_TO_FAIL):
            health = advance(health, PollOutcome.ERROR, NOW)
        state = news_poll_state(health, items_found=0)
        assert not state.is_confirming, (
            "the absence of fetched news does not prove the absence of relevant "
            "news (§30.8)"
        )

    def test_an_unpolled_source_is_unknown_not_empty(self) -> None:
        assert (
            news_poll_state(SourceHealth("fmp.news"), items_found=0)
            is NewsPollState.UNKNOWN
        )


class TestConflictingHeadlines:
    def test_conflict_is_reachable_and_sticky_until_resolved(self) -> None:
        state = state_for_sources(frozenset({"fmp.news"}), frozenset())
        assert state is VerificationState.SINGLE_SOURCE
        state = transition(state, VerificationState.CONFLICTING)
        # A conflicted item cannot jump straight back to SINGLE_SOURCE.
        with pytest.raises(ValueError, match="quietly"):
            transition(state, VerificationState.SINGLE_SOURCE)

    def test_retraction_is_terminal(self) -> None:
        state = transition(VerificationState.SINGLE_SOURCE, VerificationState.RETRACTED)
        with pytest.raises(ValueError, match="superseding"):
            transition(state, VerificationState.CORROBORATED)

    def test_one_provider_repeating_itself_is_not_corroboration(self) -> None:
        assert (
            state_for_sources(frozenset({"fmp.news"}), frozenset())
            is VerificationState.SINGLE_SOURCE
        )
        assert (
            state_for_sources(frozenset({"fmp.news", "official.boe"}), frozenset())
            is VerificationState.CORROBORATED
        )


class TestDuplicateNewsStorm:
    def test_a_storm_collapses_to_one_item(self) -> None:
        seen: dict[str, dt.datetime] = {}
        headlines = [
            "GBP rallies on BoE decision!",
            "gbp RALLIES on boe decision",
            "GBP rallies on BoE decision…",
        ]
        fresh = 0
        for minute, headline in enumerate(headlines):
            item = normalize_item(
                headline=headline,
                source_id="fmp.news",
                publication_time_utc=NOW + dt.timedelta(minutes=minute),
                ingested_at_utc=NOW + dt.timedelta(minutes=minute),
            )
            if not is_recirculation(item, seen, window_seconds=900):
                fresh += 1
                seen.setdefault(item.content_hash, item.publication_time_utc)
        assert fresh == 1

    def test_relevance_prefilter_drops_untraded_currencies(self) -> None:
        assert potentially_affected(
            "Yen surges as BoJ intervenes", ("GBP_USD", "EUR_USD")
        ) == ()
        assert potentially_affected(
            "Sterling slides after BoE holds", ("GBP_USD", "EUR_USD")
        ) == ("GBP_USD",)


class TestCalendarRevision:
    ROWS = [{"date": "2026-07-29 13:30:00", "currency": "USD", "event": "CPI", "impact": "High"}]

    def test_normalization_requires_an_explicit_zone(self) -> None:
        est = normalize_calendar(self.ROWS, source_tz="America/New_York")
        utc = normalize_calendar(self.ROWS, source_tz="UTC")
        assert est[0].scheduled_utc != utc[0].scheduled_utc
        assert est[0].scheduled_utc == dt.datetime(2026, 7, 29, 17, 30, tzinfo=dt.UTC)

    def test_a_revised_time_is_a_new_version_of_the_same_event(self) -> None:
        first = normalize_calendar(self.ROWS, source_tz="UTC")
        revised_rows = [dict(self.ROWS[0], date="2026-07-29 14:00:00")]
        revised = normalize_calendar(revised_rows, source_tz="UTC")
        assert first[0].event_id == revised[0].event_id, "same event, new time"
        rows = revision_rows(
            revised, {first[0].event_id: 1}, "fmp", NOW, names={}
        )
        assert rows[0]["version"] == 2

    def test_an_overdue_event_is_named_not_silent(self) -> None:
        events = normalize_calendar(self.ROWS, source_tz="UTC")
        late = dt.datetime(2026, 7, 29, 13, 45, tzinfo=dt.UTC)
        assert overdue(events, frozenset(), late) == events
        assert overdue(events, frozenset({events[0].event_id}), late) == []

    def test_blackout_window_around_a_high_impact_event(self) -> None:
        events = normalize_calendar(self.ROWS, source_tz="UTC")
        inside = dt.datetime(2026, 7, 29, 13, 10, tzinfo=dt.UTC)
        outside = dt.datetime(2026, 7, 29, 12, 30, tzinfo=dt.UTC)
        assert blackout_active(events, "GBP_USD", inside)
        assert not blackout_active(events, "GBP_USD", outside)
        assert not blackout_active(events, "EUR_GBP", inside), "USD event, no USD leg"


class TestClockDrift:
    def test_a_future_timestamp_beyond_skew_reads_stale(self) -> None:
        thresholds = FreshnessThresholds({"prices": 900})
        from_the_future = NOW + dt.timedelta(minutes=10)
        assert (
            component_status(from_the_future, "prices", thresholds, NOW)
            is ComponentStatus.STALE
        )

    def test_small_ntp_jitter_is_tolerated(self) -> None:
        thresholds = FreshnessThresholds({"prices": 900})
        slightly_ahead = NOW + dt.timedelta(seconds=30)
        assert (
            component_status(slightly_ahead, "prices", thresholds, NOW)
            is ComponentStatus.FRESH
        )


class TestCrossMarketLag:
    def test_underobserved_windows_return_no_verdict(self) -> None:
        rel = RegisteredRelationship("gbpusd_eurusd", "GBP_USD", "EUR_USD", "co_moving")
        finding = evaluate(rel, [Decimal("0.1")] * 3, [Decimal("0.1")] * 3)
        assert finding is None, "an absent measurement is not a divergence (§30.1)"

    def test_a_broken_comovement_is_a_divergence(self) -> None:
        rel = RegisteredRelationship("gbpusd_eurusd", "GBP_USD", "EUR_USD", "co_moving")
        a = [Decimal(x) for x in ("0.1", "0.2", "-0.1", "0.3", "0.1", "0.2")]
        b = [Decimal(x) for x in ("-0.1", "-0.2", "0.1", "-0.3", "-0.1", "-0.2")]
        finding = evaluate(rel, a, b)
        assert finding is not None and finding.diverging

    def test_an_intact_relationship_is_not(self) -> None:
        rel = RegisteredRelationship("gbpusd_eurusd", "GBP_USD", "EUR_USD", "co_moving")
        a = [Decimal(x) for x in ("0.1", "0.2", "-0.1", "0.3", "0.1", "0.2")]
        finding = evaluate(rel, a, list(a))
        assert finding is not None and not finding.diverging


class TestMisalignedInputsFailLoudly:
    def test_unaligned_return_series_raise(self) -> None:
        rel = RegisteredRelationship("x", "A_B", "C_D", "co_moving")
        with pytest.raises(ValueError, match="aligned"):
            evaluate(rel, [Decimal("0.1")] * 6, [Decimal("0.1")] * 5)

    def test_calendar_rows_missing_fields_raise(self) -> None:
        with pytest.raises(ValueError, match="§30.8"):
            normalize_calendar([{"event": "CPI"}], source_tz="UTC")

    def test_naive_news_timestamps_raise(self) -> None:
        with pytest.raises(ValueError, match="aware"):
            normalize_item(
                headline="x y z",
                source_id="fmp.news",
                publication_time_utc=NOW.replace(tzinfo=None),
                ingested_at_utc=NOW,
            )
