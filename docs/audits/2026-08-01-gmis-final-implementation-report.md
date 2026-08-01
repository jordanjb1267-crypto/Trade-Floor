# GMIS-001 final implementation report (amendment §23 / spec §30.18)

**Date:** 2026-08-01 · **Amendment:** A-3 / GMIS-001 · **Spec:** v2.3.0

## Commits and branch

- **Baseline commit:** b2ef800 (tip of `claude/trading-firm-review-xowwvx`,
  pre-amendment; carries the §18 supervisor and §19 notification code this
  build extends)
- **Working branch:** `claude/add-global-market-intelligence-surveillance`
- **Commits:** 13, one per workstream W0–W13 plus governance, each leaving
  the full suite, ruff, both §-checkers, and the config validator green
- **Diff:** ~105 files changed, ~13,000 insertions, 30 deletions (the
  deletions are guard-list and registry-test extensions — nothing existing
  was removed)

## Files added and modified

Added: the governing spec v2.3.0 (new file; v2.2.0 preserved unedited); the
GMIS handoff verbatim under `docs/spec/`; the Phase A audit and this report;
`src/trading_firm/surveillance/` (30 modules: config, schemas, events,
freshness, source_health, state_builder, materiality, alerts, deduplication,
budget, coordinator, packet, preconditions, monitoring; technical/, macro/,
news/, cross_market/, sources/, positions/; options/README.md only);
`src/trading_firm/features/registry.py`; five config/registry YAML files;
migration `0002_surveillance.sql`; three scripts (`db_backup.py`,
`db_restore.py`, `run_surveillance_sweep.py`); ten `.claude/agents/` role
files; fourteen new test files across unit, acceptance, replay, integration,
and failure_injection.

Modified (additively): `agents/schemas.py` (+3 payload kinds),
`agents/__init__.py`, `models.py` (Candidate +6 nullable reference fields,
excluded from `content_key()`), `notify/surface.py` (+2 kinds in a third
registered set), `runner/supervisor.py` (injected optional sweep),
`scripts/run_supervisor.py` (composes None while disabled; refuses a
premature enable loudly), `scripts/validate_config.py` (covers surveillance
layers and registries), `CLAUDE.md`, `governance/constitution.md`,
`governance/model-routing-policy.md`, `governance/decision-log.md`, the nine
existing agent files (governing pointer), and two guard suites
(`test_a2_guard.py`, `test_adaptive_workflow.py`).

## Migrations

`0002_surveillance.sql`: 14 additive tables plus one nullable column on
`candidates`. Applied status on this repository: applied only inside tests
(no production database file exists in the repo — the owner's laptop
database is migrated on first run, after `scripts/db_backup.py`). Tested:
empty database, copy of a populated pre-amendment database (row counts
preserved), rerun detection, old candidate rows reading NULL references,
backup/restore round-trip, and the disable-rollback posture (every new
table empty with flags off).

## Configuration flags and current values

`config/base/surveillance.yaml` and `config/research/surveillance.yaml`,
both: `enabled: false`, `mode: observe_only`,
`influence_candidate_generation: false`, `influence_live_eligibility:
false`, `post_entry_monitoring_enabled: false`, macro/news/cross-market/
claude_agents/positions/options all disabled,
`alerts.telegram_minimum_severity: MATERIAL` (owner decision, severe-only),
`fail_closed_on_required_component_failure: true`. The loader refuses:
influence flags true, fail-open unknown states, sub-MATERIAL phone
delivery, options activation, automatic order changes, non-FX asset
classes, any mode but observe_only. `config/live/surveillance.yaml` does
not exist (protected path; Phase H owner action).

## Agents added

Ten §30.3 role files (technical-surveillance-lead, price-structure-monitor,
indicator-feature-monitor, liquidity-auction-monitor,
volatility-regime-monitor, macro-event-monitor, cross-market-monitor,
news-verification-relevance, opportunity-alert-agent,
position-contradiction-monitor). Roster is nineteen by explicit owner
decision (2026-07-31). All route frontier per
`governance/model-routing-policy.md`; none is invoked by any process while
`claude_agents.enabled` is false.

## Sources connected and approval status

