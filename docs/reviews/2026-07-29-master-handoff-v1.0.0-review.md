# Design Review — Claude London Trading Firm, Master Handoff v1.0.0

| | |
|---|---|
| **Reviewed document** | `docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF.md` (v1.0.0, 27 sections) |
| **SHA-256 of reviewed copy** | `e6daa1d16591f1a199fb1b372aeacbb916ac3d18039a3b38236a57fbac9749d1` |
| **Review date** | 2026-07-29 |
| **Reviewer** | Claude (Claude Code), acting per the spec's own §26 mandate — this review partially fulfills §26 items 5 (assumption register), 6 (risk and architecture conflict review), and 10 (blocking owner decisions) |
| **Scope** | The specification document only. The repository contains no implementation to review. Nothing was built as part of this review. |
| **Method** | Full read of the spec; independent verification of all arithmetic cited below (Appendix A); regulatory facts checked against current sources as of July 2026; internal-consistency checks logged in Appendix B, including the ones that **passed**. |

---

## 1. Executive summary

This is an unusually disciplined specification. Its central architectural commitment — *LLMs recommend, deterministic code enforces* (§2, §27) — is the correct one, and the spec carries it through more consistently than most professional trading-system designs: stop-first position sizing (§3.3), fail-closed defaults (§0.10, §24), broker-held stops (§0.9), broker-state-authoritative reconciliation (§8.1), an explicit prohibition on recovery behavior (§0.7), `live_allowed: []` as the shipped default (§24), and a serious anti-overfitting protocol (§12.4). The strengths section below is not a courtesy; the passed-checks log in Appendix B shows the spec's arithmetic is internally consistent throughout.

The spec is nevertheless **not buildable as written**, for three reasons that are defects of fact rather than of taste:

1. **The upper half of the risk ladder is margin-infeasible in the owner's jurisdiction.** Under the US retail cap of 50:1 on major pairs, a $25-risk GBP/USD trade with a 25-pip stop requires ≈$266 of margin — more than the entire $250 account. The spec's own `broker_and_margin_safe_capacity` term (§3.3) would silently veto most High and Exceptional trades, meaning the headline ladder the whole document is organized around largely cannot execute at the initial tier (finding C-1).
2. **The default session schedule contradicts the spec's own timezone doctrine.** §8.1 commands "Never use a fixed UTC offset for the London open," yet §24 hard-codes Chicago-local session times. On 27 days of 2026 (9–28 March, 25–31 October) 02:00 Chicago is 07:00 London, so the configured firm trades the pre-open lull and flattens mid-morning (finding C-2).
3. **Automatic capital-tier promotion silently doubles every live risk limit** with only a notification, in tension with §0 rule 4 ("No unilateral production changes") and §12.5 ("Owner approval for live permission changes") — and §4.2's own promotion conditions allow a deposit to trigger it (finding C-3).

Beyond the Critical items, the Major findings share one theme: **the deterministic perimeter leaks where LLM output becomes numeric input.** The Edge Confidence Score (§5) is computed partly from LLM-agent judgments yet gates real dollar risk; the protective hooks (§7.3) live inside the repository the constrained agent edits; and the news/calendar agent (§6.3.J) ingests external text with no prompt-injection defenses specified.

**Verdict: approve the architectural direction; block build Phases 2+ (§22) until the three Critical findings are resolved by spec amendment (v1.1.0). The proposed amendments in §7 of this review are sufficient and mechanical.**

*Process note:* this review was produced by a single reviewer. The intended multi-agent adversarial-verification pass could not run in this session (account usage limit); in partial compensation, every quantitative claim was verified by direct computation or a current primary/secondary source, reproduced in Appendix A, and every section citation was grep-verified against the reviewed copy.

---

## 2. Strengths

These are specific and load-bearing, not generic praise. They should survive any revision.

| # | Strength | Where | Why it matters |
|---|---|---|---|
| S-1 | Deterministic order path with no skippable stages; LLMs cannot submit orders | §2 | The single most important property of the design. Most retail "AI trading" projects get exactly this wrong. |
| S-2 | Stop defined first, size derived second; reject if broker minimums force over-risk | §3.3, §8.1 | Prevents the classic inversion where desired size dictates a fantasy stop. |
| S-3 | Fail-closed doctrine enumerated concretely (stale data, missing calendar, reconciliation failure → no new entries) | §0.10, §24 | Enumerating the triggers makes it testable (§21 acceptance tests do so). |
| S-4 | Broker-held protective stops mandatory; stop confirmation is a pipeline stage | §0.9, §2, §8.1 | Survives laptop death, the design's weakest physical link. |
| S-5 | Prohibition of martingale, averaging down, stop widening, revenge sizing — as *architecture*, not advice | §0.7, §3.4, §24 | Encoded as config flags with required tests (§3.4: "These amounts must become configuration values with tests"). |
| S-6 | `live_allowed: []` is the shipped default; live permission requires phases + owner approval | §24 | The repo cannot trade live by accident. |
| S-7 | Restart sequence: reconcile against broker before any new order; halt if uncertain | §18 | Correct crash-recovery posture; broker state is treated as authoritative (§8.1). |
| S-8 | Champion immutability during live sessions; challengers cannot write production config | §15, §6.4.O | Blocks the most common self-sabotage loop in adaptive systems. |
| S-9 | Anti-overfitting protocol: purged validation, multiple-testing record, separate discovery/confirmation samples, probability-of-overfitting diagnostics | §12.4 | Above the bar of most published retail methodology. |
| S-10 | Audit-before-build directive; "no trade" as preferred outcome; no profit target | §0.6, §3.5, §26 | Correct incentives from the first page. |
| S-11 | The arithmetic is right | §3.2, §4.3, §5.1 | Ladder percentages, tier doubling table, and edge-weight sums all verify exactly (Appendix B). |

