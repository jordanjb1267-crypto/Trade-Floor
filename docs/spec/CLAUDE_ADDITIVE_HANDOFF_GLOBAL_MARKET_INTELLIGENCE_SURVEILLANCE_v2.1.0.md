# CLAUDE ADDITIVE IMPLEMENTATION HANDOFF
## Global Market Intelligence and Surveillance Division

**Document type:** Additive migration specification  
**Amendment ID:** GMIS-001  
**Amendment version:** 2.1.0  
**Applies to:** `CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.md`  
**Repository state:** Existing system already built and running locally on the owner's laptop  
**Owner:** Jordan  
**Primary engineering environment:** Claude Code  
**Control timezone:** America/Chicago  
**Deployment constraint:** Single laptop, minimal recurring cost  

---

# 0. AUTHORITY AND IMPLEMENTATION MODE

This document is an **additive amendment** to the existing trading-firm system. It does not authorize a rewrite, redesign, repository replacement, database reset, broker change, risk-policy change, strategy-policy change, or live-trading activation.

The existing system must remain operational while this capability is introduced behind disabled feature flags.

## 0.1 Governing instruction to Claude

Act as the senior principal engineer and migration lead. Your task is to inspect the existing implementation and integrate the Global Market Intelligence and Surveillance Division with the smallest safe code change that satisfies this specification.

Do not assume the repository matches the recommended tree in the master handoff. Inspect the actual codebase first and adapt this amendment to the existing architecture without weakening its controls.

## 0.2 Non-negotiable preservation rules

1. **Add, do not replace.** Preserve all working broker, market-data, risk, sizing, execution, reconciliation, strategy, audit, notification, and supervisor behavior.
2. **No live behavior change by default.** All new surveillance features must be disabled in live mode until explicitly enabled through approved configuration.
3. **No destructive migrations.** Database migrations must be forward-only, backward-compatible, idempotent where practical, and tested against a copy of the current database.
4. **No credential changes.** Reuse current secret-management patterns. Do not print, move, rotate, or rewrite secrets unless a genuine defect requires owner action.
5. **No risk-policy changes.** The existing deterministic risk engine remains authoritative and unchanged unless a compatibility defect is discovered and documented.
6. **No agent execution authority.** New agents may monitor, classify, interpret, and escalate. They may not place orders, alter stops, size positions, or bypass the candidate and risk workflow.
7. **No silent strategy promotion.** Surveillance observations may inform existing candidates and create research hypotheses. They may not convert a novel idea into a live strategy.
8. **Fail closed.** Missing, stale, conflicting, or unhealthy required live-intelligence data must never be treated as confirming evidence.
9. **Rollback required.** The complete amendment must be removable or disable-able without damaging the pre-amendment system.
10. **Preserve auditability.** Every new observation, alert, interpretation, source-health event, state transition, and configuration change must be reproducible from stored inputs and versioned logic.

## 0.3 Required branch and change isolation

Before implementation:

- Confirm the current branch, status, and latest known-good commit.
- Create a dedicated branch using the repository's established naming convention. Suggested name:
  - `claude/add-global-market-intelligence-surveillance`
- Tag or record the pre-migration baseline commit in the implementation report.
- Do not modify unrelated code.
- Keep commits narrow and reversible.
- Do not merge or enable live behavior without owner approval.

---

# 1. REASON FOR THIS AMENDMENT

The current firm has historical research, strategy specialists, adaptive senior traders, deterministic execution, and risk governance. That is not sufficient by itself.

Historical evidence answers:

- What happened before?
- Which conditions were associated with positive or negative outcomes?
- Which strategy or feature combinations survived testing?

The new division must answer:

- What is affecting the market now?
- What changed since the last observation?
- Does the current market still resemble the conditions in which a historical edge was observed?
- Are news, volatility, liquidity, execution conditions, cross-market relationships, or event risk strengthening or invalidating the thesis?
- Has the position's original premise deteriorated after entry?

The firm must not apply historical relationships without live context. The surveillance system becomes a permanent shared intelligence layer between data collection and senior-trader interpretation.

---

# 2. TARGET OPERATING MODEL

The revised decision path is:

```text
Broker and approved external data sources
        -> deterministic collectors and normalizers
        -> deterministic technical and market-state calculations
        -> source-health and data-quality gates
        -> Global Market Intelligence and Surveillance Division
        -> immutable Market State Packet
        -> independent Senior Trader Alpha and Beta reviews
        -> relevant specialist consultations
        -> Market Opportunity Arbiter
        -> deterministic candidate validation and risk gate
        -> existing execution and reconciliation system
```

The new division is an intelligence provider, not a trading authority.

## 2.1 Separation of responsibilities

### Deterministic services must perform

