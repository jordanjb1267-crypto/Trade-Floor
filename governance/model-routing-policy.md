# Model Routing Policy (§7.4, §6.6)

Cost-aware routing that never trades quality for cost on safety-critical
decisions. "Frontier" means the highest-quality Claude model available to
the owner at the time of use.

**Updated 2026-07-30 for the v2 roster.** The previous version predated §6.6 and
the independent senior-trader pair, so it routed by *duty* only and had no row
for Alpha, Beta, or the Arbiter. One routing is deliberately changed rather than
extended — see "What changed and why" below.

## By duty

| Duty | Tier | Rationale |
|---|---|---|
| Governance changes, spec amendments, promotion decisions | **Frontier** | §7.4: safety-critical |
| Risk reviews (CRO verdicts), incident response | **Frontier** | Adversarial quality is the product |
| Architecture and production-code changes to `src/trading_firm/` | **Frontier** | Deterministic core correctness |
| Strategy validation review, overfitting diagnostics | **Frontier** | §12.4 rigor |
| §12.7 adversarial review of research code | **Frontier** | A-1: refutation-default review is the gate on every published number |
| Report synthesis, session summaries | **Mid-tier** | Recoverable errors |
| Log parsing, extraction, formatting, schema conversion | **Low-cost or deterministic code** | Prefer code over any model |

## By agent (§6.6)

| Agent | Tier | Why |
|---|---|---|
| `senior-trader-alpha` | **Frontier** | §6.6 names it |
| `senior-trader-beta` | **Frontier** | §6.6 names it |
| `market-opportunity-arbiter` | **Frontier** | §6.6 names it |
| `firm-governor` | **Frontier** | §6.6 "governance" |
| `chief-risk-officer` | **Frontier** | §6.6 "risk" |
| `chief-quant-validation` | **Frontier** | §6.6 "quantitative review, promotion decisions" |
| `learning-audit-director` | **Frontier** | Scores calibration under A-2 — see below |
| `context-analyst` | **Frontier** | Produces the evidence everything else reasons from |
| `session-strategist` | **Frontier** | Its REJECT surfaces — see below |

## Surveillance division (§30.3, A-3 — added 2026-07-31)

All ten surveillance roles route **Frontier** initially, under rule 5 below:
none has recorded real-session agreement evidence yet, and until it exists a
cheaper model's divergence would land on exactly the unusual sessions that
matter. Two are additionally not down-routable in principle:

| Agent | Tier | Why |
|---|---|---|
| `technical-surveillance-lead` | **Frontier** | §30.15 names it for material events |
| `news-verification-relevance` | **Frontier** | Its `PAUSE_NEW_ENTRIES`/`IGNORE` output is rejection-adjacent — rule 5's first condition fails permanently |
| `opportunity-alert-agent` | **Frontier** | A missed material change is a missed rejection's twin |
| `position-contradiction-monitor` | **Frontier** | Escalation quality is position protection (§30.10) |
| the six domain monitors | **Frontier** | Rule 5: no recorded-sample agreement evidence exists |

§30.15's deterministic-first policy is the real cost control and is already
structural: extraction, normalization, dedup, severity, and throttling are
deterministic code, and the §30.15 invocation budgets bound what reaches any
model at all. Down-routing a monitor later follows rule 5 exactly — recorded
agreement on real sessions, decision-log entry — not a cost hunch.

## What changed and why

The previous table routed "pre-session strategist/context analysis" to
**mid-tier**, on the rationale that its influence is "bounded, schema-validated,
veto-only". Two of those three are still true and the conclusion no longer
follows.

**Veto-only cuts the other way.** A specialist's SUPPORT is worth nothing by
construction — `ConsultationRound.tier_delta` is non-positive and no branch
reads supports (§6.3). So the only thing a specialist contributes that changes
an outcome is its **REJECT**, and a missed rejection is a trade the firm should
not have taken. The half of the job that looked cheap and the half that is
safety-critical are the same call. "It can only veto" is an argument for
routing it *up*, not down.

**Context is not one opinion among several.** `context-analyst` now produces the
deterministic context packet that Alpha, Beta, and the Arbiter all build on
(§6.4). An error there is not a bad opinion the pair can outvote; it is bad
evidence that every downstream agent then reasons from correctly.

**A-2 added a scoring duty that did not exist.** `learning-audit-director` now
scores under-claim and over-claim as a matched pair (§6.6). Getting that wrong
in either direction is a systematic bias applied to every future session: too
harsh and the firm learns to over-claim, too lax and A-2 does nothing.

The arithmetic makes this easy. The firm takes at most two trades per London
session against $250 (§3.4). Nine frontier agents for one session costs far less
than a single avoidable loss, and vastly less than a promotion granted on
mis-scored calibration. Where the trade-off is this lopsided, §7.4's closing
constraint — *"never lower quality for safety-critical decisions merely to
reduce cost"* — is not a tiebreaker; it decides.

## Rules

1. Downgrading a safety-critical duty to save cost is prohibited (§7.4).
2. Anything whose output enters the deterministic runtime passes schema
   validation regardless of model tier (§6.5) — routing never substitutes
   for validation.
3. Agent influence on risk is lowering-only at the type level
   (`TierAdjustment.adjustment ≤ 0`), so a cheaper model can degrade
   opportunity, never safety.
4. Revisit this table when model generations change; record changes in the
   decision log.
5. Route an agent **down** only when all three hold, recorded in
   `governance/decision-log.md`: its output cannot raise risk, cannot suppress a
   rejection, and cannot enter a §12.6 evidence count; its output is
   schema-validated so a degraded answer fails loudly rather than passing
   quietly as a worse judgement; and measured agreement with the frontier model
   on a recorded sample of *real* sessions, not constructed examples. The third
   condition is the one that usually fails, and for a reason worth keeping in
   view: the sessions where a cheaper model diverges are the unusual ones, which
   are exactly the sessions that matter.

## Enforcement, and its limit

This is a policy, not a control. Nothing in the deterministic runtime reads it
and nothing can — model selection happens in the harness, above the code. Rule 4
is a reminder to a human, not a gate.

That limit is stated rather than glossed because what *is* enforced is the thing
routing could otherwise put at risk. No model of any tier can raise a tier,
authorize size, or reach the broker: §0.3 and §2 hold regardless of which model
answers, `TierAdjustment.adjustment` is `Field(le=0)`, and `classification.py`
cannot read firm state whatever is doing the classifying. A cheap model routed
here by mistake produces a worse recommendation, never a larger position.