---

## 3. Findings

Severity taxonomy:

- **Critical** — would cause capital loss, a regulatory breach, or a safety-control failure if built as written.
- **Major** — materially undermines the spec's own goals; must be resolved before build Phase 2 (§22).
- **Minor** — contained correctness or clarity defect.
- **Observation** — realism or judgment note; no spec change strictly required.

### 3.1 Critical

---

#### C-1 · The High and Exceptional risk tiers are margin-infeasible at the $250 tier under US leverage rules

**Citations:** §3.2 (risk ladder), §3.3 (`broker_and_margin_safe_capacity`), §16 ("Legal availability to the owner’s jurisdiction"), §1 ($250 initial capital).

**Defect.** The spec's control timezone (America/Chicago, §heading) makes the owner a US resident for planning purposes. CFTC rules cap retail forex leverage at 50:1 on major pairs (2% security deposit; 20:1/5% on minors) — verified against current sources, Appendix A.4. At the live GBP/USD rate of 1.3298 (2026-07-29), the margin required to open each ladder trade is:

| Risk | 10-pip stop | 20-pip stop | 25-pip stop | 40-pip stop |
|---|---:|---:|---:|---:|
| $2.50 (Standard) | $66.49 | $33.25 | **$26.60** | $16.62 |
| $7.50 (Strong) | $199.47 | $99.74 | $79.79 | $49.87 |
| $12.50 (High) | **$332.45 ✗** | $166.23 | $132.98 | $83.11 |
| $25.00 (Exceptional) | **$664.90 ✗** | **$332.45 ✗** | **$265.96 ✗** | $166.23 |

(✗ = margin exceeds the entire $250 account. Computation: `units = risk / (stop_pips × $0.0001)`; `margin = units × 1.3298 × 0.02`. EUR/USD at 1.1394 is ~14% lighter but the Exceptional/25-pip case still consumes $227.88 — 91% of equity.)

An Exceptional trade with any stop tighter than ~27 pips **cannot be opened at all**, and even at wider stops the position consumes most of the account as margin, leaving almost no buffer above the broker's margin-closeout threshold. A High trade with the tight stops typical of London-breakout entries (10–15 pips) is likewise unopenable.

**Consequence.** The `broker_and_margin_safe_capacity` term in §3.3 would correctly and silently veto most High/Exceptional candidates — so the system is *safe*, but the entire edge-classification superstructure (§5) is built to unlock tiers that mostly cannot execute. Research effort, agent design, and owner expectations are all mis-aimed. Nothing in the spec surfaces this; §16's broker audit asks generic questions and would discover it late.

**Recommendation.** Amend §3.2 with a margin-feasibility overlay: publish, per tier, the minimum stop distance at which the tier is executable at the current anchor (a derived table, recomputed per tier anchor and instrument). Amend §16 to name the US regime explicitly (CFTC 50:1/20:1, NFA FIFO rule 2-43(b), no hedging, RFED shortlist) as first-class audit inputs. Either re-derive the Exceptional ceiling from margin-feasible sizing (e.g., cap risk such that margin ≤ 30% of equity at the intended stop), or accept and document that Exceptional is aspirational until roughly the $1,000 tier.

---

#### C-2 · The default session schedule violates the spec's own timezone doctrine and trades the wrong hour 27 days per year

**Citations:** §8.1 Session Clock ("Never use a fixed UTC offset for the London open"), §14 ("Default Chicago-oriented schedule"), §24 (`activation_local: "02:00"` etc. under `session:`).

**Defect.** §14 and §24 anchor the trading day in **America/Chicago local time** (startup 01:15, activation 02:00, cutoff 04:30, flatten 05:00). The London open is a Europe/London phenomenon. The two zones' DST transitions diverge: verified by direct computation (Appendix A.3), on exactly **27 days of 2026 — 9–28 March and 25–31 October — 02:00 Chicago is 07:00 London**, not 08:00. During those windows the configured firm activates into the pre-London lull (the exact low-liquidity, wide-spread regime the strategies are designed to avoid), finalizes the "Asian range" an hour early — silently changing the *feature definitions* of all three strategies — and flattens at 10:00 London, mid-morning. §14's own caveat ("must be calculated using `Europe/London` and `America/Chicago`, not hard-coded offsets") does not save it: the *anchor* is Chicago, so the calculation is faithful to the wrong reference.

**Consequence.** Two ~1–3-week windows per year of systematically distorted features, entries, and session statistics — precisely the DST-mismatch weeks §10.3 demands be tested. Backtests anchored to London time would not reproduce live behavior anchored to Chicago time; the divergence would corrupt strategy validation samples without any error being raised.

**Recommendation.** Amend §14/§24: define all session boundaries in **Europe/London** (e.g., `activation_london: "08:00"`), derive Chicago times for display and owner notifications only. Add a §21 unit test asserting the activation instant equals 08:00 Europe/London on 2026-03-15 and 2026-10-28 (both inside divergence windows).

---

#### C-3 · Automatic tier promotion silently doubles every live risk limit — and a deposit can trigger it

**Citations:** §4.2 ("By default, tier promotion is automatic once these deterministic conditions pass"), §4.2 condition 4 ("The milestone is produced by trading P&L and recognized deposits according to configured capital-accounting rules"), versus §0 rule 4 ("No unilateral production changes"), §12.5 ("Owner approval for live permission changes"), §3.1 ("Deposits, withdrawals, credits, rebates, and manual broker adjustments must be separated from trading P&L").