- Price and candle ingestion
- Timestamp normalization
- Technical indicator calculations
- Market-structure level calculations where rules are deterministic
- Economic-event ingestion and normalization
- News ingestion, deduplication, timestamping, and source attribution
- Cross-market data ingestion
- Data freshness and source-health checks
- Alert-threshold evaluation
- Market State Object persistence
- Post-entry contradiction-rule evaluation
- Audit logging

### Claude agents may perform

- Interpretation of structured observations
- Relevance assessment
- News significance analysis
- Conflict and contradiction analysis
- Market narrative construction
- Escalation summaries
- Situation-specific thesis support
- Research-hypothesis generation

### Claude agents must not perform

- Inventing indicator values
- Calculating production risk from prose
- Direct broker order submission
- Silent code or formula changes during a live session
- Treating missing news as evidence that no news exists
- Claiming centralized forex order flow when only broker/tick proxies are available

---

# 3. NEW PERMANENT DIVISION

Create the **Global Market Intelligence and Surveillance Division**, abbreviated `GMIS` internally.

The division must be asset-class neutral at the domain-model level. The first production implementation covers the firm's currently approved forex instruments. Options-specific capability is scaffolded but remains disabled and incomplete until a separate owner-approved amendment.

## 3.1 Agent roster

Use the fewest agents necessary while preserving genuine specialization. Agents may be implemented as separate Claude Code subagents or as role-isolated workflows if that better fits the existing system.

### A. Technical Surveillance Lead

**Purpose:** Coordinate the division and produce a concise, evidence-grounded current-state report.

**Inputs:**

- Latest Market State Objects
- Technical observation events
- Macro/news events
- Cross-market events
- Source-health events
- Existing open-position state
- Material-change alerts

**Outputs:**

- Surveillance Situation Report
- Material-change summary
- Required escalation list
- Data-quality limitations
- Recommended specialist consultations

**May not:**

- Create orders
- Authorize candidates
- Override Senior Traders
- Suppress severe risk or data-quality alerts

### B. Price Structure Monitor

Monitors deterministically supplied observations including:

- Higher highs, higher lows, lower highs, and lower lows
- Breaks and failed breaks of approved structural levels
- Range formation and range escape
- Session highs and lows
- Prior-day and prior-week levels
- Opening-range behavior
- Compression, expansion, and displacement
- Price acceptance and rejection
- Distance from approved reference levels

Narrative output must cite the underlying feature names, values, timestamps, and calculation versions.

### C. Indicator and Feature Monitor

Monitors only indicators present in the approved registry.

Initial supported categories may include, when already available or approved after testing:

- ATR and realized volatility
- Rolling range and range-compression ratios
- Moving-average slope and separation
- Momentum and rate of change
- RSI or equivalent bounded momentum measure
- Statistical deviation bands
- Session-range expansion
- Spread percentile
- Tick-volume anomaly where available
- Correlation and divergence features
- Distance from key deterministic levels

This monitor must not create new formulas during live operation. New indicators follow the existing research and promotion process.

### D. Liquidity and Auction Monitor

Monitors observable or inferable behavior around:

- Asian-session highs and lows
- Prior-session highs and lows
- Equal or repeated highs and lows
- Repeated testing of levels
- Sweep-and-reclaim or sweep-and-reject sequences
- Rapid displacement
- Failed acceptance
- Spread and tick-volume changes

Every field must identify its evidence type:

- `OBSERVED`
- `BROKER_PROXY`
- `PRICE_ACTION_INFERENCE`
- `UNAVAILABLE`

Do not present inferred retail-FX liquidity behavior as verified institutional order flow.

### E. Volatility and Regime Monitor

Maintains current regime classifications across approved horizons:

- Intraday
- Session
- Daily
- Weekly, when supported

Initial controlled labels:

- `TRENDING`
- `MEAN_REVERTING`
- `COMPRESSING`
- `EXPANDING`
- `EVENT_DRIVEN`
- `ILLIQUID`
- `DISLOCATED`
- `TRANSITIONAL`
- `INDETERMINATE`

A regime classification must include evidence values, version, confidence calibration if used, and expiration time.

### F. Macro and Event Monitor

Monitors approved scheduled and unscheduled market events.

For scheduled events, store:

- Event ID
- Source
- Country or currency exposure
- Event name
- Scheduled UTC time
- Importance classification
- Forecast, prior, and actual values where available
- Revision values where available
- Surprise calculation version
- Active blackout or caution window

For unscheduled events, store:

- Original source timestamp
- Ingestion timestamp
- Source identity
- Instruments or currencies potentially affected
- Verification state
- Materiality state
- Supersession or correction links

### G. Cross-Market Monitor

Tracks approved contextual instruments only. Initial forex context may include, subject to available reliable data:

- Dollar index or approved dollar proxy
- Relevant government-yield proxies
- Major equity-index proxies
- Gold
- Oil where currency relevance is defined
- Relevant currency crosses
- Volatility proxy where available

A relationship must never be assumed permanent. Store rolling relationship statistics and current divergence state.

### H. News Verification and Relevance Agent

Separates collection from interpretation.

