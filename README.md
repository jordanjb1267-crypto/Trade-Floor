# Trade-Floor

## OANDA candle fixtures

`scripts/fetch_oanda_candles.py` fetches candles from the OANDA v20 API and
writes one JSON fixture per instrument under `fixtures/oanda/`. It needs an
OANDA v20 personal access token in `OANDA_API_KEY` (set `OANDA_ENV=live` to
use the live host instead of practice):

```sh
OANDA_API_KEY=... python3 scripts/fetch_oanda_candles.py \
    --instruments GBP_USD,EUR_USD \
    --from 2026-07-01 --to 2026-07-29 \
    --granularity H1 \
    --out fixtures/oanda
```

Each fixture records the instrument, granularity, date range, and the
complete mid-price candles exactly as OANDA returned them.