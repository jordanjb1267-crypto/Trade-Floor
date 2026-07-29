# Phase 0 audit record — OANDA practice connection (2026-07-29)

| | |
|---|---|
| **Environment** | OANDA fxTrade **Practice** (`api-fxpractice.oanda.com`), read-only |
| **Method** | `oanda_connection_audit` tool of the `oanda-practice-readonly` MCP bundle (v0.1.0), run by the owner in Claude Desktop on the trading laptop |
| **Reference** | Master Handoff §16 required broker capabilities; §22 Phase 0 deliverables |
| **Result** | **8/8 checks PASS** — with one material sizing finding (F-1 below) |

## Results as reported by the owner

| Check | Result |
|---|---|
| API reachable, token accepted (practice) | PASS — `api-fxpractice.oanda.com` |
| Account currency USD | PASS |
| Margin rate vs. US 50:1 majors cap | PASS — 0.02 → 50:1 (account level) |
| Hedging disabled (NFA FIFO) | PASS — `hedgingEnabled=false` |
| GBP_USD 1-unit granularity | PASS — min size 1, precision 0 |
| EUR_USD 1-unit granularity | PASS — min size 1, precision 0 |
| GBP_USD live pricing / spread | PASS — 1.9 pips, tradeable |
| EUR_USD live pricing / spread | PASS — 1.5 pips, tradeable |

## Findings

### F-1 · GBP_USD carries a 5% per-instrument margin rate (20:1), overriding the 2% account-level rate

The account-level `marginRate` is 0.02 (50:1), but the GBP_USD instrument
record reports `marginRate=0.05` (20:1) — 2.5× the margin per unit of a flat
50:1 assumption. EUR_USD is at the account-level 2%. **Per-instrument
overrides govern actual sizing;** any component that sizes off the
account-level rate under-reserves on GBP_USD by 2.5×.

Recomputed margin at the $250 anchor, GBP_USD @ 1.3298 with 5% margin
(`units = risk / (stop_pips × $0.0001)`, `margin = units × 1.3298 × 0.05`):

| Risk | 10-pip stop | 25-pip stop | 40-pip stop | 66.5-pip stop |
|---|---:|---:|---:|---:|
| $2.50 (Standard) | $166.23 | $66.49 | $41.56 | $25.00 |
| $7.50 (Strong) | $498.68 ✗ | $199.47 | $124.67 | $75.00 |
| $12.50 (High) | $831.13 ✗ | $332.45 ✗ | $207.78 | $125.00 |
| $25.00 (Exceptional) | $1,662.25 ✗ | $664.90 ✗ | $415.56 ✗ | $250.00 |

(✗ = exceeds the whole $250 account.)

Consequences at the $250 anchor, GBP_USD, under the §3.2 30% margin-utilization
cap ($75):

- **Exceptional:** not executable at any stop below ≈66.5 pips even at 100%
  margin utilization; below ≈222 pips under the 30% cap — effectively never.
- **High:** requires ≈33-pip+ stops at 100% utilization; ≈111 pips under the cap.
- **Strong:** ≈27-pip+ stops under the 30% cap.
- **Standard:** ≈22-pip+ stops under the 30% cap — workable for typical
  London-breakout invalidations, but note F-3's spread interaction.
- **EUR_USD (2%)** is unaffected; the review's Appendix A.2 numbers stand.

**Action:** the risk engine and position-sizing engine must read each
instrument's `marginRate` from the broker instrument record at decision time
and never assume the account-level rate. Spec patched accordingly
(v1.1.1, §3.2 and §16).

### F-2 · Practice results do not transfer to live

Every result above describes the practice environment with a read-only
connector. It says nothing about live credentials, live margin treatment, or
live fill quality; practice fills and pricing are systematically more
forgiving. **Action:** a fresh connection audit against the live environment
is a mandatory gate before Phase 7 (limited live probation) — already implied
by §13/§22, recorded here as an explicit checklist item.

### F-3 · Spreads of 1.5–1.9 pips were measured off-peak

Audit ran outside the London/NY overlap; these are upper-range spreads for
majors. At a 22-pip Standard-tier stop on GBP_USD, 1.9 pips is 8.6% of risked
amount — above the 8% spread-drag guidance in the design review (N-9).
**Action:** re-measure spreads during the trading window itself
(08:00–10:30 London) before treating any spread number as a strategy input;
the deterministic execution-conditions component of the edge score must use
live measured spread, not an assumption.

## Standing caveats

- Token was transmitted through chat during setup; owner should rotate it in
  the practice account and store the replacement only in the OS keychain via
  the extension settings.
- This audit covers connection capability, not order lifecycle. Phase 4
  (broker sandbox integration) still requires the full order state-machine
  tests: submit/ack/fill, stop attachment and verification, partial fills,
  rejections, reconciliation, restart recovery (§21, §22).
