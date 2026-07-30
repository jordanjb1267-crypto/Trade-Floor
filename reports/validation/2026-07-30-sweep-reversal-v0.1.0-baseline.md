# Baseline replay — asian_range_sweep_reversal v0.1.0 (2026-07-30)

> **⚠ SUPERSEDED IN PART (2026-07-30).** Two independent defects affect the
> tables below. (1) **P&L:** the replay engine filled gapped entries at an
> unobtainable price and sized them against a stop distance the trade never
> had — corrected figures, including two sign flips, are in
> `2026-07-30-CORRECTION-achievable-fills.md`. (2) **Denominators:** any
> `sessions` count below is inflated ~19% because it included Sunday-reopen
> dates that can never produce features — the honest counts are **88** (GBP,
> Mar 30–Jul 29) and **38** (EUR, Jun 8–Jul 29), not 105/45. Coverage holes in
> the FMP fixture (15 absent weekdays) are documented in
> `data/research/README.md`. Per §12.7(6) a report that overstates its own
> evidence is a §12.4 violation even where its P&L is right. This report is
> preserved unedited below that line per §0.11; do not cite its numbers.


**Status: framework replay output — NOT validation** (§12.4, §12.6).
First replay of the research queue's second strategy, at first-guess
parameters declared in the manifest BEFORE any replay ran. Single parameter
set, no selection event → no §12.4 test spent (same precedent as the
london_breakout v0.1.0 baseline).

## Rules (deterministic translation, strategies/sweep_reversal.py)

A sweep 3–25 pips beyond an Asian-range extreme that closes back inside the
range within 3 bars becomes the session's single signal, entered at the
re-entry close, stopped 2 pips beyond the sweep extreme (never widened or
tightened into invalidation — a required stop over 40 pips is no-setup),
targeting the opposing range extreme. Deeper sweeps and slow re-entries are
acceptance (no setup). Same 15–60-pip range regime filter as the champion.
Both sides resolving on one bar is ambiguous: no trade (§0.6).

Engine addition: `entry_at_close` signals begin exit checks on the bar
AFTER entry — pre-entry price action inside the trigger bar can never exit
the trade (unit-tested). The F-1 margin overlay binds these tighter-stop
trades before the tier does: the engineered 16-pip-stop golden case is
margin-capped to $1.79 approved risk, and its stopped trade loses exactly
that (tests/unit/test_sweep_reversal.py).

## Data & results

Canonical broker-feed fixtures, measured per-bar spread costs
(`python3 scripts/run_replay.py <fixture> <pair> <margin> asian_range_sweep_reversal`):

| | sessions | traded | W/L/F | net | expectancy | PF | maxDD |
|---|---|---|---|---|---|---|---|
| GBP_USD (Mar 30–Jul 29) | 105 | 27 | 12/15/6 | +$1.48 | +$0.05 | 1.11 | $5.36 |
| EUR_USD (Jun 8–Jul 29) | 45 | 3 | 1/2/1 | −$3.28 | −$1.09 | 0.24 | $4.34 |

## Reading (discovery data only)

- **The exit structure differs from the champion in kind.** Flatten share
  is 22% (6/27) vs the breakout's 79%: the opposing-liquidity target is
  reachable within the session, so trades resolve. Whatever else is true,
  this strategy's results are *decision-driven*, not clock-driven.
- **GBP's +$1.48 over 27 trades is noise-sized.** The feed-robustness
  finding (same day) showed sign flips at larger samples than this;
  PF 1.11 on 27 trades claims nothing.
- **EUR generates almost no setups** (3 in 45 sessions) at these
  thresholds — the tighter EUR ranges rarely sweep 3+ pips and return.
  A parameter question for future pre-registered research, not something
  to tune now (§12.4).
- 30 total trades sit far below every §12.6 threshold. No promotion
  implications (§0.5); status stays `research`, permissions stay false.

## Multiple-testing note

This baseline is recorded as the strategy's single first-look. Any variant
or parameter change is a new pre-registered test starting from a ledger of
1 prior look at this data (plus the 3 spent exit-variant tests recorded
against the GBP sample for london_breakout).
