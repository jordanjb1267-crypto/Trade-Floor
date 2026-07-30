#!/usr/bin/env python3
"""Session-aware-exit challenger evaluation (§12.4 pre-registered protocol).

Hypothesis (registered 2026-07-30, decision log): london_breakout v0.1.0's
dominant FLATTENED exit share (79% on the extended GBP sample) means exit
logic, not entry logic, is the binding constraint; a session-aware exit
(nearer target and/or breakeven trail) may capture what the 11:00 flatten
gives back.

Pre-registered BEFORE any variant was run on data (multiple-testing record):

- Variants (exactly three; no others may be added after seeing results):
    V1  target 1.5R + breakeven trail armed at +1.0R
    V2  target 1.0R, no trail
    V3  target 1.0R + breakeven trail armed at +0.5R
- Data: the extended GBP_USD fixture only. EUR_USD is EXCLUDED (its 31
  sessions were already inspected for the v0.1.0 baseline report).
- Split: discovery = session dates < 2026-06-16; confirmation = dates
  >= 2026-06-16. The split date was declared when the extended fixture
  was assembled, before any challenger replay.
- Selection rule (mechanical): a variant is ELIGIBLE iff its DISCOVERY
  window shows trades >= 20 AND expectancy > $0. Among eligible variants,
  the one with the highest profit factor is the sole winner; ONLY the
  winner is evaluated on the confirmation window. If no variant is
  eligible, the hypothesis is REJECTED at these parameters and no
  confirmation replay is run.
- Caveat recorded up front: the confirmation window was previously seen by
  the v0.1.0 baseline replays, so a pass here is WEAK confirmation at
  best. §12.6 minimum-evidence thresholds are far from met either way —
  nothing in this script's output is validation or grounds for promotion.

Usage:
    python3 scripts/run_challenger_eval.py \
        data/research/GBPUSD_M5_london_sessions_2026-03-30_2026-07-29_nytz.json
"""

import datetime as dt
import json
import sys
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from trading_firm.config import BASE_CONFIG_PATH, load_config  # noqa: E402
from trading_firm.market_data import from_fmp_rows  # noqa: E402
from trading_firm.models import InstrumentSpec  # noqa: E402
from trading_firm.research import ExitPolicy, ReplayReport, replay_range  # noqa: E402
from trading_firm.risk import RiskEngine  # noqa: E402
from trading_firm.sessions import SessionClock  # noqa: E402
from trading_firm.strategies import load_manifests  # noqa: E402

SOURCE_TZ = "America/New_York"
LONDON = ZoneInfo("Europe/London")
NY = ZoneInfo(SOURCE_TZ)

SPLIT_DATE = dt.date(2026, 6, 16)  # pre-declared; do not move after seeing results
MIN_DISCOVERY_TRADES = 20

VARIANTS: dict[str, ExitPolicy] = {
    "V1 1.5R + BE@1.0R": ExitPolicy(
        target_r=Decimal("1.5"), breakeven_trigger_r=Decimal("1.0")
    ),
    "V2 1.0R": ExitPolicy(target_r=Decimal("1.0")),
    "V3 1.0R + BE@0.5R": ExitPolicy(
        target_r=Decimal("1.0"), breakeven_trigger_r=Decimal("0.5")
    ),
}


def summarize(label: str, report: ReplayReport) -> None:
    print(
        f"  {label:<22} sessions={report.sessions:>3} traded={report.traded:>3} "
        f"W/L/F={report.wins}/{report.losses}/{report.flat_exits} "
        f"net=${report.net_pnl_usd} exp=${report.expectancy_usd} "
        f"PF={report.profit_factor} maxDD=${report.max_drawdown_usd}"
    )


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    fixture = Path(sys.argv[1])

    rows = json.loads(fixture.read_text())
    series = from_fmp_rows(
        rows, instrument="GBP_USD", granularity_minutes=5, source_tz=SOURCE_TZ
    )
    print(f"GBP_USD: {len(series.bars)} bars, {len(series.quality_events)} quality events")

    config = load_config(BASE_CONFIG_PATH)
    clock = SessionClock(config.session)
    engine = RiskEngine(config, clock)
    manifest = load_manifests(
        BASE_CONFIG_PATH.parents[1] / "research" / "strategies"
    )["london_breakout"]
    spec = InstrumentSpec(name="GBP_USD", margin_rate=Decimal("0.05"))

    session_dates = sorted(
        {
            dt.datetime.fromisoformat(r["date"]).replace(tzinfo=NY).astimezone(LONDON).date()
            for r in rows
        }
    )
    last_bar_london = series.bars[-1].ts.astimezone(LONDON)
    session_dates = [
        d for d in session_dates
        if d < last_bar_london.date()
        or last_bar_london.time() >= clock.boundaries(d)["flatten"].timetz().replace(tzinfo=None)
    ]
    discovery = [d for d in session_dates if d < SPLIT_DATE]
    confirmation = [d for d in session_dates if d >= SPLIT_DATE]
    print(
        f"split @ {SPLIT_DATE}: discovery={len(discovery)} sessions "
        f"({discovery[0]}..{discovery[-1]}), confirmation={len(confirmation)} "
        f"({confirmation[0]}..{confirmation[-1]})"
    )

    def run(dates: list[dt.date], policy: ExitPolicy | None) -> ReplayReport:
        return replay_range(
            series,
            dates,
            config=config,
            clock=clock,
            engine=engine,
            manifest=manifest,
            spec=spec,
            exit_policy=policy,
        )

    print("\nDISCOVERY window (champion baseline shown for reference only):")
    summarize("champion v0.1.0", run(discovery, None))
    discovery_reports = {name: run(discovery, policy) for name, policy in VARIANTS.items()}
    for name, report in discovery_reports.items():
        summarize(name, report)

    eligible = {
        name: r
        for name, r in discovery_reports.items()
        if r.traded >= MIN_DISCOVERY_TRADES
        and r.expectancy_usd is not None
        and r.expectancy_usd > 0
    }
    print(
        f"\nselection rule: trades>={MIN_DISCOVERY_TRADES} AND expectancy>0, "
        f"then max PF | eligible: {sorted(eligible) or 'NONE'}"
    )
    if not eligible:
        print(
            "VERDICT: no variant eligible on discovery — hypothesis REJECTED at "
            "these parameters. No confirmation replay run (§12.4)."
        )
        return 0

    winner = max(
        eligible, key=lambda name: eligible[name].profit_factor or Decimal("0")
    )
    print(f"winner on discovery: {winner} — sole variant advanced to confirmation")

    print("\nCONFIRMATION window (winner only; champion baseline for reference):")
    summarize("champion v0.1.0", run(confirmation, None))
    summarize(winner, run(confirmation, VARIANTS[winner]))

    print(
        "\nCaveat: confirmation window was previously seen by the v0.1.0 baseline "
        "replays — treat any pass as WEAK confirmation. NOT validation (§12.4, "
        "§12.6); no promotion implications (§0.5)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
