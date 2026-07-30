# Exit-logic challenger evaluation — london_breakout (2026-07-30)

> **⚠ SUPERSEDED IN PART (2026-07-30).** The result tables below were
> computed with a replay engine that filled gapped entries at an unobtainable
> price and sized them against a stop distance the trade never had. Corrected
> figures — including two sign flips — are in
> `2026-07-30-CORRECTION-achievable-fills.md`. This report is preserved
> unedited below that line per §0.11; do not cite its numbers.


**Status: framework replay output — NOT validation** (§12.4, §12.6).
**Verdict: hypothesis REJECTED at these parameters. Champion v0.1.0 stands.
No v0.2.0 manifest is created.**

## Hypothesis under test

Registered in the decision log with the first real-data replay (2026-07-30):
v0.1.0's dominant FLATTENED exit share (79% of trades on the extended GBP
sample) suggests exit logic, not entry logic, is the binding constraint — a
session-aware exit (nearer target and/or breakeven trail) might capture what
the 11:00 flatten gives back.

## Pre-registration (§12.4 multiple-testing record)

Declared before any variant touched data:

- **Variants — exactly three; none added after seeing results:**
  - V1: target 1.5R, breakeven trail armed at +1.0R
  - V2: target 1.0R, no trail
  - V3: target 1.0R, breakeven trail armed at +0.5R
- **Data:** extended GBP_USD fixture only
  (`data/research/GBPUSD_M5_london_sessions_2026-03-30_2026-07-29_nytz.json`).
  EUR_USD excluded — its 31 sessions were already inspected for the v0.1.0
  baseline report.
- **Split:** discovery = sessions before 2026-06-16 (44 sessions,
  2026-04-01..2026-06-15); confirmation = 2026-06-16 onward (27 sessions,
  ..2026-07-29). Split date declared when the extended fixture was
  assembled, before any challenger replay.
- **Selection rule (mechanical):** a variant is eligible iff its discovery
  window shows ≥20 trades AND expectancy > $0; among eligible variants the
  highest profit factor wins; only the winner runs on confirmation. No
  eligible variant → hypothesis rejected, no confirmation replay.
- **Confirmation bar:** the winner must show positive expectancy on the
  confirmation window and not underperform the champion baseline there.
- **Caveat declared up front:** the confirmation window was previously seen
  by the v0.1.0 baseline replays, so even a pass would have been WEAK
  confirmation. It did not come to that.

Trail semantics (implemented in `research/replay.py::ExitPolicy`, unit-tested
in `tests/unit/test_replay_exits.py`): the stop moves to the entry price once
a bar's range touches the arming level, effective from the NEXT bar —
within-bar sequence is unknowable on M5 data, so a same-bar spike-and-collapse
takes the full original-stop loss (pessimistic for the challenger). Stops only
ever tighten; §0.7's no-stop-widening rule is structurally unrepresentable.

## Results

Reproduce with:
`python3 scripts/run_challenger_eval.py data/research/GBPUSD_M5_london_sessions_2026-03-30_2026-07-29_nytz.json`

### Discovery (44 sessions, 31 trades per variant)

| Variant | W/L/F | Net | Expectancy | PF | MaxDD |
|---|---|---|---|---|---|
| champion v0.1.0 (reference) | 17/14/26 | −$1.81 | −$0.06 | 0.90 | $8.39 |
| V1 1.5R + BE@1.0R | 17/14/26 | −$1.81 | −$0.06 | 0.90 | $8.39 |
| **V2 1.0R** | 17/14/23 | **+$0.52** | **+$0.02** | **1.03** | $8.91 |
| V3 1.0R + BE@0.5R | 14/17/22 | −$4.36 | −$0.14 | 0.76 | $8.91 |

Eligible: V2 only. V2 advanced to confirmation.

### Confirmation (27 sessions, 17 trades) — winner only

| Variant | W/L/F | Net | Expectancy | PF | MaxDD |
|---|---|---|---|---|---|
| champion v0.1.0 (reference) | 7/10/12 | −$2.02 | −$0.12 | 0.84 | $7.55 |
| V2 1.0R | 7/10/12 | **−$4.36** | **−$0.26** | **0.66** | $7.55 |

V2 fails both confirmation criteria: negative expectancy, and it
underperforms the champion on the identical trade set.

## Reading of the evidence

- **V1 is bit-identical to the champion on discovery.** A breakeven trail
  armed at +1.0R under a 1.5R target never altered a single exit across 31
  trades: trades that reach +1R here either go on to resolve or retrace so
  fast the next-bar-armed trail catches nothing the flatten wouldn't. The
  trail is dead weight at these parameters.
- **V2's discovery edge was noise-sized.** +$0.52 across 44 sessions
  (~1.2 cents/session on a $250 account) cleared the pre-registered bar by
  the thinnest possible margin — and inverted on confirmation.
- **On confirmation, capping winners at 1.0R only gave money back.** Same
  17 trades, same 7 winners, $2.34 worse: every trade that reached 1.0R also
  went further, so the cap clipped winners without saving a single loser
  (identical flatten count, 12).
- **The flatten-exit dominance persists** (23–26 of 31 discovery trades,
  12 of 17 confirmation trades) but reshaping exits inside the session did
  not convert it into expectancy. The binding constraint looks like entry
  quality or the cost floor (2-pip spread ≈ 5% of risk per round trip), not
  exit placement.

## Multiple-testing ledger

Three exit-variant tests are now SPENT against this GBP sample. Any future
exit-logic proposal on this data must count them (§12.4): the next
researcher starts at test #4, not #1. The clean path to another exit study
is NEW data — sessions after 2026-07-29, or a properly held-out instrument.

## Consequences

- Champion london_breakout v0.1.0 stands. No challenger manifest is
  registered; `config/research/strategies/` is unchanged.
- The exit-logic hypothesis is closed at these parameters. It may be
  reopened only with new data and a fresh pre-registration.
- Nothing here is validation and nothing here has promotion implications
  (§0.5): 48 distinct trades total remain far below every §12.6 threshold.
