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

## Operational readiness (§18, §19)

Any live-readiness procedure — the §25 definition of done, a probation start
(§13), or any owner activation of a live permission — **must require**:

```bash
.venv/bin/python scripts/supervisor_status.py --require-notify-confirmed
```

exiting **0**. This is a gate, not a diagnostic. It asserts two independent
things at once: that the §18 supervisor is genuinely running (`HEALTHY` — not
merely loaded, not hung, not crash-looping) and that the §19 notification path
has a **confirmed delivery**.

Process health and notifier health are deliberately **independent axes**.
Installation may succeed with a degraded notifier, because a running supervisor
is not made better by uninstalling it — but live readiness may not, because a
risk-halt alert nobody receives is worse than no alert at all (§0.10, §19).

`legacy_assumed_confirmation` **does not satisfy this gate**. That state means a
migrated marker from an older build is suppressing a duplicate message; the old
marker recorded a send *attempt*, never a delivery. An assumption inherited from
an upgrade is not evidence that the owner is reachable, and it expires on a
finite TTL so a real send produces real confirmation.

## Paper/shadow limits (§13)

Paper and shadow validate process, session logic, order lifecycle, and
spread-aware cost accounting — not fill quality. No strategy is promoted on
paper-measured execution quality alone.
