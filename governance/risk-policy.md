# Risk Policy

Operative summary of the governing spec's risk framework (§3–§5). The spec
wins on any conflict; the numbers below are enforced by
`config/base/firm.yaml` + `src/trading_firm/config.py`, with tests in
`tests/unit/test_config.py`.

## Per-trade risk ladder at the $250 anchor (§3.2)

| Tier | Max risk | Fraction | Gate |
|---|---:|---:|---|
| Standard | $2.50 | 1% | Edge score 70–79 |
| Strong | $7.50 | 3% | 80–89 |
| High | $12.50 | 5% | 90–94 |
| Exceptional | $25.00 | 10% | 95–100 + §5.3 gates + owner approval during probation |

Within-tier: `allowed = min(tier_dollar_cap, fraction × current_closed_equity)` —
contraction below the anchor, never expansion above it (§3.2).

## Hard limits (§3.4)

- 1 open position; 2 trades per session; 1 exceptional trade per session
- Session realized loss cap $25 (ends session); weekly cap $37.50
  (ISO week, Europe/London — D-6)
- Live floor $200: at/below, live entries disabled, return to shadow
- Any session loss disables Exceptional for the remainder of that session

## Margin feasibility (§3.2, audit F-1)

Margin at intended size must not exceed 30% of closed equity
(`margin_utilization_cap_fraction`), computed with the **instrument's own
broker-reported margin rate** — never the account-level rate. Evidence:
GBP_USD practice margin is 5% (20:1) against an account-level 2% (50:1).

## Drawdown states (§4.5)

| State | Equity vs. tier anchor | Restrictions |
|---|---|---|
| NORMAL | above −5% | full tier permissions |
| CAUTION | −5% to −10% | Exceptional disabled; max Strong |
| RESTRICTED | below −10%, above floor | max Standard; 1 trade/session |
| SHADOW | at/below live floor | live entries disabled |

## Tier promotion (§4.2, D-2/D-3)

Deterministic conditions arm a **pending promotion**; it takes effect only on
explicit owner approval (lapses after 7 days). Deposits adjust the sizing
base but never advance milestones. Risk always contracts on current closed
equity (§4.4).

## Edge score containment (§5.1, M-1)

LLM-derived inputs may lower a candidate's tier below its deterministic
baseline, never raise it. Score thresholds are unvalidated priors until the
§12.6 recalibration milestone (100 classified candidates).

## Session boundaries (§14, F-5)

Entries 08:00–10:30 London; mandatory flatten 11:00 London — inviolate, and
structurally prevents any exposure through the 21:00 UTC rollover, where
audited spreads blow out ~10× with near-zero depth.
