# Trade-Floor

Working repository for the **Claude London Trading Firm** project.

- **Original specification (as reviewed):** [`docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF.md`](docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF.md) (v1.0.0, verbatim)
- **Design review of the specification:** [`docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md`](docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md) — verdict, findings (C/M/N/O), blocking owner decisions, and a v1.1.0 amendment changelist
- **Governing specification:** [`docs/spec/CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.1.0.md`](docs/spec/CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.1.0.md) — the owner-supplied adaptive rewrite (v2.0.0) with the seven protections it omitted restored: London-anchored sessions (C-2), owner-approved promotion (D-2), deposit exclusion (D-3), per-instrument margin (F-1), rollover blackout (F-5), minimum-evidence thresholds (§12.6/D-5), and the research publication gate (§12.7/A-1). Ratification and changelist in §29; v2.0.0 and v1.1.4 preserved unedited.
- **Phase 0 audit record:** [`docs/audits/2026-07-29-oanda-practice-connection-audit.md`](docs/audits/2026-07-29-oanda-practice-connection-audit.md) — OANDA practice connection audit: 8/8 PASS; findings F-1 (per-instrument margin), F-2 (practice≠live), F-3/F-4/F-5 (spread regimes and the 21:00 UTC rollover hazard)

## Phase 1 — governance & skeleton

- [`CLAUDE.md`](CLAUDE.md) — iron rules, protected paths, repo map, development guide
- [`governance/`](governance/) — constitution, risk policy, promotion policy, incident policy, decision log
- [`config/base/firm.yaml`](config/base/firm.yaml) — §24 baseline, validated by [`src/trading_firm/config.py`](src/trading_firm/config.py) (constitution violations fail to load; see `tests/unit/test_config.py`)
- [`.claude/agents/`](.claude/agents/) — the six firm agents (§6); [`.claude/hooks/`](.claude/hooks/) — pre-edit protection + secret scan (§7.3)
- CI: `.github/workflows/ci.yml` — ruff + config validation + pytest

```bash
pip install -e ".[dev]" && pytest && ruff check src tests scripts
```

## Phase 2 — offline deterministic core

- [`src/trading_firm/models.py`](src/trading_firm/models.py) — domain models; Decimal money; §5.2 tier-from-score
- [`src/trading_firm/sessions/clock.py`](src/trading_firm/sessions/clock.py) — London-anchored session clock; DST divergence; ISO-week keys (D-6); 21:00 UTC rollover blackout (F-5)
- [`src/trading_firm/risk/`](src/trading_firm/risk/) — capital manager (§4: drawdown states, owner-approved promotions) and the risk engine (§3.3 minimum over five capacities, per-instrument margin — F-1)
- [`src/trading_firm/sizing/engine.py`](src/trading_firm/sizing/engine.py) — stop-first sizing, spread-inclusive, round-down, margin defense-in-depth
- [`src/trading_firm/audit/`](src/trading_firm/audit/) — hash-chained append-only log + SQLite/WAL migrations ([`database/migrations/`](database/migrations/))

## Phase 3 — data & strategy research framework

- [`src/trading_firm/market_data/bars.py`](src/trading_firm/market_data/bars.py) — normalization (FMP/OANDA adapters, explicit source timezones, quality events)
- [`src/trading_firm/features/engine.py`](src/trading_firm/features/engine.py) — versioned session features, no future leakage
- [`src/trading_firm/strategies/`](src/trading_firm/strategies/) — §11 manifest schema (permissions follow promotion) + london_breakout v0.1.0 rules; manifests in [`config/research/strategies/`](config/research/strategies/)
- [`src/trading_firm/research/replay.py`](src/trading_firm/research/replay.py) — session replay through the real risk/sizing engines; conservative fills; inviolate flatten
- 130 unit tests (`tests/unit/`), incl. audited golden numbers, DST-divergence dates, and exact replay P&L

## Phase 4 — broker sandbox integration

- [`src/trading_firm/execution/`](src/trading_firm/execution/) — order state machine, deterministic broker adapter (the only order-capable component: approved risk+sizing required, live transports refused, stop attached on fill, idempotent client ids, UNKNOWN resolved by query), fake broker with failure injection, practice-only OANDA transport
- [`src/trading_firm/reconciliation/`](src/trading_firm/reconciliation/) — broker-authoritative reconciler; position mismatch → HALTED, equity-only → MANAGE_ONLY (§18)
- [`tests/failure_injection/`](tests/failure_injection/) + [`tests/acceptance/`](tests/acceptance/) — §21 drills: timeouts, dropped stops, desync; no order bypasses the risk engine
- [`scripts/broker_sandbox_lifecycle.py`](scripts/broker_sandbox_lifecycle.py) — guarded 1-unit demo order lifecycle against the practice account (requires network + token)
- **157 tests total**

## Phase 5 — agent orchestration

- [`src/trading_firm/agents/schemas.py`](src/trading_firm/agents/schemas.py) — the §6.5 validation gate: agent JSON must parse through strict schemas before entering the runtime; tier adjustments are type-bounded ≤ 0 (M-1 as a type); §13 approval card with owner-facing renderer
- [`.claude/commands/pre-session-briefing.md`](.claude/commands/pre-session-briefing.md) / [`post-session-review.md`](.claude/commands/post-session-review.md) — the §14/§15 workflows over the six agents
- [`governance/model-routing-policy.md`](governance/model-routing-policy.md) — §7.4 routing; safety-critical duties never downgrade
- **171 tests total**
