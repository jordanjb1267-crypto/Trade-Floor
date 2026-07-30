"""Historical replay engine (§12.2), research environment only.

Replays sessions bar-by-bar through the REAL pipeline: feature engine →
strategy rules → deterministic risk engine → sizing engine → simulated
execution with spread costs → mandatory flatten. No orders exist here
(§12.1); fills are simulated conservatively (same-bar stop priority).

Metrics from this engine are framework outputs, NOT validation: §12.4 and
the §12.6 minimum-evidence table govern what any number here may be used for.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from trading_firm.config import FirmConfig
from trading_firm.features.engine import prior_session_structure, session_features
from trading_firm.market_data.bars import Bar, BarSeries
from trading_firm.market_data.spreads import SpreadSeries
from trading_firm.models import (
    AccountState,
    Candidate,
    Direction,
    InstrumentSpec,
    cents,
)
from trading_firm.risk.engine import RiskEngine
from trading_firm.sessions.clock import SessionClock
from trading_firm.sizing.engine import size_position
from trading_firm.strategies.breakout import BreakoutParams, first_breakout_signal
from trading_firm.strategies.continuation import ContinuationParams, first_continuation_signal
from trading_firm.strategies.manifest import StrategyManifest
from trading_firm.strategies.sweep_reversal import (
    SweepReversalParams,
    first_sweep_reversal_signal,
)

CENT = Decimal("0.01")
RESEARCH_BASELINE_SCORE = 75  # fixed Standard-tier baseline until §12.6 calibration exists


class SessionStatus(enum.Enum):
    TRADED = "TRADED"
    NO_FEATURES = "NO_FEATURES"
    NO_SIGNAL = "NO_SIGNAL"
    REJECTED = "REJECTED"


class TradeOutcome(enum.Enum):
    TARGET = "TARGET"
    STOP = "STOP"
    FLATTENED = "FLATTENED"


@dataclass(frozen=True)
class ExitPolicy:
    """Challenger exit parameterization (§15). None anywhere = champion v0.1.0.

    breakeven_trigger_r moves the stop to the entry (trigger) price once the
    trade has run that many R in favor — stops only ever TIGHTEN (§0.7:
    stop widening is unrepresentable here). Activation applies from the NEXT
    bar, which is pessimistic for the challenger (within-bar sequence is
    unknowable on M5 data)."""

    target_r: Decimal = Decimal("1.5")
    breakeven_trigger_r: Decimal | None = None


@dataclass(frozen=True)
class SessionTrade:
    direction: Direction
    units: int
    entry_ts: dt.datetime
    entry_price: Decimal
    exit_ts: dt.datetime
    exit_price: Decimal
    outcome: TradeOutcome
    allowed_risk_usd: Decimal
    pnl_usd: Decimal


@dataclass(frozen=True)
class SessionOutcome:
    session_date: dt.date
    status: SessionStatus
    trade: SessionTrade | None = None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReplayReport:
    strategy_id: str
    strategy_version: str
    feature_version: str
    sessions: int
    traded: int
    wins: int
    losses: int
    flat_exits: int
    net_pnl_usd: Decimal
    gross_win_usd: Decimal
    gross_loss_usd: Decimal
    max_drawdown_usd: Decimal
    outcomes: tuple[SessionOutcome, ...]
    disclaimer: str = (
        "Framework replay output — NOT validation. §12.4 anti-overfitting protocol and "
        "§12.6 minimum-evidence thresholds govern any use of these numbers."
    )

    @property
    def expectancy_usd(self) -> Decimal | None:
        if self.traded == 0:
            return None
        return (self.net_pnl_usd / self.traded).quantize(CENT)

    @property
    def profit_factor(self) -> Decimal | None:
        if self.gross_loss_usd == 0:
            return None
        return (self.gross_win_usd / self.gross_loss_usd).quantize(CENT)


def tradeable_session_dates(series: BarSeries, clock: SessionClock) -> list[dt.date]:
    """London dates whose Asian window actually holds data.

    A date whose [00:00, asian_range_final) window is empty can never produce
    features, so counting it inflates the denominator of every published rate
    (§12.4 honest reporting). The emptiness test is calendar-agnostic — it
    drops the Sunday 22:00 London reopen bars and market holidays alike,
    without hard-coding weekday numbers.
    """
    london = ZoneInfo("Europe/London")
    dates = sorted({bar.ts.astimezone(london).date() for bar in series.bars})
    return [
        day
        for day in dates
        if series.between(
            dt.datetime.combine(day, dt.time(0, 0), tzinfo=london),
            clock.boundaries(day)["asian_range_final"],
        )
    ]


def _pnl(direction: Direction, units: int, entry: Decimal, exit_price: Decimal) -> Decimal:
    move = exit_price - entry if direction is Direction.LONG else entry - exit_price
    return (units * move).quantize(CENT, rounding=ROUND_FLOOR)  # conservative both ways


def replay_session(
    series: BarSeries,
    session_date: dt.date,
    *,
    config: FirmConfig,
    clock: SessionClock,
    engine: RiskEngine,
    manifest: StrategyManifest,
    spec: InstrumentSpec,
    equity: Decimal = Decimal("250"),
    spread_pips: Decimal = Decimal("2.0"),
    exit_policy: ExitPolicy | None = None,
    spreads: SpreadSeries | None = None,
) -> SessionOutcome:
    features = session_features(series, session_date, clock, spec.pip_size)
    if features is None:
        return SessionOutcome(session_date, SessionStatus.NO_FEATURES)

    boundaries = clock.boundaries(session_date)
    active_bars = series.between(boundaries["activation"], boundaries["entry_cutoff"])
    if manifest.strategy_id == "london_breakout":
        signal = first_breakout_signal(
            features,
            active_bars,
            BreakoutParams.from_manifest_params(manifest.params),
            spec.pip_size,
        )
    elif manifest.strategy_id == "asian_range_sweep_reversal":
        signal = first_sweep_reversal_signal(
            features,
            active_bars,
            SweepReversalParams.from_manifest_params(manifest.params),
            spec.pip_size,
        )
    elif manifest.strategy_id == "london_continuation":
        structure = prior_session_structure(series, session_date, clock, spec.pip_size)
        if structure is None:  # no prior-session data: fail closed (§0.10)
            return SessionOutcome(session_date, SessionStatus.NO_FEATURES)
        signal = first_continuation_signal(
            features,
            structure,
            active_bars,
            ContinuationParams.from_manifest_params(manifest.params),
            spec.pip_size,
        )
    else:
        raise NotImplementedError(f"no replay rules implemented for {manifest.strategy_id}")
    if signal is None:
        return SessionOutcome(session_date, SessionStatus.NO_SIGNAL)

    trigger_bar = signal.triggered_by
    is_long = signal.direction is Direction.LONG

    # §14 gate sees the true FILL moment. A bar's close lands at ts+granularity,
    # so an at-close entry on the last bar before the cutoff actually fills AT
    # the cutoff — outside the half-open [activation, entry_cutoff) window.
    # Feeding this moment to the risk engine makes the existing expiry/window
    # gates reject it visibly instead of silently accepting a late entry.
    granularity = dt.timedelta(minutes=series.granularity_minutes)
    entry_moment = (
        trigger_bar.ts + granularity
        if getattr(signal, "entry_at_close", False)
        else trigger_bar.ts
    )

    # ACHIEVABLE FILL (adversarial-review finding, 2026-07-30).
    # A stop-order entry cannot fill at a price the market has already passed.
    # The Asian range freezes at 07:30 but entries open at 08:00, so when the
    # break happens inside that gap the first ACTIVE bar OPENS beyond the
    # trigger: the earliest obtainable price is that open, not the stale
    # trigger. Clamping to the adverse side of the trigger bar's open models
    # the gap fill a broker would actually give. Entering the risk engine with
    # this price (not the trigger) is what keeps §3 sizing honest: the real
    # stop distance is wider, so the approved size is smaller — previously the
    # engine sized a stop distance the trade never had, breaching the risk cap.
    # Strategies entering AT a bar's close (entry_at_close) are unaffected:
    # the close is by definition a traded price of that bar.
    if getattr(signal, "entry_at_close", False):
        entry_mid = signal.trigger_price
    else:
        entry_mid = (
            max(signal.trigger_price, trigger_bar.open)
            if is_long
            else min(signal.trigger_price, trigger_bar.open)
        )
    # Note: no "gapped past the stop" branch is needed. Clamping moves the
    # entry only in the ADVERSE direction (up for a long, down for a short),
    # i.e. always away from the stop, which every strategy places on the
    # opposite side of the trigger. Entry therefore stays on the correct side
    # of invalidation for any gap size; a gap large enough to be untradeable
    # instead widens the stop distance until sizing rejects it. Pinned by
    # tests/unit/test_replay_fills.py::test_entry_stays_on_the_live_side_of_the_stop.

    candidate = Candidate(
        instrument=spec.name,
        strategy_id=manifest.strategy_id,
        strategy_version=manifest.version,
        direction=signal.direction,
        entry_price=entry_mid,
        stop_price=signal.stop_price,
        edge_score=RESEARCH_BASELINE_SCORE,
        created_at=entry_moment,
        expires_at=boundaries["entry_cutoff"],
        data_fresh=True,
        news_state_known=True,
        stop_broker_compatible=True,
    )
    account = AccountState(closed_equity=equity, tier_anchor=Decimal("250"))
    decision = engine.evaluate(candidate, account, spec, entry_moment)
    if not decision.approved:
        return SessionOutcome(session_date, SessionStatus.REJECTED, reasons=decision.reasons)

    sizing = size_position(
        candidate,
        spec,
        decision.allowed_risk_usd,
        closed_equity=equity,
        margin_utilization_cap_fraction=Decimal(
            str(config.risk.margin_utilization_cap_fraction)
        ),
        spread_pips_assumption=spread_pips,
    )
    if not sizing.approved:
        return SessionOutcome(session_date, SessionStatus.REJECTED, reasons=sizing.reasons)

    # Costs: sizing always uses the flat ASSUMPTION (the live engine cannot
    # know future spreads); execution charges the MEASURED per-bar spread
    # when a SpreadSeries is supplied — so replay surfaces exactly how far
    # realized losses drift from approved risk when spreads move.
    def half_spread(bar: Bar) -> Decimal:
        if spreads is None:
            return spread_pips / 2 * spec.pip_size
        return spreads.at(bar.ts) / 2

    entry_exec = (
        entry_mid + half_spread(trigger_bar) if is_long else entry_mid - half_spread(trigger_bar)
    )

    def exit_exec(bar: Bar, mid: Decimal) -> Decimal:
        return mid - half_spread(bar) if is_long else mid + half_spread(bar)

    # Conservative simulation: same-bar stop priority, then remaining bars
    # until the flatten boundary — which is inviolate (§14, F-5). Strategies
    # entering AT a bar's close (entry_at_close) start exit checks on the
    # NEXT bar: pre-entry price action inside the trigger bar must never
    # exit the trade.
    manage_bars = [
        bar
        for bar in series.between(trigger_bar.ts, boundaries["flatten"])
        if bar.ts >= trigger_bar.ts
    ]
    if getattr(signal, "entry_at_close", False):
        manage_bars = [bar for bar in manage_bars if bar.ts > trigger_bar.ts]
    risk_distance = candidate.stop_distance()
    if exit_policy is None:
        target_price = signal.target_price
        breakeven_level: Decimal | None = None
    else:
        # R-multiples anchor on the ACHIEVABLE entry, not the trigger: R is
        # defined by the risk actually taken (risk_distance already derives
        # from the candidate's clamped entry).
        target_price = (
            entry_mid + exit_policy.target_r * risk_distance
            if is_long
            else entry_mid - exit_policy.target_r * risk_distance
        )
        breakeven_level = (
            (
                entry_mid + exit_policy.breakeven_trigger_r * risk_distance
                if is_long
                else entry_mid - exit_policy.breakeven_trigger_r * risk_distance
            )
            if exit_policy.breakeven_trigger_r is not None
            else None
        )

    current_stop = signal.stop_price
    exit_price: Decimal | None = None
    exit_ts: dt.datetime | None = None
    outcome: TradeOutcome | None = None
    for bar in manage_bars:
        stop_hit = bar.low <= current_stop if is_long else bar.high >= current_stop
        target_hit = bar.high >= target_price if is_long else bar.low <= target_price
        if stop_hit:  # worst case first
            exit_price, exit_ts, outcome = (
                exit_exec(bar, current_stop),
                bar.ts,
                TradeOutcome.STOP,
            )
            break
        if target_hit:
            exit_price, exit_ts, outcome = (
                exit_exec(bar, target_price),
                bar.ts,
                TradeOutcome.TARGET,
            )
            break
        # Trail AFTER exit checks: activation applies from the next bar
        # (pessimistic for the challenger). Stops only tighten (§0.7).
        if breakeven_level is not None:
            trail_armed = bar.high >= breakeven_level if is_long else bar.low <= breakeven_level
            if trail_armed:
                new_stop = entry_mid  # breakeven = where the trade actually got in
                tighter = max if is_long else min
                current_stop = tighter(current_stop, new_stop)
                breakeven_level = None
    if outcome is None:
        # entry on the final pre-flatten bar leaves no later bars: flatten
        # against the trigger bar itself.
        last_bar = manage_bars[-1] if manage_bars else trigger_bar
        exit_price, exit_ts, outcome = (
            exit_exec(last_bar, last_bar.close),
            boundaries["flatten"],
            TradeOutcome.FLATTENED,
        )

    trade = SessionTrade(
        direction=signal.direction,
        units=sizing.units,
        entry_ts=entry_moment,
        entry_price=entry_exec,
        exit_ts=exit_ts,
        exit_price=exit_price,
        outcome=outcome,
        allowed_risk_usd=decision.allowed_risk_usd,
        pnl_usd=_pnl(signal.direction, sizing.units, entry_exec, exit_price),
    )
    return SessionOutcome(session_date, SessionStatus.TRADED, trade=trade)


def replay_range(
    series: BarSeries,
    session_dates: list[dt.date],
    *,
    config: FirmConfig,
    clock: SessionClock,
    engine: RiskEngine,
    manifest: StrategyManifest,
    spec: InstrumentSpec,
    equity: Decimal = Decimal("250"),
    spread_pips: Decimal = Decimal("2.0"),
    exit_policy: ExitPolicy | None = None,
    spreads: SpreadSeries | None = None,
) -> ReplayReport:
    outcomes = [
        replay_session(
            series,
            day,
            config=config,
            clock=clock,
            engine=engine,
            manifest=manifest,
            spec=spec,
            equity=equity,
            spread_pips=spread_pips,
            exit_policy=exit_policy,
            spreads=spreads,
        )
        for day in session_dates
    ]
    trades = [o.trade for o in outcomes if o.trade is not None]
    wins = [t for t in trades if t.pnl_usd > 0]
    losses = [t for t in trades if t.pnl_usd < 0]

    running = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for trade in trades:
        running += trade.pnl_usd
        peak = max(peak, running)
        max_dd = max(max_dd, peak - running)

    return ReplayReport(
        strategy_id=manifest.strategy_id,
        strategy_version=manifest.version,
        feature_version=manifest.features[0] if manifest.features else "",
        sessions=len(outcomes),
        traded=len(trades),
        wins=len(wins),
        losses=len(losses),
        flat_exits=sum(1 for t in trades if t.outcome is TradeOutcome.FLATTENED),
        net_pnl_usd=cents(sum((t.pnl_usd for t in trades), Decimal("0"))),
        gross_win_usd=cents(sum((t.pnl_usd for t in wins), Decimal("0"))),
        gross_loss_usd=cents(-sum((t.pnl_usd for t in losses), Decimal("0"))),
        max_drawdown_usd=cents(max_dd),
        outcomes=tuple(outcomes),
    )
