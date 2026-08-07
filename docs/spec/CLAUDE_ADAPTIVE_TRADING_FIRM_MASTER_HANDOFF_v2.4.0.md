# CLAUDE ADAPTIVE LONDON-SESSION TRADING FIRM
## Master Build Handoff, Constitution, and Source of Truth

**Document status:** Governing specification  
**Current version:** 2.3.0  
**Supersedes:** Version 2.2.0. The lineage: v2.1.0 superseded Version 2.0.0
(adaptive architecture) and Version 1.1.4 (amended London firm) — v2.0.0 was
drafted from v1.0.0 and therefore did not carry the amendments ratified between
2026-07-29 and 2026-07-30, and v2.1.0 restored them, every restored item tagged
inline with its origin id and registered in §29. v2.2.0 added amendment A-2,
conviction discipline, tagged `[A-2]` in §3.5, §5.1, §6.6, §21, and §25.
v2.3.0 adds amendment A-3 (owner document id GMIS-001): the Global Market
Intelligence and Surveillance Division, carried entirely in the new §30 and
registered in §29.5. A-3 is additive — no prior section changed meaning, all
surveillance capability ships disabled, and repo code cites the division as
§30.x only (the owner's uploaded amendment document keeps its own internal
numbering and is preserved verbatim in `docs/spec/`, outside citation scope).  
**Owner:** Jordan  
**Primary engineering environment:** Claude Code on a single laptop  
**Initial live capital:** $250  
**Primary session:** London session  
**Control timezone:** America/Chicago  
**Market timezone:** Europe/London  

---

# 0. CLAUDE EXECUTION DIRECTIVE

You are the senior principal engineer, quantitative systems architect, chief risk systems designer, and implementation lead for this project.

This document is the project's governing source of truth. Build the system described here without silently weakening its controls, changing its mandate, deploying unvalidated strategy logic, or inventing production permissions. The firm is intentionally adaptive at the senior-trader layer and must not be hard-coded around any single named strategy family.

Your first responsibility is not to write code. Your first responsibility is to inspect the environment, identify every assumption, audit available connectors and broker capabilities, produce a build plan, and establish the repository structure and governance files.

## Mandatory operating rules for Claude

1. **Audit before implementation.** Inspect the laptop environment, existing repository, installed tools, Claude Code capabilities, MCP servers, credentials configuration, broker integrations, data sources, and operating-system limitations.
2. **Never expose secrets.** API keys, account identifiers, tokens, passwords, and signing secrets must never be committed, printed in logs, embedded in prompts, or stored in plaintext.
3. **Never let an LLM directly bypass deterministic risk controls.** Claude and all subagents may research, evaluate, explain, and recommend. Only deterministic code may authorize size, enforce limits, and submit orders.
4. **No unilateral production changes.** A research agent cannot promote a strategy, modify live parameters, alter risk tiers, or enable a new instrument.
5. **No implied profitability.** Optimize for positive net expectancy, execution quality, controlled drawdown, and reproducibility. Never claim guaranteed profit.
6. **No forced trading.** “No trade” is always a valid and preferred outcome when conditions are incomplete.
7. **No recovery behavior.** Martingale, loss chasing, revenge sizing, averaging into losers, stop widening, and risk escalation after losses are prohibited.
8. **Production must be restart-safe.** A Claude session ending, terminal closing, laptop process crashing, or internet interruption must not leave unmanaged exposure.
9. **Broker-held protection is mandatory.** Whenever supported, every live position must have a broker-native stop-loss order confirmed active.
10. **Fail closed.** Uncertain data, stale prices, broker desynchronization, abnormal spreads, corrupted state, missing economic-calendar status, or failed reconciliation must disable new entries.
11. **Preserve an immutable audit trail.** Every material decision, candidate, rejection, approval, order, fill, modification, close, error, model version, and configuration version must be recorded.
12. **Ask the owner only for decisions that cannot be safely resolved from inspection or this source of truth.** Do not repeatedly ask for information already available.

---

# 1. PROJECT MISSION

Build a low-cost, high-quality, agent-assisted proprietary trading operating system that runs from one laptop, is directed and maintained through Claude Code, and initially concentrates its activity during the London session.

The system begins with **$250 in live capital**, has **no daily profit target**, and may risk up to **$25 on a single exceptional-edge trade** at the initial capital tier. That $25 amount is an absolute ceiling, not a routine allocation and not permission for an unvalidated idea.

The firm is **market-opportunity driven rather than strategy driven**. Its senior trading layer must diagnose the current situation, construct independent market theses, select relevant evidence, consult specialists when appropriate, and decide whether a tradeable opportunity exists. No named setup receives permanent priority or guaranteed capital allocation.

The long-term objective is not a single trading bot. It is a modular trading-firm operating system capable of discovering, validating, deploying, demoting, and retiring strategies while retaining one governance, risk, execution, audit, and learning framework.

## Core trading doctrine

1. The market state comes first; strategy selection comes second.
2. A senior trader may recommend no trade, an existing playbook, a recombination of validated trading primitives, or a new research hypothesis.
3. No agent may label an idea profitable merely because its narrative is persuasive or its historical chart looks favorable.
4. Existing playbooks must continuously earn capital through net expectancy, calibration, drawdown control, and execution quality.
5. Novel strategy logic may be created freely in research, but it may not be deployed live until it passes the appropriate validation and promotion path.
6. Senior-trader discretion must be structured, auditable, reproducible, and bounded by deterministic risk controls.

## Initial specialist playbooks

Retain these strategy families as specialist domains, not as the firm's exclusive mandate:

1. **London Breakout**
2. **Asian Range Sweep and Reversal**
3. **London Continuation**

These specialists are consulted by default only when the current market state resembles their validated domain. They receive no trade quota and no automatic capital allocation.

## Adaptive opportunity mandate

Two independent Senior Trader agents may identify situation-specific opportunities outside the named playbooks. They may:

- Interpret the current regime and market structure
- Select from the approved deterministic feature and indicator registry
- Combine validated evidence in a new situation-specific thesis
- Request specialist analysis
- Define entry, invalidation, exit, expiration, and evidence requirements
- Propose new indicators, signs, or strategies for research

They may not:

- Invent an indicator value that was not deterministically calculated
- Deploy new executable code during a live session
- Treat a new strategy as production-qualified without validation
- Bypass the risk engine or broker safeguards
- Increase risk because both agents use persuasive language

## Initial instrument universe

Default research priority:

- GBP/USD
- EUR/USD

Additional instruments are research-only until broker suitability, execution cost, liquidity, sizing precision, and strategy performance are independently validated.

---

# 2. NON-NEGOTIABLE ARCHITECTURAL PRINCIPLE

The system must function **through Claude Code**, but safety-critical runtime behavior must not depend on an active conversational turn.

Claude is the firm's:

- Chief executive coordinator
- Senior engineer
- Quantitative research director
- Strategy-review board
- Post-trade analyst
- Documentation and governance engine

Deterministic local services are the firm's:

- Market-data listener
- Session clock
- Feature calculator
- Risk gate
- Position-sizing calculator
- Broker adapter
- Order-state reconciler
- Stop-loss verifier
- Kill switch
- Persistent audit writer

## Prohibited architecture

Do not build a system in which an LLM response directly sends an unrestricted broker order.

## Required order path

```text
Market data
  -> deterministic feature engine
  -> strategy candidate specification
  -> Claude-assisted or deterministic analysis
  -> deterministic validation
  -> independent deterministic risk gate
  -> human approval during probation, when required
  -> price/spread revalidation
  -> broker adapter
  -> broker order acknowledgement
  -> stop-loss confirmation
  -> continuous reconciliation
```

No stage may be skipped.

---

# 3. OPERATING CONSTITUTION

## 3.1 Capital mandate

- Initial closed equity: **$250**
- No profit target
- Maximum initial single-trade loss: **$25**
- Maximum single-trade risk is a ceiling, not a default
- All risk uses closed, reconciled broker equity
- Floating profit does not unlock a higher capital tier
- Deposits, withdrawals, credits, rebates, and manual broker adjustments must be separated from trading P&L

## 3.2 Initial adaptive risk ladder

At the $250 capital tier:

| Classification | Maximum risk | Initial-equity share |
|---|---:|---:|
| No qualified edge | $0 | 0% |
| Standard edge | $2.50 | 1% |
| Strong edge | $7.50 | 3% |
| High edge | $12.50 | 5% |
| Exceptional edge | $25.00 | 10% |

A high potential payout is not the same as high edge. Risk elevation requires validated expectancy, regime alignment, structural confirmation, acceptable execution conditions, and an eligible account state.

## 3.3 Risk ceiling formula

For each trade:

```text
allowed_trade_risk = minimum(
  tier_max_risk,
  capital_tier_exceptional_ceiling,
  current_equity_based_ceiling,
  remaining_session_loss_capacity,
  remaining_weekly_loss_capacity,
  broker_and_margin_safe_capacity
)
```

**[F-1]** `broker_and_margin_safe_capacity` must be computed from the
**per-instrument** margin rate reported by the broker, never the account-level
rate. The 2026-07-29 practice audit measured GBP_USD at 5% against an
account-level 2% — using the account rate overstates capacity by 2.5x on that
instrument. A `margin_utilization_cap_fraction` bounds the share of equity that
may be committed as margin. At the $250 tier this overlay frequently binds
*before* the tier ladder does, which is intended.

The technical invalidation stop is defined first. Position size is calculated second.

```text
position_size = allowed_trade_risk / loss_per_unit_at_technical_stop
```

If broker minimum size, spread, commission, margin, or stop-distance rules make the trade exceed the approved loss, reject the trade.

## 3.4 Initial account controls

At $250 closed equity:

- Maximum open positions: **1**
- Maximum exceptional-risk trades per session: **1**
- Maximum trades per London session: **2**
- Maximum session realized loss: **$25**
- A $25 loss ends the session immediately
- Any session loss disables exceptional-risk classification for the remainder of that session
- Maximum weekly realized loss: **$37.50**
- Initial live-trading floor: **$200**
- At or below $200 closed equity, live entries are disabled and the system returns to shadow mode
- Stop widening is prohibited
- Averaging into a losing trade is prohibited
- Martingale and recovery sizing are prohibited

These amounts must become configuration values with tests, not scattered constants.

## 3.5 No-profit-target doctrine

The system has no obligation to trade and no obligation to earn a specific amount per session.

It must never:

- Force a setup to reach a target
- Increase frequency because the session is quiet
- Continue trading solely because profit is below a desired amount
- Expand risk because earlier trades were profitable
- Treat realized gains as permission to ignore risk limits

**[A-2]** Every prohibition above is a prohibition on an *input*, not on size.
Each names a fact about the firm — a target, a quiet session, profit below a
desired amount, earlier gains — and forbids it from influencing exposure. The
conviction-discipline clause in §6.6 asks the firm to claim the evidence it
holds, which is a statement about a different input class entirely. Where the
two appear to conflict, this section wins: no aspiration, elapsed time, or
progress toward any goal may enlarge a position by any mechanism, and the firm
must remain unable to represent a profit target at all.

---

# 4. SELF-ADJUSTING CAPITAL TIER SYSTEM

The system must automatically adjust whenever the trading account's **verified closed equity doubles relative to the current confirmed tier anchor**.

## 4.1 Tier anchors

Initial sequence:

```text
$250
$500
$1,000
$2,000
$4,000
$8,000
$16,000
$32,000
$64,000
$128,000
...
```

## 4.2 Promotion requirements

A tier promotion occurs only when all conditions are true:

1. All positions are closed.
2. Broker-reported closed equity is reconciled.
3. Closed equity is at or above the next milestone.
4. The milestone is produced by trading P&L and recognized deposits according to configured capital-accounting rules.
5. There are no unresolved fills, rejected-order ambiguities, duplicate orders, missing stops, or reconciliation errors.
6. The runtime health check passes.
7. The promotion event is written to the audit log.

**[D-2, R: C-3]** Deterministic conditions only **arm** a promotion; they do
not apply it. An armed promotion is presented to the owner and lapses unapproved
after a configured window (default 7 days), after which it re-arms while
conditions still hold. Automatic promotion is prohibited: a tier change doubles
every live risk limit and is therefore a production change under §0 rule 4. The
owner may additionally freeze scaling globally.

**[D-3]** Deposits, withdrawals, credits, rebates, and manual broker adjustments
**never** advance a milestone tier. Milestones recognize trading P&L only, which
is what condition 4 above means; capital-accounting rules may not be configured
to relax this.

## 4.3 Scaling formula

At capital tier `n`:

```text
capital_anchor(n) = 250 * 2^n
scale_factor(n) = capital_anchor(n) / 250
```

Initial dollar limits scale by the tier factor unless a separate safety cap, broker constraint, liquidity constraint, or owner-approved ceiling applies.

Example:

| Tier anchor | Standard | Strong | High | Exceptional ceiling |
|---:|---:|---:|---:|---:|
| $250 | $2.50 | $7.50 | $12.50 | $25 |
| $500 | $5 | $15 | $25 | $50 |
| $1,000 | $10 | $30 | $50 | $100 |
| $2,000 | $20 | $60 | $100 | $200 |
| $4,000 | $40 | $120 | $200 | $400 |

