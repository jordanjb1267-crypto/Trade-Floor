---
description: Run the post-session review workflow (§15 loop; learning-audit-director)
---

Run the post-session review for the completed session.

1. Gather the session's record: briefing file in `reports/sessions/`,
   candidates, risk decisions, orders/fills (when live phases exist),
   rejections, and no-trade outcomes. Rejected and no-trade sessions are
   first-class learning inputs (§15) — never review only trades.
2. Invoke the `learning-audit-director` agent with that record. Validate its
   output with `validate_agent_payload("post_session_report", …)`.
   Classification discipline: a profitable trade that violated process is a
   `lucky_win`; a rule-following loss is a `good_loss`. Never grade by P&L
   alone.
3. Write the validated report to `reports/sessions/YYYY-MM-DD-review.md`.
4. Queue any challenger hypotheses for the `chief-quant-validation` agent,
   each tagged with its §12.6 evidence requirement. Challengers never touch
   production configuration (§15).
5. Append material findings to `governance/decision-log.md`.