**Defect.** Tier promotion doubles the dollar value of every live risk limit — per-trade ceilings, session loss, weekly loss (§4.3: "Initial dollar limits scale by the tier factor"). That is a production risk-parameter change, the exact class of change §0.4 and §12.5 place behind owner approval; §4.2 grants it to a deterministic trigger with only a notification and an after-the-fact freeze. Worse, condition 4 explicitly admits "recognized deposits" into milestone accounting, while §3.1 requires deposits be separated from trading P&L. As written, depositing $250 the day after going live doubles all limits with no human in the loop and no trading evidence behind the promotion.

**Consequence.** The system's risk envelope can expand without owner consent, and can expand on capital that reflects no validated performance — contradicting §4.6's own principle that "Scaling is not permission to degrade quality."

**Recommendation.** Flip the default: promotion conditions arm a **pending promotion** that takes effect only on explicit owner approval (one notification tap; expires if unapproved). Resolve the deposit question explicitly — recommended rule: deposits raise the *active risk base* (sizing denominator) but never advance the *milestone tier*; only closed trading P&L advances milestones. (This is also the blocking owner decision D-2/D-3 in §6 below.)

---

### 3.2 Major

---

#### M-1 · The Edge Confidence Score lets LLM judgment leak through the deterministic perimeter into position size

**Citations:** §5.1 (components: "30% strategy expectancy quality, 20% regime match, 15% structural confirmation, 15% execution conditions, 10% higher-timeframe alignment, 10% model stability"), §5.2 ("It only determines the maximum tier the deterministic risk gate may consider"), §6.3 (Regime Analyst, Liquidity and Structure Analyst are LLM agents), §0.3.

**Defect.** The risk engine deterministically enforces caps *given* a classification — but several score components (regime match, structural confirmation, higher-timeframe alignment) originate as LLM-agent judgments. An enthusiastic (or prompt-injected — see M-5) agent chain can inflate the score and *legitimately* unlock the 10% tier through the front door. §5.3's independent gates ("Claude confidence language… can never unlock this tier") mitigate but do not close this: the gates check binary conditions, while the score itself remains LLM-influenced. §6.3.K gestures at the fix ("express them as deterministic data where possible") without requiring it.

**Consequence.** The spec's central safety claim — deterministic code authorizes size (§0.3) — is weaker than stated. The perimeter is deterministic; the *inputs* to it are not.

**Recommendation.** Amend §5.1: partition each component into deterministically computable sub-scores (expectancy from validation records, execution conditions from live spread/latency measurements, regime from coded classifiers) and LLM-assessed sub-scores. Rule: **LLM-derived inputs may lower a candidate's tier, never raise it** above what the deterministic sub-scores alone support. This preserves the agents' value as a veto layer while closing the escalation path.

---

#### M-2 · A 10% single-trade risk ceiling is far outside professional practice, and the spec never argues for it

**Citations:** §3.2 (Exceptional: $25.00, 10%), §3.4, §4.3.

**Defect.** Professional risk norms for discretionary/systematic FX run 0.25–2% per trade. The spec's session/weekly caps do bound the damage (one Exceptional loss ends the session; the $200 floor is unreachable within a single week — verified, Appendix A.1), but the per-trade ceiling is still 5–20× conventional practice, and the document nowhere justifies the number beyond "exceptional edge." Three Exceptional losses across three weeks is −27.1% compounded. The floor sits only two max-loss sessions away, so the realistic failure mode is rapid demotion to shadow mode — safe, but making the Exceptional tier's practical value questionable even where marginable (see C-1).

**Consequence.** Combined with C-1, the top tier is both statistically aggressive and mostly unexecutable — the strongest candidate for simplification in the whole spec.

**Recommendation.** Either cap Exceptional at 5% with the same gates, or retain 10% but add the justification the spec owes itself: a required minimum validated expectancy and sample size for the *specific setup subtype* (§5.3 already requires subtype qualification; add numbers), plus the margin-feasibility overlay from C-1.

---

#### M-3 · Probation requires the owner to approve every trade between 01:40 and 05:00 in the owner's own timezone, indefinitely

**Citations:** §13 ("Human approval for every live trade during probation", "Review after a predefined sample of correctly processed signals"), §14 (briefing 01:40, activation 02:00, cutoff 04:30 America/Chicago), §0.12, §19.

**Defect.** The spec's probation design assumes a decision-capable human at 2–4:30 a.m. Chicago time every trading night for an undefined duration — §13's "predefined sample" never defines N, so probation has no computable end. Approval expiry (§13) handles the *mechanics* of a missed approval but not the *viability* of the arrangement; owner fatigue is a real risk-of-error input the reliability section (§18) never models. There is also unacknowledged friction with §0.12 ("Ask the owner only for decisions that cannot be safely resolved…") — probation deliberately violates it nightly, which is fine, but the spec should say which rule dominates and for how long.

**Consequence.** The most likely real-world outcome is skipped sessions and an inconsistent probation sample — or a fatigued owner rubber-stamping at 3 a.m., which defeats the control's purpose.