Responsibilities:

- Detect duplicates and near-duplicates
- Identify stale or recirculated headlines
- Distinguish event time from publication time
- Track corrections and retractions
- Compare multiple reliable sources where available
- Assign verification state
- Estimate instrument relevance
- Determine whether facts remain unresolved

Required verification states:

- `UNVERIFIED`
- `SINGLE_SOURCE`
- `CORROBORATED`
- `OFFICIAL_SOURCE`
- `CONFLICTING`
- `CORRECTED`
- `RETRACTED`

Conflicting or unresolved material news must escalate uncertainty and may invoke a configured entry pause.

### I. Opportunity Alert Agent

Receives structured events and creates an alert only when a material state change occurs.

It does not output `BUY` or `SELL` instructions.

It outputs:

- What changed
- Why the change is material
- Affected instruments
- Supporting deterministic observations
- Conflicting observations
- Data-quality limitations
- Suggested agents or specialists to consult
- Alert expiration

### J. Position Contradiction Monitor

Operates only when an approved paper or live position exists.

It compares the live market to the position's pre-registered thesis expectations:

- Expected confirmations
- Allowed noise
- Soft contradictions
- Hard invalidations
- Time expiration
- Event invalidation
- Execution degradation
- Data-health degradation

It may recommend review, risk attention, or thesis invalidation. It may not independently alter an order unless existing deterministic policy already authorizes a specific preconfigured action.

---

# 4. MARKET STATE OBJECT

Create a versioned, immutable-at-publication `MarketState` domain object for each approved instrument and observation horizon.

Use the existing schema framework, preferably Pydantic if already present.

## 4.1 Minimum schema

```yaml
market_state_id: UUID
schema_version: "1.0.0"
instrument_id: "EUR_USD"
asset_class: "FX_SPOT"
as_of_utc: "2026-07-31T19:30:00Z"
valid_until_utc: "2026-07-31T19:35:00Z"
source_snapshot_ids: []
feature_snapshot_id: UUID
configuration_version: string

session_state:
  named_session: "LONDON"
  phase: "ACTIVE"
  local_control_time: "14:30:00"
  market_local_time: "20:30:00"

market_regime:
  intraday: "EXPANDING"
  session: "TRENDING"
  daily: "TRANSITIONAL"
  evidence_feature_ids: []
  classifier_version: string

technical_state:
  structure_state: string
  momentum_state: string
  volatility_percentile: number | null
  session_range_fraction_of_atr: number | null
  key_levels: []
  active_indicator_observations: []

liquidity_state:
  classification: string
  evidence_type: string
  tracked_levels: []
  spread_state: string
  spread_percentile: number | null

macro_state:
  active_drivers: []
  upcoming_events: []
  blackout_active: boolean
  uncertainty_state: string

news_state:
  material_items: []
  verification_state: string
  unresolved_conflict: boolean
  last_successful_poll_utc: datetime | null

cross_market_state:
  confirmations: []
  divergences: []
  relationship_versions: []

execution_state:
  broker_health: string
  market_data_health: string
  expected_slippage_state: string
  tradability_state: string

data_quality:
  overall_status: "HEALTHY | DEGRADED | FAILED"
  stale_components: []
  missing_components: []
  conflicting_components: []

change_summary:
  prior_market_state_id: UUID | null
  material_changes: []
  non_material_changes_suppressed: integer
```

## 4.2 Immutability rules

- Published Market State Objects are append-only.
- Corrections create a replacement object linked with `supersedes_market_state_id`.
- Senior Trader Alpha and Beta receive the same object ID and checksum for their independent first pass.
- The exact Market State Object used for a candidate must be linked to the candidate and retained.

## 4.3 Freshness rules

Each component must have its own freshness threshold. Do not use one global threshold for all data.

Examples:

- Broker price data: seconds
- Technical state: dependent on timeframe and bar completion
- Scheduled event calendar: hours before session, then tighter around release
- Breaking news polling: source-dependent
- Cross-market data: source-dependent

If a required component expires, the published state becomes `DEGRADED` or `FAILED` according to configuration.

---

# 5. IMMUTABLE MARKET STATE PACKET FOR SENIOR TRADERS

Extend the existing Market State Packet used by Senior Trader Alpha and Beta.

It must contain:

1. Latest valid Market State Object
2. Prior material Market State Object for comparison
3. Deterministic feature snapshot
4. Active scheduled-event packet
5. Material verified-news packet
6. Cross-market confirmation/divergence packet
7. Execution-conditions packet
8. Source-health report
9. Data limitations
10. Open-position contradiction packet, when applicable

The packet must be serialized, checksumed, stored, and provided identically to both senior traders before either first-pass analysis begins.

Do not include another agent's narrative thesis in the first-pass packet.

---

# 6. EVENT AND ALERT ARCHITECTURE

Prefer the existing internal event mechanism. Do not add Kafka, Redis, or cloud queues for this laptop deployment unless the existing architecture already depends on them.

