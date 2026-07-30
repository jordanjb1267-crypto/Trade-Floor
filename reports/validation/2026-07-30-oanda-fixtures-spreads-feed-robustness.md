# OANDA practice fixtures: spread measurement & feed-robustness (2026-07-30)

**Status: framework replay output — NOT validation** (§12.4, §12.6).

## Data

First broker-feed research fixtures, fetched with the governed read-only
script (`scripts/fetch_oanda_candles.py`, practice host only) by an
owner-directed session and committed to this branch:

- `data/research/GBP_USD_M5_oanda_practice_2026-07-01_2026-07-29.json`
  (6,044 M5 candles, mid/ask/bid; 3 quality events)
- `data/research/EUR_USD_M5_oanda_practice_2026-07-01_2026-07-29.json`
  (6,047 candles; 1 quality event)

All four quality events are 10–15-minute gaps immediately after Sunday
~21:00 UTC market opens — expected weekend-open illiquidity, not data
defects. Cross-validation against the independent FMP fixture at 247 shared
H1-open timestamps: median divergence 0.2 pips, max 0.7 (decision log,
2026-07-30). Practice-feed caveat (F-5): spreads usable for modeling; fills
and slippage are not represented.

## Measured spreads (close-of-candle, pips)

Reproduce: `python3 scripts/measure_spreads.py <fixture>`

| Window | GBP_USD med / p95 / max | EUR_USD med / p95 / max |
|---|---|---|
| Asian range 00:00–07:00 London | 2.00 / 2.20 / 4.50 | 1.60 / 1.70 / 2.00 |
| London session 07:00–11:00 | 1.90 / 2.10 / 3.20 | 1.60 / 1.70 / 1.80 |
| Rollover 20:30–22:00 UTC | 8.00 / 20.0 / 20.0 | 2.80 / 8.60 / 10.0 |

Findings:

- **The 2.0-pip sizing assumption is nearly exact for GBP_USD** (session
  median 1.90, p95 2.10). At the p95 tail a stopped 25-pip-stop trade loses
  ~0.4% more than approved risk (0.1 pip on a 27-pip all-in cost) —
  measured, negligible, and now known rather than assumed.
- **EUR_USD is materially cheaper to trade** (1.60 vs 1.90 median): the flat
  2.0-pip assumption over-charges EUR replays by ~0.4 pips/trade.
- **The F-5 rollover blowout reproduces exactly**: GBP spreads reach 20
  pips (~10× session levels) around 21:00 UTC. The inviolate 11:00 London
  flatten keeps the firm seven-plus hours away from that regime.

## Feed-robustness: same sessions, two feeds

Champion london_breakout v0.1.0, identical parameters, on the 21 July
sessions present in both the OANDA and FMP fixtures:

| | GBP OANDA | GBP FMP | EUR OANDA | EUR FMP |
|---|---|---|---|---|
| traded | 14 | 13 | 7 | 7 |
| W/L/F | 5/9/9 | 5/8/9 | 4/3/6 | 5/2/6 |
| net | −$7.55 | −$5.81 | −$2.26 | **+$0.72** |
| PF | 0.45 | 0.52 | 0.63 | **1.17** |

Per-session agreement (status match, |pnl Δ| ≤ $0.30): **19/21 on both
pairs**. Every disagreement is a marginal breakout trigger that sub-pip
feed differences flip (2026-07-01 and 2026-07-20 on both pairs).

Interpretation:

- **Feed noise exceeds the measured edge.** EUR's July result changes sign
  between two feeds that agree to 0.2 pips median. No result of this size
  can be evidence of edge — quantified support for what §12.6's thresholds
  already assume.
- **Broker feed becomes the canonical research feed.** Paper and live will
  execute against OANDA prices; replaying on the venue's own feed removes
  one layer of unrepresentativeness. FMP remains the deep-history and
  cross-validation source.

## Consequences

- Champion v0.1.0's July numbers are weak on either feed; nothing here
  changes its status or spends any §12.4 test (no parameter was varied —
  this is a data-layer diagnostic).
- Future spread-aware replay (using measured per-bar bid/ask instead of the
  flat assumption) is now possible with these fixtures; registered as
  framework work, not a strategy test.
- Nothing here is validation; sample sizes remain far below every §12.6
  threshold (§0.5).
