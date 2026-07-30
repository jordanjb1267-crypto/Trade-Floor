# Trade-Floor

Working repository for the **Claude London Trading Firm** project.

- **Original specification (as reviewed):** [`docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF.md`](docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF.md) (v1.0.0, verbatim)
- **Design review of the specification:** [`docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md`](docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md) — verdict, findings (C/M/N/O), blocking owner decisions, and a v1.1.0 amendment changelist
- **Governing specification:** [`docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF_v1.1.3.md`](docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF_v1.1.3.md) — v1.0.0 with all review amendments applied; owner ratified decisions D-1–D-7 on 2026-07-29 (§28.2); v1.1.3 incorporates the practice connection audit (findings F-1 through F-5)
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
- 104 unit tests (`tests/unit/`), incl. audited golden numbers and DST-divergence dates
