# Replay report — london_breakout v0.1.0 on real M5 data (2026-07-30)

> **⚠ SUPERSEDED IN PART (2026-07-30).** The result tables below were
> computed with a replay engine that filled gapped entries at an unobtainable
> price and sized them against a stop distance the trade never had. Corrected
> figures — including two sign flips — are in
> `2026-07-30-CORRECTION-achievable-fills.md`. This report is preserved
> unedited below that line per §0.11; do not cite its numbers.


**Status: framework replay output — NOT validation.** The §12.4
anti-overfitting protocol and the §12.6 minimum-evidence table govern any
use of these numbers. 30 trades total across both instruments sits below
every §12.6 threshold; nothing here qualifies any tier, informs promotion,
or implies profitability (§0.5).

## Data

| | |
|---|---|
| Source | FMP intraday 5-min bars via the licensed connector (fetched 2026-07-30) |
| Timezone | Naive NY-local timestamps, pinned empirically (newest bar 3 min old under America/New_York; hours wrong under all alternatives) |
| Coverage | 31 completed London sessions per pair, 2026-06-10 → 2026-07-29 |
| Quality | 4,029 bars/pair after dedup + London-window trim; 25 quality events/pair (intraday gaps flagged by the normalizer; none fatal) |
| Prices | Mid-only (no per-bar bid/ask); costs modeled via the sizing engine's conservative 2-pip spread assumption vs the 1.5–2.0 pips measured in F-3/F-5 |
| Fixtures | `data/research/*_M5_london_sessions_2026-06-08_2026-07-29_nytz.json`; reproduce via `scripts/run_replay.py` |

Every session ran the full deterministic pipeline: feature engine (Asian
range at 07:30 London, no lookahead) → breakout rules (v0.1.0 defaults,
untouched first-guess parameters, zero optimization passes) → risk engine
(Standard-tier baseline score 75, per-instrument margin rates from audit
F-1) → sizing engine (2-pip spread inclusive, round-down) → conservative
fill simulation (same-bar stop priority) → inviolate 11:00 flatten.

## Results

### GBP_USD (margin rate 0.05 — F-1)

```
DATE        STATUS      OUTCOME     UNITS      PNL
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

**london_breakout v0.1.0 on GBP_USD | sessions=31 traded=19 W/L/F=8/11/14
net=$-3.97 expectancy=$-0.21 PF=0.73 maxDD=$7.55**

### EUR_USD (margin rate 0.02)

```
DATE        STATUS      OUTCOME     UNITS      PNL
2026-06-10  NO_SIGNAL   -               0        -
2026-06-11  NO_SIGNAL   -               0        -
2026-06-12  TRADED      FLATTENED     753    -0.49
2026-06-15  NO_SIGNAL   -               0        -
2026-06-16  TRADED      FLATTENED    1024     0.18
2026-06-17  NO_SIGNAL   -               0        -
2026-06-18  TRADED      FLATTENED     912     2.09
2026-06-19  NO_SIGNAL   -               0        -
2026-06-29  TRADED      FLATTENED    1184     0.16
2026-06-30  NO_SIGNAL   -               0        -
2026-07-01  TRADED      FLATTENED    1106     1.09
2026-07-02  TRADED      FLATTENED    1213     1.72
2026-07-03  NO_SIGNAL   -               0        -
2026-07-06  TRADED      FLATTENED    1059     0.46
2026-07-07  NO_SIGNAL   -               0        -
2026-07-08  TRADED      STOP          859    -2.50
2026-07-09  NO_SIGNAL   -               0        -
2026-07-10  NO_SIGNAL   -               0        -
2026-07-13  TRADED      FLATTENED     868     1.58
2026-07-14  TRADED      FLATTENED    1111     0.03
2026-07-15  NO_SIGNAL   -               0        -
2026-07-16  NO_SIGNAL   -               0        -
2026-07-17  NO_SIGNAL   -               0        -
2026-07-20  NO_SIGNAL   -               0        -
2026-07-21  NO_SIGNAL   -               0        -
2026-07-22  TRADED      FLATTENED    1275    -1.66
2026-07-23  NO_SIGNAL   -               0        -
2026-07-24  NO_SIGNAL   -               0        -
2026-07-27  NO_SIGNAL   -               0        -
2026-07-28  NO_SIGNAL   -               0        -
2026-07-29  NO_SIGNAL   -               0        -
```

**london_breakout v0.1.0 on EUR_USD | sessions=31 traded=11 W/L/F=8/3/10
net=$2.66 expectancy=$0.24 PF=1.57 maxDD=$2.55**

## Observations (research questions, not conclusions)

1. **Exit distribution is the headline.** 24 of 30 trades ended FLATTENED at
   the 11:00 boundary with small P&L; only 3 reached the 1.5R target and 3
   hit full stops on GBP (0 full stops' worth of clean stop-outs on EUR
   beyond its 3 losses). The v0.1.0 target/exit logic rarely resolves within
   the session — the strategy as parameterized is mostly a small-P&L
   coin-flip at the flatten boundary. Challenger question: session-aware
   exits (partial at 1R, trail, or time-based) — requires §12.6 evidence
   before any change is promoted.
2. **Per-pair divergence at small n.** GBP: 19 signals, PF 0.73, net −$3.97.
   EUR: 11 signals, PF 1.57, net +$2.66. With ~10–20 trades per pair this
   difference is statistically uninformative; treat as noise until the
   sample grows.
3. **Loss containment held exactly.** Every stopped trade lost precisely the
   approved $2.50 or less after costs — the §3.3 stop-first chain held on
   real data as it did on synthetic goldens.
4. **Margin overlay behaved.** GBP sizes (700–1,024 units) kept margin at
   5% within the 30% budget every session; the F-1 per-instrument rate is
   binding reality, not theory.
5. **Range filter frequency.** 12/31 GBP and 20/31 EUR sessions produced no
   signal (range filter or no breakout) — consistent with §0.6's
   no-trade-is-normal doctrine.

## §12.6 accounting

| Decision this could inform | Threshold | This sample | Verdict |
|---|---|---|---|
| Tier qualification above Standard | 50 trades/strategy | 30 (both pairs pooled) | Insufficient |
| Challenger promotion | Separate confirmation sample | none exists | Not applicable |
| Any live permission | Full §12.2 ladder | replay stage only | Not applicable |

Next research steps: extend the sample backward as FMP history allows,
register the exit-logic challenger hypothesis with the §12.4
multiple-testing record, and re-run on OANDA bid/ask candles when
available so spread costs come from data rather than assumption.