A local in-process event bus, durable SQLite outbox, or existing scheduler is sufficient if reliability tests pass.

## 6.1 Required event families

```text
market_data.received
market_data.stale
bar.closed
feature.snapshot.created
market_state.published
market_state.degraded
regime.changed
structure.level_reached
structure.break_detected
structure.failed_break_detected
volatility.threshold_crossed
spread.threshold_crossed
economic_event.upcoming
economic_event.released
news.item_ingested
news.item_verified
news.conflict_detected
cross_market.divergence_detected
opportunity.material_change_detected
position.contradiction_detected
source.health_changed
surveillance.briefing_due
```

## 6.2 Event requirements

Every event must include:

- Unique event ID
- Event type and schema version
- UTC event time
- UTC ingestion time
- Source or producer
- Instrument scope
- Correlation ID
- Configuration version
- Data-quality status
- Payload checksum where useful

## 6.3 Alert deduplication and throttling

Prevent alert floods.

Implement:

- Correlation windows
- State-change-only alerts
- Severity-based cooldowns
- Duplicate-content hashes
- Supersession links
- Acknowledgement state
- Escalation state

Severe risk, source-failure, broker, or position-protection alerts must never be suppressed by normal throttling.

---

# 7. TECHNICAL FEATURE REGISTRY EXTENSION

Extend the existing approved feature and indicator registry. Do not create a second independent registry.

## 7.1 Additional required metadata

Each production-capable feature must include:

```yaml
feature_id: string
version: string
status: research | shadow | paper | production | retired
asset_classes: []
instruments: []
timeframes: []
calculation_module: string
required_inputs: []
lookback_requirements: {}
output_type: string
null_behavior: string
warmup_behavior: string
freshness_policy: string
purpose: string
known_failure_modes: []
leakage_review_status: string
validation_report_ids: []
owner_approval_id: string | null
```

## 7.2 Initial implementation policy

- Reuse existing features before adding new ones.
- Inventory all current indicator calculations.
- Eliminate duplicate implementations by wrapping rather than rewriting when safe.
- Add tests that compare old and new outputs for identical inputs.
- New calculations begin as `research` and cannot affect live decisions.
- Production surveillance may initially observe approved production features without changing existing strategy logic.

---

# 8. NEWS, EVENT, AND SOURCE GOVERNANCE

## 8.1 Source registry

Create one versioned registry for all approved external intelligence sources.

Minimum fields:

```yaml
source_id: string
source_type: broker | official | calendar | news | market_data | derived
provider_name: string
base_url_or_connector_reference: string | null
assets_or_currencies: []
auth_required: boolean
polling_policy: string
rate_limit_policy: string
freshness_sla_seconds: integer | null
priority: integer
reliability_tier: integer
license_or_usage_notes: string
production_approved: boolean
fail_closed_when_unavailable: boolean
```

## 8.2 Source quality rules

- Prefer official releases and broker-native data when available.
- Preserve original timestamps and values.
- Never scrape or store data in violation of source terms.
- Do not allow an unapproved free source to silently become production-critical.
- A source outage must be visible in health status.
- If an external source is only suitable for research, mark it accordingly.

## 8.3 Missing-news behavior

The absence of fetched news does not prove the absence of relevant news.

The system must distinguish:

- `NO_MATERIAL_ITEMS_FOUND`
- `SOURCE_HEALTHY_NO_ITEMS`
- `SOURCE_UNAVAILABLE`
- `POLL_FAILED`
- `VERIFICATION_PENDING`
- `UNKNOWN`

Existing `reject_unknown_news_state` behavior must remain fail-closed where configured.

---

# 9. SCHEDULED AND EVENT-DRIVEN OPERATION

The low-cost design must avoid continuous high-token Claude analysis.

## 9.1 Always-running deterministic processes

Where compatible with the current supervisor, add or extend lightweight processes for:

- Price and candle ingestion
- Feature calculations
- Economic-event polling
- News polling
- Cross-market polling
- Market-state publication
- Alert rules
- Source-health monitoring
- Audit persistence

These processes must use the current supervisor and heartbeat framework rather than introducing a second supervisor.

## 9.2 Claude invocation triggers

Invoke high-quality Claude agents only when:

- A scheduled briefing is due
- A material market-state change occurs
- A relevant verified news item arrives
- A regime changes
- A key structural level is reached or fails
- A significant cross-market divergence occurs
- A candidate is being assembled
- A live or paper position receives contradictory evidence
- A post-session review is due

## 9.3 Briefing schedule

Integrate with the existing session configuration. Suggested checkpoints, configurable rather than hard-coded:

- Asia-context snapshot
- Pre-London briefing
- London activation briefing
- Mid-session update only if material change exists
- Entry-cutoff briefing
- Post-session review

Do not generate repetitive briefings when the state is unchanged.

---

# 10. POST-ENTRY MONITORING