Three registry records, zero new vendors: `oanda_practice` (broker data,
existing practice account), `fmp` (calendar, existing subscription, D-7),
`fmp.news` (research-only). **All `production_approved: false**`; all
`fail_closed_when_unavailable: true`. No live polling is wired — adapters
normalize data handed to them, and the always-on collectors arrive with
their rollout step.

## Tests added and results

Suite grew from 1,075 to **1,337, all passing** (~260 added): surveillance
config mutation tests, registry consistency, schema/checksum, migration
matrix, technical surveillance (freshness, structure, indicators,
liquidity, regime, materiality, no-lookahead), 22 failure-injection
scenarios, alert discipline and budgets, notify registry, supervisor sweep
containment, coordinator flow, packet identity, candidate golden-hash,
precondition refusals, contradiction precedence, the a2 boundary fence,
surveillance no-order-path (glob + fresh-import eviction), one-config
disable, golden replay, replay-scale no-lookahead, bounded alert volume,
and the six integration pipelines. `ruff`, `check_spec_refs` (2,470
references), `check_spec_quotes`, and `validate_config` (6/6 artifacts)
all green.

## Supervisor and heartbeat status

The sweep is injected like the heartbeat: default None makes the supervisor
byte-identical to the pre-amendment build (pinned by report diff); degraded
days withhold it; a raising sweep is contained and recorded. Heartbeat,
liveness ledgers, and the two-message nominal day are unchanged. §30.16
health reporting beyond the sweep note arrives with the always-on
collectors in the live-data rollout step.

## Observe-only demonstration

`python3 scripts/run_surveillance_sweep.py --date 2026-07-29` against the
stored OANDA practice fixture: Market State `32bd773feb83…`, phase ACTIVE,
intraday regime COMPRESSING, structure inside_reference_range, liquidity
undisturbed, data quality DEGRADED with news/macro/cross-market honestly
listed missing, one INFO alert created and kept local (severe-only phone
gate), zero orders, report written to `reports/ops/surveillance/`.

## Regression comparison

Golden replay: `research/replay.py` outcomes and net P&L bit-identical with
surveillance running observe-only over the same series. Candidate
`content_key()` unchanged with reference fields populated.
`MarketSnapshot`/`MarketStatePacket` untouched. Supervisor session records
byte-identical with the sweep absent. `live_allowed` empty everywhere;
halt-only command surface untouched; §19 minimum set still eleven.

## Known limitations

No always-on collectors exist yet (state builds run on handed-in series;
live-data observe-only is the next rollout step and `run_supervisor.py`
refuses a premature enable). Prior-session HIGH/LOW levels await a feature
engine extension (v1 tracks Asian extremes; mislabeled substitutes were
deliberately not shipped). The session-horizon regime label is
INDETERMINATE by design in classifier v1. News/macro/cross-market domains
are normalization-and-governance only until their rollout steps. Feature
records carry `leakage_review_status: not_reviewed` at research status —
honest, and a named §12.7 gate before any production promotion.

## Recurring cost

**$0/month new.** OANDA practice data free; FMP already subscribed; zero
surveillance Claude invocations while `claude_agents.enabled` is false,
budget-bounded thereafter (§30.15). Storage growth is megabytes/month at
observe-only cadence.

## Rollback command and verified result

Primary: set `surveillance.enabled: false` (already the default) — the
acceptance suite proves a wired coordinator short-circuits before any work
and every new table stays empty. Secondary:
`python3 scripts/db_restore.py database/backups/<stamp>.sqlite --force` —
the backup/restore round-trip is exercised in-suite (integrity check plus
table-by-table row counts; the displaced file is kept, never deleted).

## Features still disabled

Everything with authority: the master switch, all influence flags,
post-entry monitoring, macro/news/cross-market ingestion, Claude agent
invocation, scheduled briefings, options scaffold (prose only), risk-gate
preconditions (built, unwired — `risk/engine.py` imports nothing from
surveillance, pinned by test).

## Owner approvals required before the next rollout phase

Per §30.12's ladder, in order: (2) research replay only — available now via
`run_surveillance_sweep.py`; (3) live-data observe-only requires the
collector build plus an owner decision to enable; source production
approvals require `approval_record_id` entries; any candidate influence
(steps 6–8) requires paper validation, §12.7-cleared evidence, and the
Phase H review. Nothing in this build activates by itself. This report
does not claim live activation: `live_allowed` is empty and no approval
record exists.