## 4.4 Critical refinement: risk contraction

Risk must contract based on current reconciled equity even if the account previously reached a higher tier.

Use two concepts:

- **Milestone tier:** highest confirmed doubling milestone reached
- **Active risk base:** current closed equity after drawdown controls

The system must not continue sizing as though equity were $1,000 when current equity is $780.

## 4.5 Demotion and drawdown behavior

- Position-size calculations always use current closed equity.
- If current equity falls below a tier's lower safety boundary, the active operating permissions contract.
- Tier history remains recorded, but larger risk permissions are suspended.
- Strategy or instrument permissions unlocked at higher tiers may be suspended if their execution economics are no longer appropriate.
- A drawdown-state machine may impose more restrictive risk than the normal tier ladder.

## 4.6 Scaling is not permission to degrade quality

A larger account does not automatically authorize:

- More trades
- More strategies
- More instruments
- Lower-quality setups
- Wider spreads
- Reduced testing
- Excessive correlated exposure

Capability expansions require independent validation.

---

# 5. EDGE CLASSIFICATION SYSTEM

The system must distinguish **high yield** from **high edge**.

## 5.1 Evidence model

Do not force every opportunity through one opaque confidence number. Store an auditable evidence vector and, where a composite score is used, version the calculation and preserve each component.

Minimum evidence dimensions:

- Historical or analog evidence quality
- Regime fit
- Structural and order-flow confirmation
- Execution conditions
- Higher-timeframe or cross-market context
- Thesis agreement and disagreement
- Model or rule stability
- Novelty level
- Data quality
- Expected value after costs

For an established production playbook, historical expectancy may receive substantial weight. For a novel or adaptive thesis, the absence of validated expectancy must reduce—not increase—its live risk eligibility.

**[A-2] Pressure invariance.** Every dimension above is a property of the market,
not of the firm. The evidence vector — and therefore the evidence class and the
tier ceiling it implies — must be a **pure function of the Market State Packet**
(§6A). The same packet must produce a bit-identical classification regardless of
equity, elapsed time, session or cumulative P&L, trades taken, time remaining in
the window, or progress toward any aspiration.

Firm state is a separate input class. It reaches the deterministic risk gate,
where it may only *reduce* allowed risk (§3.3), and it must not reach
classification at all. Implementations must make this structural rather than
procedural: the packet separates market-derived state from firm state, and the
classifier's signature admits only the former, so reading firm state during
classification is a type error rather than a review finding.

This is a testable property and §21 requires it to be tested.

## 5.2 Evidence classes and risk eligibility

Use the following default evidence classes:

| Evidence class | Description | Default live eligibility |
|---|---|---|
| E0 | Missing, stale, contradictory, or malformed evidence | Reject |
| E1 | New hypothesis or untested indicator/sign | Research or shadow only |
| E2 | Recombination of validated primitives with limited analog support | Paper or tightly limited probation only |
| E3 | Validated strategy/playbook with acceptable current regime fit | Standard or Strong review |
| E4 | Robustly validated strategy subtype with strong current fit and execution quality | High review |
| E5 | Rare exceptional case with qualified production history and all exceptional gates passed | Exceptional review |

A score or evidence class does not authorize size. It only determines the maximum tier the deterministic risk gate may consider.

## 5.3 Exceptional-edge gate

All must pass:

- Exact strategy subtype or adaptive thesis class is production-qualified for exceptional sizing; newly invented or E1/E2 ideas are ineligible
- Current regime matches validated favorable regime
- Net expectancy remains positive after costs and stress assumptions
- Independent structural confirmations are present
- Spread and slippage are within limits
- Market data is fresh and complete
- Broker connection is healthy
- Stop is technically valid and broker-compatible
- No disqualifying high-impact event is present
- Account is not in a caution, drawdown, or degraded-execution state
- No previous loss occurred in the session
- During probation, explicit human approval is received

Claude confidence language, narrative persuasiveness, or projected reward alone can never unlock this tier.

---

# 6. AGENT ORGANIZATION

Use the smallest number of high-quality agents that produces genuine specialization. Do not create agents merely to simulate a large firm. The central change in Version 2 is the creation of an independent senior-trader pair above the strategy specialists.

## 6.1 Executive and portfolio agents

### A. Firm Governor / CEO Agent

**Purpose:** Coordinate the complete workflow and maintain institutional discipline.

**May:**

- Initiate pre-session workflow
- Request analysis from senior traders and specialists
- Consolidate evidence
- Produce the final institutional brief
- Trigger research and review workflows

**May not:**

- Override risk engine
- Directly submit unrestricted orders
- Change production strategy files
- Promote a challenger

### B. Chief Quant Agent

**Purpose:** Own research methodology, feature definitions, tests, and strategy validation.

**Outputs:**

- Research specifications
- Backtest reports
- Walk-forward reports
- Sensitivity analyses
- Challenger proposals
- Multiple-testing and experiment ledgers

### C. Chief Risk Officer Agent

**Purpose:** Independently challenge candidate trades and system changes.

Its advisory veto is supplemented by an absolute deterministic risk-engine veto.

### D. Market Opportunity Arbiter / Head Trader

**Purpose:** Compare the independently completed Senior Trader Alpha and Beta theses, identify genuine agreement and unresolved disagreement, consult relevant specialists, and determine whether any candidate deserves formal risk review.

**Rules:**

- Must not reveal Alpha's analysis to Beta or Beta's analysis to Alpha before both submit locked first-pass reports.
- Must distinguish independent agreement from duplicated evidence.
- Must not average two weak theses into one apparently strong thesis.
- May reject both traders and declare no trade.
- Cannot transform an E1 or E2 hypothesis into a high-risk live trade.

### E. Learning Director Agent

**Purpose:** Run post-session analysis and coordinate improvement proposals without altering live production.

## 6.2 Independent senior trader pair

### F. Senior Trader Alpha — Regime and Structure Lead

**Mandate:** Develop an independent, situation-specific market thesis without being restricted to a named strategy.

Primary orientation:

- Regime classification
- Market structure
- Liquidity and auction behavior
- Volatility transition
- Session context
- Cross-timeframe coherence

May:

- Select relevant indicators and features from the approved registry
- Propose an existing playbook when appropriate
- Construct an adaptive thesis from validated primitives
- Define a new research hypothesis
- Call specialist agents for domain review
- Recommend no trade

Must output a complete Adaptive Trade Thesis Schema. May not see Beta's first-pass conclusion before locking its own.

### G. Senior Trader Beta — Statistical and Adversarial Lead

**Mandate:** Form a separate situation-specific thesis and actively search for reasons Alpha's likely interpretation could fail, without seeing Alpha's report beforehand.

Primary orientation:

- Statistical analogs
- Base rates
- Indicator interaction
- Execution economics
- Counterfactual scenarios
- Failure modes and invalidation

May exercise the same opportunity-generation authority as Alpha. It must identify what evidence would disprove its own thesis and may recommend no trade.

### Senior-trader independence protocol

1. Both receive the same immutable Market State Packet.
2. They work in separate context windows or subagent runs.
3. Neither receives the other's reasoning before first-pass submission.
4. First-pass reports are hashed or marked immutable.
5. The Arbiter compares them only after both are complete.
6. Any second-round response must explicitly list what changed after seeing the opposing thesis.
7. Agreement earns value only when based on materially independent evidence.

## 6.3 Strategy specialist bench

These agents remain experts but no longer define the firm's boundaries.

### H. London Breakout Specialist

Analyzes validated breakout variants when requested or when a deterministic relevance classifier identifies a breakout-like state.

### I. Asian Range Sweep and Reversal Specialist

Analyzes liquidity-sweep and failed-acceptance reversal structures when relevant.

### J. London Continuation Specialist

Analyzes validated directional continuation structures when relevant.

### Specialist operating rule

- A specialist may support, reject, or qualify a senior-trader thesis.
- A specialist may not force the firm to trade its playbook.
- Irrelevant specialists should return `NOT_APPLICABLE`, not manufacture a signal.
- Specialist performance is evaluated only on opportunities within its declared domain.

## 6.4 Context and evidence agents

### K. Regime Analyst

Produces a deterministic-data-grounded regime packet covering trend, balance, compression, expansion, volatility, and event distortion.

### L. Macro and Event Risk Analyst

Maps scheduled events and restrictions. Missing or stale calendar data causes fail-closed behavior according to configuration.

### M. Liquidity and Structure Analyst

Maps validated structural levels and expresses them as reproducible data where possible rather than subjective chart prose.

### N. Historical Analog and Base-Rate Agent

Searches only approved historical data for comparable situations and reports:

- Search definition
- Number of analogs
- Similarity method
- Outcome distribution after costs
- Regime breakdown
- Sensitivity to similarity thresholds
- Data limitations

It must not cherry-pick a favorable analog set after seeing the desired trade direction.

### O. Execution Conditions Agent

Assesses spread, expected slippage, liquidity, fill risk, broker constraints, and whether the expected edge survives current costs.

## 6.5 Alpha research and validation agents

### P. Trade Auditor

Classifies each result:

- Good win
- Lucky win
- Good loss
- Bad loss
- Execution error
- Strategy error
- Risk error
- Data error
- Operational error
- Thesis-quality error
- Invalidation-discipline error

### Q. Pattern Discovery Agent

Searches for candidate improvements while controlling for multiple-testing bias and data leakage. It creates hypotheses, not live permissions.

### R. Indicator and Feature Research Agent

May propose new deterministic indicators, signs, transformations, interactions, or market-state descriptors. Every proposal must include:

- Economic or behavioral rationale
- Exact deterministic definition
- Required data
- Leakage assessment
- Parameter count
- Stability expectations
- Falsification test

### S. Strategy Designer Agent

Converts observations into explicit, testable candidate strategies. It may create strategy-agnostic state policies, conditional playbooks, ensembles, or meta-strategies.

### T. Model Validation Agent

Runs:

- In-sample analysis
- Locked holdout testing
- Walk-forward testing
- Monte Carlo analysis
- Spread/slippage stress testing
- Parameter sensitivity
- Regime stability
- Probability-of-overfitting diagnostics
- Deflated performance metrics where appropriate

### U. Strategy Evolution Agent

Creates challengers but cannot write directly to production configuration.

## 6.6 Agent quality and incentive policy

- Use the highest-quality available Claude model for Senior Trader Alpha, Senior Trader Beta, Market Opportunity Arbiter, governance, risk, quantitative review, promotion decisions, and complex debugging.
- Use lower-cost models only for bounded extraction, formatting, routine test generation, or log classification.
- Score agents on calibrated decision quality, net expectancy after costs, drawdown contribution, invalidation discipline, no-trade quality, evidence integrity, and rule adherence—not gross P&L alone.
- Do not reward an agent for taking more trades.
- A lucky win must not improve an agent's rating as much as a well-structured good loss or correctly rejected trade.
- Every agent must have a narrow role, explicit tools, prohibited actions, and a machine-validatable output schema.
- No agent may receive broker credentials unless technically unavoidable; credentials remain isolated in the broker service.

### Conviction discipline [A-2]

The scoring rules above are one-sided as written. They forbid rewarding an agent
for taking more trades, but say nothing about an agent that consistently claims
less than the evidence it holds. That asymmetry is not neutral: over-sizing is
already structurally impossible — the risk gate only ever lowers a tier — while
under-sizing is invisible, costs an agent nothing, and imposes a systematic
negative bias on expectancy that no control detects. This clause closes it.

**The firm is expected to claim the evidence it holds.** Systematically
classifying below the evidence available is a calibration error, scored
symmetrically with classifying above it. Where the deterministic record shows a
thesis was entitled to a higher evidence or novelty class on data the agent held
at decision time, that is a scored miss.

Bounds on that expectation, all of which are absolute:

- A correct `no trade` is never a miss. §0 rule 6 makes it a preferred outcome
  and this clause does not touch that.
- A correct `NOT_APPLICABLE` from a specialist outside its domain is never a
  miss (§6.3).
- Uncertainty resolves downward. Where the evidence genuinely does not
  distinguish two classes, the lower class is correct and scoring it as a miss
  is itself an error.
- Scoring is applied **post-session only**, by the Learning Director against
  reconciled data. An in-session under-classification signal would itself become
  a pressure input and is prohibited.
- Classification remains pressure-invariant per §5.1. This clause changes what
  is *measured*; it grants no permission and adds no input to the risk gate.

Where this clause and §3.5, §0 rule 6, or §0 rule 7 appear to conflict, they win.
Conviction is a claim about evidence. It is never a claim about need.

## 6.7 Adaptive Trade Thesis Schema

Every Senior Trader candidate must include at least:

```yaml
thesis_id: unique_id
trader_id: alpha_or_beta
timestamp_utc: required
instrument: required
direction: long_short_or_none
market_state:
  regime: required
  volatility_state: required
  session_phase: required
observations: []
selected_features:
  - feature_id: versioned_id
    observed_value: deterministic_value
    relevance: explanation
specialist_consultations: []
historical_analogs:
  query_id: optional
  sample_size: 0
  net_outcome_summary: null
thesis:
  causal_or_behavioral_rationale: required
  expected_path: required
  failure_scenario: required
trade_plan:
  entry_rule: explicit
  invalidation_rule: explicit
  exit_rule: explicit
  expiration_rule: explicit
novelty_class: N0_N1_N2_or_N3
evidence_class: E0_to_E5
estimated_costs: required
expected_value_basis: required
uncertainties: []
confidence_calibration_reference: required
```