Every candidate eligible for paper or live execution must register a `ThesisMonitoringPlan`.

## 10.1 Minimum schema

```yaml
monitoring_plan_id: UUID
candidate_id: UUID
schema_version: "1.0.0"
expected_confirmations: []
acceptable_noise_conditions: []
soft_contradictions: []
hard_invalidation_conditions: []
time_expiration_utc: datetime | null
event_invalidation_rules: []
execution_degradation_rules: []
data_health_rules: []
review_required_on_soft_contradiction: boolean
policy_actions: []
```

## 10.2 Action boundaries

The Position Contradiction Monitor may:

- Record a contradiction
- Escalate to Senior Traders, Arbiter, CRO, or owner according to severity
- Mark a thesis as under review
- Trigger existing deterministic policy actions if those actions were preconfigured and already authorized

It may not invent a new exit rule after entry.

Existing broker-native stops remain authoritative.

---

# 11. OPTIONS-READY EXTENSION POINTS — SCAFFOLD ONLY

This amendment must prepare domain boundaries for future options trading without enabling options, changing broker permissions, ingesting paid options data, or adding options strategies now.

## 11.1 Asset-class-neutral requirements

Avoid forex-only assumptions in new interfaces.

Use:

- `instrument_id`
- `asset_class`
- `venue`
- `session_calendar_id`
- `price_increment`
- `contract_multiplier`
- `settlement_type`
- `market_data_capabilities`

Do not hard-code pip semantics into the surveillance domain.

## 11.2 Reserved options modules

Create interfaces or empty extension points only if doing so is low-risk and consistent with the existing architecture:

```text
surveillance/options/
  underlying_state.py
  implied_volatility.py
  volatility_surface.py
  greeks.py
  chain_liquidity.py
  event_catalysts.py
  contract_selection.py
  expiration_assignment.py
```

These modules must remain disabled, unregistered, and excluded from production dependency paths.

## 11.3 Future options agents

Document but do not activate:

- Underlying Technical Analyst
- Implied Volatility Analyst
- Greeks and Convexity Monitor
- Options Chain and Liquidity Monitor
- Options Flow Analyst
- Corporate Event and Catalyst Monitor
- Contract Selection Agent
- Exercise, Assignment, and Expiration Monitor
- Options Portfolio Risk Officer

A separate owner-approved options amendment will define data vendors, broker permissions, risk limits, supported structures, suitability controls, and testing requirements.

---

# 12. REPOSITORY ADDITIONS

Map these additions into the actual repository rather than forcing a duplicate tree.

Recommended additions when compatible:

```text
src/trading_firm/
├── surveillance/
│   ├── __init__.py
│   ├── service.py
│   ├── coordinator.py
│   ├── events.py
│   ├── state_builder.py
│   ├── materiality.py
│   ├── deduplication.py
│   ├── source_health.py
│   ├── technical/
│   │   ├── structure.py
│   │   ├── indicators.py
│   │   ├── liquidity.py
│   │   └── regime.py
│   ├── macro/
│   │   ├── calendar.py
│   │   ├── releases.py
│   │   └── blackout.py
│   ├── news/
│   │   ├── ingestion.py
│   │   ├── normalization.py
│   │   ├── verification.py
│   │   └── relevance.py
│   ├── cross_market/
│   │   ├── ingestion.py
│   │   ├── relationships.py
│   │   └── divergence.py
│   ├── positions/
│   │   └── contradiction.py
│   └── options/
│       └── README.md
├── schemas/
│   ├── market_state.py
│   ├── surveillance_event.py
│   ├── surveillance_alert.py
│   ├── source_registry.py
│   └── thesis_monitoring_plan.py
```

Suggested agent additions:

```text
.claude/agents/
├── technical-surveillance-lead.md
├── price-structure-monitor.md
├── indicator-feature-monitor.md
├── liquidity-auction-monitor.md
├── volatility-regime-monitor.md
├── macro-event-monitor.md
├── cross-market-monitor.md
├── news-verification-relevance.md
├── opportunity-alert-agent.md
└── position-contradiction-monitor.md
```

Do not create all agents as always-running processes. They are Claude role definitions invoked by the orchestration workflow.

Suggested configuration additions:

```text
config/base/surveillance.yaml
config/research/surveillance.yaml
config/paper/surveillance.yaml
config/live/surveillance.yaml
config/schemas/surveillance.schema.json
config/registries/sources.yaml
config/registries/market_context_instruments.yaml
```

---

# 13. DATABASE ADDITIVE MIGRATIONS

Do not modify or drop existing tables in the initial migration unless absolutely required.

## 13.1 New entities

Recommended additions:

- `source_registry_versions`
- `source_health_events`
- `economic_event_versions`
- `news_items`
- `news_item_sources`
- `news_verification_events`
- `cross_market_observations`
- `feature_snapshots`
- `market_states`
- `market_state_components`
- `surveillance_events`
- `surveillance_alerts`
- `alert_acknowledgements`
- `market_state_packets`
- `thesis_monitoring_plans`
- `position_contradictions`
- `surveillance_agent_reviews`

