# Decision Log

Append-only. Every material decision gets a dated entry; never edit past
entries — append corrections (§0.11).

---

**2026-07-29 · Spec received and reviewed.** Master Handoff v1.0.0 received
from owner. Full design review delivered
(`docs/reviews/2026-07-29-master-handoff-v1.0.0-review.md`): 3 Critical,
8 Major, 13 Minor findings, 4 Observations. Verdict: sound architecture,
not buildable as written; amendments required before Phases 2+.

**2026-07-29 · v1.1.0 amendments drafted.** All review amendments applied to
a draft spec with recommended defaults for the seven blocking decisions.

**2026-07-29 · Owner ratified D-1…D-7.** Broker target OANDA US (D-1);
owner-approved tier promotion (D-2); deposits never advance milestones (D-3);
Exceptional retained at 10% under margin overlay (D-4); probation exit at 30
processed signals (D-5); ISO week Europe/London (D-6); FMP economics-calendar
as the allowlisted calendar source, implementer-selected at owner direction
(D-7). Draft promoted to governing v1.1.0.

**2026-07-29 · Calendar source verified (D-7 closed).** FMP calendar endpoint
verified live on the owner's upgraded plan: 508 structured events/3 days with
impact ratings. Caveat recorded: feed timestamps are unmarked UTC — pin and
test in Phase 0/2 (§10.3).

**2026-07-29 · Phase 0 broker connection audit (owner-run).** 8/8 PASS via
the read-only MCP bundle on the practice host. Findings recorded in
`docs/audits/2026-07-29-oanda-practice-connection-audit.md`:
F-1 per-instrument margin (GBP_USD 5% vs account 2%) → spec v1.1.1;
F-2 live re-audit gate before Phase 7; F-3 off-peak spreads 1.5–1.9 pips.

**2026-07-29 · F-4 recorded, then superseded by F-5.** London-window
measurement suggested near-constant synthetic spreads (v1.1.2); owner-run
falsification across the 21:00 UTC rollover and 13 daily sessions corrected
it — the feed reproduces real spread regimes including a ~10× rollover
blowout. Spec v1.1.3: practice feed usable for spread modeling; fills and
slippage require live/licensed data; 11:00 London flatten boundary declared
inviolate as rollover protection. F-4 preserved unedited in the audit record.

**2026-07-29 · Phase 1 started (owner instruction).** Deliverables per §22:
repo structure, CLAUDE.md, six agent definitions (§6 consolidated roster),
settings/permissions/hooks (§7.2–7.3), §24 config baseline with validated
schema and constitution-violation tests, governance documents, CI baseline.
Protection hook verified live during its own installation: it blocked a test
file containing a static credential-shaped string (test rewritten to build
such strings at runtime).

**2026-07-30 · Phase 2 delivered (owner instruction "continue").** Offline
deterministic core per §22: domain models (Decimal money, frozen dataclasses);
London-anchored session clock with DST-divergence handling, ISO-week keys, and
the F-5 rollover blackout; capital manager (anchor doubling, drawdown-state
machine, owner-approved pending promotions with 7-day lapse, deposit
exclusion); risk engine implementing the §3.3 minimum across tier/fraction/
session/weekly/margin capacities with per-instrument margin rates (F-1) and
the §5.3 exceptional gates; sizing engine (stop-first, spread-inclusive,
round-down, margin defense-in-depth); hash-chained audit log with tamper
detection; SQLite/WAL migration layer with the first decision-trail schema.
104 unit tests pass, including F-1 golden numbers (GBP_USD exceptional
margin-capacity $2.81 vs EUR_USD $8.22 at a 25-pip stop on $250).

**2026-07-30 · Phase 3 framework delivered (owner instruction "continue").**
Data and strategy research framework per §22: market-data normalization
(FMP/OANDA adapters, mandatory explicit source timezone, duplicate/gap/
malformed-bar quality events); versioned feature engine (session_features_v1:
Asian range, pre-London compression) with a no-future-leakage boundary test;
§11 strategy-manifest schema whose validators refuse risk permissions without
promotion, live status without a signed promotion record, and paper status
without a validation record; three research manifests (london_breakout 0.1.0
with implemented rule logic; sweep-reversal and continuation declared for the
research queue); and a historical replay engine that runs the REAL risk and
sizing engines per session with conservative same-bar-stop fills, spread
costs, and the inviolate 11:00 flatten. 130 tests pass; replay goldens
confirm a stopped trade loses exactly the approved risk after costs.
Data note: the upgraded FMP connector was unavailable this session, so
framework verification used engineered synthetic sessions; real-history
backtests await the connector or the F-4/F-5 historical tick-source decision
(Phase 3 remaining item). No validation claims are made (§12.4, §12.6).

**2026-07-30 · Phase 4 delivered (owner instruction "continue").** Broker
sandbox integration per §22, built offline against a deterministic
OANDA-v20-shaped fake broker (network to the practice host still unavailable
in this session): order state machine with enforced transitions (a fill
cannot close without the stop question answered; STOP_MISSING is a
kill-switch state); deterministic broker adapter — the only order-capable
component — which refuses unapproved risk/sizing inputs as order-path
violations, refuses live transports at construction, revalidates price
before submission (N-13), attaches the broker-held stop on fill (§0.9),
submits idempotently via deterministic client ids, and resolves UNKNOWN
timeouts by querying the broker (never blind resubmission); reconciler with
broker-authoritative fail-closed semantics (position mismatch → HALTED,
equity-only → MANAGE_ONLY); practice-only OANDA transport; failure-injection
suite (timeout before/after landing, dropped stop, rejection, desync) and
first §21 acceptance tests (no order bypasses the risk engine; no live
transport; stop always attached; no duplicates). 157 tests pass. A guarded
demo lifecycle script (scripts/broker_sandbox_lifecycle.py) awaits practice
network access. An adversarial multi-agent review of the execution code was
run; outcomes recorded in the PR.

**2026-07-30 · Phase 5 delivered (owner instruction "continue").** Agent
orchestration per §22 (the six agents themselves shipped in Phase 1): the
§6.5 machine-validation gate — pydantic schemas for context reports,
strategist assessments, CRO verdicts, §13 trade approval cards (all fields
mandatory, markdown renderer for owner notification), and post-session
reports with the §6.4 outcome taxonomy. The M-1 containment rule is now a
type constraint: TierAdjustment.adjustment ≤ 0, so an agent payload that
tries to RAISE a tier is unrepresentable and fails validation before any
code sees it. Fail-closed plumbing: a stale/missing calendar or any
freshness doubt makes news_state_known false. Briefing and post-session
review workflows added as commands; §7.4 model-routing policy recorded in
governance. 171 tests pass.

**Standing owner to-dos:** rotate the FMP and OANDA practice tokens that
passed through chat during setup; merge PR #1 to make v1.1.3 governing on
`main`; re-enable the upgraded FMP connector (or select the historical tick
source) for real-data backtesting; run scripts/broker_sandbox_lifecycle.py
once OANDA network access exists (fresh VM or locally).
