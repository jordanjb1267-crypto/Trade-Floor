# CLAUDE LONDON TRADING FIRM
## Master Build Handoff, Constitution, and Source of Truth

**Document status:** Governing specification — owner ratified decisions D-1 through D-7 on 2026-07-29 (§28.2)  
**Version:** 1.1.0 (amends v1.0.0 per `docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md`; finding IDs cited as R: C-n/M-n/N-n/O-n)  
**Owner:** Jordan  
**Primary engineering environment:** Claude Code on a single laptop  
**Initial live capital:** $250  
**Primary session:** London session  
**Control timezone:** America/Chicago  
**Market timezone:** Europe/London  

---

# 0. CLAUDE EXECUTION DIRECTIVE

You are the senior principal engineer, quantitative systems architect, chief risk systems designer, and implementation lead for this project.

This document is the project's governing source of truth. Build the system described here without silently weakening its controls, changing its mandate, adding unsupported strategies, or inventing production permissions.

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

Build a low-cost, high-quality, agent-assisted proprietary trading operating system that runs from one laptop, is directed and maintained through Claude Code, and initially trades a narrowly defined London-session mandate.

The system begins with **$250 in live capital**, has **no daily profit target**, and may risk up to **$25 on a single exceptional-edge trade** at the initial capital tier.

The long-term objective is not a single trading bot. It is a modular trading-firm operating system capable of adding independently validated desks, instruments, and strategies while retaining one governance, risk, execution, audit, and learning framework.

## Initial strategies

Only these strategy families are in scope for the first production desk:

1. **London Breakout**
2. **Asian Range Sweep and Reversal**
3. **London Continuation**

No other strategy may trade live until it completes the formal research-to-production promotion process.

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
- Dollar loss caps bound orders, not fills: gaps, news spikes, and slippage can fill beyond a stop. Mitigations: no positions held through the flatten boundary, event blackouts, and slippage-inclusive sizing. (R: N-10)
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

**Within-tier sizing rule (R: N-1).** For any current closed equity `E`, the allowed risk at a classification is:

```text
allowed_risk = minimum(tier_dollar_cap, tier_equity_fraction * E)
```

Risk contracts continuously below the tier anchor and never expands above the tier's dollar cap until a confirmed promotion.

**Margin-feasibility overlay (R: C-1, M-2).** Before a candidate may be classified at any tier, the risk engine must deterministically verify that the margin required at the intended size — under the account's actual leverage cap — does not exceed `margin_utilization_cap_fraction` (default 30%) of closed equity. The system must publish, per tier anchor and instrument, the minimum stop distance at which each tier is executable, and recompute it at every tier transition and material rate move. At the $250 anchor under the US 50:1 cap, the High and Exceptional tiers are executable only at wide stops; Exceptional is effectively aspirational until approximately the $1,000 anchor. **[D-4 ratified 2026-07-29: 10% ceiling retained under this overlay; revisit at first tier promotion.]**

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
- A week is the ISO week (Monday 00:00 through Sunday 24:00) evaluated in Europe/London **[D-6]** (R: N-2)
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

This sequence is bookkeeping, not a forecast. Most accounts never confirm the first doubling; consistent with rule 5 of §0, the ladder implies no profitability. (R: O-1)

## 4.2 Promotion requirements

A tier promotion occurs only when all conditions are true:

1. All positions are closed.
2. Broker-reported closed equity is reconciled.
3. Closed equity is at or above the next milestone.
4. The milestone is produced by **closed trading P&L only**. Deposits raise the active risk base (§4.4) but never advance the milestone tier. **[D-3]** (R: C-3)
5. There are no unresolved fills, rejected-order ambiguities, duplicate orders, missing stops, or reconciliation errors.
6. The runtime health check passes.
7. The promotion event is written to the audit log.

When these deterministic conditions pass, the system arms a **pending promotion** and notifies the owner. The promotion takes effect only on explicit owner approval and lapses if unapproved after 7 days (it re-arms automatically while conditions still hold). The owner can freeze scaling globally. Promotion is a production risk-parameter change and therefore falls under rule 4 of §0. **[D-2]** (R: C-3)

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
- Strategy or instrument permissions unlocked at higher tiers may be suspended if their execution economics are no longer appropriate. Each strategy and instrument permission is bound to a named tier **and** a drawdown state; both must be satisfied. (R: O-4)
- The drawdown-state machine imposes more restrictive risk than the normal tier ladder according to the following states, measured from the current tier anchor on closed reconciled equity (R: N-4):