Free-form prose may accompany this schema but cannot replace it.

## 6.8 Novelty classes

| Class | Meaning | Permission |
|---|---|---|
| N0 | Existing validated production playbook | Eligible according to its approved risk permissions |
| N1 | New combination of already validated primitives and indicators | Shadow/paper by default; limited probation only with explicit policy |
| N2 | New indicator, sign, rule, parameterization, or strategy logic | Research and shadow only |
| N3 | Exploratory idea without reproducible specification | Research notebook only |

No N1, N2, or N3 thesis may receive Exceptional risk. N2 and N3 may never place live orders.

---

# 6A. ADAPTIVE OPPORTUNITY WORKFLOW

```text
Deterministic market data and feature calculation
  -> immutable Market State Packet
  -> independent Senior Trader Alpha analysis
  -> independent Senior Trader Beta analysis
  -> first-pass report lock
  -> Arbiter comparison
  -> relevant specialist consultations
  -> historical analog and execution review
  -> novelty and evidence classification
  -> deterministic candidate validation
  -> deterministic risk gate
  -> human approval during probation or when required
  -> price/spread revalidation
  -> broker execution and stop confirmation
```

## Market State Packet

The packet must be generated deterministically and may include:

- Timestamped bid/ask and spread
- Multi-timeframe bars
- Session phase
- Volatility measures
- Range and displacement measures
- Trend and balance descriptors
- Liquidity/structure levels
- Approved indicator values
- Scheduled-event state
- Broker and data health
- Current positions, P&L, and risk capacity

Both senior traders receive the exact same packet checksum.

## Situational freedom boundary

Senior traders are free to interpret, combine, and prioritize approved evidence. They are not free to fabricate data, rewrite indicator formulas mid-session, fit parameters to the current chart, or convert an unvalidated idea into high-risk live exposure.

# 7. CLAUDE CODE IMPLEMENTATION

## 7.1 Required Claude Code components

Build and document:

- Project-level `CLAUDE.md`
- Custom subagents under `.claude/agents/`
- Reusable skills under `.claude/skills/`
- Project settings and permissions
- Hooks for tests, secret scanning, production-file protection, and deployment gates
- MCP servers only where they reduce cost or provide required capabilities
- Clear separation between research and live runtime commands

## 7.2 Required Claude permissions model

Claude should have broad rights inside development and research directories but restricted rights for:

- Live broker credentials
- Production risk configuration
- Production strategy manifests
- Deployment scripts
- Live-order commands
- Database destructive operations

Implement approval gates for sensitive commands.

## 7.3 Required hooks

At minimum:

1. **Pre-edit protection:** block unauthorized edits to production risk and strategy manifests.
2. **Post-edit tests:** run formatting, type checks, unit tests, and configuration validation.
3. **Secret scanner:** reject commits or file writes containing credentials.
4. **Pre-commit gate:** require passing test suite and clean configuration diff.
5. **Production promotion gate:** require signed promotion record and owner approval.
6. **Broker command gate:** prohibit direct shell invocation outside the approved broker service.
7. **Audit hook:** record material configuration changes.

## 7.4 Cost-aware model routing

Create a model-routing policy:

- **Frontier/highest-quality model:** governance, architecture, risk reviews, strategy changes, production incidents, challenger promotion.
- **Mid-tier model:** code implementation, refactoring, ordinary debugging, report synthesis.
- **Low-cost model or deterministic code:** repetitive extraction, schema conversion, log parsing, basic summaries.

Model routing must never lower quality for safety-critical decisions merely to reduce cost.

---

# 8. DETERMINISTIC LOCAL RUNTIME

Use Python unless a broker SDK or operating-system integration strongly justifies another language.

## 8.1 Services

### Market Data Service

Responsibilities:

- Connect to approved broker/data source
- Receive bid, ask, candles, timestamps, and available volume
- Normalize symbols and precision
- Detect stale or missing data
- Persist required raw data
- Publish health status

### Session Clock Service

Responsibilities:

- Use IANA zones `America/Chicago`, `Europe/London`, and UTC
- Correctly handle DST divergence
- Control startup, activation, entry cutoff, flattening, and review windows
- Never use a fixed UTC offset for the London open

### Feature Engine

Responsibilities:

- Calculate strategy features deterministically
- Version every feature definition
- Avoid future leakage
- Reproduce historical and live calculations identically

### Candidate Engine

Responsibilities:

- Generate schema-valid strategy candidates
- Include entry, invalidation, targets, expiration, features, strategy version, and evidence
- Never submit orders

### Risk Engine

Responsibilities:

- Read reconciled equity
- Determine capital tier and drawdown state
- Enforce risk ladder
- Enforce session and weekly limits
- Enforce position and trade-count limits
- Enforce exceptional-edge gates
- Reject stale or malformed candidates
- Produce immutable approval or rejection record

### Position Sizing Engine

Responsibilities:

- Convert technical stop distance to monetary loss
- Apply symbol pip/tick value and contract size
- Include spread and commission assumptions
- Round down to broker-supported size increment
- Reject if minimum size exceeds allowed risk

### Broker Adapter

Responsibilities:

- Abstract broker-specific API
- Submit idempotent orders
- Attach or immediately place protective stop
- Confirm acknowledgement and fill
- Prevent duplicate order submission
- Reconcile positions and orders
- Handle rejected, partial, cancelled, and unknown states

### Order State Reconciler

Responsibilities:

- Treat broker state as authoritative for live exposure
- Compare local state to broker state
- Disable entries on mismatch
- Escalate unresolved discrepancies

### Kill Switch

Must support:

- Manual owner activation
- Risk-limit activation
- Data-health activation
- Broker-health activation
- Stop-loss failure activation
- Drawdown activation
- Configuration-integrity activation

Actions:

- Disable new entries
- Cancel pending entries where safe
- Preserve or close live positions according to emergency policy
- Notify owner
- Write incident record

### Audit Service

Append-only records for:

- Market snapshots used for decisions
- Candidates
- Rejections
- Agent analyses
- Human approvals
- Risk decisions
- Orders and broker responses
- Position changes
- Session state
- Config changes
- Model changes
- Incidents

---

# 9. REPOSITORY STRUCTURE

Create a dedicated private Git repository.

Recommended structure:

```text
claude-london-trading-firm/
├── CLAUDE.md
├── README.md
├── SECURITY.md
├── CONTRIBUTING.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── .claude/
│   ├── agents/
│   ├── skills/
│   ├── commands/
│   ├── hooks/
│   └── settings.json
├── config/
│   ├── base/
│   ├── research/
│   ├── paper/
│   ├── live/
│   └── schemas/
├── governance/
│   ├── constitution.md
│   ├── risk-policy.md
│   ├── strategy-promotion-policy.md
│   ├── incident-policy.md
│   ├── decision-log.md
│   └── approvals/
├── src/
│   └── trading_firm/
│       ├── market_data/
│       ├── sessions/
│       ├── features/
│       ├── strategies/
│       ├── candidates/
│       ├── risk/
│       ├── sizing/
│       ├── execution/
│       ├── reconciliation/
│       ├── audit/
│       ├── notifications/
│       ├── research/
│       └── cli/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── replay/
│   ├── broker_sandbox/
│   ├── failure_injection/
│   └── acceptance/
├── data/
│   ├── raw/
│   ├── normalized/
│   ├── features/
│   └── research/
├── state/
│   ├── runtime/
│   ├── locks/
│   └── recovery/
├── database/
│   ├── migrations/
│   └── backups/
├── reports/
│   ├── sessions/
│   ├── weekly/
│   ├── monthly/
│   ├── incidents/
│   └── validation/
├── scripts/
├── dashboard/
└── docs/
```

Do not commit live data containing sensitive account information unless encrypted and explicitly approved.

---

# 10. DATA AND STORAGE

## 10.1 Initial database

Use SQLite in WAL mode for the low-cost laptop deployment if concurrency tests prove sufficient.

Design migrations so PostgreSQL can be adopted later without redesigning domain models.

## 10.2 Minimum entities

- instruments
- market_ticks or market_bars
- data_quality_events
- economic_events
- sessions
- strategy_versions
- feature_versions
- model_versions
- candidates
- candidate_features
- agent_reviews
- risk_decisions
- approvals
- orders
- fills
- positions
- stops
- account_snapshots
- capital_tiers
- tier_transitions
- drawdown_states
- incidents
- configuration_versions
- promotion_records
- audit_events

## 10.3 Time requirements

- Store timestamps in UTC
- Preserve source timezone and source timestamp
- Use timezone-aware datetimes only
- Test US/UK DST mismatch weeks explicitly

## 10.4 Data retention

Retain all data required to reproduce a decision. Raw tick retention may be bounded by storage policy, but aggregated bars, decision snapshots, orders, fills, and audit records must remain reproducible.

---

# 11. STRATEGY, PLAYBOOK, AND ADAPTIVE POLICY STANDARD

Each named strategy, specialist playbook, adaptive policy, indicator, feature, and reusable trading primitive must be declarative and versioned. A Senior Trader may construct a one-session thesis without creating a permanent strategy, but the thesis must still use the Adaptive Trade Thesis Schema and novelty controls.

Minimum manifest fields:

```yaml
strategy_id: london_breakout
version: 1.0.0
status: research
instruments: [GBP_USD, EUR_USD]
session_definition: london_v1
features: []
entry_rules: []
invalidation_rules: []
exit_rules: []
expiration_rules: []
regime_filters: []
news_filters: []
spread_limits: {}
slippage_limits: {}
risk_permissions:
  standard: false
  strong: false
  high: false
  exceptional: false
validation_record_id: null
promotion_record_id: null
```

Production manifests are immutable. Any modification creates a new version.

## Adaptive policy manifest

Create a separate versioned manifest governing what Senior Traders may combine live:

```yaml
adaptive_policy_id: senior_trader_policy
version: 1.0.0
approved_feature_registry: []
approved_indicator_registry: []
approved_trading_primitives: []
allowed_novelty_classes_live: [N0]
limited_probation_classes: []
required_analog_sample_size: null
required_evidence_class_by_risk_tier: {}
prohibited_behaviors:
  - intraday_parameter_fitting
  - unversioned_indicator_creation
  - lookahead_data
  - post_loss_risk_escalation
  - narrative_only_edge_claim
```

A change to the adaptive policy is a production change and requires the same promotion and approval controls as a strategy change.

---

# 12. RESEARCH AND VALIDATION PROTOCOL

## 12.1 Research separation

Use distinct environments:

- Research
- Historical replay
- Shadow
- Paper
- Live

Research code must never place a live order.

## 12.2 Validation ladder

```text
Specification
  -> deterministic implementation
  -> unit tests
  -> historical replay
  -> holdout evaluation
  -> walk-forward evaluation
  -> cost stress test
  -> Monte Carlo analysis
  -> shadow mode
  -> paper trading
  -> limited live probation
  -> production qualification
```

## 12.3 Required metrics

- Net expectancy after costs
- Win rate
- Average win and loss
- Profit factor
- Maximum drawdown
- Time under water
- Sharpe and Sortino where meaningful
- MAE and MFE
- Slippage
- Fill rate
- Rejection rate
- Performance by regime
- Performance by instrument
- Performance by session time
- Strategy attribution
- Calibration by edge tier
- Probability of overfitting diagnostics
- Senior-trader calibration and Brier/log-loss style scoring where applicable
- Performance of agreement, disagreement, and no-trade decisions
- Performance by novelty class
- Research trials attempted and selection-bias accounting

## 12.4 Anti-overfitting requirements

- No future leakage
- No look-ahead indicators
- Purged or embargoed validation where appropriate
- Explicit transaction-cost model
- Parameter sensitivity analysis
- Multiple-testing record
- No promotion based solely on one favorable interval
- Separate discovery and confirmation samples
- Pre-registered hypothesis or experiment record before confirmation testing
- Immutable holdout periods that Senior Trader and research agents cannot inspect during development
- Trial-count tracking across indicators, parameter sets, strategies, and agent-generated variants
- No use of live P&L alone as evidence that a newly generated strategy has edge

## 12.5 Promotion authority

Promotion requires:

- Validation Agent recommendation
- Chief Quant review
- Chief Risk review
- Reproducible report
- Signed promotion record
- Owner approval for live permission changes

## 12.6 Minimum evidence requirements [D-5, R: M-8]

v2.0.0 left the probation sample as "a predefined sample". These are the
predefined values, ratified 2026-07-29 and retained:

| Decision | Minimum sample |
|---|---|
| Probation exit review | 30 correctly processed signals **[D-5]** |
| Per-strategy tier qualification above Standard | 50 trades across shadow, paper, and live combined |
| Challenger promotion | Separate confirmation sample per §12.4 |
| Edge-score / evidence-weight recalibration | 100 classified candidates with recorded outcomes (§5.1) |