Reuse existing `economic_events`, `feature_versions`, `agent_reviews`, or `audit_events` tables when they already meet the requirement. Do not create duplicate concepts merely to match this document.

## 13.2 Migration requirements

Each migration must:

- Run successfully on an empty test database
- Run successfully on a copy of the current database
- Preserve existing row counts and constraints
- Support rerun detection
- Include downgrade guidance or a feature-disable rollback path
- Be covered by migration tests
- Produce a backup before first local production application

## 13.3 Indexing

Add indexes based on measured query needs, likely including:

- Instrument plus `as_of_utc`
- Event type plus timestamp
- Source plus health timestamp
- Candidate or position correlation ID
- News content hash
- Scheduled event time

Avoid premature indexing that degrades laptop write performance.

---

# 14. CONFIGURATION AND FEATURE FLAGS

All new functions must be independently controllable.

## 14.1 Baseline configuration

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

## 14.2 Rollout flag progression

Use this progression:

1. `enabled: false`
2. Research replay only
3. Live-data observe-only; no Claude calls
4. Live-data observe-only with scheduled summaries
5. Event-driven Claude summaries; no candidate influence
6. Paper candidate context enabled
7. Paper post-entry contradiction monitoring
8. Owner-reviewed live context influence

No step may be skipped without documented approval.

---

# 15. CLAUDE AGENT OUTPUT SCHEMAS

Every new agent must return machine-validated structured output. Free-form commentary may accompany but cannot replace the schema.

## 15.1 Surveillance Situation Report

```yaml
report_id: UUID
market_state_id: UUID
agent_id: string
agent_version: string
generated_at_utc: datetime
overall_state: NORMAL | MATERIAL_CHANGE | DEGRADED | CRITICAL
material_changes: []
active_market_drivers: []
technical_observations: []
macro_observations: []
news_observations: []
cross_market_observations: []
contradictions: []
data_limitations: []
specialists_to_consult: []
escalation_required: boolean
expiration_utc: datetime
```

## 15.2 Opportunity Alert

```yaml
alert_id: UUID
market_state_id: UUID
severity: INFO | WATCH | MATERIAL | CRITICAL
instrument_ids: []
change_type: string
what_changed: string
supporting_observation_ids: []
conflicting_observation_ids: []
data_quality_status: string
suggested_recipients: []
trade_direction: null
expires_at_utc: datetime
```

`trade_direction` must remain null at the surveillance-alert layer.

## 15.3 News Relevance Review

```yaml
review_id: UUID
news_item_id: UUID
verification_state: string
event_time_utc: datetime | null
publication_time_utc: datetime
potentially_affected_instruments: []
materiality: NONE | LOW | MEDIUM | HIGH | UNKNOWN
already_known_or_recirculated: boolean
conflicting_facts: []
pricing_assessment: UNKNOWN | POSSIBLY_PRICED | REACTION_ONGOING | NOT_OBSERVED
recommended_state: IGNORE | WATCH | ESCALATE | PAUSE_NEW_ENTRIES
```

---

# 16. EXISTING WORKFLOW INTEGRATION

## 16.1 Pre-candidate integration

The new Market State Packet becomes an input to Senior Trader Alpha and Beta. It does not replace existing historical analogs, specialist reports, or execution checks.

Senior traders must explicitly separate:

- Historical evidence
- Current technical evidence
- Current macro/news evidence
- Current cross-market evidence
- Current execution evidence
- Unknowns and contradictions

## 16.2 Candidate schema additions

Add references rather than copying large payloads:

```yaml
market_state_id: UUID
market_state_packet_id: UUID
surveillance_report_ids: []
material_news_item_ids: []
source_health_snapshot_id: UUID
thesis_monitoring_plan_id: UUID | null
```

Preserve backward compatibility for existing candidates. New fields should initially be nullable.

## 16.3 Risk-gate integration

Do not rewrite risk calculations.

Add optional deterministic preconditions such as:

- Required Market State Packet exists
- Packet has not expired
- Required source-health components are not failed
- No active configured event blackout
- No unresolved critical news conflict

These checks must remain disabled in live configuration until paper validation and owner approval.

## 16.4 Specialist activation

The Opportunity Alert Agent may recommend consultation with existing specialists:

- London Breakout
- Asian Range Sweep and Reversal
- London Continuation

It may also recommend the broad Senior Traders evaluate an uncategorized situation. It must not manufacture relevance for a specialist.

---

# 17. COST AND MODEL ROUTING POLICY

The implementation must preserve minimal recurring cost.

## 17.1 Deterministic-first policy

Do not send raw tick streams, full news feeds, or unchanged state repeatedly to Claude.

Claude receives:

