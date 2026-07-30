# CORRECTION — achievable-fill defect invalidates earlier published tables (2026-07-30)

**Status: correction notice. Supersedes the result tables in three earlier
reports of the same date.** Per §0.11 the superseded reports are preserved
unedited except for a pointer banner; nothing is rewritten in place.

## What was wrong

An adversarial multi-agent review of the research layer (5 independent
lenses, refutation-default verification) confirmed a **critical fill
defect** in `research/replay.py`, found independently by three lenses.

The Asian range freezes at **07:30** London but entries open at **08:00**
(§14). When the breakout happened inside that 30-minute blackout, the first
ACTIVE bar OPENED already beyond the trigger — and the engine still booked
the entry at the stale trigger price. In 5 of 14 affected trades the assumed
fill was outside the trigger bar's entire high–low range: **a price that did
not trade at any moment in the entry window.**

Two consequences, the second worse than the first:

1. **Fictitious profit.** Every gapped entry was booked at a strictly better
   price than the market offered.
2. **A silent risk-cap breach (§3).** The candidate was handed to the risk
   engine with the *trigger* as its entry, so sizing measured a stop distance
   the trade never had. The position was too large for its real risk, and a
   stopped trade could lose more than the approved amount — the one property
   this framework exists to guarantee.

Sweep-reversal was unaffected (it enters at a bar's close, always a traded
price).

Two further confirmed defects also moved published numbers:

- **`features/engine.py`** accepted a partially-covered Asian window, so the
  first session of each fixture computed a truncated range and produced
  phantom trades. It now fails closed (§0.10).
- **`strategies/sweep_reversal.py`** could emit a signal whose re-entry close
  had already blown through the *opposite* extreme, putting the
  opposing-liquidity target BEHIND the entry — a guaranteed loss that replay
  scored as a `TARGET` win.

## The fix

Entry is clamped to the adverse side of the trigger bar's open
(`max(trigger, open)` long / `min(trigger, open)` short) — the gap fill a
broker would actually give — and the **candidate is built from that
achievable price**, so the risk engine sizes the true stop distance. R-based
targets and the breakeven trail now anchor on the real entry. Regression
tests in `tests/unit/test_replay_fills.py` pin the behavior in both
directions and assert the risk-cap property across a sweep of gap sizes;
the mutation audit had found the SHORT paths entirely untested.

## Corrected results (canonical broker feed, measured per-bar costs)

| Strategy / pair | Published | **Corrected** |
|---|---|---|
| london_breakout GBP_USD | 65 trades, −$9.02, PF 0.78 | 64 trades, **−$11.53**, PF 0.72 |
| london_breakout EUR_USD | 18 trades, **+$0.67**, PF 1.07 | 17 trades, **−$0.24**, PF 0.98 |
| sweep_reversal GBP_USD | 27 trades, +$1.48, PF 1.11 | 26 trades, +$2.05, PF 1.16 |
| sweep_reversal EUR_USD | 3 trades, −$3.28, PF 0.24 | 3 trades, −$3.28, PF 0.24 |
| london_continuation GBP_USD | 9 trades, +$1.94, PF 1.72 | 9 trades, **+$1.44**, PF 1.46 |
| london_continuation EUR_USD | 2 trades, **+$0.30**, 2W/0L | 2 trades, **−$0.70**, 1W/1L |

**Two results changed sign.** Both were positive-looking EUR figures; both
were artifacts. Every corrected number is worse than or equal to what was
published, which is the expected direction when removing an optimistic fill.

## Corrected feed-robustness comparison

The earlier table did not reproduce: it was computed on July-only fixtures
that were later replaced by backward-extended files, so the stated command
could not regenerate it. Recomputed over all shared sessions:

| | GBP OANDA | GBP FMP | EUR OANDA | EUR FMP |
|---|---|---|---|---|
| shared sessions | 72 | 72 | 32 | 32 |
| traded | 49 | 46 | 12 | 11 |
| net | −$6.71 | −$6.70 | +$0.07 | +$1.45 |
| PF | 0.79 | 0.78 | 1.01 | 1.27 |
| agreement | 63/72 | | 30/32 | |

The original conclusion **survives in substance and is now better supported**:
GBP agrees to a cent between two independent feeds while EUR still diverges
materially on a small sample. Feed noise remains larger than any measured
edge. (Note the two feeds are not cost-identical — OANDA uses measured
per-bar spreads, FMP the flat 2-pip assumption, since FMP publishes no
bid/ask.)

## Exit-challenger verdict re-checked (unchanged, now cleaner)

The pre-registered exit-variant evaluation was re-run under the corrected
fill model. **The REJECTED verdict stands, and now arrives more decisively:**

| Variant (discovery, 44 sessions / 29 trades) | Published | Corrected |
|---|---|---|
| champion (reference) | −$1.81, PF 0.90 | −$3.52, PF 0.80 |
| V1 1.5R + BE@1.0R | −$1.81, PF 0.90 | −$3.09, PF 0.83 |
| V2 1.0R | **+$0.52, PF 1.03 → advanced** | −$1.57, PF 0.91 |
| V3 1.0R + BE@0.5R | −$4.36, PF 0.76 | −$4.46, PF 0.75 |

Previously V2 cleared the eligibility bar by the thinnest margin and then
failed confirmation. **Now no variant is eligible at all** — the hypothesis
is rejected on discovery without spending the confirmation window.

One earlier reading was itself an artifact and is corrected: V1 was reported
as *bit-identical* to the champion ("the trail is dead weight"). It no longer
is (−$3.09 vs −$3.52), because the breakeven trail now anchors on the real
entry rather than the trigger. The trail does something on gapped entries; it
just does not do enough to matter.

## What this does and does not change

- **No strategy status changes.** All three remain `research` with all risk
  permissions false. Nothing was promoted on the bad numbers.
- **No §12.4 test is refunded or newly spent.** The ledger is unchanged: a
  corrected computation of an already-recorded look is not a new look.
- **The champion's verdict hardens.** london_breakout was already judged a
  costs-eat-edge coin flip; it is worse than reported on every feed.
- **Continuation's registered hypothesis survives but weakens**: 9 trades,
  PF 1.46 (was 1.72). It was never evidence and still is not.

## Lesson (recorded in the decision log)

The execution layer got an adversarial review and yielded 21 defects. The
research layer was written headless in a single day and merged **without
one** — and contained a critical defect that made losing strategies look
profitable. Silent optimism in a backtest is more dangerous than a crash: it
is persuasive and it survives a green test suite. **Adversarial review is
mandatory for research code before any number it produces is published**, not
only for order-path code.