A sample below these thresholds is not evidence of edge regardless of its
profit factor.

## 12.7 Research-code adversarial review (mandatory) [A-1]

Research code is order-path-adjacent in consequence: its outputs decide which
strategies advance toward real capital. A defect that makes a losing strategy
look profitable is more dangerous than a crash — it is persuasive, silent, and
survives a green test suite.

Precedent establishing this requirement (2026-07-30): replay filled stop-order
entries at the strategy's trigger price even when the entry bar had already
opened beyond it, booking prices that never traded, and simultaneously handed
the risk engine a stop distance the trade never had — breaching the §3 risk cap.
A 236-test suite passed throughout. Two published results changed sign once
corrected.

Requirements:

1. **Publication gate.** No number produced by research code may be published in
   a validation report, cited in a promotion record, or counted toward §12.6
   minimum evidence until the code paths that produced it have passed an
   adversarial review.
2. **Independence and posture.** The review must be independent of the code's
   author and must default to refutation: a finding is not actionable until
   independently reproduced.
3. **Minimum coverage.** Look-ahead and data leakage; fill realism and the
   transaction-cost model; rule logic versus the §11 manifest; claim-versus-
   computation integrity (every published figure recomputed independently from
   committed data); and test adequacy, including mutation testing of the
   engine's core invariants.
4. **Refutations are recorded.** Confirmed and refuted findings are both logged.
   Acting on an unverified claim is itself a defect vector.
5. **Re-review triggers.** Any change to the replay fill model, cost model,
   feature boundaries, or a strategy's rule logic voids the prior review for the
   affected paths.
6. **Honest denominators and disclosed coverage.** Published tables state sample
   size as sessions actually capable of producing features, and disclose known
   data-coverage holes. A report that overstates its own evidence is a §12.4
   violation even when every P&L figure is correct.
7. **Audit trail.** Review outcome — confirmed, refuted, and any findings left
   unverified — is recorded in `governance/decision-log.md` with a pointer to
   the report (§0 rule 11; superseded tables are annotated, never rewritten).

---

# 13. LIVE TRADING PROBATION

Because the system starts with real capital, live deployment must still be staged.

## Required sequence

1. Broker sandbox or demo connection
2. Full order lifecycle tests
3. Shadow sessions with live data
4. Paper sessions
5. Owner-approved live activation
6. Human approval for every live trade during probation
7. Review after a predefined sample of correctly processed signals

A profitable short run does not prove readiness. Operational correctness, stop protection, reconciliation, and rule adherence are mandatory.

## Trade approval card

Every approval-required candidate must show:

- Instrument
- Strategy/playbook version or adaptive thesis ID and novelty class
- Direction
- Proposed entry
- Technical stop
- Target and exit method
- Maximum dollar loss
- Position size
- Estimated spread, commission, and slippage
- Expected net reward-to-risk
- Edge tier and supporting components
- Regime classification
- Economic-event status
- Candidate expiration
- Risk-engine status
- Current session and weekly loss capacity

Approval expires if market conditions move outside configured tolerance.

---

# 14. LONDON SESSION WORKFLOW

**[R: C-2] The schedule is anchored in `Europe/London`. Chicago times are
display-only and must never be the configured value.**

| Boundary | Europe/London (authoritative) | America/Chicago (display) |
|---|---|---|
| Runtime and broker health checks | 07:15 | ~01:15 |
| Asian range finalized | 07:30 | ~01:30 |
| Market-state packet, senior-trader analyses, briefing | 07:40 | ~01:40 |
| Trading activation | 08:00 | ~02:00 |
| New-entry cutoff | 10:30 | ~04:30 |
| Mandatory flatten / review transition | 11:00 | ~05:00 |

Why this is not a stylistic choice: the US and UK change clocks on different
dates. On **27 calendar days in 2026** a Chicago-anchored 02:00 resolves to
London **07:00** — an hour before the London open, inside the window from which
the Asian range is computed. A firm configured on Chicago wall-clock would trade
the wrong hour on every one of those days, silently. The configuration therefore
stores London wall-clock values and a `Europe/London` anchor; Chicago is
rendered for the owner's convenience only.

**[F-5] Rollover protection.** The 21:00 UTC daily rollover exhibits a ~10x
spread blowout with near-zero depth on the practice feed. The 11:00 London
flatten boundary is **inviolate**: nothing may hold or adjust a position through
rollover. Any future logic that would trade near it must first clear a
configured rollover blackout window (default: 30 minutes before to 45 minutes
after 21:00 UTC), during which new entries are rejected.

## Session state machine

```text
OFFLINE
-> STARTING
-> HEALTH_CHECK
-> DATA_WARMUP
-> BRIEFING
-> ACTIVE
-> ENTRY_CUTOFF
-> MANAGE_ONLY
-> FLATTENING
-> RECONCILIATION
-> REVIEW
-> CLOSED
```

Any critical failure transitions to `HALTED`.

---

# 15. SELF-IMPROVEMENT LOOP

The system may learn continuously, but it may not mutate live strategy continuously.

## Champion-challenger model

- Production strategy is the **Champion**
- Improvements are **Challengers**
- Champion remains immutable during live sessions
- Challengers run in research, replay, shadow, or paper modes
- Promotion requires the formal process

## Post-session loop

```text
Close and reconcile session
-> audit decisions and execution
-> classify outcomes
-> update analytics
-> detect drift
-> identify research questions
-> generate challenger hypotheses
-> test challengers
-> reject or queue promotion review
```

## Learning inputs

Include:

- Trades taken
- Qualified candidates rejected by risk
- Candidates rejected by trader/owner
- Near-miss setups
- No-trade sessions
- Execution failures
- Spread and slippage behavior
- Regime misclassification
- Model calibration
- Alpha/Beta independent agreement and disagreement
- Specialist relevance and `NOT_APPLICABLE` accuracy
- Adaptive-thesis novelty class and subsequent validation outcome
- Indicators or signs proposed but rejected

Do not train only on winning trades.

---

# 16. BROKER AND DATA CONNECTOR AUDIT

Claude must produce a connector audit before selecting an implementation.

## Required broker capabilities

- Legal availability to the owner’s jurisdiction
- Account type and regulatory status verified
- API access for market data and trading
- Demo or sandbox environment
- Position-size increments compatible with $250 capital
- Broker-native stop orders
- Clear order and fill identifiers
- Idempotency or duplicate-order protection strategy
- Account equity endpoint
- Open orders and positions endpoints
- Historical data access or approved secondary source
- Documented rate limits
- Stable authentication
- Mobile emergency access

## Audit output

For each broker candidate:

- Regulatory/entity verification
- API suitability
- Minimum order size
- Margin and leverage constraints
- Spread/commission model
- Stop-order behavior
- Partial fill behavior
- Weekend/session behavior
- Sandbox quality
- Python SDK or REST/WebSocket support
- Laptop reliability considerations
- Estimated operating cost
- Recommendation and rejected alternatives

Do not connect live funds until the owner approves the broker audit.

---

# 17. SECURITY

## Required controls

- Secrets in OS keychain or approved encrypted secret store
- `.env` only for noncommitted local references; never commit actual secrets
- Least-privilege broker API permissions
- Separate demo and live credentials
- Production mode requires explicit environment flag and confirmation
- Encrypt sensitive backups
- Redact account IDs in logs and reports
- Dependency pinning and vulnerability scanning
- Signed or hashed production configuration
- Tamper-evident audit records
- Automatic lockout after repeated authentication failures

## Credential isolation

Claude subagents should interact with the broker through a constrained local interface. They should not read raw credentials.

---

# 18. RELIABILITY ON A LAPTOP

## Minimum operational requirements

- Laptop connected to power during live window
- Sleep and hibernation disabled during session
- Stable wired or high-quality internet where possible
- Process supervisor for automatic restart
- Persistent state checkpoints
- Startup reconciliation before new orders
- Broker-held stops
- Mobile emergency access
- Local notifications plus optional Telegram/Discord notification path
- Regular database backup

## Process supervision

Use the platform-appropriate supervisor:

- macOS: `launchd`
- Linux: `systemd` or equivalent
- Windows: Task Scheduler/service wrapper

Claude must detect the operating system and implement the correct option.

## Restart behavior

After any restart:

1. Load last known local state.
2. Query broker account, positions, orders, and recent fills.
3. Reconcile differences.
4. Verify protective stops.
5. Enter halted/manage-only mode if uncertain.
6. Do not submit a new entry until health is restored.

---

# 19. NOTIFICATIONS AND OWNER CONTROL

At minimum provide:

- Session-start health report
- Candidate approval request
- Order submitted/fill confirmation
- Stop confirmation
- Position closed summary
- Risk halt alert
- Data/broker failure alert
- Tier promotion or demotion alert
- Daily session report
- Weekly performance report

Owner controls:

- Global live enable/disable
- Kill switch
- Approve/reject trade during probation
- Freeze capital scaling
- Freeze strategy promotion
- Disable instrument
- Disable strategy

---

# 20. DASHBOARD

Build a lightweight local dashboard only after the runtime core is stable.

Minimum views:

1. Firm health
2. Current account and tier
3. Session state
4. Open exposure and protection
5. Candidate queue
6. Strategy performance
7. Risk utilization
8. Execution quality
9. Drawdown and high-water mark
10. Incidents
11. Champion/challenger status
12. Senior Trader Alpha/Beta thesis comparison
13. Specialist consultations and relevance
14. Research hypothesis and novelty queue
15. Audit search

Use a minimal local framework such as Streamlit or a small web UI unless requirements justify more complexity.

---

# 21. TESTING REQUIREMENTS

No live activation until all critical tests pass.

## Unit tests

- Capital tier calculations
- Tier promotion and contraction
- Risk ladder
- Position sizing
- Pip/tick conversion
- Rounding
- Session limits
- Weekly limits
- Drawdown state
- DST logic
- Candidate expiration
- Configuration schema
- Adaptive Trade Thesis schema
- Novelty classification
- Feature/indicator registry enforcement
- Independent-context packet checksum
- Pressure invariance of evidence classification [A-2]

## Integration tests

- Market data to features
- Features to candidate
- Candidate to risk decision
- Approval to order
- Order to stop confirmation
- Broker state to reconciliation
- Audit completeness

## Failure-injection tests

- Internet loss
- Broker timeout
- Duplicate response
- Partial fill
- Rejected stop
- Stale price
- Clock drift
- Database lock
- Process crash
- Laptop restart
- Missing economic calendar
- Corrupted config
- Broker/local position mismatch

## Acceptance tests

- No order can bypass risk engine
- No order can exceed allowed dollar risk within defined rounding tolerance
- No new order after kill switch
- No exceptional trade after a session loss
- No live trade with stale data
- No live trade without required stop capability
- Tier promotion uses closed reconciled equity only
- Risk contracts after drawdown
- Research agents cannot alter production files
- Alpha cannot access Beta's first-pass report before submitting its own, and vice versa
- N2/N3 theses cannot place live orders
- N1 theses cannot receive Exceptional risk
- Irrelevant specialists can return `NOT_APPLICABLE` without causing workflow failure
- A narrative-only thesis with no deterministic evidence is rejected
- Evidence classification is bit-identical across firm states for the same
  Market State Packet, including a state far behind any aspiration [A-2]

---

# 22. BUILD PHASES

## Phase 0: Discovery and audit

Deliverables:

- Environment audit
- Existing connector audit
- Broker/data-source comparison
- Risk assumptions register
- Legal/regulatory verification checklist
- Final implementation plan
- Repository initialized

## Phase 1: Governance and skeleton

Deliverables:

- Repository structure
- `CLAUDE.md`
- Agent definitions
- Skills and commands
- Settings, permissions, and hooks
- Configuration schema
- Adaptive Trade Thesis schema
- Novelty classification
- Feature/indicator registry enforcement
- Independent-context packet checksums
- Governance documents
- CI/test baseline

## Phase 2: Offline deterministic core

Deliverables:

- Domain models
- SQLite schema and migrations
- Capital manager
- Risk engine
- Position-sizing engine
- Session clock
- Audit service
- Unit tests

## Phase 3: Data, feature registry, and alpha research framework

Deliverables:

- Market data normalization
- Historical replay
- Feature engine
- Versioned feature and indicator registry
- Strategy and adaptive-policy manifests
- Historical analog engine
- Experiment and multiple-testing ledger
- Backtest and validation reports
- Initial champion candidates

## Phase 4: Broker sandbox integration

Deliverables:

- Broker adapter
- Order state machine
- Stop verification
- Reconciliation
- Failure handling
- Demo lifecycle tests

## Phase 5: Agent orchestration

Deliverables:

- Executive agents, independent Senior Trader Alpha/Beta, and specialist bench
- Structured Adaptive Trade Thesis schemas
- Independent-context enforcement
- Market State Packet and thesis comparison workflow
- Session briefing workflow
- Trade approval cards
- Post-session review workflow
- Model-routing policy

## Phase 6: Shadow and paper operation

Deliverables:

- Scheduled laptop operation
- Live market-data shadow sessions
- Paper execution
- Performance and operational reports
- Defect resolution

## Phase 7: Limited live probation

Deliverables:

