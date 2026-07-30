# Model Routing Policy (§7.4)

Cost-aware routing that never trades quality for cost on safety-critical
decisions. "Frontier" means the highest-quality Claude model available to
the owner at the time of use.

| Duty | Tier | Rationale |
|---|---|---|
| Governance changes, spec amendments, promotion decisions | **Frontier** | §7.4: safety-critical |
| Risk reviews (CRO verdicts), incident response | **Frontier** | Adversarial quality is the product |
| Architecture and production-code changes to `src/trading_firm/` | **Frontier** | Deterministic core correctness |
| Strategy validation review, overfitting diagnostics | **Frontier** | §12.4 rigor |
| Pre-session strategist/context analysis | **Mid-tier** | Bounded, schema-validated, veto-only influence (§5.1) |
| Report synthesis, session summaries | **Mid-tier** | Recoverable errors |
| Log parsing, extraction, formatting, schema conversion | **Low-cost or deterministic code** | Prefer code over any model |

Rules:

1. Downgrading a safety-critical duty to save cost is prohibited (§7.4).
2. Anything whose output enters the deterministic runtime passes schema
   validation regardless of model tier (§6.5) — routing never substitutes
   for validation.
3. Agent influence on risk is lowering-only at the type level
   (`TierAdjustment.adjustment ≤ 0`), so a cheaper model can degrade
   opportunity, never safety.
4. Revisit this table when model generations change; record changes in the
   decision log.