**Recommendation.** Define N (e.g., 30 correctly processed signals). State that missed approval = no trade = still a valid probation observation (the spec's own §0.6 supports this). Consider an explicit "approval session" model: the owner pre-approves the session's strategy/tier envelope at briefing time, with per-trade approval only for High/Exceptional candidates.

---

#### M-4 · The protective hooks live inside the repository the constrained agent edits — they are advisory, not enforcement

**Citations:** §7.3 ("Pre-edit protection: block unauthorized edits to production risk and strategy manifests"), §7.2, §17 ("Signed or hashed production configuration").

**Defect.** Claude Code hooks and settings live under `.claude/` in the working tree. An agent with repository write access — which the builder agent must have — can in principle modify the hooks, the settings, or the protected files through paths the hooks don't cover. A control that the constrained party can edit is a convention, not a control. The spec's own §17 contains the right idea (signed/hashed production configuration) but doesn't connect it to hook integrity, and no runtime component verifies config hashes at startup.

**Consequence.** §21's acceptance test "Research agents cannot alter production files" cannot actually be guaranteed by the mechanism §7.3 proposes.

**Recommendation.** Layer the defenses: (1) OS-level file permissions — production manifests owned by a separate OS user, read-only to the agent's user; (2) the deterministic runtime verifies signed hashes of risk config, strategy manifests, **and the hook files themselves** at startup and refuses to trade on mismatch (extend §8.1 Kill Switch's "Configuration-integrity activation", which already exists, to enumerate these inputs); (3) hooks remain as fast-feedback, not as the security boundary.

---

#### M-5 · The news/calendar agent ingests external text with no prompt-injection defenses anywhere in the spec

**Citations:** §6.3.J (Macro and Event Risk Analyst; "It must not hallucinate calendar data"), §17 (security controls list — no injection item), §5.1 (regime/context feed the edge score).

**Defect.** Agent J consumes economic-calendar and news content from external sources, and its output flows into trade briefs and the edge-score context. External text processed by an LLM is an injection surface: a crafted headline or calendar-feed field could steer the analysis chain. §17's control list covers secrets, credentials, and tampering, but not adversarial input to agents.

**Consequence.** Combined with M-1, external text has a (bounded but real) path toward influencing position size. The deterministic gates cap the damage; they don't eliminate the vector.

**Recommendation.** Add to §17: calendar data must arrive as **structured fields from an allowlisted source** (times, currencies, impact ratings — not prose); free-text news is summarize-only and may only *downgrade* risk state (consistent with the M-1 rule); agent-J output is schema-validated (§6.5 already requires this — make the schema forbid free-text fields that downstream agents would re-read).

---

#### M-6 · Fifteen agents contradicts the spec's own minimality rule and its own cost doctrine

**Citations:** §6 preamble ("Use the smallest number of high-quality agents… Do not create agents merely to simulate a large firm"), §6.1–6.4 (agents A through O), §7.4 (cost-aware model routing), §23 (minimal-cost stack).

**Defect.** The roster defines 15 agents, several of which are the same skill with different nouns: three strategy specialists (F/G/H) that all "analyze validated variants of a session structure," three context analysts (I/J/K), four validation/learning agents (L/M/N/O). Each agent multiplies orchestration code, schema maintenance, and per-session token cost — against a $250 account (see O-2) and §7.4's own frontier-model quality floor for safety-critical calls.

**Consequence.** Slower build, higher run cost, more schema surface to validate — for no demonstrated specialization gain at the initial mandate of *three strategies on two instruments*.

