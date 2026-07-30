# OANDA practice fixtures: spread measurement & feed-robustness (2026-07-30)

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

## Addendum (same day): spread-aware replay implemented

Replay now accepts a `SpreadSeries` (measured per-bar close spreads from a
MAB fixture) and charges each fill the measured half-spread of its bar,
while **sizing keeps the flat assumption** — exactly what the live engine
would experience. Fails closed on any bar without a measured spread. Unit
invariants: measured==assumed reproduces the flat result to the cent; a
1-pip-wider measured spread turns the $2.50 approved-risk stop into a
−$2.56 realized loss, 1 pip tighter into −$2.44 (`tests/unit/
test_replay_spreads.py`). `run_replay.py` uses measured costs
automatically for OANDA fixtures.

July sessions, flat 2.0-pip assumption vs measured per-bar costs:

| | net (flat) | net (measured) | Δ | W/L/F |
|---|---|---|---|---|
| GBP_USD | −$7.55 | −$7.34 | +$0.21 | 5/9/9 (unchanged) |
| EUR_USD | −$2.26 | −$1.93 | +$0.33 | 4/3/6 (unchanged) |

The assumption is mildly conservative in-session (≈1.5¢/trade GBP,
≈4.7¢/trade EUR), and no trade outcome changes — the flat-spread results
were cost-biased, not path-biased. The 2.0-pip sizing assumption stays:
conservative sizing is the correct side to err on (§3).

## Consequences

- Champion v0.1.0's July numbers are weak on either feed; nothing here
  changes its status or spends any §12.4 test (no parameter was varied —
  this is a data-layer diagnostic).
- Future spread-aware replay (using measured per-bar bid/ask instead of the
  flat assumption) is now possible with these fixtures; registered as
  framework work, not a strategy test.
- Nothing here is validation; sample sizes remain far below every §12.6
  threshold (§0.5).

## Postscript (2026-07-30, later): fixtures extended backward

The two July-only fixtures this report measured were superseded on this
branch by extended files mirroring the FMP series' per-instrument coverage:

- `data/research/GBP_USD_M5_oanda_practice_2026-03-30_2026-07-29.json`
  (25,337 candles; 6 quality events, all Sunday-open gaps)
- `data/research/EUR_USD_M5_oanda_practice_2026-06-08_2026-07-29.json`
  (10,943 candles; 1 quality event)

The extended files were verified to contain every candle of the originals
with identical values, so all measurements above remain reproducible by
restricting to the 2026-07-01…29 window. Nothing above is re-stated.
