# Constitution

The firm's constitution is the governing specification:
**`docs/spec/CLAUDE_LONDON_TRADING_FIRM_MASTER_HANDOFF_v1.1.3.md`**.
This file is a pointer and amendment ledger, not a restatement — one source
of truth, no divergence.

## Binding principles (§0, §27)

1. LLMs research, evaluate, and recommend. Only deterministic code
   authorizes size, enforces limits, and submits orders.
2. Fail closed on uncertainty of any kind.
3. Broker-held stops are mandatory on every live position.
4. No recovery behavior — martingale, averaging down, stop widening, and
   risk escalation after losses are prohibited as architecture.
5. No profit target; "no trade" is a preferred outcome.
6. Immutable audit trail for every material decision.
7. No unilateral production changes; tier promotions and live permissions
   require explicit owner approval (D-2, §12.5).

## Amendment process

A spec change requires: a version bump, a row in the spec's §28.1
changelist, a dated entry in `governance/decision-log.md`, and — for any
change that weakens a control or grants a permission — explicit owner
approval recorded in `governance/approvals/`. Corrections driven by audit
evidence follow the same path (see v1.1.1–v1.1.3 for worked examples,
including a superseded finding preserved unedited per §0.11).

## Version lineage

| Version | Date | Nature |
|---|---|---|
| v1.0.0 | 2026-07-29 | Original handoff (preserved verbatim in `docs/spec/`) |
| v1.1.0 | 2026-07-29 | Design-review amendments (C-1…O-4) |
| v1.1.0 ratified | 2026-07-29 | Owner ratified decisions D-1…D-7 |
| v1.1.1 | 2026-07-29 | Audit F-1: per-instrument margin rates govern sizing |
| v1.1.2 | 2026-07-29 | Audit F-4 (later superseded) |
| v1.1.3 | 2026-07-29 | Audit F-5 corrects F-4; rollover hazard codified |
