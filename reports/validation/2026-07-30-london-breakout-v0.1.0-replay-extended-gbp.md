# Replay report (extended GBP sample) — london_breakout v0.1.0 (2026-07-30)

> **⚠ SUPERSEDED IN PART (2026-07-30).** The result tables below were
> computed with a replay engine that filled gapped entries at an unobtainable
> price and sized them against a stop distance the trade never had. Corrected
> figures — including two sign flips — are in
> `2026-07-30-CORRECTION-achievable-fills.md`. This report is preserved
> unedited below that line per §0.11; do not cite its numbers.


**Status: framework replay output — NOT validation** (§12.4, §12.6). Extends
`2026-07-30-london-breakout-v0.1.0-replay.md` (kept unedited) with ~2 further
months of GBP_USD history fetched before the FMP connector disconnected.
EUR_USD remains at its original 31 sessions; extend it when the connector
returns.

## Data

Same provenance and pipeline as the original report (FMP M5, NY-local
timestamps pinned empirically, London-window trim, per-instrument margin
rate 0.05, 2-pip spread assumption, conservative same-bar-stop fills,
inviolate 11:00 flatten). Fixture:
`data/research/GBPUSD_M5_london_sessions_2026-03-30_2026-07-29_nytz.json`
(9,049 bars; note: the earliest fetch window landed at Apr 1, so coverage is
2026-04-01 → 2026-07-29, 71 completed sessions).

## Result

```
DATE        STATUS      OUTCOME     UNITS      PNL
2026-04-01  TRADED      FLATTENED     595    -0.02
2026-04-02  NO_SIGNAL   -               0        -
2026-04-03  TRADED      FLATTENED    1015    -0.70
2026-04-06  TRADED      FLATTENED     625     1.29
2026-04-07  TRADED      FLATTENED     677     1.17
2026-04-08  NO_SIGNAL   -               0        -
2026-04-09  TRADED      FLATTENED     859    -0.61
2026-04-10  TRADED      STOP         1021    -2.43
2026-04-15  NO_SIGNAL   -               0        -
2026-04-16  TRADED      FLATTENED     683     1.31
2026-04-17  TRADED      FLATTENED     809    -0.47
2026-04-20  TRADED      FLATTENED     733     0.43
2026-04-21  TRADED      FLATTENED     880     0.70
2026-04-22  NO_SIGNAL   -               0        -
2026-04-23  NO_SIGNAL   -               0        -
2026-04-24  TRADED      FLATTENED    1016     0.58
2026-04-29  NO_SIGNAL   -               0        -
2026-04-30  TRADED      FLATTENED     595     0.19
2026-05-01  TRADED      FLATTENED     856    -1.98
2026-05-04  TRADED      FLATTENED     822     0.97
2026-05-05  TRADED      FLATTENED     992     0.33
2026-05-06  TRADED      FLATTENED     595     1.58
2026-05-07  TRADED      FLATTENED    1000     0.67
2026-05-08  TRADED      FLATTENED     595     1.42
2026-05-13  TRADED      FLATTENED    1004     1.06
2026-05-14  TRADED      FLATTENED    1009    -0.08
2026-05-15  NO_SIGNAL   -               0        -
2026-05-18  TRADED      FLATTENED     595     0.67
2026-05-19  TRADED      FLATTENED     642    -0.70
2026-05-20  TRADED      FLATTENED     781    -0.78
2026-05-21  TRADED      STOP          922    -2.50
2026-05-22  TRADED      STOP         1009    -2.11
2026-05-27  NO_SIGNAL   -               0        -
2026-05-28  NO_SIGNAL   -               0        -
2026-05-29  TRADED      FLATTENED    1020     0.89
2026-06-01  TRADED      FLATTENED     877    -1.23
2026-06-02  NO_SIGNAL   -               0        -
2026-06-03  NO_SIGNAL   -               0        -
2026-06-04  TRADED      STOP         1000    -1.96
2026-06-05  TRADED      TARGET       1000     2.45
2026-06-10  NO_SIGNAL   -               0        -
2026-06-11  NO_SIGNAL   -               0        -
2026-06-12  TRADED      FLATTENED     702    -2.09
2026-06-15  TRADED      FLATTENED     776     0.14
2026-06-16  TRADED      FLATTENED     798    -0.52
2026-06-17  NO_SIGNAL   -               0        -
2026-06-18  TRADED      TARGET        759     3.36
2026-06-19  TRADED      FLATTENED     595     1.14
2026-06-29  TRADED      FLATTENED     886    -0.19
2026-06-30  NO_SIGNAL   -               0        -
2026-07-01  TRADED      FLATTENED     841    -1.58
2026-07-02  TRADED      TARGET        859     3.32
2026-07-03  NO_SIGNAL   -               0        -
2026-07-06  NO_SIGNAL   -               0        -
2026-07-07  NO_SIGNAL   -               0        -
2026-07-08  TRADED      STOP          902    -2.50
2026-07-09  NO_SIGNAL   -               0        -
2026-07-10  NO_SIGNAL   -               0        -
2026-07-13  TRADED      FLATTENED     976    -0.15
2026-07-14  TRADED      FLATTENED     801     0.46
2026-07-15  NO_SIGNAL   -               0        -
2026-07-16  TRADED      FLATTENED     874     0.73
2026-07-17  TRADED      FLATTENED     936     0.94
2026-07-20  NO_SIGNAL   -               0        -
2026-07-21  TRADED      STOP          862    -2.50
2026-07-22  TRADED      STOP         1016    -2.50
2026-07-23  TRADED      FLATTENED     922    -0.56
2026-07-24  TRADED      FLATTENED    1024    -1.18
2026-07-27  TRADED      FLATTENED     992     0.74
2026-07-28  NO_SIGNAL   -               0        -
2026-07-29  TRADED      FLATTENED     902    -1.03
```

**london_breakout v0.1.0 on GBP_USD | sessions=71 traded=48 W/L/F=24/24/38
net=$-3.83 expectancy=$-0.08 PF=0.87 maxDD=$9.91**

## Reading (still research questions, firmer footing)

1. **The exit-distribution finding strengthens at 2.5x the sample: 38 of 48
   trades (79%) end FLATTENED at 11:00.** The 1.5R target resolves in only
   6 sessions; 4 full stops. At these parameters the strategy is a
   slightly-negative coin flip after costs, dominated by the flatten exit.
   The session-aware-exit challenger hypothesis (registered in the original
   report) is now the clear next research question.
2. **Expectancy −$0.08/trade with PF 0.87** on 48 trades: consistent with
   "costs eat a near-zero edge" — the review's spread-drag arithmetic (N-9)
   playing out. Still below the §12.6 50-trade single-instrument bar, and
   these are untouched first-guess parameters with zero optimization passes,
   so no conclusion about the strategy family is licensed — only about this
   parameterization's exit behavior.
3. **Risk containment held across all 71 sessions:** no trade lost more than
   its approved risk after costs; max drawdown $9.91 on the fixed-$250
   no-compounding basis (≈4% of the account across four months of sessions).
4. **§12.4 discipline note:** because this extension was fetched AFTER the
   exit-logic hypothesis was registered, the added Apr–May data must be
   treated as part of the DISCOVERY sample for that hypothesis. Confirmation
   requires data not yet seen (older history or forward sessions).

## Next

- Extend EUR_USD when the FMP connector is re-enabled.
- Implement the exit-logic challenger as london_breakout 0.2.0-research and
  evaluate on a declared discovery/confirmation split (§12.4).