- Owner-approved live configuration
- Human approval required
- Strict single-position mode
- Daily incident and performance review
- No automatic strategy promotion

## Phase 8: Controlled autonomy

Only after owner review of sufficient operational evidence:

- Consider limited auto-execution for explicitly qualified setup classes
- Preserve risk-engine veto
- Preserve kill switch
- Preserve immutable production versions

---

# 23. MINIMAL-COST STACK

Preferred initial stack:

- Claude Code for engineering, orchestration, research, and reports
- Python 3.12+
- `uv` or equivalent fast package manager
- Pydantic for schemas
- SQLite in WAL mode
- SQLAlchemy or SQLModel if useful
- Pandas/Polars for research as justified
- NumPy/SciPy for analysis
- Pytest
- Ruff
- Mypy or Pyright
- Git and private GitHub repository
- Broker REST/WebSocket API
- Optional Streamlit dashboard
- Optional Telegram or Discord notifications

Avoid paid infrastructure until it creates a measurable reliability or capability benefit.

Do not add Kubernetes, distributed queues, cloud databases, or microservice sprawl for the initial laptop deployment.

---

# 24. CONFIGURATION BASELINE

Create validated configuration equivalent to:

```yaml
firm:
  name: Claude Adaptive London-Session Trading Firm
  environment: research
  starting_capital_usd: 250.00
  profit_target: null
  control_timezone: America/Chicago
  market_timezone: Europe/London

risk:
  tier_anchor_usd: 250.00
  scaling_multiplier: 2.0
  current_equity_risk_contraction: true
  max_open_positions: 1
  max_trades_per_session: 2
  max_exceptional_trades_per_session: 1
  initial_session_loss_limit_usd: 25.00
  initial_weekly_loss_limit_usd: 37.50
  initial_live_floor_usd: 200.00
  week_boundary: iso_week_europe_london     # [D-6]
  tier_promotion_requires_owner_approval: true   # [D-2, R: C-3]
  deposits_advance_milestones: false             # [D-3]
  margin_utilization_cap_fraction: 0.30          # [F-1]
  stop_widening: false
  averaging_down: false
  martingale: false
  recovery_sizing: false

risk_ladder:
  standard:
    initial_usd: 2.50
    initial_equity_fraction: 0.01
  strong:
    initial_usd: 7.50
    initial_equity_fraction: 0.03
  high:
    initial_usd: 12.50
    initial_equity_fraction: 0.05
  exceptional:
    initial_usd: 25.00
    initial_equity_fraction: 0.10
    prohibited_after_session_loss: true
    human_approval_during_probation: true

execution:
  require_broker_stop_confirmation: true
  reject_stale_data: true
  reject_abnormal_spread: true
  reject_unknown_news_state: true
  reject_minimum_size_overrisk: true
  idempotency_required: true
  fail_closed: true

session:                      # [R: C-2] London-anchored; Chicago is display-only
  anchor_timezone: Europe/London
  startup_london: "07:15"
  asian_range_final_london: "07:30"
  briefing_london: "07:40"
  activation_london: "08:00"
  entry_cutoff_london: "10:30"
  flatten_london: "11:00"
  display_timezone: America/Chicago
  holiday_calendar_required: true          # [R: N-11]

adaptive_trading:
  senior_trader_pair_enabled: true
  independent_first_pass_required: true
  market_state_packet_checksum_required: true
  allowed_live_novelty_classes: []
  exceptional_risk_allowed_novelty_classes: [N0]
  narrative_only_candidates_rejected: true

feature_registry:
  production_allowed: []
  research_allowed: []

strategies:
  live_allowed: []
  specialist_research_allowed:
    - london_breakout
    - asian_range_sweep_reversal
    - london_continuation

instruments:
  research_priority:
    - GBP_USD
    - EUR_USD
  live_allowed: []
```

The initial repository must begin with `live_allowed: []`. Live permission is added only after the required phases and owner approval.

---

# 25. DEFINITION OF DONE FOR INITIAL BUILD

The initial production candidate is not complete until:

- All governance files exist
- Claude agents and hooks are installed and tested
- Broker audit is approved
- Market data is stable
- Risk and sizing tests pass
- Capital-tier scaling and contraction tests pass
- Order lifecycle works in sandbox
- Broker-held stop verification works
- Restart reconciliation works
- Audit records are complete
- Senior Trader Alpha/Beta independence controls pass
- Adaptive thesis, novelty, and feature-registry gates pass
- Historical analog and experiment-ledger workflows are reproducible
- Shadow and paper phases meet acceptance criteria
- Owner can activate the kill switch from laptop and approved mobile path
- Live mode remains disabled by default
- A documented live activation checklist exists
- Session boundaries resolve to 08:00/10:30/11:00 `Europe/London` on DST-
  divergence dates [R: C-2]
- Sizing uses per-instrument margin rates and the margin-utilization overlay [F-1]
- Research code producing any published number has passed §12.7 review [A-1]
- Evidence classification is proven pressure-invariant across firm states, and
  the audit record distinguishes a gate-bound decision from a thesis-bound one
  [A-2]

---

# 26. REQUIRED FIRST RESPONSE FROM CLAUDE

After receiving this file, do not immediately implement the entire system.

Produce:

1. **Environment audit**
2. **Existing repository audit**, if one exists
3. **Claude Code capability and connector audit**
4. **Broker and data-source information needed**
5. **Assumption register**
6. **Risk and architecture conflict review**
7. **Proposed repository tree**
8. **Phased implementation plan with acceptance criteria**
9. **Minimal monthly cost estimate**
10. **Senior-trader and specialist architecture review**
11. **Feature/indicator registry design**
12. **Historical analog and experiment-ledger design**
13. **List of owner decisions that are genuinely blocking**

Then begin Phase 1 using the safest reasonable defaults for nonblocking implementation details.

---

# 27. DESIGN REFERENCES AND IMPLEMENTATION RATIONALE

The implementation team should consult and preserve links to the following source categories in project documentation:

- Anthropic Claude Code custom subagents: https://docs.anthropic.com/en/docs/claude-code/sub-agents
- Anthropic Claude Code hooks and deterministic lifecycle controls: https://docs.anthropic.com/en/docs/claude-code/hooks-guide
- Anthropic Claude Code MCP integrations: https://docs.anthropic.com/en/docs/claude-code/mcp
- NFA supervision of automated order-routing systems: https://www.nfa.futures.org/rulebooksql/rules.aspx?RuleID=9046&Section=9
- Bailey et al., *The Probability of Backtest Overfitting*: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253

These references do not certify profitability. They support the architecture's separation of agents, deterministic controls, external-tool integration, supervision, and anti-overfitting research discipline.

---

# 28. FINAL GOVERNING PRINCIPLE

Build a selective, adaptive, evidence-driven, self-scaling trading firm—not a bot imprisoned by three named strategies, not a narrative-driven discretionary gambler, and not a permanently timid system.

The Senior Trader pair may think broadly, diagnose the situation, choose relevant evidence, consult specialists, and create new hypotheses. The specialist agents remain deep experts whose playbooks are used only when the market makes them relevant. No strategy owns the firm; every strategy must earn and retain its place.

The system may act aggressively when a rare, statistically validated exceptional-edge opportunity appears, but newly invented logic does not become exceptional edge by declaration. Aggressiveness remains bounded by deterministic risk controls, current closed equity, execution quality, novelty class, evidence quality, and drawdown state.

Claude creates intelligence and hypotheses. Deterministic software enforces reality. Validation earns live permission.

---

# 29. AMENDMENT RECORD

## 29.6 v2.3.0 -> v2.4.0 changelist [A-4 / SESSION-TIMING-001]

Amendment A-4, **session timing and sleep integrity**. Proposed by the owner
after the 2026-08-05 and 2026-08-06 forensic audits, and ratified with
amendments on 2026-08-06.

| Section | Change | Driver |
|---|---|---|
| §31 | New: ratified execution tolerances per boundary, flat-state verification deadline, suspension handling, stability-gate qualification, and the prohibition on "nominal" | A-4 |
| §14 | Unchanged. §31 supplies the tolerances §14 never defined | A-4 |
| §18 | Unchanged. §31.5 makes the existing "sleep and hibernation disabled" requirement machine-checkable | A-4 |

What went wrong: §14 defined six boundaries as exact London wall-clock times
and marked flatten inviolate, but never said how late is too late. The
supervisor's session validator therefore counted an event as clean whenever
its outcome string omitted one substring, and set the degraded flag from the
pre-startup probe alone. On 2026-08-05 a flatten 73 minutes past the inviolate
boundary was reported to the owner as "nominal, 5/5 events clean"; on
2026-08-06 a flatten 76 minutes late whose account verification returned HTTP
401 was reported as "nominal". Both sessions ran on a laptop that had entered
clamshell sleep, which `caffeinate -i` never prevented. A monitor that cannot
see a missed hard boundary makes every session report untrustworthy, so the
tolerances are ratified here rather than left to implementation.


## 29.5 v2.2.0 → v2.3.0 changelist [A-3 / GMIS-001]

Amendment A-3, the **Global Market Intelligence and Surveillance Division**.
Proposed by the owner as an uploaded additive implementation handoff (owner
document id GMIS-001, preserved verbatim at
`docs/spec/CLAUDE_ADDITIVE_HANDOFF_GLOBAL_MARKET_INTELLIGENCE_SURVEILLANCE_v2.1.0.md`,
SHA-256 `36e72f8e4b30b77c3bb0eebc1fe6467cf01a0a669a920010a60fa9c57be36bbe`) and
ratified by the owner on 2026-07-31. No provision was removed and no permission
was granted; the amendment adds one new major section and an agent roster
expansion, all of it behind disabled feature flags.

