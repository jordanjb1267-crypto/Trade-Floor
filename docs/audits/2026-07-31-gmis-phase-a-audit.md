# GMIS-001 Phase A audit — repository state and additive compatibility map

**Date:** 2026-07-31 · **Amendment:** GMIS-001 (adopted as A-3, spec v2.3.0)
**Source document:** `docs/spec/CLAUDE_ADDITIVE_HANDOFF_GLOBAL_MARKET_INTELLIGENCE_SURVEILLANCE_v2.1.0.md`
(SHA-256 `36e72f8e4b30b77c3bb0eebc1fe6467cf01a0a669a920010a60fa9c57be36bbe`)

This is the audit report the amendment's own §22 requires as the first
response, produced before any production code. Section numbers G§N below
refer to the GMIS document; bare §N references resolve against the governing
Master Handoff. The fifteen numbered items follow G§22's list exactly.

## 1. Branch, state, and latest commit

Working branch `claude/add-global-market-intelligence-surveillance`, created
from `claude/trading-firm-review-xowwvx` at its tip **b2ef800** ("Add
environment validator and ignore runtime session reports"), which is the
pre-amendment baseline commit. Tree clean at branch creation. The branch is
cut from the session branch rather than `main` because it must build on the
§18 supervisor and §19 notification code that `main` will only receive when
draft PR #19 merges.

Verified before this build started: **no surveillance implementation exists
anywhere reachable from this repository** — all eight remote branches, the
working tree, untracked files, stashes, and dangling objects were searched
for `surveillance`, `GMIS`, the ten agent filenames, and the suggested
config paths; every search returned nothing. This is a green-field build.
The owner confirmed: "the implementation is not in github yet nothing has
been built yet it must first be reviewed and spec'd by you then once built
pushed to github".

## 2. Runtime and supervisor architecture

One supervisor, composed in `scripts/run_supervisor.py` and kept alive by a
launchd KeepAlive agent (`deploy/macos/`): `runner/supervisor.py::Supervisor`
takes injected dependencies (`clock, probe, notify, report_dir, now, sleep,
heartbeat`) and handles the five `SessionEvent`s (`PRE_STARTUP, BRIEFING,
ACTIVATION, ENTRY_CUTOFF, FLATTEN`) computed by `runner/schedule.py` from the
`Europe/London`-anchored `SessionClock`. The probe is read-only (open
positions only); a failed probe degrades the day fail-closed but keeps the
schedule so the flatten check still runs; not-flat at 11:00 London is a
RISK_HALT. `runner/liveness.py` provides the heartbeat file, append-only
events JSONL, secret scanning (`assert_secret_free`), and the
delivery-marker/attempt-ledger pair that rate-limits notifications.
`tests/acceptance/test_supervisor_no_order_path.py` proves no module under
`runner/` can import an order-placing path. GMIS services must ride this
supervisor (G§9.1: no second supervisor) — the attach points are the
reserved BRIEFING/ACTIVATION branch in `Supervisor.handle` and the injected
heartbeat callable.

## 3. Agent inventory and invocation flow

Nine agent role definitions under `.claude/agents/` (firm-governor,
senior-trader-alpha, senior-trader-beta, market-opportunity-arbiter,
chief-quant-validation, chief-risk-officer, session-strategist,
context-analyst, learning-audit-director). Invocation flow:
`MarketSnapshot` + `FirmSnapshot` → `MarketStatePacket` (checksummed) →
`IndependenceLedger.for_packet` → Alpha and Beta lock independent theses →
`arbiter.arbitrate` → specialist bench consultation
(`agents/bench.py::consult`, tier delta ≤ 0) → deterministic
`classification.classify` → `RiskEngine.evaluate` with `thesis_ceiling`
applied downward only. Every agent payload enters deterministic code through
one gate: `agents/schemas.py::validate_agent_payload` (five registered
kinds). All nine agents route to the frontier tier per
`governance/model-routing-policy.md`. GMIS adds ten surveillance role
definitions and three new payload kinds through the same gate.

## 4. Price, feature, economic-calendar, news, and cross-market capabilities

- **Price:** OANDA fxTrade Practice via the read-only MCP bundle
  (`mcp/oanda-practice/`, no order tools by design) and
  `execution/oanda_transport.py` (behind the §12.1 lazy-import control).
  `market_data/bars.py` normalizes OANDA candles and FMP intraday rows into
  `BarSeries` (gap detection, completeness); `market_data/spreads.py` builds
  `SpreadSeries`; H1/M5 research fixtures exist for GBP_USD and EUR_USD.
- **Features:** `features/engine.py` — `session_features_v1` (8 features)
  and `structure_features_v1`, both registered in
  `config/research/adaptive_policy.yaml` and gated by
  `AdaptivePolicyManifest.permits_feature`.
- **Economic calendar:** FMP is the ratified source (D-7), used via scripts
  and fixtures; the known caveat that FMP timestamps arrive as unmarked
  local times is pinned in `market_data/bars.py`. No always-on calendar
  poller exists.
- **News:** none. No ingestion, verification, or storage exists.
- **Cross-market:** none. No context instruments are tracked.

So G§20 Phase C (technical surveillance) can be built entirely from existing
data; Phase D adapters normalize sources the firm already pays for (OANDA
practice: free; FMP: existing subscription) — no new vendor is required.

## 5. Database entities and migration framework

SQLite (WAL, foreign keys on) via `audit/db.py::connect`. Migrations are
plain SQL files applied in filename order by `audit/db.py::apply_migrations`,
which creates and consults a `schema_migrations` ledger — rerun detection is
built in and tested (`tests/unit/test_audit.py`). One migration exists,
`0001_init.sql`: `configuration_versions`, `account_snapshots`, `candidates`,
`risk_decisions`, `capital_tier_events`, `incidents`, `audit_events`
(hash-chained mirror of `audit/chain.py::AuditLog`), plus three indices.
Conventions: Decimals stored as TEXT, ISO-8601 UTC TEXT timestamps,
CHECK-constrained enums. What G§13 assumes but does not exist: a backup
script and a copied-database test harness — both are added in this build.

## 6. Existing candidate, Market State Packet, and senior-trader schemas

- `models.py::Candidate` — frozen, with `content_key()` (idempotency hash)
  and `edge_tier`; `RiskDecision` carries `thesis_ceiling`/`tier_bound_by`.
- `packet.py` — `MarketSnapshot` (market half; the only classification
  input), `FirmSnapshot` (capacity half), `MarketStatePacket`
  (`market_id`, `packet_id`, `verify()`), checksums via `_canonical`/`_digest`
  with explicit field lists. `PACKET_VERSION = "market_state_packet_v1"`.
- `adaptive.py` — `AdaptiveThesis` (§6.7 schema), `NoveltyClass` N0–N3,
  `EvidenceClass` E0–E5 with permission tables as type constraints; note
  `adaptive.MarketState` already exists (regime/volatility/session-phase
  triple), which is why the GMIS §4 object is named `MarketStateObject`.
- `agents/schemas.py` — `ContextReport`, `StrategistAssessment`,
  `CroVerdict`, `ApprovalCard`, `PostSessionReport`; `bench.py::ContextPacket`
  binds a report to a packet via `verify_against(market)`.

## 7. Existing source-health and fail-closed behavior

Fail-closed is enforced at four layers today: config validators
(`config.py`) reject constitution violations at load; `reject_unknown_news_state`
in `config/base/firm.yaml` plus `news_state_known` fields on `ContextReport`
and `Candidate` refuse entries when calendar state is unknown; the
reconciliation engine (`reconciliation/engine.py::startup_mode`) blocks new
entries on mismatch; and a degraded supervisor day skips evaluation
boundaries while keeping the flatten check. What does not exist: per-source
health states, freshness SLAs, or the six-way missing-news distinction of
G§8.3 — GMIS adds these, and the existing `reject_unknown_news_state`
behavior is preserved exactly as the fail-closed floor.

## 8. Components that can be reused (reuse-versus-add table)

| Existing component | GMIS use |
|---|---|
| `packet._canonical` / `_digest` | checksums for `MarketStateObject` and `SurveillancePacket` |
| `agents/schemas.py::validate_agent_payload` | the single gate for the three new agent output kinds |
| `bench.ContextPacket.verify_against` pattern | bind-and-verify for surveillance reports |
| `bench.BENCH` frozen-mapping pattern | source registry exposure (no runtime `add()`) |
| `policy.AdaptivePolicyManifest.permits_feature` | unchanged feature gate; G§7 metadata extends, never replaces |
| `strategies/manifest.py` loader pattern | `SourceRecord` / `FeatureRecord` registry loaders |
| `notify/surface.py` registered-kind sets + `notify_owner` | surveillance alert delivery (new third registered set) |
| `runner/liveness.py` ledger + `assert_secret_free` | alert dedup/rate-limit and secret-free event writes |
| `Supervisor` injected-dependency pattern (`heartbeat`) | the `sweep` callable (default `None` ⇒ byte-identical) |
| `audit/db.py::apply_migrations` | `0002_surveillance.sql`, no new framework |
| `audit/chain.py::AuditLog` | first production consumer: surveillance decision trail |
| `market_data/bars.py`, `spreads.py`, `features/engine.py` | the entire Phase C state-builder input |
| `research/replay.py` | golden replay proving observe-only changes nothing |
| `tests/a2_guard.py` | pressure-blindness of all surveillance classification |
| no-order-path test patterns (glob + tuple) | `surveillance/**` coverage |
| `SessionClock` boundaries | briefing checkpoints (no new wall-clock times) |

## 9. Components that must be added

`src/trading_firm/surveillance/` (config, schemas, events, freshness,
state_builder, materiality, deduplication, alerts, budget, source_health,
coordinator, packet, preconditions; `technical/`, `macro/`, `news/`,
`cross_market/`, `sources/`, `positions/`, `options/README.md`),
`features/registry.py`, `config/base|research/surveillance.yaml`,
`config/registries/{sources,market_context_instruments,features}.yaml`,
`database/migrations/0002_surveillance.sql`,
`scripts/{db_backup,db_restore,run_surveillance_sweep}.py`, ten agent files,
and the governing-spec v2.3.0 lineage (new §30, §29.5 changelist).

## 10. File-by-file additive implementation plan

Fourteen workstreams W0–W13, each leaving the full suite and both
§-checkers green; the complete ordered plan with per-file responsibilities
is the ratified plan of record for this build (session plan, reproduced in
the PR description). Order: audit → spec lineage → config/flags →
registries → schemas/events → migration → technical surveillance → source
health/adapters → alerts/budget/notify → supervisor integration → packet/
candidate refs/preconditions → thesis monitoring/contradiction → agent
files/docs → replay/acceptance closure and the G§23 final report.

## 11. Database migration plan and backup procedure

`0002_surveillance.sql` adds 13 tables (`source_health_events`,
`economic_events` versioned by (event_id, version), `news_items` with a
UNIQUE content hash, `news_item_sources`, `news_verification_events`,
`cross_market_observations`, `feature_snapshots`, `market_states`,
`surveillance_events`, `surveillance_alerts`, `market_state_packets`,
`thesis_monitoring_plans`, `position_contradictions`,
`surveillance_agent_reviews`) and one nullable column
(`candidates.market_state_packet_id` — verified: no code writes to
`candidates` today, so no writer breaks). Deliberate reuse per G§13.1:
registry file versions are recorded in the existing
`configuration_versions`; `market_state_components` folds into
`market_states.payload_json`; `alert_acknowledgements` folds into columns on
`surveillance_alerts` (single-operator deployment). Backup:
`scripts/db_backup.py` (SQLite backup API → `database/backups/`) runs before
the first real application; restore is `scripts/db_restore.py` and is
exercised by the test suite. Rollback paths, in preference order:
(1) `surveillance.enabled: false` — the new tables sit empty and inert;
(2) restore the pre-migration backup.

## 12. Feature-flag and rollback plan

`config/base/surveillance.yaml` implements G§14.1 verbatim with
`enabled: false` and every influence flag false. The loader enforces, as
validation errors: the master switch dominates every sub-block;
`influence_candidate_generation` / `influence_live_eligibility` refuse true
outside paper/live; `severe_alerts_never_throttled` and
`fail_closed_on_required_component_failure` refuse false. Per owner
decision (2026-07-31), phone delivery is severe-only: a new
`alerts.telegram_minimum_severity: MATERIAL` key governs delivery while
G§14.1's `minimum_severity: INFO` governs local alert creation.
`config/live/surveillance.yaml` is **deliberately not created** — it is a
protected path (§7.2) and belongs to Phase H with owner sign-off. One-line
disable of the whole division: `enabled: false` (already the default).
Rollout follows G§14.2's eight steps; no step skipped without documented
approval.

## 13. Regression-test plan

Existing 1,075 tests must pass unchanged apart from documented additive
edits (guard-list extensions, notify registry union). New proofs: flags-off
supervisor `SessionRecord` byte-identical with the sweep absent vs disabled;
golden replay — `research/replay.py` strategy results bit-identical with
surveillance running observe-only; `Candidate.content_key()` golden hash
unchanged with reference fields present; `MarketSnapshot` checksum
untouched; no-order-path over `surveillance/**`; `trade_direction` non-null
rejected at the type layer; identical Alpha/Beta packet checksums; a2_guard
probed with synthetic violations in both directions; migration applied to
an empty and a copied database, rerun-skipped, backed up and restored.

## 14. Estimated new recurring cost by source and model usage

Sources: **$0/month new.** OANDA practice data is free with the existing
practice account; FMP calendar/news use the existing paid FMP key; both are
registered `production_approved: false`. No new vendor, no options data.
Model usage: **$0 until Phase E flags are enabled** — `claude_agents.enabled`
is false, so no surveillance Claude invocation occurs; when enabled, G§17.3
budget controls (per-session and per-hour caps, materiality floor, cooldown)
bound the spend, and all ten agents route frontier per
`governance/model-routing-policy.md` until rule 5's down-routing evidence
exists. Storage: SQLite growth on the order of megabytes per month at
observe-only cadence.

## 15. Blockers that genuinely require owner input

None outstanding. The four decisions this audit would otherwise have
blocked on were put to the owner and answered on 2026-07-31: (1) all ten
agents land as separate role files (roster 9 → 19, boundary with
context-analyst documented); (2) phone alerts are severe-only
(MATERIAL/CRITICAL); (3) options scaffolding is prose plus asset-class-
neutral fields, no stub modules; (4) the build lands on this dedicated
branch with its own draft PR. Deferred by design, not blocked: the live
config layer (Phase H, owner-gated), source production approvals (Phase D+
review), and any live influence (Phase H, requires §12.7-cleared evidence).