- Material deltas
- Compact structured snapshots
- Relevant source excerpts or normalized facts
- Current candidate context
- Explicit uncertainties

## 17.2 Model quality routing

Use the highest-quality available model for:

- Technical Surveillance Lead on material events
- News verification where ambiguity is consequential
- Senior Trader Alpha and Beta
- Market Opportunity Arbiter
- Chief Risk review
- Post-incident analysis

Use lower-cost models or deterministic code for:

- Routine extraction
- Schema normalization
- Duplicate detection
- Non-material scheduled summaries
- Log classification
- Data-quality formatting

## 17.3 Invocation budget controls

Implement configuration for:

- Maximum scheduled Claude invocations per session
- Maximum noncritical event-driven invocations per hour
- Minimum materiality threshold
- Cooldown period
- Context-size limits
- Fallback behavior when the budget is exhausted

Budget exhaustion must reduce interpretation frequency, not disable deterministic risk or source-health monitoring.

---

# 18. SUPERVISION, HEALTH, AND RECOVERY

Integrate all new services into the existing supervisor.

## 18.1 Required health checks

- Collector heartbeat
- Last successful price update
- Last successful feature snapshot
- Last Market State publication
- Economic-calendar source health
- News-source health
- Cross-market source health
- Event queue backlog
- Database write health
- Claude orchestration health
- Alert delivery health

## 18.2 Restart recovery

On restart:

1. Reconcile existing broker positions using the current process.
2. Restore source-health states.
3. Resume collectors from safe cursors where supported.
4. Rebuild current Market State from persisted source snapshots.
5. Mark reconstructed state clearly.
6. Do not issue candidate-influencing alerts until freshness requirements are satisfied.
7. Reattach active positions to their Thesis Monitoring Plans.

## 18.3 Degraded mode

Define explicit degraded modes:

- Technical-only observation
- Macro unavailable
- News unavailable
- Cross-market unavailable
- Claude interpretation unavailable
- Full surveillance failed

The risk and candidate systems must receive the exact degraded state rather than a generic healthy flag.

---

# 19. TEST PLAN

No feature-flag progression until required tests pass.

## 19.1 Unit tests

- Market State schema validation
- Freshness calculations
- Regime-label transitions
- Structure-event detection
- Feature-registry enforcement
- News deduplication
- Publication-time versus event-time handling
- Source-health state machine
- Cross-market divergence calculation
- Materiality thresholds
- Alert throttling and severe-alert bypass
- Market State checksum
- Thesis Monitoring Plan validation
- Post-entry contradiction classification
- Asset-class-neutral instrument handling

## 19.2 Migration tests

- Upgrade empty database
- Upgrade copied current database
- Existing tests pass after migration
- Existing queries still work
- New nullable candidate references do not break old rows
- Backup and restore exercise
- Feature-disable rollback exercise

## 19.3 Integration tests

- Broker data to feature snapshot
- Feature snapshot to Market State
- Economic event to blackout state
- News ingestion to verification to alert
- Cross-market observation to divergence event
- Market State Packet delivered identically to Alpha and Beta
- Surveillance alert to Arbiter consultation workflow
- Candidate references Market State correctly
- Open position to contradiction alert
- Supervisor restart restores state safely

## 19.4 Replay tests

Use stored historical sessions to verify:

- No look-ahead information enters Market State
- Publication timestamps reflect data availability
- Scheduled releases are unavailable before actual publication time
- News items are not backfilled into earlier decisions
- State transitions can be reproduced
- Alert volume remains manageable
- Existing strategy results remain unchanged while influence flags are disabled

## 19.5 Failure-injection tests

- Price feed stalls
- One news source fails
- All news sources fail
- Conflicting headlines arrive
- Calendar reports wrong or revised time
- Cross-market feed lags
- Duplicate news storm
- Database locked
- Event queue backlog
- Claude invocation fails
- Laptop sleeps and resumes
- Internet disconnects and reconnects
- System clock drift
- Supervisor restarts one collector repeatedly

## 19.6 Acceptance tests

The amendment is not complete unless:

- Existing test suite passes unchanged or with documented additive updates
- Existing live-disabled baseline behavior is preserved
- New services can run in observe-only mode
- No new agent can place an order
- No alert contains an executable direction
- Alpha and Beta receive identical Market State Packet checksums
- Stale required data cannot be treated as confirmation
- Unknown news state remains distinguishable from no news
- Existing strategy P&L replay is unchanged with surveillance influence disabled
- One command or config change disables the entire new division
- Database can be restored to the pre-migration backup
- Supervisor health reports include all new processes

---

# 20. ADDITIVE ROLLOUT PHASES

## Phase A — Audit and compatibility map

Deliverables:

- Actual repository architecture map
- Existing market-data and feature inventory
- Existing news/calendar capability inventory
- Existing agent and orchestration inventory
- Existing database schema map
- Existing supervisor and scheduler map
- Reuse-versus-add decision table
- Risk and regression analysis
- Exact file-level implementation plan