**Recommendation.** Consolidate to 6: Governor (A), Quant/Validation (B+N+M), Risk (C), Strategist (F+G+H parameterized by strategy manifest), Context (I+J+K), Learning/Audit (E+L+O; D's comparison duty folds into the Governor). The spec's manifest-driven strategy standard (§11) makes the parameterized strategist natural. Re-expand only on evidence a merged agent underperforms.

---

#### M-7 · The US regulatory regime is never named, though it decides broker selection and shapes the design

**Citations:** §16 ("Legal availability to the owner’s jurisdiction", "Position-size increments compatible with $250 capital"), §8.1 Broker Adapter, control timezone America/Chicago.

**Defect.** The broker audit is written jurisdiction-generically, but the binding facts are specific and knowable now (verified, Appendix A.4): CFTC leverage caps (50:1 majors / 20:1 minors); NFA Rule 2-43(b) FIFO offsets and the hedging prohibition; a shortlist of roughly five RFED/FCM brokers serving US retail (OANDA, FOREX.com/GAIN, IG US, tastyfx, Interactive Brokers); and — decisive for this design — **sub-1,000-unit sizing**. Standard-tier trades at $2.50 risk with stops wider than 25 pips require positions *smaller than one micro lot* (e.g., 625 units at a 40-pip stop). Among US brokers, effectively only OANDA offers 1-unit granularity plus a public REST API (v20). Elsewhere, §8.1's (correct) "reject if minimum size exceeds allowed risk" rule would veto much of the Standard tier. FIFO also matters *now*: it forbids simultaneous long/short in one pair, which any future multi-position or hedged-scaling plan (§4.6 hints at expansions) must respect.

**Consequence.** Without these constraints stated, Phase 0's broker audit (§22) could burn weeks rediscovering that the candidate set has one realistic member.

**Recommendation.** Add a jurisdiction annex to §16 with the facts above and "as of" dating; make *unit-level sizing granularity* and *API quality* the top two audit criteria at the $250 tier. Add a governance note (§17 or governance docs): US spot forex defaults to IRC Section 988 ordinary-income treatment — keep records accordingly. Also record the reassurance: trading solely your own capital requires no license; "firm" is branding, not a regulatory status — and must stay that way (no outside capital) without separate legal review.

---

#### M-8 · The validation ladder's statistics are underpowered at the mandated trade frequency, and probation has no defined sample size

**Citations:** §3.4 (max 2 trades/session), §12.3 ("Sharpe and Sortino where meaningful"), §12.5, §13 ("Review after a predefined sample of correctly processed signals"), §5.2 (score thresholds 70/80/90/95).

**Defect.** At ≤2 trades per London session and ~21 sessions/month, the live-sample accumulation rate is ≤42 trades/month *across all strategies combined* — months to reach even n≈30 per strategy. Against that reality: §13's "predefined sample" is never given a number; annualized Sharpe/Sortino at this frequency is statistically meaningless (the spec half-knows this — "where meaningful" — but names no alternative); and the edge-score thresholds (70/80/90/95) plus component weights are unvalidated priors stated to three significant figures, with no minimum-evidence requirement before the score is allowed to gate real dollars, and no stated handling of boundary scores. §12.3's "calibration by edge tier" requirement is the right instinct but has no teeth without a sample-size floor.

**Consequence.** Early live statistics will be noise; the danger is not that the system won't compute them, but that they'll be *acted on* (tier qualification, challenger promotion) long before they mean anything.

**Recommendation.** Define minimum samples per decision type (e.g., probation exit: 30 processed signals; per-strategy tier qualification: 50 trades in shadow+paper+live combined; challenger promotion: per §12.4's separate confirmation sample). Replace Sharpe/Sortino at this scale with trade-level bootstrap confidence intervals on expectancy. State that edge-score weights/thresholds are priors, and schedule their first recalibration at a defined sample milestone.

---

### 3.3 Minor

---

#### N-1 · Within-tier sizing basis is ambiguous (fixed dollars vs. percent of current equity)

**Citations:** §3.2 (dollar amounts *and* "Initial-equity share" column), §3.3 (`current_equity_based_ceiling` — used, never defined), §4.4 ("Active risk base: current closed equity"), §24 (`initial_usd` and `initial_equity_fraction` both present).

At $310 closed equity (between anchors), is a Standard trade $2.50 (tier dollars) or $3.10 (1% of equity)? §4.4 mandates contraction below the anchor but is silent above it. **Recommendation:** define `allowed = min(tier_dollar_cap, fraction × current_closed_equity)` — contraction below anchor, no expansion above it until promotion. One sentence and one unit test (§21 already lists "Risk ladder" tests; add this case).

#### N-2 · "Week" is never defined for the weekly loss limit

**Citations:** §3.4 ("Maximum weekly realized loss: $37.50"), §10.3.

Calendar week in which zone? ISO week? Broker statement week? The limit's bite depends on the boundary (a Sunday-night vs. Monday-morning reset differs materially in FX). **Recommendation:** ISO week boundaries evaluated in Europe/London, stated in §3.4 and §24, with a DST-week unit test.

#### N-3 · The kill switch's "emergency policy" is referenced but never defined

**Citations:** §8.1 Kill Switch ("Preserve or close live positions according to emergency policy").

Whether to hold or flatten on each trigger class is the highest-stakes runtime decision the spec leaves blank. **Recommendation:** add a per-trigger table to §8.1 (e.g., data-stale → hold, stop verified; stop-verification-failure → flatten immediately; broker-desync → hold, no modifications, escalate).

#### N-4 · Drawdown machinery is invoked but unparameterized

**Citations:** §4.5 ("a tier's lower safety boundary", "A drawdown-state machine **may** impose more restrictive risk"), §24 (no corresponding keys).

No boundary values, no state definitions, no entry/exit conditions — untestable as specified, though §21 lists "Drawdown state" among required unit tests. **Recommendation:** define states (NORMAL / CAUTION at −5% from tier anchor / RESTRICTED at −10% / SHADOW at the $200 floor) with per-state permission sets in §24.

#### N-5 · Tamper-evidence and config-signing mechanisms are named but not specified — and the key would live on the same laptop

**Citations:** §17 ("Signed or hashed production configuration", "Tamper-evident audit records").

Unspecified mechanism, unspecified key custody; a signing key on the machine the agent operates weakens M-4's fix. **Recommendation:** hash-chain the audit log (each record embeds the previous record's hash) with periodic anchors pushed off-machine (e.g., to the private GitHub repo); sign production config with a key held in the OS keychain under a *different* OS user than the agent runs as (aligning with M-4's permission split).

#### N-6 · SQLite-WAL with ~10 concurrently writing services is the architecture's known weak joint

**Citations:** §8.1 (ten services), §10.1 ("Use SQLite in WAL mode… if concurrency tests prove sufficient").

WAL allows one writer at a time; a market-data writer persisting ticks contends with the audit writer on every decision. The spec's hedge ("if concurrency tests prove sufficient") is honest but leaves the likely outcome undesigned. **Recommendation:** specify a **single-process asyncio supervisor** hosting the services as tasks with one DB-writer coordinator. This also simplifies the kill switch (in-process flag beats inter-process signaling) and §18's process supervision (one process to babysit). Failure-injection tests (§21) get easier, not harder.

#### N-7 · Nothing watches the watcher

**Citations:** §8.1 Kill Switch, §18 (process supervisor).

The kill switch and reconciler are processes that can hang silently; §18's supervisor restarts *crashed* processes but detects no *stalled* ones. **Recommendation:** require a heartbeat file/row updated per service per interval, a dead-man's check that halts entries when any heartbeat staleness exceeds a threshold, and (given §18 already requires mobile access) a phone-side alert on heartbeat loss.

#### N-8 · "Available volume" is not a well-defined concept in spot FX

**Citations:** §8.1 Market Data Service ("Receive bid, ask, candles, timestamps, and available volume").

Spot FX has no consolidated tape; only per-broker tick counts or top-of-book sizes exist. Any strategy feature built on "volume" would silently mean "this broker's activity metric." **Recommendation:** rename to the specific field intended (e.g., broker tick volume) and forbid cross-broker comparability assumptions in feature definitions (§8.1 Feature Engine versioning makes this easy to encode).

#### N-9 · Spread drag makes the Standard tier structurally expensive, and the spec never quantifies it

**Citations:** §3.2, §12.4 ("Explicit transaction-cost model"), §16 (spread/commission model).

At a typical 1.2-pip GBP/USD retail spread, the round-trip cost is 12% of risked amount at a 10-pip stop, 6% at 20, 4.8% at 25, 3% at 40 (Appendix A.2) — identical in percentage terms at every tier, but hardest on Standard trades where a single pip of spread is a large fraction of the $2.50 risk after integer-unit rounding. **Recommendation:** add a spread-drag ceiling to candidate validation (e.g., reject if spread > 8% of intended risk), which also operationalizes §24's `reject_abnormal_spread` with a number.

#### N-10 · The dollar loss caps are intent, not physics — the spec should say so

**Citations:** §3.1 ("Maximum initial single-trade loss: $25"), §21 acceptance test ("No order can exceed allowed dollar risk within defined rounding tolerance").

A broker-held stop bounds *orders*, not *fills*: weekend gaps and news spikes fill past stops (US brokers offer no guaranteed stops). The §21 test is correctly phrased about orders; the constitution's language reads as an outcome guarantee. **Recommendation:** one honest sentence in §3.1 acknowledging gap risk, plus the mitigation already implicit in the design: no positions held through the flatten boundary (§14) and event blackouts (§6.3.J) — and size Exceptional trades assuming slippage (§13's card already estimates it; make it a sizing input, not just a display field).

#### N-11 · Holiday, Friday, and flatten-failure behavior are undefined

**Citations:** §14 (session schedule and state machine), §8.1 Session Clock.

UK/US bank holidays (thin, distorted sessions), Friday flatten (any special weekend rule?), and the FLATTENING → what-if-close-fails path are all unspecified; §16 asks brokers about "Weekend/session behavior" but the firm's own policy is absent. **Recommendation:** add a holiday calendar input with fail-closed default (no calendar → no session), and define FLATTENING failure as a kill-switch trigger class (broker-health) with owner escalation.

#### N-12 · The economic-calendar source is load-bearing and unnamed

**Citations:** §6.3.J ("Missing or stale calendar data causes fail-closed behavior"), §24 (`reject_unknown_news_state: true`).

Fail-closed on missing calendar means the calendar feed's reliability *is* the system's uptime. Free calendar feeds are scrape-based, unlicensed for programmatic use, or rate-limited — an operational and legal detail worth deciding early. **Recommendation:** name candidate sources in Phase 0's connector audit (§22) with licensing status; treat "calendar source down > X hours" as an incident class.

#### N-13 · The order path's "price/spread revalidation" stage has no owning service

**Citations:** §2 (required order path stage), §8.1 (service responsibilities).

Every other §2 stage maps to a named §8.1 service; final revalidation between approval and submission is assigned to none of them. **Recommendation:** assign it explicitly to the Broker Adapter (pre-submission check against candidate tolerances), so §21's integration tests have a component to target.

---

### 3.4 Observations

---

#### O-1 · The doubling ladder quietly implies the profitability the constitution prohibits

**Citations:** §4.1 (anchor sequence $250 → … → $128,000), §0.5 ("No implied profitability").

Printing nine doublings as the default tier sequence frames 512× growth as the expected trajectory. No control is wrong; the framing sits oddly beside rule 5 and shapes owner expectations. A sentence noting that most accounts never reach the second anchor would align the document with its own doctrine.

#### O-2 · Operating costs will likely exceed plausible trading returns by an order of magnitude at the initial tier

**Citations:** §7.4, §23, §26 item 9 (minimal monthly cost estimate).

Even one Claude Code subscription plus data/calendar costs will plausibly run $100–200+/month; a *good* month of disciplined trading at the $250 tier (say +10%) is $25. The project's honest near-term return is the infrastructure, the audit discipline, and the learning — which §1 ("The long-term objective is not a single trading bot") half-acknowledges. The §26.9 cost estimate should present this comparison explicitly so the owner prices the project as R&D, not income.

#### O-3 · The $200 floor is two bad sessions away — expect to visit shadow mode

**Citations:** §3.4 (floor $200, session cap $25, weekly cap $37.50).

The total live drawdown budget is $50: two maximum-loss sessions (necessarily spread across ≥2 weeks, since the weekly cap makes the floor unreachable in one — Appendix A.1). This is coherent and arguably the spec's most protective feature, but the owner should expect the live → shadow → revalidate cycle to be the *normal* rhythm of the first months, not a failure state.

#### O-4 · Milestone-vs-active-base is designed correctly — extend the same idea to permissions

**Citations:** §4.4 ("Milestone tier" vs "Active risk base"), §4.5.

The two-concept design (records don't un-ring the bell; sizing follows current equity) is right. §4.5's permission suspension ("may be suspended") would benefit from the same crispness: bind each strategy/instrument permission to a named tier and an explicit drawdown state (dovetails with N-4).

---

## 4. Cross-cutting themes

**(a) The deterministic perimeter is real, but its inputs are soft.** C-3, M-1, M-4, M-5 are one defect seen from four angles: numbers and files that *feed* the deterministic gate (edge scores, config files, hook files, calendar text) are producible or modifiable by LLM-influenced processes. The fix pattern is uniform — deterministic floors and ceilings that LLM output can tighten but never loosen, and integrity verification of every config artifact at runtime startup.

**(b) Jurisdiction is a design input, not a deployment detail.** C-1, M-7, N-9 all follow from facts (leverage caps, FIFO, broker shortlist, unit granularity, spreads) that were knowable at spec-writing time and reshape the risk ladder, the broker audit, and the cost model. The v1.1.0 amendment should promote a "Jurisdiction and venue constraints" section to the constitution level.

**(c) $250 is a stress test the spec passes architecturally and fails economically.** The controls scale down gracefully — that is genuinely impressive. But margin (C-1), spread drag (N-9), sub-micro sizing (M-7), and operating costs (O-2) mean the initial tier is best understood as a *live-fire validation environment* for the machine, not a profit venture. The spec's own no-profit-target doctrine (§3.5) is the right frame; the owner-facing documents should adopt it explicitly.

---

## 5. Prioritized recommendations

| Priority | Finding(s) | Action | Blocks (per §22) |
|---|---|---|---|
| 1 | C-1, M-7 | Add jurisdiction annex; margin-feasibility overlay on the risk ladder; make unit-granularity + API the top broker-audit criteria | Phase 0 (broker audit) |
| 2 | C-2 | Re-anchor all session times to Europe/London; add DST divergence-week tests | Phase 2 (session clock) |
| 3 | C-3 | Owner-approved promotion default; deposits never advance milestones | Phase 2 (capital manager) |
| 4 | M-1, M-5 | Partition edge score into deterministic/LLM inputs; LLM may only lower tiers; structured-only calendar ingestion | Phase 5 (agents) |
| 5 | M-4, N-5 | OS-user permission split; startup hash verification of config + hooks; hash-chained audit log | Phase 1 (governance/hooks) |
| 6 | M-8, M-3 | Define minimum samples (probation N, tier qualification, promotion); bootstrap CIs instead of Sharpe at this scale | Phase 6–7 |
| 7 | M-6 | Consolidate 15 agents → 6 | Phase 5 |
| 8 | M-2 | Re-justify or reduce the 10% Exceptional ceiling | Phase 2 (risk engine) |
| 9 | N-1 – N-13 | Sweep of definitions/parameters per findings above | Phase 1–2 (config schemas) |

---

## 6. Blocking owner decisions (per §26 item 10)

Genuinely blocking — cannot be safely defaulted by the implementer:

- **D-1 · Broker.** Accept OANDA US as the working target (sole US RFED with 1-unit granularity + public API, per M-7), or direct otherwise. Everything in Phase 0 keys off this.
- **D-2 · Promotion default.** Auto-promotion (spec as written) vs. owner-confirmed promotion (this review's C-3 recommendation).
- **D-3 · Deposit accounting.** May deposits advance milestone tiers? (Recommended: no — deposits adjust the active risk base only.)
- **D-4 · Exceptional tier.** Retain 10% (accepting C-1's margin reality and M-2's aggressiveness), reduce to 5%, or defer the tier until a higher anchor.
- **D-5 · Probation exit.** The value of N (recommended: 30 correctly processed signals) and the approval model at 2 a.m. (per-trade vs. session-envelope, per M-3).
- **D-6 · Week boundary.** Recommended: ISO week, Europe/London (N-2).
- **D-7 · Economic-calendar source** and the budget for it (N-12, O-2).

---

## 7. Suggested spec amendments (v1.0.0 → v1.1.0 changelist)

| Section | Amendment |
|---|---|
| §3.1 | Add gap-risk acknowledgement sentence (N-10). |
| §3.2 | Add margin-feasibility overlay table + derivation rule (C-1); resolve dollar-vs-fraction rule as `min(tier_cap, fraction × current_equity)` (N-1); revisit Exceptional % per D-4 (M-2). |
| §3.4 | Define week boundary (N-2). |
| §4.2 | Default promotion = owner-approved pending promotion; deposits excluded from milestones (C-3). |
| §4.5 | Parameterize drawdown states and boundaries; bind permissions to tier + state (N-4, O-4). |
| §5.1–5.3 | Partition score components deterministic/LLM; LLM inputs lower-only; state boundary handling and a recalibration milestone (M-1, M-8). |
| §6 | Consolidate roster to 6 agents (M-6). |
| §6.3.J / §17 | Structured-only calendar ingestion from allowlisted source; injection defenses; name the source (M-5, N-12). |
| §7.3 / §17 | OS-permission split; startup hash verification of config and hooks; hash-chained audit with off-machine anchors; key custody under non-agent OS user (M-4, N-5). |
| §8.1 | Define kill-switch emergency-policy table (N-3); heartbeat/dead-man requirement (N-7); rename "available volume" (N-8); assign price/spread revalidation to the Broker Adapter (N-13); single-process asyncio supervisor guidance (N-6). |
| §13 | Define probation N; missed approval = valid no-trade observation; optional session-envelope approval model (M-3). |
| §14 / §24 | Re-anchor all session times to Europe/London; Chicago for display only; add divergence-week tests to §21 (C-2). Add holiday/Friday/flatten-failure policy (N-11). |
| §12.3 | Replace Sharpe/Sortino at this scale with trade-level bootstrap CIs; add minimum-sample table (M-8). |
| §16 | Jurisdiction annex: CFTC 50:1/20:1, NFA 2-43(b) FIFO, no hedging, RFED shortlist, unit granularity as top criterion, Section 988 note (M-7, C-1). |
| §26 item 9 | Cost estimate must include cost-vs-plausible-return comparison (O-2). |
| §4.1 | Add expectation-setting sentence per O-1. |

---

## Appendix A — Verification worksheet

Every number used in this review, with its computation. Live rates captured 2026-07-29 (GBP/USD 1.32978, EUR/USD 1.13944; Financial Modeling Prep real-time feed; rounded to 1.3298 / 1.1394 in tables).

### A.1 Ladder and limits arithmetic (PASS — spec internally consistent)

```
$2.50 / $250 = 1.0%   $7.50 / $250 = 3.0%   $12.50 / $250 = 5.0%   $25 / $250 = 10.0%   (§3.2 exact)
§4.3 table: each row = 2 × previous row at every tier (verified all 20 cells)
Edge weights (§5.1): 30+20+15+15+10+10 = 100
Weekly floor check: 250 − 37.50 = 212.50 > 200  → $200 floor unreachable within one week (§3.4 coherent)
Fastest path to floor: two $25 max-loss sessions across ≥2 weeks → equity $200 → live disabled (§3.4)
Three Exceptional losses compounded: 250 × 0.9³ = 182.25 → −27.1%
```

### A.2 Margin, sizing, and spread (basis of C-1, M-7, N-9)

```
Pip value (USD-quote pairs): $0.0001/unit/pip.  units = risk / (stop_pips × 0.0001)
margin = units × rate × 0.02   (US 2% security deposit on majors = 50:1)

GBP/USD @ 1.3298:
risk $2.50 : 10p→2,500u/$66.49   20p→1,250u/$33.25   25p→1,000u/$26.60   40p→625u/$16.62
risk $7.50 : 10p→7,500u/$199.47  20p→3,750u/$99.74   25p→3,000u/$79.79   40p→1,875u/$49.87
risk $12.50: 10p→12,500u/$332.45 20p→6,250u/$166.23  25p→5,000u/$132.98  40p→3,125u/$83.11
risk $25.00: 10p→25,000u/$664.90 20p→12,500u/$332.45 25p→10,000u/$265.96 40p→6,250u/$166.23
EUR/USD @ 1.1394, risk $25, 25p → 10,000u → margin $227.88 (91% of $250)
Exceptional feasibility bound (GBP/USD): margin ≤ $250 ⇒ units ≤ 250/(1.3298×0.02) ≈ 9,400 ⇒ stop ≥ 26.6 pips
Sub-micro-lot cases: $2.50 @ 40p → 625 units (< 1,000-unit micro lot) → requires unit-granular broker

Spread drag @ 1.2-pip typical GBP/USD retail spread: 1.2/stop = 12.0% (10p), 6.0% (20p), 4.8% (25p), 3.0% (40p) of risked amount
```

### A.3 Timezone divergence (basis of C-2) — computed with Python `zoneinfo`, TZDB current as of run date

```
Days in 2026 where 02:00 America/Chicago ≠ 08:00 Europe/London: exactly 27
  Window 1: 2026-03-09 .. 2026-03-28  (US enters CDT Mar 8; UK enters BST Mar 29)  → 02:00 Chicago = 07:00 London
  Window 2: 2026-10-25 .. 2026-10-31  (UK exits BST Oct 25; US exits CDT Nov 1)   → 02:00 Chicago = 07:00 London
All other days: offset 6h, 02:00 Chicago = 08:00 London (§14 mapping holds)
Spot checks: 2026-03-15 → London 08:00 GMT = Chicago 03:00 CDT; 2026-10-28 → London 08:00 GMT = Chicago 03:00 CDT
```

### A.4 Regulatory facts (basis of C-1, M-7) — as of July 2026

- CFTC retail forex security deposits: 2% majors (50:1), 5% others (20:1) — [CFTC final rule fact sheet](https://www.cftc.gov/sites/default/files/idc/groups/public/@newsroom/documents/file/forexfinalrulefactsheet.pdf)
- NFA Compliance Rule 2-43(b): FIFO offsets required; no carrying of offsetting (hedged) positions — [overview](https://greentradertax.com/new-cftc-forex-trading-rules-call-for-501-leverage/), [regulation guide](https://www.innreg.com/blog/forex-broker-regulation)
- US retail forex broker set (RFED/FCM): OANDA, FOREX.com (GAIN), IG US, tastyfx, Interactive Brokers — [ForexBrokers.com US guide](https://www.forexbrokers.com/guides/united-states), [StockBrokers.com guide](https://www.stockbrokers.com/guides/best-forex-brokers)
- OANDA US: no minimum deposit, trade sizes from 1 unit, REST API (v20) — [StockBrokers.com guide](https://www.stockbrokers.com/guides/best-forex-brokers)

Tax note (M-7): US spot forex defaults to IRC §988 ordinary income treatment — flag for the governance docs; confirm treatment with a CPA.

---

## Appendix B — Consistency checks log

Checks that **passed** (the spec was checked, not skimmed):

| Check | Result |
|---|---|
| Risk-ladder dollars = stated equity fractions at $250 (§3.2) | PASS (exact) |
| §4.3 scaling table vs `capital_anchor(n) = 250 × 2ⁿ` | PASS (all cells) |
| Edge-weight sum = 100 (§5.1) | PASS |
| Edge-score bands contiguous, no overlap (§5.2: <70 / 70–79 / 80–89 / 90–94 / 95–100) | PASS |
| §24 YAML vs §3.4 prose ($25 session, $37.50 weekly, $200 floor, 1 position, 2 trades, 1 exceptional) | PASS (all match) |
| §24 session times vs §14 schedule | PASS (match; both inherit defect C-2) |
| Session/weekly limit interplay (one max session leaves $12.50 weekly capacity ≥ one High trade) | PASS (coherent) |
| §14 schedule maps to sensible London morning in aligned periods (02:00 CT = 08:00 London) | PASS (except C-2 windows) |
| §2 order-path stages each owned by a §8.1 service | FAIL for one stage → N-13 |
| Exceptional-gate conditions (§5.3) vs config flags (§24 `risk_ladder.exceptional`) | PASS (consistent) |
| Anti-overfitting checklist (§12.4) covers leakage, costs, sensitivity, multiple testing, discovery/confirmation split | PASS (complete for scope) |

Checks that **failed** are findings: C-1 (margin vs ladder), C-2 (§24/§14 vs §8.1 doctrine), C-3 (§4.2 vs §0.4/§12.5/§3.1), N-13 (order-path ownership).

---

*End of review. Amendments proposed in §7 are drafted to be mechanically applicable to produce Master Handoff v1.1.0.*
