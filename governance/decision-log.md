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

**2026-07-30 · Adversarial review of the execution layer; 21 findings
fixed.** A multi-agent adversarial review (two independent lenses + a
refutation-default verifier) confirmed 21 defects in the Phase 4 execution
code — 5 critical, 10 major, 6 minor, 0 refuted. Highlights: the UNKNOWN
resolution path could authorize duplicate positions (pending-order lookup
404s for instantly-filled market orders); client order ids collided for
distinct same-day candidates, silently swallowing a second trade and
raising a false STOP_MISSING kill-switch; real-transport connection
failures bypassed UNKNOWN handling entirely; the fake broker diverged from
OANDA's API in exactly the code paths meant to prevent duplicates, so tests
validated shapes OANDA never sends; reconciliation skipped §18 step 4
(stop verification). All fixed in one commit with regression tests per
finding; suite grew from 171 to 194. Lesson recorded: unit tests against a
too-friendly fake prove intent, not integration truth — the live practice
lifecycle run (Phase 4 remaining item) and periodic adversarial review are
both mandatory before Phase 6.

**2026-07-30 · First real-data replay (owner re-attached the FMP
connector).** Six weeks of M5 GBPUSD/EURUSD pulled via the licensed FMP
connector; feed timestamps pinned empirically to America/New_York (D-7
discipline). 31 completed London sessions per pair replayed through the
full deterministic pipeline with untouched v0.1.0 parameters. GBP_USD:
19 trades, net −$3.97, PF 0.73. EUR_USD: 11 trades, net +$2.66, PF 1.57.
Framework findings: 24/30 trades exit FLATTENED at 11:00 (exit-logic
challenger hypothesis registered for the §12.4 multiple-testing record);
every stopped trade lost exactly the approved risk or less after costs;
the F-1 margin overlay bound as audited. 30 trades is below every §12.6
threshold — NOT validation, no promotion implications (§0.5). Report:
`reports/validation/2026-07-30-london-breakout-v0.1.0-replay.md`.

**2026-07-30 · Exit-logic challenger evaluated and REJECTED (§12.4).** The
registered hypothesis (flatten-dominated exits mean exit logic is the binding
constraint) was tested under a pre-registered protocol: three variants fixed
in advance, GBP-only, discovery/confirmation split at 2026-06-16 declared
before any replay, mechanical selection (≥20 discovery trades, expectancy>0,
max PF advances alone). Replay engine gained an ExitPolicy parameterization
(next-bar breakeven trail, stops only tighten — §0.7 widening remains
unrepresentable; unit-tested, suite now 199). Outcome: V1 (1.5R+BE@1.0R) was
bit-identical to the champion — the trail never fired usefully; V3
(1.0R+BE@0.5R) was worst; V2 (plain 1.0R target) squeaked past discovery
(PF 1.03, +$0.02/trade) then failed confirmation outright (PF 0.66,
−$0.26/trade, $2.34 worse than the champion on the identical trade set —
capping winners at 1R clipped every runner and saved no loser). Hypothesis
closed at these parameters; champion v0.1.0 stands; no v0.2.0 manifest.
Three exit-variant tests are recorded as spent against this GBP sample —
future exit research starts at test #4 or brings new data. Report:
`reports/validation/2026-07-30-exit-challenger-eval.md`.

**Standing owner to-dos:** rotate the FMP and OANDA practice tokens that
passed through chat during setup; merge PR #1 to make v1.1.3 governing on
`main`; run scripts/broker_sandbox_lifecycle.py once OANDA network access
exists (fresh VM or locally); extend the replay sample backward as FMP
history allows before any parameter research begins.