No production code before this phase is documented.

## Phase B — Schemas, flags, and migrations

Deliverables:

- New schemas
- Disabled configuration
- Source registry
- Additive database migrations
- Backup and restore scripts
- Migration tests

No external polling or Claude invocation yet.

## Phase C — Deterministic technical surveillance

Deliverables:

- Market State builder using existing price and feature data
- Technical, structure, regime, liquidity-proxy, and spread observations
- Source-health framework
- Observe-only local reports
- No candidate influence

## Phase D — Macro, news, and cross-market ingestion

Deliverables:

- Approved source adapters
- Economic-event normalization
- News normalization and deduplication
- Verification workflow
- Cross-market adapters
- Health and failure states
- Data licensing and cost report

Remain observe-only.

## Phase E — Event-driven alerts and Claude surveillance agents

Deliverables:

- Materiality engine
- Opportunity alerts
- Agent definitions and schemas
- Scheduled and event-driven invocation routing
- Invocation-budget controls
- Notification integration

No candidate or risk influence.

## Phase F — Senior Trader packet integration

Deliverables:

- Immutable Market State Packet
- Identical Alpha/Beta packet checksums
- Candidate reference fields
- Specialist consultation routing
- Shadow comparison reports showing decisions with and without surveillance context

## Phase G — Paper-trading influence

Deliverables:

- Paper candidate context enabled
- Thesis Monitoring Plans
- Post-entry contradiction monitoring
- Performance and calibration comparison
- Alert precision and false-positive review

## Phase H — Owner review for limited live influence

Required evidence:

- Stable supervisor operation
- Acceptable source reliability
- Acceptable alert volume
- No regression to existing execution or risk behavior
- Demonstrated value in paper/shadow analysis
- Documented recurring cost
- Rollback test passed
- Owner approval recorded

Only then may selected surveillance components influence live eligibility.

---

# 21. DEFINITION OF DONE

This additive amendment is complete when:

1. The current system remains operational and its pre-amendment tests pass.
2. The Global Market Intelligence and Surveillance Division exists behind disabled feature flags.
3. Deterministic services publish versioned Market State Objects.
4. Market State Packets are immutable and identical for Alpha and Beta first-pass analysis.
5. Technical, macro, news, cross-market, source-health, and post-entry contradiction domains are represented.
6. All new agents use structured, validated output schemas.
7. The new division cannot submit orders or alter risk.
8. New database migrations are additive, tested, backed up, and recoverable.
9. The new processes are supervised, heartbeat-monitored, restart-safe, and visible in health reports.
10. The system can run in observe-only mode with no change to existing candidate or execution decisions.
11. Paper-trading integration is available but disabled until the corresponding rollout phase.
12. Options-ready domain boundaries exist without enabling options trading.
13. A rollback runbook and one-command disable path are documented and tested.
14. Claude produces an implementation report listing changed files, migrations, tests, costs, remaining risks, and activation status.

---

# 22. REQUIRED FIRST RESPONSE FROM CLAUDE

After receiving this file, do not immediately begin a broad refactor.

Produce the following in one audit report:

1. Current repository branch, clean/dirty state, and latest commit
2. Current runtime and supervisor architecture
3. Current agent inventory and invocation flow
4. Current price, feature, economic-calendar, news, and cross-market capabilities
5. Current database entities and migration framework
6. Existing candidate, Market State Packet, and Senior Trader schemas
7. Existing source-health and fail-closed behavior
8. Exact components that can be reused
9. Exact components that must be added
10. File-by-file additive implementation plan
11. Database migration plan and backup procedure
12. Feature-flag and rollback plan
13. Regression-test plan
14. Estimated new recurring cost by source and model usage
15. Any blocker that genuinely requires owner input

Then implement only the first approved additive phase using safe defaults.

---

# 23. REQUIRED FINAL IMPLEMENTATION REPORT

When the code change is complete, Claude must report:

- Baseline commit
- Working branch
- Final commit(s)
- Files added
- Files modified
- Migrations added and applied status
- Configuration flags and their current values
- Agents added
- Sources connected and approval status
- Tests added
- Full test results
- Supervisor and heartbeat status
- Observe-only demonstration results
- Regression comparison against the previous system
- Known limitations
- Monthly recurring cost estimate
- Rollback command and verified result
- Features still disabled
- Owner approvals required before the next rollout phase

The report must not claim live activation unless the live configuration and owner approval record prove it.

---

# 24. OWNER-APPROVED DESIGN DECISION

The firm shall not rely solely on historical strategies or static historical relationships. Historical evidence identifies possible edge. The Global Market Intelligence and Surveillance Division determines whether the present market supports, weakens, contradicts, or invalidates that edge.

This division is a permanent shared service for the current forex operation and the future multi-asset firm. It must be implemented additively, economically, auditably, and without weakening the deterministic risk and execution architecture already running on the owner's laptop.