| State | Trigger (equity vs. tier anchor) | Restrictions |
|---|---|---|
| NORMAL | above −5% | full tier permissions |
| CAUTION | −5% to −10% | Exceptional disabled; maximum classification Strong |
| RESTRICTED | below −10%, above live floor | maximum classification Standard; 1 trade per session |
| SHADOW | at or below live floor | live entries disabled; shadow mode only |

Recovery transitions require closed equity back above the boundary plus one full session in the less restrictive state without a limit breach.

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

## 5.1 Edge components

Create an auditable Edge Confidence Score with versioned weights. Initial research weights:

- 30% strategy expectancy quality
- 20% regime match
- 15% structural confirmation
- 15% execution conditions
- 10% higher-timeframe alignment
- 10% model stability

Weights are research defaults and may not be changed in production without the promotion workflow.

**Deterministic/LLM partition (R: M-1).** Components are partitioned by input origin:

- **Deterministic:** strategy expectancy quality (from validation records), execution conditions (from live spread/latency/slippage measurements), model stability (from versioned model metrics).
- **LLM-assessed:** regime match, structural confirmation, higher-timeframe alignment — each also has a deterministic baseline computed from coded classifiers and structural data.

**LLM-derived assessments may lower a component below its deterministic baseline, never raise it above.** The maximum tier a candidate can reach is therefore bounded by its deterministic sub-scores alone; agent judgment operates strictly as a veto layer.

## 5.2 Initial classification thresholds

- Below 70: reject
- 70–79: eligible for Standard
- 80–89: eligible for Strong
- 90–94: eligible for High
- 95–100: eligible for Exceptional review

A score does not itself authorize size. It only determines the maximum tier the deterministic risk gate may consider.

Scores are integers; fractional intermediate values round down. Weights and thresholds are unvalidated priors: their first recalibration review is mandatory once 100 classified candidates with recorded outcomes exist, and calibration-by-tier (§12.3) may not gate real dollars above Standard until that review completes. (R: M-8)

## 5.3 Exceptional-edge gate

All must pass:

- Exact strategy subtype is production-qualified for exceptional sizing
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

Use the smallest number of high-quality agents that produces genuine specialization. Do not create agents merely to simulate a large firm.

The roster is consolidated to six agents (R: M-6). Duties from the v1.0.0 fifteen-agent roster are absorbed as noted below; re-expansion into separate agents requires documented evidence that a merged agent underperforms.

## 6.1 Executive agents

### A. Firm Governor / CEO Agent

**Purpose:** Coordinate the complete workflow and maintain institutional discipline. Absorbs the head-trader duty: compare qualified strategy candidates and determine whether any candidate is worth presenting.

**May:**

- Initiate pre-session workflow
- Request analysis from specialist agents
- Consolidate evidence
- Compare qualified candidates and select at most one to present
- Produce the final trade brief
- Trigger research and review workflows

**May not:**

- Override risk engine
- Directly submit unrestricted orders
- Change production strategy files
- Promote a challenger

### B. Chief Quant and Validation Agent

**Purpose:** Own research methodology, feature definitions, tests, and strategy validation. Absorbs pattern discovery (controlling for multiple-testing bias and data leakage) and model validation.

**Outputs:**

- Research specifications
- Backtest reports
- Walk-forward, holdout, and Monte Carlo reports
- Spread/slippage stress tests, parameter sensitivity, and regime-stability analyses
- Probability-of-overfitting diagnostics
- Challenger proposals

### C. Chief Risk Officer Agent

**Purpose:** Independently challenge candidate trades and system changes.

**Important:** Its advisory veto is supplemented by an absolute deterministic risk-engine veto.

## 6.2 Strategy agent

### D. Session Strategist

One agent, parameterized by the strategy manifest (§11) it is invoked for. Analyzes only validated variants of the invoked strategy; per-strategy feature sets remain distinct and versioned.

For **London Breakout** (validated breakout variants), required features may include:

