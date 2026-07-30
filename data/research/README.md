# Research fixtures

Historical market data for research replay (§12.1: research only; never
drives live behavior).

## `*_M5_london_sessions_*_nytz.json`

- **Source:** Financial Modeling Prep intraday 5-minute forex bars, fetched
  2026-07-30 via the licensed FMP connector (Starter plan). Personal
  research use within this private repository; do not redistribute.
- **Timestamps:** naive strings in **America/New_York** local time. Pinned
  empirically (D-7 discipline): at fetch time the newest bar was 3 minutes
  old under NY and hours wrong under UTC/London/Chicago. Always pass
  `source_tz="America/New_York"` to `from_fmp_rows`.
- **Content:** deduplicated bars trimmed to the London trading-day slice
  (00:00–11:05 Europe/London), covering 2026-06-10 → 2026-07-29 session
  dates for GBPUSD and EURUSD.
- **Prices:** single mid-like series (FMP does not publish bid/ask for
  these bars). Spread costs in replay therefore come from the sizing
  engine's conservative 2-pip assumption, not from measured per-bar
  spreads (F-3/F-5 measured 1.5–2.0 pips in-session on practice).

## `*_M5_oanda_practice_*.json` (none committed yet)

Fetched by `scripts/fetch_oanda_candles.py` (read-only, practice host only,
token via `OANDA_DEMO_API_TOKEN`). Shape: `{"meta": {...}, "candles": [...]}`
with raw OANDA mid/ask/bid blocks preserved — real measured spreads for
research, unlike the FMP mid-only series. Timestamps are RFC3339 UTC from
the API (no D-7 pinning question). Practice-feed caveat (F-5): usable for
spread modeling; fills and slippage require live/licensed data. Normalize
with `from_oanda_candles` on the `candles` list.

Run a replay:

```bash
python3 scripts/run_replay.py \
    data/research/GBPUSD_M5_london_sessions_2026-03-30_2026-07-29_nytz.json GBP_USD 0.05
python3 scripts/run_replay.py \
    data/research/EURUSD_M5_london_sessions_2026-06-08_2026-07-29_nytz.json EUR_USD 0.02
```