| Section | Change | Nature |
|---|---|---|
| §30 | New division: surveillance agent roster, Market State Object, source registry, event/alert architecture, thesis monitoring, options-ready boundaries, flags and rollout ladder | addition |
| §30.3 | Agent roster grows from nine to nineteen role files — an explicit owner decision superseding the 2026-07-30 nine-file roster, with the context-analyst boundary documented | addition |
| §30.5 | The senior-trader packet gains surveillance components; the open-position contradiction packet is carried post-entry on the firm side, preserving §5.1 [A-2] | addition + tightening |
| §30.11 | US jurisdiction constraints restored into the governing spec (previously carried only by the §29.2 pointer to v1.1.4 §16) | restoration (C-1, D-1) |
| §30.12 | Surveillance configuration baseline, all influence flags false; Telegram delivery bound to MATERIAL/CRITICAL severity by owner decision | addition |
| §19 | Notification surface gains a surveillance class, registered separately from the §19 minimum set, delivered severe-only | addition (recorded here; §19's minimum list is unchanged) |

**Origin.** The owner uploaded the GMIS handoff with the instruction "we made an
oversight and i would like to add these agents", and separately confirmed that
nothing was yet built and that the amendment must first be reviewed and spec'd
against the actual repository. The uploaded document targets a spec filename
that does not exist in this repository and never cites a section of this
document, so adopting its internal numbering would have made every citation of
it silently mis-resolve — its §4 reads here as the capital-tier system. Its
normative content therefore lands renumbered as §30.x, the only form repo code
may cite; the uploaded original remains the historical record.

**Scope limit, recorded deliberately.** A-3 unlocks nothing at ratification.
`surveillance.enabled` is false, `influence_candidate_generation` and
`influence_live_eligibility` are false, no source is production-approved, no
surveillance Claude invocation is enabled, `live_allowed` remains empty
everywhere, and the remote command surface remains halt-only. Surveillance
observations cannot change a classification input (§5.1 [A-2]), cannot raise a
tier, and cannot reach an order path. Shadow and calibration numbers produced
under §30.18's later phases are §12.7 publication-gated before they can support
any live-influence decision.

This subsection is numbered 29.5 because 29.0–29.4 are taken; it is placed
first so the record reads newest-first, and no existing citation is renumbered.

## 29.0 v2.1.0 → v2.2.0 changelist [A-2]

Amendment A-2, **conviction discipline**. Proposed by the implementer in
`docs/design/2026-07-30-v2-pass-2-scope.md` and ratified by the owner on
2026-07-30. No provision was removed and no permission was granted; the
amendment adds a measurement obligation and one testable invariant.

| Section | Change | Nature |
|---|---|---|
| §3.5 | The no-profit-target prohibitions restated as prohibitions on *inputs*; explicit precedence over §6.6 | clarification + tightening |
| §5.1 | Pressure invariance: the evidence vector must be a pure function of the Market State Packet; firm state may only reduce, structurally separated | addition |
| §6.6 | Conviction discipline: under-classification scored symmetrically with over-classification, with five absolute bounds and a conflict clause | addition |
| §21 | Unit test "pressure invariance of evidence classification"; acceptance criterion for bit-identical classification across firm states | addition |
| §25 | Definition of done gains the invariance proof and the gate-bound vs thesis-bound audit distinction | addition |

**Origin.** The owner directed that agents "should be encouraged to trade harder
with achieving the goal in mind when they have found an edge in sessions. Never
just blindly out of pressure of reaching a target." Conviction-driven and
pressure-driven sizing produce the same action and differ only in inputs, so the
amendment separates them by input class rather than by instruction: evidence — a
function of the market — may raise the ceiling the gate considers; firm state — a
function of us — may only lower it. That reduces the owner's distinction to a
property test rather than a matter of agent tone.

**Scope limit, recorded deliberately.** A-2 unlocks nothing at ratification. All
three strategy manifests carry `risk_permissions` false, so no thesis of any
evidence class can produce size. The route to larger positions runs through §12.5
promotion and the §12.6 evidence thresholds and through nothing else. A-2 builds
the mechanism by which earned conviction can express itself once the evidence
exists; any reading that produces size before the evidence does is the pressure
response wearing conviction's clothes, and §5.1's invariance test exists to catch
exactly that.

This subsection is numbered 29.0 so that §29.1's existing citations continue to
resolve unchanged.

## 29.1 v2.0.0 → v2.1.0 changelist

v2.0.0 was drafted from v1.0.0 and did not carry the amendments ratified against
the v1.1.x line. v2.1.0 adopts v2.0.0's adaptive architecture unchanged and
restores those amendments. No v2.0.0 provision was removed; each entry below is
an addition or a tightening.

| Section | Restored provision | Origin |
|---|---|---|
| §3.3 | Margin capacity from the **per-instrument** broker rate + utilization overlay | F-1 |
| §4.2 | Owner-approved pending promotion with lapse; automatic promotion prohibited | D-2, R: C-3 |
| §4.2 | Deposits never advance milestone tiers | D-3 |
| §12.6 | Minimum-evidence thresholds (30 signals; 50 trades; 100 candidates) | D-5, R: M-8 |
| §12.7 | Research-code adversarial review / publication gate | A-1 |
| §14 | London-anchored session schedule; Chicago display-only; rollover blackout and inviolate flatten | R: C-2, F-5 |
| §24 | Config baseline: London session keys, week boundary, promotion and deposit flags, margin cap, holiday calendar | C-2, D-2, D-3, D-6, F-1, N-11 |
| §25 | Definition of done gains DST, margin-overlay, and §12.7 criteria | C-2, F-1, A-1 |

Section numbering is otherwise identical to v2.0.0, which is itself aligned with
v1.1.4 for §0–§26. The §0 iron-rule list is unchanged in order and content, so
every existing `§0.N` citation remains valid. v2.0.0's §27 (design references)
and §28 (final governing principle) keep their numbers; the amendment record
moves here to §29.

## 29.2 Prior ratifications carried forward

Owner decisions D-1…D-7 (ratified 2026-07-29), amendments A-1 and A-2 (both
ratified 2026-07-30), and amendment A-3 / GMIS-001 (ratified 2026-07-31)
remain in force. Practice-audit findings F-1…F-5 remain in force,
with F-4 preserved as superseded-by-F-5 rather than deleted. Design-review
findings C-1…C-3, M-1…M-8, N-1…N-13 remain applied. Full text of each is
retained in `docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF_v1.1.4.md`
§28, which is preserved unedited.

## 29.3 Ratification record

**v2.1.0 — ratified 2026-07-30.** The owner supplied v2.0.0 as the new source of
truth. The implementer identified that it superseded v1.0.0 rather than v1.1.4
and therefore silently dropped seven ratified or audit-backed protections, and
presented the choice. The owner selected the merge ("Merge into v2.1.0") and
directed governance-first sequencing. The implementer proposed; the owner
ratified. Changing or weakening any restored item requires editing its section
and re-versioning this document.

**v2.2.0 — ratified 2026-07-30.** Amendment A-2, conviction discipline. The owner
directed that the firm reach for tiers it has earned while remaining incapable of
sizing up under target pressure. The implementer proposed the amendment in
`docs/design/2026-07-30-v2-pass-2-scope.md`, together with the input-class
separation that makes the two cases distinguishable by test rather than by
judgment, and presented it for ratification rather than applying it. The owner
ratified. Weakening §5.1's invariance requirement, or removing any of the five
bounds in §6.6, requires re-versioning this document.

**v2.3.0 — ratified 2026-07-31.** Amendment A-3, the Global Market Intelligence
and Surveillance Division (owner document id GMIS-001). The owner supplied the
additive handoff and directed that the ten surveillance agents be added; the
implementer audited the actual repository first (the amendment's own §22
requirement, delivered as `docs/audits/2026-07-31-gmis-phase-a-audit.md`),
surfaced the conflicts with ratified protections, and put four decisions to the
owner rather than resolving them silently. The owner chose: all ten agents as
separate role files; severe-only Telegram delivery; options boundaries as
prose without stub modules; a dedicated branch and pull request. The owner
ratified the plan. Enabling any surveillance influence flag, approving any
source for production, or creating the live surveillance config layer requires
the §30.18 phase evidence and explicit owner approval — none of it follows
from this ratification.

## 29.4 Predecessor documents

| File | Status |
|---|---|
| `CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.2.0.md` | Prior governing spec, superseded, preserved unedited |
| `CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.1.0.md` | Prior governing spec, superseded, preserved unedited |
| `CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.0.0.md` | Owner-supplied, verbatim, superseded, preserved unedited |
| `CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF_v1.1.4.md` | Prior governing spec, superseded, preserved unedited |
| `CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF_v1.1.3.md` | Superseded, preserved unedited |
| `CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF.md` | v1.0.0 verbatim original, preserved unedited |

---

# 30. GLOBAL MARKET INTELLIGENCE AND SURVEILLANCE DIVISION [A-3 / GMIS-001]

The firm shall not rely solely on historical strategies or static historical
relationships. Historical evidence identifies possible edge. The Global Market
Intelligence and Surveillance Division determines whether the present market
supports, weakens, contradicts, or invalidates that edge. The division is a
permanent shared service for the current forex operation and any future
multi-asset firm, implemented additively, economically, auditably, and without
weakening the deterministic risk and execution architecture.

This section is the citable form of the owner's GMIS-001 amendment document,
renumbered and adapted to the repository it governs. Where the uploaded
document and this section differ, this section wins, and every difference is
recorded in §29.5.

## 30.1 Authority, additive mode, and preservation rules

The division is an additive amendment. It does not authorize a rewrite,
redesign, repository replacement, database reset, broker change, risk-policy
change, strategy-policy change, or live-trading activation. Its non-negotiable
preservation rules:

1. **Add, do not replace.** Preserve all working broker, market-data, risk,
   sizing, execution, reconciliation, strategy, audit, notification, and
   supervisor behavior.
2. **No live behavior change by default.** All new surveillance features must
   be disabled in live mode until explicitly enabled through approved
   configuration.
3. **No destructive migrations.** Database migrations must be forward-only,
   backward-compatible, idempotent where practical, and tested against a copy
   of the current database.
4. **No credential changes.** Reuse current secret-management patterns. Do not
   print, move, rotate, or rewrite secrets unless a genuine defect requires
   owner action.
5. **No risk-policy changes.** The existing deterministic risk engine remains
   authoritative and unchanged unless a compatibility defect is discovered and
   documented.
6. **No agent execution authority.** New agents may monitor, classify,
   interpret, and escalate. They may not place orders, alter stops, size
   positions, or bypass the candidate and risk workflow.
7. **No silent strategy promotion.** Surveillance observations may inform
   existing candidates and create research hypotheses. They may not convert a
   novel idea into a live strategy.
8. **Fail closed.** Missing, stale, conflicting, or unhealthy required
   live-intelligence data must never be treated as confirming evidence.
9. **Rollback required.** The complete amendment must be removable or
   disable-able without damaging the pre-amendment system.
10. **Preserve auditability.** Every new observation, alert, interpretation,
    source-health event, state transition, and configuration change must be
    reproducible from stored inputs and versioned logic.

## 30.2 Operating model and separation of responsibilities

Deterministic services perform: data collection and normalization; feature and
indicator computation from the approved registry; Market State Object
construction and publication; freshness, staleness, and source-health
tracking; event detection against configured rules; alert deduplication and
throttling; persistence and audit logging; schedule and budget enforcement.

Claude agents may perform: interpretation of deterministically supplied
observations; classification against controlled vocabularies; materiality and
relevance assessment inside configured bounds; verification reasoning over
news items; escalation recommendations; structured report authorship.

Claude agents must not perform: order placement, modification, or
cancellation; position sizing; risk-limit changes; direct market-data
ingestion bypassing the deterministic layer; invention of features, sources,
thresholds, or exit rules; suppression of severe alerts. Surveillance output
enters deterministic code only through
`trading_firm.agents.validate_agent_payload`, and no surveillance output can
raise a risk tier, an evidence class, or a size — the §5.1 [A-2] direction of
influence is preserved: market-derived evidence may inform, firm state may
only reduce, and nothing surveillance produces is an authorization.

## 30.3 Surveillance agent roster

Ten agent role definitions, invoked by the orchestration workflow — they are
not always-running processes. The deterministic services run continuously;
the agents interpret on schedule or on material change.

- **A. Technical Surveillance Lead** — coordinates the division and produces
  a concise, evidence-grounded current-state report. May not create orders,
  authorize candidates, override Senior Traders, or suppress severe risk or
  data-quality alerts.
- **B. Price Structure Monitor** — monitors deterministically supplied
  structure observations: higher highs and lows, breaks and failed breaks,
  range formation and escape, session and prior-period levels, opening range,
  compression, expansion, displacement, acceptance and rejection.
- **C. Indicator and Feature Monitor** — monitors only indicators present in
  the approved registry (§30.7).
- **D. Liquidity and Auction Monitor** — monitors observable or inferable
  behavior around Asian-session and prior-session extremes, equal highs and
  lows, repeated tests, sweep-and-reclaim or reject, rapid displacement,
  failed acceptance, and spread or tick-volume changes. Every field it
  reports carries an evidence label: `OBSERVED`, `BROKER_PROXY`,
  `PRICE_ACTION_INFERENCE`, or `UNAVAILABLE`.
- **E. Volatility and Regime Monitor** — maintains current regime
  classifications across approved horizons using the controlled labels
  `TRENDING`, `MEAN_REVERTING`, `COMPRESSING`, `EXPANDING`, `EVENT_DRIVEN`,
  `ILLIQUID`, `DISLOCATED`, `TRANSITIONAL`, `INDETERMINATE`.
- **F. Macro and Event Monitor** — monitors approved scheduled and
  unscheduled market events.
- **G. Cross-Market Monitor** — tracks approved contextual instruments only.
- **H. News Verification and Relevance Agent** — separates collection from
  interpretation; assigns the verification states `UNVERIFIED`,
  `SINGLE_SOURCE`, `CORROBORATED`, `OFFICIAL_SOURCE`, `CONFLICTING`,
  `CORRECTED`, `RETRACTED`.
- **I. Opportunity Alert Agent** — receives structured events and creates an
  alert only when a material state change occurs. It does not output `BUY`
  or `SELL` instructions.
- **J. Position Contradiction Monitor** — operates only when an approved
  paper or live position exists, comparing the live market to the position's
  pre-registered thesis expectations (§30.10). It may recommend review, risk
  attention, or thesis invalidation. It may not independently alter an order.

**Roster boundary, recorded deliberately.** The 2026-07-30 roster decision set
nine agent files by consolidating the §6.4 context roles into the Context
Analyst. This amendment expands the roster to nineteen by explicit owner
decision (2026-07-31), taken with the overlap in view: the Context Analyst
owns the pre-session context packet; the surveillance monitors own
intra-session continuous observation. The two must not silently merge or
duplicate — a monitor restating pre-session context adds no evidence, and the
Context Analyst does not re-derive intra-session surveillance.

## 30.4 Market State Object

A versioned, immutable-at-publication Market State Object exists per approved
instrument and observation horizon. In the repository the type is
`MarketStateObject` (the name `MarketState` belongs to the adaptive thesis
layer). Its components: identity and versioning (id, schema version,
instrument, asset class, as-of and valid-until times in UTC, source snapshot
ids, feature snapshot id, configuration version); session state; market
regime per horizon with evidence feature ids and classifier version;
technical state; liquidity state with evidence labels; macro state; news
state; cross-market state; execution state; data quality
(`HEALTHY`/`DEGRADED`/`FAILED` with stale, missing, and conflicting
components enumerated); and a change summary linking the prior object.

Immutability rules: Published Market State Objects are append-only.
Corrections create a replacement object linked with
`supersedes_market_state_id`. Senior Trader Alpha and Beta receive the same
object ID and checksum for their independent first pass. The exact Market
State Object used for a candidate must be linked to the candidate and
retained.

Freshness rules: Each component must have its own freshness threshold. Do not
use one global threshold for all data. Broker price data ages in seconds;
technical state with its timeframe and bar completion; the scheduled event
calendar in hours before the session and tighter around releases; news and
cross-market data per source. If a required component expires, the published
state becomes `DEGRADED` or `FAILED` according to configuration.

Timezone rule, carried from C-2: every timestamp in a Market State Object is
UTC or carries an explicit IANA zone. No naive local-time string may enter an
immutable object. Chicago remains display-only (§14).

## 30.5 Market State Packet extension for the senior traders

The Market State Packet (§6A) gains surveillance content. It must contain,
when the corresponding domain is enabled: the latest valid Market State
Object; the prior material Market State Object for comparison; the
deterministic feature snapshot; the active scheduled-event packet; the
material verified-news packet; the cross-market confirmation and divergence
packet; the execution-conditions packet; the source-health report; and data
limitations. The packet must be serialized, checksummed, stored, and provided
identically to both senior traders before either first-pass analysis begins.
Do not include another agent's narrative thesis in the first-pass packet.

**A-3 tightening of the uploaded text, binding.** The uploaded amendment
listed an open-position contradiction packet as a first-pass packet
component. That would walk firm state into classification input, which §5.1
[A-2] makes a type error. In this specification the open-position
contradiction packet is post-entry material: it travels on the firm side of
the packet split, reaches the Position Contradiction Monitor, the Arbiter,
the CRO, and the owner, and never reaches evidence classification or the
first-pass packet. The market half of every surveillance component remains a
pure function of the market.

## 30.6 Event and alert architecture

The event mechanism is the existing internal architecture — a local
in-process event flow with a durable SQLite outbox. Do not add Kafka, Redis,
or cloud queues for this laptop deployment.

Required event families: `market_data.received`, `market_data.stale`,
`bar.closed`, `feature.snapshot.created`, `market_state.published`,
`market_state.degraded`, `regime.changed`, `structure.level_reached`,
`structure.break_detected`, `structure.failed_break_detected`,
`volatility.threshold_crossed`, `spread.threshold_crossed`,
`economic_event.upcoming`, `economic_event.released`, `news.item_ingested`,
`news.item_verified`, `news.conflict_detected`,
`cross_market.divergence_detected`, `opportunity.material_change_detected`,
`position.contradiction_detected`, `source.health_changed`,
`surveillance.briefing_due`.

Every event carries: a unique event ID, event type and schema version, UTC
event time, UTC ingestion time, source or producer, instrument scope, a
correlation ID, the configuration version, data-quality status, and a payload
checksum where useful.

Alert discipline: Prevent alert floods. Implement correlation windows,
state-change-only alerts, severity-based cooldowns, duplicate-content hashes,
supersession links, acknowledgement state, and escalation state. Severe risk,
source-failure, broker, or position-protection alerts must never be
suppressed by normal throttling.

Owner delivery (owner decision, 2026-07-31): surveillance alerts reach the
§19 Telegram surface only at `MATERIAL` or `CRITICAL` severity. `INFO` and
`WATCH` alerts are recorded locally and summarized in the daily session
report. The surveillance notification kinds are registered as their own class
beside the §19 minimum set; the §19 minimum set itself is unchanged, and the
inbound command surface remains halt-only.

## 30.7 Feature registry extension

Extend the existing approved feature and indicator registry. Do not create a
second independent registry. Each production-capable feature carries:
feature id, version, lifecycle status (`research`, `shadow`, `paper`,
`production`, `retired`), asset classes, instruments, timeframes, calculation
module, required inputs, lookback requirements, output type, null behavior,
warmup behavior, freshness policy, purpose, known failure modes, leakage
review status, validation report ids, and owner approval id.

Policy: Reuse existing features before adding new ones. Inventory current
indicator calculations and eliminate duplicates by wrapping rather than
rewriting when safe, with tests comparing old and new outputs on identical
inputs. New calculations begin as `research` and cannot affect live
decisions. Production surveillance may initially observe approved production
features without changing existing strategy logic. Changing feature
boundaries re-triggers the §12.7 review of research code that consumes them.

## 30.8 Source governance and missing-news behavior

One versioned registry describes every approved external intelligence source:
source id, source type (`broker`, `official`, `calendar`, `news`,
`market_data`, `derived`), provider, connector reference, assets or
currencies, authentication requirement, polling policy, rate-limit policy,
freshness SLA, priority, reliability tier, license notes, production
approval, and whether the system fails closed when the source is unavailable.

Source quality rules: Prefer official releases and broker-native data when
available. Preserve original timestamps and values. Never scrape or store
data in violation of source terms. Do not allow an unapproved free source to
silently become production-critical. A source outage must be visible in
health status. A source suitable only for research is marked accordingly.

Missing-news behavior: The absence of fetched news does not prove the absence
of relevant news. The system must distinguish `NO_MATERIAL_ITEMS_FOUND`,
`SOURCE_HEALTHY_NO_ITEMS`, `SOURCE_UNAVAILABLE`, `POLL_FAILED`,
`VERIFICATION_PENDING`, and `UNKNOWN`. The existing
`reject_unknown_news_state` behavior remains fail-closed where configured.

## 30.9 Scheduled and event-driven operation

The design avoids continuous high-token Claude analysis. Deterministic
processes — price and candle ingestion, feature calculation, calendar and
news polling, cross-market polling, market-state publication, alert rules,
source-health monitoring, and audit persistence — must use the current
supervisor and heartbeat framework rather than introducing a second
supervisor. The surveillance sweep attaches to the existing session events
and the supervisor heartbeat; §14's London-anchored boundaries are the only
schedule, and briefing checkpoints (Asia context, pre-London briefing,
activation briefing, material-change-only mid-session, entry-cutoff
briefing, post-session review) bind to those boundaries, configurable rather
than hard-coded.

Claude agents are invoked only when: a scheduled briefing is due; a material
market-state change occurs; a relevant verified news item arrives; a regime
changes; a key structural level is reached or fails; a significant
cross-market divergence occurs; a candidate is being assembled; a paper or
live position receives contradictory evidence; or a post-session review is
due. Do not generate repetitive briefings when the state is unchanged.

## 30.10 Post-entry monitoring

Every candidate eligible for paper or live execution registers a
`ThesisMonitoringPlan` before entry: expected confirmations, acceptable noise
conditions, soft contradictions, hard invalidation conditions, a time
expiration, event invalidation rules, execution degradation rules, data
health rules, whether soft contradiction requires review, and the
preconfigured policy actions. The plan's time bounds are capped by the §14
flatten boundary — no plan may extend monitoring expectations past the point
where the position must not exist (F-5).

The Position Contradiction Monitor may record a contradiction, escalate to
the Senior Traders, the Arbiter, the CRO, or the owner according to severity,
mark a thesis as under review, and trigger existing deterministic policy
actions if those actions were preconfigured and already authorized. It may
not invent a new exit rule after entry. Existing broker-native stops remain
authoritative.

## 30.11 Options-ready boundaries and jurisdiction constraints

The division's interfaces avoid forex-only assumptions: instruments carry
`instrument_id`, `asset_class`, `venue`, `session_calendar_id`,
`price_increment`, `contract_multiplier`, `settlement_type`, and
`market_data_capabilities`. Do not hard-code pip semantics into the
surveillance domain.

By owner decision (2026-07-31) the options scaffold is documentation, not
code: no stub modules exist. The reserved module boundaries — underlying
state, implied volatility, volatility surface, greeks, chain liquidity,
event catalysts, contract selection, expiration and assignment — and the
nine future options agents (Underlying Technical Analyst, Implied Volatility
Analyst, Greeks and Convexity Monitor, Options Chain and Liquidity Monitor,
Options Flow Analyst, Corporate Event and Catalyst Monitor, Contract
Selection Agent, Exercise Assignment and Expiration Monitor, Options
Portfolio Risk Officer) are recorded here and in
`src/trading_firm/surveillance/options/README.md`, and remain inactive. A
separate owner-approved options amendment must define data vendors, broker
permissions, risk limits, supported structures, suitability controls, and
testing requirements before any options module exists.

**Jurisdiction constraints (restored, C-1 / D-1).** The owner is a US
resident. Retail spot forex is available only through CFTC-registered
RFED/FCM brokers; NFA Compliance Rule 2-43(b) prohibits offsetting positions
within a pair and requires FIFO close-out; leverage is capped at 50:1 on
major pairs. OANDA US is the ratified broker (D-1) and is a spot-FX RFED —
it cannot trade options, which is one reason the options scaffold is prose.
These constraints previously survived v2.x only through the §29.2 pointer to
v1.1.4 §16; they are restored here as binding text.

## 30.12 Surveillance configuration and rollout

The baseline configuration ships every influence path off:

```yaml
surveillance:
  enabled: false
  mode: observe_only
  asset_classes_enabled:
    - FX_SPOT
  instruments_enabled: []
  publish_market_state: true
  influence_candidate_generation: false
  influence_live_eligibility: false
  post_entry_monitoring_enabled: false
  fail_closed_on_required_component_failure: true

  schedules:
    asia_context_enabled: true
    pre_london_briefing_enabled: true
    london_activation_briefing_enabled: true
    material_change_only_mid_session: true
    entry_cutoff_briefing_enabled: true
    post_session_review_enabled: true

  technical:
    enabled: true
    approved_feature_registry_only: true
    structure_monitoring_enabled: true
    regime_monitoring_enabled: true
    liquidity_inference_enabled: true
    liquidity_evidence_label_required: true

  macro:
    enabled: false
    source_ids: []
    unknown_state_behavior: fail_closed

  news:
    enabled: false
    source_ids: []
    verification_required_for_material_alert: true
    duplicate_window_seconds: 900
    unknown_state_behavior: fail_closed

  cross_market:
    enabled: false
    context_instruments: []
    relationship_registry_only: true

  alerts:
    enabled: true
    minimum_severity: INFO
    telegram_minimum_severity: MATERIAL
    state_change_only: true
    severe_alerts_never_throttled: true

  claude_agents:
    enabled: false
    scheduled_briefings: false
    event_driven_analysis: false
    highest_quality_for_material_events: true

  positions:
    contradiction_monitoring_enabled: false
    automatic_order_changes_enabled: false

  options_scaffold:
    enabled: false
    registered: false
```

Semantics, binding: the master switch dominates — while `enabled` is false,
every sub-block is inert regardless of its own flags, and the configuration
loader must expose only effective values. `minimum_severity` governs local
alert creation; `telegram_minimum_severity` governs owner delivery and may
not be set below `MATERIAL` without a new owner decision recorded in the
decision log. `fail_closed_on_required_component_failure` and
`severe_alerts_never_throttled` refuse to be false. The live configuration
layer for surveillance does not exist until the §30.18 Phase H review
creates it under owner approval.

Rollout flag progression: (1) `enabled: false`; (2) research replay only;
(3) live-data observe-only, no Claude calls; (4) live-data observe-only with
scheduled summaries; (5) event-driven Claude summaries, no candidate
influence; (6) paper candidate context enabled; (7) paper post-entry
contradiction monitoring; (8) owner-reviewed live context influence. No step
may be skipped without documented approval.

## 30.13 Surveillance agent output schemas

Every surveillance agent returns machine-validated structured output through
`trading_firm.agents.validate_agent_payload`; free-form commentary may
accompany but cannot replace the schema. Three schemas:

**Surveillance Situation Report** (kind `surveillance_situation_report`):
report id, market state id, agent id and version, generation time, overall
state (`NORMAL`, `MATERIAL_CHANGE`, `DEGRADED`, `CRITICAL`), material
changes, active market drivers, technical/macro/news/cross-market
observations, contradictions, data limitations, specialists to consult,
escalation flag, expiration.

**Opportunity Alert** (kind `opportunity_alert`): alert id, market state id,
severity (`INFO`, `WATCH`, `MATERIAL`, `CRITICAL`), instruments, change
type, what changed, supporting and conflicting observation ids, data-quality
status, suggested recipients, trade direction, expiry. `trade_direction`
must remain null at the surveillance-alert layer — the schema makes a
non-null direction a validation error, not a review finding.

**News Relevance Review** (kind `news_relevance_review`): review id, news
item id, verification state, event time, publication time, potentially
affected instruments, materiality (`NONE`, `LOW`, `MEDIUM`, `HIGH`,
`UNKNOWN`), already-known flag, conflicting facts, pricing assessment
(`UNKNOWN`, `POSSIBLY_PRICED`, `REACTION_ONGOING`, `NOT_OBSERVED`),
recommended state (`IGNORE`, `WATCH`, `ESCALATE`, `PAUSE_NEW_ENTRIES`).

## 30.14 Integration with the existing workflow

Pre-candidate: the extended packet (§30.5) is an input to Senior Trader
Alpha and Beta. It does not replace historical analogs, specialist reports,
or execution checks. Senior traders must explicitly separate historical
evidence, current technical evidence, current macro and news evidence,
current cross-market evidence, current execution evidence, and unknowns.

Candidate schema: candidates gain nullable reference fields —
market state id, market state packet id, surveillance report ids, material
news item ids, source-health snapshot id, thesis monitoring plan id.
References, not payload copies; existing candidates remain valid.

Risk gate: Do not rewrite risk calculations. The gate gains optional
deterministic preconditions — a required Market State Packet exists and has
not expired, required source-health components are not failed, no configured
event blackout is active, no unresolved critical news conflict exists. These
checks must remain disabled in live configuration until paper validation and
owner approval. They can only refuse; they cannot raise anything.

Specialist activation: the Opportunity Alert Agent may recommend consulting
the existing specialist bench or the senior traders for an uncategorized
situation. It must not manufacture relevance for a specialist.

## 30.15 Cost, model routing, and invocation budgets

Deterministic-first: Do not send raw tick streams, full news feeds, or
unchanged state repeatedly to Claude. Claude receives material deltas,
compact structured snapshots, relevant source excerpts or normalized facts,
current candidate context, and explicit uncertainties.

Model routing follows `governance/model-routing-policy.md`: all ten
surveillance agents route to the frontier tier until that policy's rule 5
evidence exists for a candidate down-routing; the News Verification agent's
`PAUSE_NEW_ENTRIES` and `IGNORE` outputs are rejection-adjacent and are not
down-routable. Routine extraction, schema normalization, duplicate
detection, log classification, and data-quality formatting belong in
deterministic code.

Invocation budgets are configuration: maximum scheduled invocations per
session, maximum noncritical event-driven invocations per hour, a minimum
materiality threshold, a cooldown period, context-size limits, and a
fallback behavior. Budget exhaustion must reduce interpretation frequency,
not disable deterministic risk or source-health monitoring.

## 30.16 Supervision, health, and recovery

All surveillance services run under the existing supervisor (§18). Health
reporting covers: collector heartbeat, last successful price update, last
feature snapshot, last Market State publication, calendar source health,
news source health, cross-market source health, event backlog, database
write health, Claude orchestration health, and alert delivery health.

Restart recovery: reconcile broker positions using the current process;
restore source-health states; resume collectors from safe cursors; rebuild
the current Market State from persisted snapshots and mark it reconstructed;
issue no candidate-influencing alerts until freshness requirements are
satisfied; reattach active positions to their Thesis Monitoring Plans.

Degraded modes are explicit and named: technical-only observation, macro
unavailable, news unavailable, cross-market unavailable, Claude
interpretation unavailable, full surveillance failed. The risk and candidate
systems must receive the exact degraded state rather than a generic healthy
flag.

## 30.17 Test and acceptance requirements

No feature-flag progression until the required tests pass. Unit coverage:
Market State schema validation, freshness calculations, regime-label
transitions, structure-event detection, feature-registry enforcement, news
deduplication, publication-time versus event-time handling, source-health
state machine, cross-market divergence, materiality thresholds, alert
throttling and severe-alert bypass, Market State checksum, Thesis Monitoring
Plan validation, contradiction classification, asset-class-neutral
instrument handling. Migration coverage: empty database, copy of the current
database, existing tests and queries unaffected, nullable candidate
references safe on old rows, backup and restore, feature-disable rollback.
Integration coverage: broker data to feature snapshot to Market State;
calendar to blackout; news to verification to alert; divergence to event;
the packet delivered identically to Alpha and Beta; alert to consultation;
candidate references; restart recovery. Replay coverage: no look-ahead
enters a Market State, publication timestamps reflect availability,
releases are invisible before publication, news is never backfilled into
earlier decisions, transitions reproduce, alert volume stays manageable, and
existing strategy results remain unchanged while influence flags are
disabled. Failure injection: feed stalls, source failures singly and
together, conflicting headlines, calendar revisions, duplicate news storms,
database locks, event backlog, failed Claude invocation, laptop sleep and
resume, network loss, clock drift, collector crash loops.

Acceptance: the pre-amendment suite passes; the live-disabled baseline is
preserved; the division runs observe-only; no new agent can place an order;
no alert contains an executable direction; Alpha and Beta receive identical
Market State Packet checksums; stale required data is never treated as
confirmation; unknown news state remains distinguishable from no news;
existing strategy replay is unchanged with influence disabled; one command
or config change disables the entire division; the database restores to the
pre-migration backup; supervisor health reports include the new processes.

## 30.18 Rollout phases and definition of done

Phases: **A** audit and compatibility map (no production code before it is
documented); **B** schemas, flags, and migrations; **C** deterministic
technical surveillance; **D** macro, news, and cross-market ingestion;
**E** event-driven alerts and Claude surveillance agents; **F** senior
trader packet integration; **G** paper-trading influence; **H** owner
review for limited live influence. Phases A–F are build phases; G and H are
activation gates. Shadow comparisons (F) and calibration comparisons (G)
produce research numbers, and §12.7 gates their publication: no such number
supports a Phase H decision until its producing code paths pass independent
adversarial review. Phase H requires stable supervisor operation, acceptable
source reliability, acceptable alert volume, no regression to execution or
risk behavior, demonstrated §12.7-cleared value, documented recurring cost,
a passed rollback test, and recorded owner approval. Only then may selected
surveillance components influence live eligibility.

The amendment is done when: the pre-amendment system passes its tests; the
division exists behind disabled flags; deterministic services publish
versioned Market State Objects; packets are immutable and identical for the
senior traders; the technical, macro, news, cross-market, source-health, and
post-entry contradiction domains are represented; all new agents use
validated output schemas; the division cannot submit orders or alter risk;
migrations are additive, tested, backed up, and recoverable; the processes
are supervised and restart-safe; observe-only mode changes no existing
decision; paper integration exists but stays disabled until its phase;
options-ready boundaries exist without options code; a rollback runbook and
one-command disable are documented and tested; and the implementation report
of record lists files, migrations, tests, costs, remaining risks, and
activation status.

---

# 31. SESSION TIMING AND SLEEP INTEGRITY [A-4 / SESSION-TIMING-001]

§14 fixes the six session boundaries to exact Europe/London wall-clock times
and declares the 11:00 flatten inviolate. It does not say how late an
execution may be before the boundary counts as missed. This section supplies
that policy. It governs reporting and qualification only: it grants no
authority, changes no strategy logic, and can never widen a trading window.

## 31.1 Execution tolerances

Every mandatory boundary has a class and a ratified execution tolerance.
Lateness is measured from the scheduled Europe/London instant.

| Boundary | London | Class | Tolerance |
|---|---|---|---|
| pre_startup | 07:15 | checkpoint / health prerequisite | 120 s |
| briefing | 07:40 | checkpoint | 120 s |
| activation | 08:00 | permission boundary | 60 s |
| entry_cutoff | 10:30 | hard prohibition | 0 s authority, 5 s handler |
| flatten | 11:00 | hard / inviolate | 0 s authority, 5 s initiation |

**pre_startup.** Health may not be treated as timely after 07:17:00. Exceeding
the tolerance marks the session degraded and non-qualifying. Activation may
not occur until required health checks are actually verified. Health is never
retroactively assumed for the missed interval.

**briefing.** After 07:42:00 the briefing is late, and a late briefing makes
the session degraded and non-qualifying.

**activation.** Activation authority begins no earlier than 08:00:00.
Execution between 08:00:00 and 08:01:00 is within scheduler tolerance. Nothing
is granted retroactively. If activation has not validly occurred by 08:01:00
it is skipped for that session, the system remains fail-closed and
manage-only or shadow-only as appropriate, and the session is non-qualifying.

**entry_cutoff.** At 10:30:00 new-entry eligibility becomes false regardless
of whether the scheduler has processed the event. Every eligibility check
consults the authoritative wall clock, so scheduler suspension can never
extend the entry window. No post-10:30 entry may become eligible because a
handler ran late. The handler should execute and log within 5 s; more than 5 s
marks the session degraded and non-qualifying. **Those five seconds do not
extend the entry window.**

**flatten.** The boundary remains exactly 11:00:00. The flatten and
reconciliation procedure must begin no later than 11:00:05. The five seconds
are implementation jitter only and do not extend trading authority. More than
five seconds late is a hard boundary breach, which always marks the session
degraded or failed and non-qualifying, generates the §19 severe owner alert,
and may never be described as nominal or clean.

## 31.2 Flat-state verification

After flatten begins, broker account flat-state reconciliation must be
successfully verified no later than **11:01:00** Europe/London.

Three states remain distinct and are never collapsed:

- `VERIFIED_FLAT` — the broker confirmed no open position.
- `VERIFIED_NON_FLAT` — the broker confirmed an open position.
- `UNVERIFIED` — the broker could not be reached or rejected the request.

If flat state is still `UNVERIFIED` at 11:01:00 the session transitions to the
§14 `HALTED` / recovery state, is marked degraded or failed, and sends the
severe owner alert. It is never reported nominal. The system never infers that
a position exists when that cannot be proven, and never infers that the
account is flat when that cannot be proven. A later successful reconciliation
does not retroactively make the original flatten timely.

## 31.3 Clean events and session qualification

An event is **clean** only when every required dimension passes: the required
event exists, it occurred in the correct sequence, its outcome is acceptable,
and its timing is within the ratified tolerance. A substring test over an
outcome string is not a validator.

A session counts toward the five-consecutive-session stability gate only if
every mandatory boundary is within tolerance and all required health and
safety outcomes are verified. Any boundary outside tolerance disqualifies that
session. Qualification is consecutive: one failure resets the streak to zero.

## 31.4 Prohibited "nominal"

A session may not be described as nominal when any of the following holds:

- any required boundary exceeded its tolerance,
- a hard boundary was missed,
- flat-state verification is `UNVERIFIED`,
- a critical health requirement failed,
- an unresolved runtime suspension occurred.

Session reports carry at least: required event count, clean event count, late
event count, failed or unverified event count, maximum lateness in seconds,
degraded status, and flat-state verification status. Scheduled and actual
timestamps are both retained; neither overwrites the other.

**Two dimensions, always both reported.** Execution health and stability
qualification are independent axes. A session may validly be
`session_health = NOMINAL` with `qualification = NON_QUALIFYING` and
`qualification_reason = POWER READINESS UNVERIFIED`; declaring technically
sound execution degraded would be false, and declaring an unprovable machine
qualifying would let it earn credit it did not earn. Owner-facing reporting
must therefore never send a bare "nominal" for a non-qualifying session — the
headline carries both, in the form `NOMINAL EXECUTION / NON-QUALIFYING —
<reason>`.

During the shadow and practice phases, failed or unprovable power readiness
runs fail-closed and cannot earn stability credit. **If live authority is ever
enabled, unverified required power readiness prohibits activation entirely.**
That live authority is not enabled by this amendment.

**Configuration may tighten, never widen.** The ratified tolerances in §31.1
are constitutional maximums enforced in the configuration schema. Ordinary
configuration may lower a tolerance; it may not raise a hard-boundary
tolerance beyond its ratified maximum. Changing a maximum itself requires a
specification amendment, owner approval, a schema and code change, tests, and
a separate reviewed pull request. A YAML edit alone must never be capable of
making a grossly late hard boundary score clean.

## 31.5 Power and suspension integrity

§18 already requires the laptop to be on power with sleep and hibernation
disabled during the session. This section makes that requirement checkable.

Pre-startup fails closed for stability qualification unless the runtime can
verify every machine-observable requirement: AC power present, the required
sleep-prevention assertion active, supervisor healthy, heartbeat healthy, no
unresolved suspension or wake condition, and the runtime suspension detector
operational. The runtime does not claim to prove lid state programmatically,
because macOS does not reliably expose it.

**Laptop-phase operational rule.** The machine must remain open and connected
to AC throughout the London session unless the owner deliberately provisions
an Apple-supported closed-display configuration. A lid-close sleep that
suspends the runtime automatically disqualifies and degrades the session.

When a suspension gap is detected after session start the runtime records the
suspension, computes the missed wall-clock interval, does not replay expired
permission boundaries as though timely, applies current wall-clock authority
immediately, marks the session degraded and non-qualifying, and applies the
recovery and reconciliation rules for any missed hard boundary.

If AC power disappears during the session the runtime records the power-state
failure, marks the session degraded and non-qualifying, sends the owner alert
under existing severity policy, and remains fail closed.

**Defense in depth only.** The supervisor is launched under `caffeinate -si`,
adding the `PreventSystemSleep` assertion to the existing idle assertion. This
is not permission for, nor a reliable mechanism to defeat, unsupported
lid-close or clamshell sleep.


## 31.6 Authority is latched, not merely compared

The authoritative Europe/London wall clock determines permission boundaries.
The scheduler and its event handlers are never the source of trading
authority.

A pure comparison is not sufficient, because it is reversible. If wall-clock
time later moves backward — an NTP correction, a manual clock change, a
system-time anomaly, a timezone anomaly — a comparison silently answers
"permitted" again. A prohibition that a clock adjustment can undo is not a
prohibition.

Session authority is therefore **latched and monotonic**:

- Once the session reaches or passes **10:30:00**, new-entry authority is
  irreversibly false for the remainder of that session. No later clock
  reading, wake, or correction restores it.
- Once the session reaches **11:00:00**, it irreversibly leaves the
  `ACTIVE` / new-entry-capable state and may never return to it that session.
  Activation cannot be replayed after a wake.
- A backward clock movement is recorded as evidence rather than absorbed
  silently: a clock that moved backward mid-session is itself a finding.

**Authority versus handler execution**, stated explicitly because the
distinction is what the 2026-08 incidents violated:

- At **10:30:00** Europe/London, new-entry authority is false immediately.
  The entry-cutoff handler may execute within its logging tolerance, and that
  tolerance never extends authority.
- At **11:00:00** Europe/London, the session's authority transitions to
  `FLATTENING` immediately. The flatten handler's allowed implementation
  jitter never extends `ACTIVE` authority beyond 11:00.

The wall clock establishes the prohibition; the latch makes it irreversible.
