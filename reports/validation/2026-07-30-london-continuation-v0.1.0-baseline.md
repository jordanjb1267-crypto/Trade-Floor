# Baseline replay — london_continuation v0.1.0 (2026-07-30)

> **⚠ SUPERSEDED IN PART (2026-07-30).** The result tables below were
> computed with a replay engine that filled gapped entries at an unobtainable
> price and sized them against a stop distance the trade never had. Corrected
> figures — including two sign flips — are in
> `2026-07-30-CORRECTION-achievable-fills.md`. This report is preserved
> unedited below that line per §0.11; do not cite its numbers.


**Status: framework replay output — NOT validation** (§12.4, §12.6).
Third and final research-queue strategy, at first-guess parameters declared
in the manifest BEFORE any replay ran. Single parameter set, no selection
event → no §12.4 test spent. Recorded as the strategy's single first look.

## Design: a one-variable experiment

Rules (`strategies/continuation.py`) are deliberately IDENTICAL to champion
london_breakout mechanics — same triggers, stops, targets, range regime
filter — plus exactly one filter: trade only in the direction of the prior
session's validated London-window structure (|net move 08:00→11:00| ≥ 20
pips, from the new no-lookahead `structure_features_v1`). The session's
first breakout decides; a counter-trend first breakout is no-trade. Any
performance difference vs the champion is attributable to the filter alone.

Fail-closed plumbing: no prior-session data → no features → no candidates
(§0.10). Structure targets and explicit pullback-extreme invalidation are
deferred to future pre-registered research — v0.1.0 tests trend alignment
and nothing else.

## Data & results

Canonical broker-feed fixtures, measured per-bar costs:

| | sessions | traded | W/L/F | net | expectancy | PF | maxDD |
|---|---|---|---|---|---|---|---|
| GBP_USD (Mar 30–Jul 29) | 105 | 9 | 6/3/9 | +$1.94 | +$0.22 | 1.72 | $2.00 |
| EUR_USD (Jun 8–Jul 29) | 45 | 2 | 2/0/2 | +$0.30 | +$0.15 | — | $0.00 |

Champion reference on the identical GBP data: 65 trades, net −$9.02, PF 0.78.

## Reading (discovery data only)

- **The filter is severe**: it keeps 9 of the champion's 65 GBP trades
  (~14%) — alignment plus the 20-pip validation bar removes almost every
  session. Those 9 went 6W/3L with the smallest drawdown of any baseline
  ($2.00).
- **9 trades decides nothing.** The same-day feed-noise finding showed
  sign flips at 3× this sample. PF 1.72 on 9 trades is a hypothesis
  ("trend-aligned breakouts are the good breakouts"), not a result. It is
  registered here as exactly that for future pre-registered testing on new
  data.
- EUR remains structurally starved of setups across all three strategies —
  an instrument-level observation, not a parameter-tuning invitation.
- 11 total trades sit far below every §12.6 threshold. No promotion
  implications (§0.5); status stays `research`, permissions false.

## Multiple-testing ledger

One first look, now spent. The GBP sample's cumulative ledger: 1 breakout
baseline + 3 exit-variant tests (rejected) + 1 sweep-reversal first look +
this. Any future variant of ANY of these strategies on this data counts
the full ledger (§12.4); the clean path is post-July data.
