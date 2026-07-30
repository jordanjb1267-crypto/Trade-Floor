# Claude Adaptive London-Session Trading Firm

Agent-assisted, **opportunity-driven** London-session FX trading operating
system. **LLMs recommend; deterministic code enforces** (§2, §28).

**Governing specification (source of truth):**
`docs/spec/CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.2.0.md`
All §-references in this repo point there. When this file and the spec
disagree, the spec wins.

**Current status:** Phases 1–5 delivered (governance, deterministic core,
research framework, broker sandbox, agent orchestration). Phase 4's practice
order-lifecycle run **passed on 2026-07-30** — 11/11 connection checks and 6/6
lifecycle checks against fxTrade Practice, with the broker-held stop confirmed
server-side and the account verified flat afterwards
(`docs/audits/2026-07-30-practice-order-lifecycle.md`, attempt 3). That
validates order *mechanics* only, not fill quality or edge. No trading system
is live. `live_allowed` is empty everywhere
and stays empty until the promotion process completes with owner approval
(§12.5, §24).

**The firm is market-opportunity driven, not strategy driven (v2 §1).** Two
independent Senior Traders may build a situation-specific thesis instead of
invoking a named playbook. That freedom is bounded by two classifications that
are enforced as TYPES, not conventions (`src/trading_firm/adaptive.py`):
**novelty** N0–N3 (§6.8 — N2/N3 can never place a live order; only N0 may
receive Exceptional risk) and **evidence** E0–E5 (§5.2 — a class sets a ceiling
on the tier the risk gate may consider, never an authorization of size). The
three named strategies are now a specialist bench, not the firm's mandate.

**Research code is publication-gated (§12.7, amendment A-1).** No number a
research script produces may enter a validation report, a promotion record,
or a §12.6 evidence count until the code paths producing it have passed an
independent, refutation-default adversarial review. Re-review is required
whenever the fill model, cost model, feature boundaries, or a strategy's rule
logic changes.

## Iron rules (from §0 — never weaken silently)

1. **No LLM order path.** No agent, skill, or tool may submit, modify, or
   cancel broker orders. Execution belongs to the deterministic broker
   adapter (Phase 4+), behind the deterministic risk engine.
2. **Deterministic risk gate.** Only deterministic code authorizes size and
   enforces limits. LLM-derived inputs may lower a candidate's risk tier,
   never raise it (§5.1).
3. **Fail closed.** Stale data, missing calendar, reconciliation mismatch,
   or config-integrity failure → no new entries.
4. **No recovery behavior.** Martingale, averaging down, stop widening, and
   revenge sizing are prohibited as architecture; the config schema rejects
   them (src/trading_firm/config.py).
5. **Never expose secrets.** No credentials in code, config, logs, prompts,
   or commits. Tokens live in the OS keychain or an untracked `.env`
   (see `.env.example`). The pre-write hook scans for credential patterns
   and cannot be overridden.
6. **Audit everything.** Material decisions go to `governance/decision-log.md`;
   spec changes bump the version and add a §29.1 changelist row.
7. **Ask the owner only for genuinely blocking decisions** (§0.12).

## Protected paths (owner approval required — §7.2/§7.3)

`config/live/**`, `governance/approvals/**`, `.claude/hooks/**`, and
`.claude/settings.json` are deny-listed in settings and blocked by the
pre-edit hook. Override only with explicit owner sign-off
(`OWNER_APPROVED_PROTECTED_EDIT=1`) and a decision-log entry.

## Repository map

- `docs/spec/` — governing spec (v1.0.0 verbatim + current version)
- `docs/reviews/`, `docs/audits/` — design review; Phase 0 audit evidence (F-1…F-5)
- `governance/` — constitution, risk policy, promotion policy, incident policy, decision log, approvals
- `config/` — base/research/paper/live layers + schemas; validated by `src/trading_firm/config.py`
- `src/trading_firm/` — deterministic runtime packages (Phase 2+): risk, sizing, sessions, execution, reconciliation, audit
- `tests/` — unit/integration/replay/broker_sandbox/failure_injection/acceptance
- `scripts/` — operational tooling (e.g., `verify_oanda_demo.py`)
- `mcp/oanda-practice/` — read-only OANDA practice MCP bundle (no order tools by design)
- `.claude/agents/` — the six firm agents (§6): firm-governor, chief-quant-validation, chief-risk-officer, session-strategist, context-analyst, learning-audit-director

## Development

```bash
pip install -e ".[dev]"   # or: uv pip install -e ".[dev]"
pytest                    # must pass before any commit (§7.3)
ruff check src tests scripts
```

- Python ≥3.11 (3.12 preferred, §23). Pydantic for schemas; SQLite/WAL later.
- Config changes: edit YAML + keep `tests/unit/test_config.py` green. The
  schema intentionally rejects constitution violations — do not "fix" a
  failing validator by deleting it.
- Timezones: all session logic anchors to `Europe/London` via IANA zones
  (§14, R: C-2). Never hard-code UTC offsets. America/Chicago is display-only.
- Broker: OANDA US (D-1). Practice host only until Phase 7; the live host
  never appears outside the (future) broker adapter service.
- Sizing: always use the **per-instrument** margin rate from the broker,
  never the account-level rate (§3.2, audit F-1: GBP_USD is 5%, not 2%).
- Rollover: nothing may hold or adjust positions through 21:00 UTC
  (§14, audit F-5); the 11:00 London flatten boundary is inviolate.

## Environments (§12.1)

`research` (default) → `replay` → `shadow` → `paper` → `live`.
Research code never places orders. Paper/shadow validate process and spread-
aware costs, not fill quality (§13, F-5). Live requires the §25 definition of
done, probation (§13), and owner activation.