- Asian range width and percentile
- Pre-London compression
- Breakout displacement
- Acceptance outside range
- Retest behavior
- Higher-timeframe alignment
- Volatility and spread regime
- News proximity

For **Asian Range Sweep and Reversal** (liquidity sweep and failed-acceptance reversals), required features may include:

- Range high/low sweep depth
- Time spent outside range
- Re-entry speed
- Displacement back into range
- Opposing liquidity target
- Higher-timeframe premium/discount context
- Session timing
- Event risk

For **London Continuation** (validated directional continuation structures), required features may include:

- Prior-session directional structure
- Pullback quality
- Continuation displacement
- Higher-timeframe trend
- Volatility regime
- Distance to liquidity and invalidation

## 6.3 Context agent

### E. Context Analyst

One agent covering regime, macro/event risk, and liquidity/structure.

Regime duty — classifies:

- Trend
- Balance
- Compression
- Expansion
- Elevated volatility
- Suppressed volatility
- Event-distorted conditions

Macro and event duty — maps scheduled events and trading restrictions. It must not hallucinate calendar data. Missing or stale calendar data causes fail-closed behavior according to configuration. Calendar data must arrive as structured fields (times, currencies, impact ratings) from the allowlisted source — the Financial Modeling Prep economic-calendar API, Starter plan or above (**D-7**, §28.2); free-text news is summarize-only and may only downgrade the risk state, never upgrade it. (R: M-5)

Liquidity and structure duty — maps validated structural levels and must express them as deterministic data where possible rather than subjective chart prose.

## 6.4 Learning agent

### F. Learning and Audit Director

**Purpose:** Run post-session analysis and coordinate improvement proposals without altering live production. Absorbs trade auditing and strategy evolution.

Audit duty — classifies each result:

- Good win
- Lucky win
- Good loss
- Bad loss
- Execution error
- Strategy error
- Risk error
- Data error
- Operational error

Evolution duty — creates challengers but cannot write directly to production configuration. Discovery and validation of challengers are executed by the Chief Quant and Validation Agent (B); this agent coordinates the loop and queues promotion reviews only.

## 6.5 Agent quality policy

- Use the highest-quality available Claude model for architecture, risk, quantitative review, promotion decisions, and complex debugging.
- Use lower-cost models only for bounded extraction, formatting, summarization, routine test generation, or log classification.
- Every agent must have a narrow role, explicit tools, explicit prohibited actions, and structured output schema.
- Agent outputs must be machine-validated before entering the deterministic runtime.
- No agent may receive broker credentials unless technically unavoidable; design so credentials remain isolated in the broker service.

---

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

Hooks are fast feedback, not the security boundary (R: M-4). Production risk configuration, production strategy manifests, and the hook files themselves must be owned by a separate OS user and be read-only to the user the agent runs as; the deterministic runtime verifies signed hashes of all three at startup and refuses to trade on any mismatch (extends the §17 signed-configuration control and the §8.1 configuration-integrity kill-switch trigger).

## 7.4 Cost-aware model routing

Create a model-routing policy:

- **Frontier/highest-quality model:** governance, architecture, risk reviews, strategy changes, production incidents, challenger promotion.
- **Mid-tier model:** code implementation, refactoring, ordinary debugging, report synthesis.
- **Low-cost model or deterministic code:** repetitive extraction, schema conversion, log parsing, basic summaries.

Model routing must never lower quality for safety-critical decisions merely to reduce cost.

---

# 8. DETERMINISTIC LOCAL RUNTIME

Use Python unless a broker SDK or operating-system integration strongly justifies another language.

Run all services as tasks inside a **single-process asyncio supervisor** with one database-writer coordinator; separate OS processes require re-proving §10.1 write concurrency and complicate the kill switch and §18 process supervision. (R: N-6)

## 8.1 Services

### Market Data Service

Responsibilities:

- Connect to approved broker/data source
- Receive bid, ask, candles, timestamps, and broker tick volume (spot FX has no consolidated volume; feature definitions must not assume cross-broker volume comparability) (R: N-8)
- Normalize symbols and precision
- Detect stale or missing data
- Persist required raw data
- Publish health status

### Session Clock Service

Responsibilities:

