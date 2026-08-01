"""Source-health state machine (§30.8, §30.16).

Every registered source carries a health state that only poll outcomes move.
The machine is deliberately asymmetric: one good poll restores HEALTHY, but
it takes `FAILURES_TO_FAIL` consecutive failures to reach FAILED — a single
timeout is weather, a run of them is an outage. The mapping into the §30.8
missing-news states is where "the absence of fetched news does not prove the
absence of relevant news" becomes code: only a HEALTHY empty poll ever reads
as no-news.

Pure transitions over frozen values; persistence is the caller's job.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass, replace

from trading_firm.surveillance.schemas import NewsPollState

FAILURES_TO_FAIL = 3


class SourceHealthState(enum.StrEnum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


class PollOutcome(enum.StrEnum):
    OK_ITEMS = "ok_items"
    OK_EMPTY = "ok_empty"
    TIMEOUT = "timeout"
    ERROR = "error"
    AUTH_FAILURE = "auth_failure"
    RATE_LIMITED = "rate_limited"

    @property
    def succeeded(self) -> bool:
        return self in (PollOutcome.OK_ITEMS, PollOutcome.OK_EMPTY)


@dataclass(frozen=True)
class SourceHealth:
    source_id: str
    state: SourceHealthState = SourceHealthState.UNKNOWN
    consecutive_failures: int = 0
    last_success_utc: dt.datetime | None = None
    last_outcome: PollOutcome | None = None


def advance(
    health: SourceHealth, outcome: PollOutcome, at: dt.datetime
) -> SourceHealth:
    if at.tzinfo is None:
        raise ValueError("poll timestamps must be timezone-aware (§30.4, C-2)")
    if outcome.succeeded:
        return replace(
            health,
            state=SourceHealthState.HEALTHY,
            consecutive_failures=0,
            last_success_utc=at,
            last_outcome=outcome,
        )
    failures = health.consecutive_failures + 1
    state = (
        SourceHealthState.FAILED
        if failures >= FAILURES_TO_FAIL
        else SourceHealthState.DEGRADED
    )
    return replace(
        health,
        state=state,
        consecutive_failures=failures,
        last_outcome=outcome,
    )


def news_poll_state(health: SourceHealth, items_found: int) -> NewsPollState:
    """§30.8: which of the six missing-news states this poll cycle earned.

    Only a HEALTHY source that genuinely returned nothing reads as no-news;
    every failure mode keeps its own name, so downstream code can never
    collapse "we couldn't look" into "there was nothing to see".
    """
    if health.state is SourceHealthState.UNKNOWN:
        return NewsPollState.UNKNOWN
    if health.last_outcome is not None and not health.last_outcome.succeeded:
        if health.state is SourceHealthState.FAILED:
            return NewsPollState.SOURCE_UNAVAILABLE
        return NewsPollState.POLL_FAILED
    if items_found > 0:
        return NewsPollState.VERIFICATION_PENDING
    return NewsPollState.SOURCE_HEALTHY_NO_ITEMS
