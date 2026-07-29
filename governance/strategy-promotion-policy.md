# Strategy Promotion Policy

How anything earns the right to trade live capital (§12, §13, §15).

## Validation ladder (§12.2)

Specification → deterministic implementation → unit tests → historical
replay → holdout → walk-forward → cost stress → Monte Carlo → shadow →
paper → limited live probation → production qualification. No stage may be
skipped; research code never places a live order (§12.1).

## Minimum evidence (§12.6)

| Decision | Minimum sample |
|---|---|
| Probation exit review | 30 correctly processed signals (D-5) |
| Per-strategy tier qualification above Standard | 50 trades across shadow+paper+live |
| Challenger promotion | Separate confirmation sample (§12.4) |
| Edge-score recalibration | 100 classified candidates with outcomes |

## Anti-overfitting requirements (§12.4)

No future leakage; purged/embargoed validation; explicit transaction-cost
model with spread-regime awareness (fill quality and slippage calibrated
from live or licensed historical execution data — audit F-5); parameter
sensitivity; a multiple-testing record; separate discovery and confirmation
samples; never promote on one favorable interval.

## Promotion authority (§12.5)

Chief Quant & Validation recommendation with reproducible report
→ Chief Risk review → signed promotion record in `governance/approvals/`
→ **owner approval for any live permission change**. Champion strategies are
immutable during live sessions; challengers live in research/replay/shadow/
paper only (§15).

## Paper/shadow limits (§13)

Paper and shadow validate process, session logic, order lifecycle, and
spread-aware cost accounting — not fill quality. No strategy is promoted on
paper-measured execution quality alone.