- Use IANA zones `America/Chicago`, `Europe/London`, and UTC
- Correctly handle DST divergence
- Control startup, activation, entry cutoff, flattening, and review windows
- All session boundaries are defined in Europe/London; every other timezone, including America/Chicago, is for display and notification only (R: C-2)
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
- Revalidate price and spread against candidate tolerances immediately before submission (owns the price/spread revalidation stage of §2) (R: N-13)
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
- Handle live positions according to the emergency-policy table below
- Notify owner
- Write incident record

Emergency policy by trigger class (R: N-3):

| Trigger | Live-position action |
|---|---|
| Manual owner activation | Owner chooses: hold with verified stop, or flatten |
| Risk-limit activation | Hold with verified broker stop; no modifications |
| Data-health activation | Hold with verified broker stop; re-verify the stop via broker API |
| Broker-health activation | Hold; no modifications; escalate to owner immediately |
| Stop-loss failure activation | Flatten immediately at market |
| Drawdown activation | Hold with verified broker stop until the flatten window |
| Configuration-integrity activation | Flatten immediately at market |

Watchdog requirement (R: N-7): every service maintains a heartbeat updated at a configured interval; a dead-man's check halts new entries when any heartbeat is stale beyond its threshold, and heartbeat loss raises a mobile alert.

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

# 11. STRATEGY SPECIFICATION STANDARD

Each strategy version must be declarative and versioned.

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
- Trade-level bootstrap confidence intervals on net expectancy (Sharpe and Sortino only where the sample supports meaningful annualization) (R: M-8)
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

## 12.4 Anti-overfitting requirements

- No future leakage
- No look-ahead indicators
- Purged or embargoed validation where appropriate
- Explicit transaction-cost model
- Parameter sensitivity analysis
- Multiple-testing record
- No promotion based solely on one favorable interval
- Separate discovery and confirmation samples

## 12.5 Promotion authority

Promotion requires:

- Chief Quant and Validation Agent recommendation with reproducible report
- Chief Risk review
- Signed promotion record
- Owner approval for live permission changes

## 12.6 Minimum evidence requirements (R: M-8)

| Decision | Minimum sample |
|---|---|
| Probation exit review | 30 correctly processed signals **[D-5]** |
| Per-strategy tier qualification above Standard | 50 trades across shadow, paper, and live combined |
| Challenger promotion | Separate confirmation sample per §12.4 |
| Edge-score weight/threshold recalibration | 100 classified candidates with recorded outcomes (§5.2) |

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
7. Review after **30 correctly processed signals** (§12.6) **[D-5]**

A missed or expired approval is a no-trade and counts as a valid probation observation (rule 6 of §0 makes "no trade" a preferred outcome; approval at 2:00–4:30 a.m. owner-local time will be missed sometimes, and that is acceptable). The owner may optionally pre-approve a session envelope — permitted strategy set and maximum tier — at briefing time, with per-trade approval retained for High and Exceptional candidates. (R: M-3)

A profitable short run does not prove readiness. Operational correctness, stop protection, reconciliation, and rule adherence are mandatory.

## Trade approval card

Every approval-required candidate must show:

- Instrument
- Strategy and version
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

Default schedule, **anchored in Europe/London** (R: C-2). America/Chicago equivalents are display-only — approximately 1:15 a.m.–5:00 a.m. Chicago outside DST-divergence windows:

- 07:15 London: runtime and broker health checks
- 07:30 London: Asian range finalized according to strategy definition
- 07:40 London: pre-session briefing
- 08:00 London: initial trading activation target
- 10:30 London: default new-entry cutoff
- 11:00 London: default mandatory flatten/review transition

All boundaries are evaluated with the `Europe/London` IANA zone, never fixed UTC offsets. During US/UK DST-divergence windows (in 2026: 9–28 March and 25–31 October) the Chicago display times shift by one hour; the London anchor does not move.

Session validity requires a holiday-calendar input: if the calendar is missing, or marks a UK or US market holiday, the session does not activate (fail closed). Friday sessions observe the same flatten boundary; no position may be held over a weekend. A failure to flatten is a broker-health kill-switch trigger with immediate owner escalation. (R: N-11)

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

## Jurisdiction annex — United States (as of July 2026) (R: M-7, C-1)

