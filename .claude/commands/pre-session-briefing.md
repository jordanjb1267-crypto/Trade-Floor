---
description: Run the pre-session briefing workflow (§14 BRIEFING window; §6 agents in order)
---

Run the London pre-session briefing. This workflow produces analysis and a
brief; it never places orders (§2) and never runs outside research/shadow/
paper environments without the deterministic runtime owning the session.

1. **Context** — invoke the `context-analyst` agent for today's session:
   regime classification, structured calendar events (UTC), and levels.
   Validate its JSON output with
   `trading_firm.agents.validate_agent_payload("context_report", …)`.
   If `news_state_known` is False, the briefing concludes NO TRADING —
   fail closed (§0.10); do not proceed to strategy analysis.
2. **Strategy** — for each strategy in `config/research/strategies/` with
   implemented rules, invoke the `session-strategist` agent named for that
   strategy. Validate each output as `strategist_assessment`. A no-setup
   assessment with a reason is a normal, good outcome (§0.6).
3. **Risk challenge** — pass any directional assessment to the
   `chief-risk-officer` agent. Validate as `cro_verdict`. A REJECT verdict
   ends that candidate's consideration; record the citations.
4. **Brief** — invoke `firm-governor` to consolidate. At most one candidate
   may be presented. If presented, construct the §13 `approval_card` and
   render it for the owner. State plainly when the brief is "no trade".
5. Record the briefing outcome in `reports/sessions/` as
   `YYYY-MM-DD-briefing.md` and note anything material in
   `governance/decision-log.md`.

Remember: agent output that fails schema validation is discarded, not
repaired by hand (§6.5). Tier adjustments in assessments can only lower.