The owner trades from the United States. The audit must treat these as binding constraints, re-verified at audit time:

- Leverage capped at 50:1 on major pairs (2% security deposit) and 20:1 on others (CFTC retail forex rules)
- NFA Compliance Rule 2-43(b): offsetting positions prohibited within a pair; FIFO close-out; no hedging
- Retail spot forex is available only through CFTC-registered RFED/FCM brokers; the current set is approximately OANDA, FOREX.com (GAIN), IG US / tastyfx, and Interactive Brokers
- Sizing granularity is the deciding constraint at the $250 tier: sub-1,000-unit orders are required for small risk at wide stops, and among US brokers effectively only OANDA offers 1-unit granularity plus a public REST API (v20). **[D-1 ratified 2026-07-29: OANDA US confirmed as the audit's working target.]**
- Tax: US spot forex defaults to IRC Section 988 ordinary-income treatment; keep records accordingly and confirm treatment with a CPA
- Trading solely the owner's own capital requires no license or registration; "firm" is branding. Accepting outside capital would change this and requires separate legal review before any such step

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
- Signed production configuration, strategy manifests, and hook files, hash-verified by the runtime at startup; any mismatch disables trading (R: M-4)
- Tamper-evident audit records: hash-chained (each record embeds the previous record's hash) with periodic anchors pushed off-machine to the private repository (R: N-5)
- Config-signing key held in the OS keychain under a separate OS user from the one the agent runs as (R: N-5)
- Structured-only ingestion of external calendar data from an allowlisted source; free-text news is summarize-only and may only downgrade risk state (R: M-5)
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
12. Audit search

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
- Weekly limits (ISO-week boundary in Europe/London) (R: N-2)
- Drawdown-state transitions and per-state permission sets (R: N-4)
- DST logic, including: session boundaries equal 08:00/10:30/11:00 Europe/London on 2026-03-15 and 2026-10-28 (DST-divergence weeks) (R: C-2)
- Margin-feasibility overlay and per-tier minimum stop distances (R: C-1)
- Pending-promotion approval flow, including lapse and re-arm (R: C-3)
- Candidate expiration
- Configuration schema

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
- No tier promotion takes effect without owner approval (R: C-3)
- Risk contracts after drawdown
- Startup hash verification blocks trading on config, manifest, or hook mismatch (R: M-4)
- Research agents cannot alter production files

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
- Configuration schemas
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

## Phase 3: Data and strategy research framework

Deliverables:

- Market data normalization
- Historical replay
- Feature engine
- Strategy manifests
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

- Executive and specialist agents
- Structured schemas
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
  name: Claude London Trading Firm
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
  week_boundary: iso_week_europe_london
  tier_promotion_requires_owner_approval: true
  deposits_advance_milestones: false
  margin_utilization_cap_fraction: 0.30
  drawdown_states:
    caution_from_anchor: -0.05
    restricted_from_anchor: -0.10
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

data:
  economic_calendar_source: financial_modeling_prep
  economic_calendar_endpoint: stable/economics-calendar
  economic_calendar_min_plan: starter

session:
  anchor_timezone: Europe/London
  startup_london: "07:15"
  asian_range_final_london: "07:30"
  briefing_london: "07:40"
  activation_london: "08:00"
  entry_cutoff_london: "10:30"
  flatten_london: "11:00"
  display_timezone: America/Chicago
  holiday_calendar_required: true

strategies:
  live_allowed: []
  research_allowed:
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
- Shadow and paper phases meet acceptance criteria
- Owner can activate the kill switch from laptop and approved mobile path
- Live mode remains disabled by default
- A documented live activation checklist exists

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
9. **Minimal monthly cost estimate**, including an explicit comparison of operating costs to plausible monthly P&L at the current capital tier (R: O-2)
10. **List of owner decisions that are genuinely blocking**

Then begin Phase 1 using the safest reasonable defaults for nonblocking implementation details.

---

# 27. FINAL GOVERNING PRINCIPLE

Build a selective, evidence-driven, self-scaling trading firm—not a reckless high-frequency gambling system and not a permanently timid bot.

The system may act aggressively when a rare, statistically validated exceptional-edge opportunity appears, but aggressiveness must always remain bounded by deterministic risk controls, current closed equity, execution quality, and the account's drawdown state.

Claude creates intelligence. Deterministic software enforces reality.

---

# 28. AMENDMENT RECORD AND PENDING OWNER DECISIONS

## 28.1 v1.0.0 → v1.1.0 changelist

Amendments applied per the design review `docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md` (finding IDs cited inline as R: …):

| Sections | Change | Findings |
|---|---|---|
| §3.1 | Gap-risk acknowledgement | N-10 |
| §3.2 | Within-tier sizing rule; margin-feasibility overlay | N-1, C-1, M-2 |
| §3.4 | ISO-week boundary (Europe/London) | N-2 |
| §4.1 | Expectation-setting note on the doubling ladder | O-1 |
| §4.2 | Owner-approved pending promotion; deposits excluded from milestones | C-3 |
| §4.5 | Parameterized drawdown states; permissions bound to tier + state | N-4, O-4 |
| §5.1–5.2 | Deterministic/LLM partition; lower-only rule; integer scores; recalibration milestone | M-1, M-8 |
| §6 | Agent roster consolidated 15 → 6 | M-6 |
| §6.3 | Structured-only calendar ingestion; news downgrade-only | M-5 |
| §7.3 | OS-permission split; startup hash verification including hooks | M-4 |
| §8 | Single-process asyncio supervisor; London-anchored session clock; broker-adapter pre-submission revalidation; kill-switch emergency-policy table; watchdog heartbeats; broker tick volume | N-6, C-2, N-13, N-3, N-7, N-8 |
| §12 | Bootstrap CIs; §12.6 minimum-evidence table; promotion list updated to consolidated roster | M-8 |
| §13 | Probation exit at 30 signals; missed approval = valid observation; optional session-envelope approval | M-3 |
| §14 | London-anchored schedule; DST-divergence note; holiday/Friday/flatten-failure policy | C-2, N-11 |
| §16 | United States jurisdiction annex | M-7, C-1 |
| §17 | Hash-chained audit with off-machine anchors; key custody; injection defenses | N-5, M-5, M-4 |
| §21 | New unit and acceptance tests for the above | C-1, C-2, C-3, N-2, N-4, M-4 |
| §24 | Configuration keys for all of the above; London-anchored session block | C-2, C-3, N-1, N-2, N-4 |
| §26 | Cost estimate must include cost-vs-plausible-return comparison | O-2 |

## 28.2 Owner decisions — ratified 2026-07-29

All seven decisions were ratified by the owner on 2026-07-29: D-1 through D-6 as recommended, D-7 with the source selected and verified by the implementer at the owner's direction. Changing any of them now requires editing the corresponding section and re-versioning this document.

- [x] **D-1 Broker target:** OANDA US as the working audit target (sole US RFED with 1-unit granularity plus a public API) — §16
- [x] **D-2 Promotion default:** owner-approved pending promotion (was: automatic) — §4.2
- [x] **D-3 Deposit accounting:** deposits never advance milestone tiers — §4.2
- [x] **D-4 Exceptional tier:** retained at 10% under the margin-feasibility overlay; revisit at first tier promotion — §3.2
- [x] **D-5 Probation exit sample:** 30 correctly processed signals — §12.6, §13
- [x] **D-6 Week boundary:** ISO week, Europe/London — §3.4
- [x] **D-7 Economic-calendar source:** **Financial Modeling Prep economic-calendar API** (`stable/economics-calendar`), Starter plan or above — §6.3, §24.

D-7 selection record: structured JSON events (timestamp, country/currency, event name, impact rating, estimate/previous/actual) satisfying the §6.3/§17 structured-fields rule; licensed for programmatic use. Verified live on 2026-07-29 that the endpoint exists and is gated to Starter-and-above plans; **the owner's current FMP plan does not include it — an upgrade (approximately $25–30/month; verify price at purchase) is required before Phase 0 completes.** Rejected alternatives: Forex Factory and Investing.com calendars (scrape-class, no programmatic license — fail the allowlist requirement), Finnhub and Trading Economics (calendars gated to costlier tiers), OANDA fxLabs calendar (deprecated). Feed outages are already handled fail-closed (§0.10, §24 `reject_unknown_news_state`).
