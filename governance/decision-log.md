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

**2026-07-30 · LLM-order-path tool proposed via chat; declined (iron
rule 1).** The owner pasted two JSON tool schemas into chat — an
`oanda_v20_trading_api` (GET/POST/PUT/PATCH to v20 endpoints including
order placement) and a read-only `oanda_exchange_rates_api` — and, when told
they were not registered tools, authorized their use "if usable."
Disposition: (a) chat-pasted JSON registers no tool, and this VM's egress
proxy still blocks OANDA hosts (CONNECT 403, re-verified), so neither is
usable in fact; (b) the order-capable tool is the LLM order path §0 iron
rule 1 prohibits — chat authorization cannot waive a constitutional rule
(§0/§28 require a formal spec amendment with a version bump), and the
implementer declines the LLM-order-path role regardless: the pasted schema
carries byte-identical `environment` enum values (practice and live
indistinguishable at the call site, violating the F-2 live-host
prohibition), no stopLossOnFill (§0.9), no clientExtensions (reintroducing
the duplicate-fill defect class from the 21-finding adversarial review),
and PATCH/PUT order modification; (c) the read-only rates-API authorization
is accepted prospectively — once the owner registers it as a real
connector/MCP tool it may be used for research data, subject to D-7
timezone pinning. The sanctioned route to real OANDA interaction is
unchanged: `scripts/verify_oanda_demo.py` then
`scripts/broker_sandbox_lifecycle.py` through the deterministic broker
adapter (practice host only, risk-gated, stop-attached, idempotent). No
code adopts either schema.

**2026-07-30 · Relay-handler implementation reviewed; order relay declined,
read path redirected.** Following the declined tool schemas (previous
entry), the owner supplied a Python relay handler (`handle_claude_tool_call`)
that would forward Claude-emitted OANDA calls with injected auth headers.
Review outcome: (a) non-functional as written — both URL builders produce
malformed addresses from the schema's scheme-less enum values, the
Exchange-Rates path invents an auth header for a separate paid product a
v20 token cannot access, placeholder-token fallbacks send garbage
credentials instead of failing closed, and a POST timeout after an order
lands is surfaced as a retryable error (the duplicate-position defect class
from the 21-finding review); (b) the order-relay half is the §0 iron-rule-1
LLM order path regardless of which process performs the HTTP call — the LLM
would compose and authorize, the script would blindly relay — declined, no
fix makes it acceptable; (c) the read half is already served by the shipped
read-only MCP bundle (`mcp/oanda-practice` v0.1.1: candles, pricing,
account, positions, orders-read, transactions; no order tools by design).
Gap filled instead: `scripts/fetch_oanda_candles.py`, a deterministic
read-only fixture fetcher (practice host hard-coded, no environment
parameter — live routing unrepresentable; token via env, fail-closed on
missing token or unreachable host, verified in-VM) that preserves raw
mid/ask/bid so research can use measured spreads instead of the 2-pip
assumption. Pure logic in `market_data/candle_fixture.py`, unit-tested
against canned payloads; suite 206.

**2026-07-30 · Parallel-session OANDA fetch reviewed (PR #2); not merged;
feeds cross-validated.** A fresh session (needed because this VM's egress
policy predates the owner's network change) fetched OANDA practice candles —
but it branched from pre-Phase-1 `main`, never saw the constitution, and so
produced: its own fetch script with an `OANDA_ENV=live` switch (live host
outside the broker adapter — prohibited), H1 granularity (unusable for the
M5 replay pipeline), mid-only prices (discarding the bid/ask advantage that
justified OANDA over FMP), and a conflicting file layout. Verdict: PR #2 is
not merged; close as superseded once M5 MAB fixtures are fetched onto the
governed branch via the governed script. Salvage: the data itself is
genuine — cross-validation at 247 shared timestamps puts OANDA H1 opens
within 0.2 pips median / 0.7 pips max of the FMP M5 fixture, independent
corroboration of both feeds. Lesson recorded: governance only binds
sessions that can see it — CLAUDE.md, hooks, and the governed scripts live
on the PR #1 branch, so merging PR #1 to `main` is the control that makes
every future session start constitutional. Practice token used for the
fetch passed through chat and joins the rotation list.

**2026-07-30 · Broker-feed fixtures landed; spreads measured; OANDA becomes
the canonical research feed.** An owner-directed session ran the governed
fetch script unmodified (read-only, practice host) and pushed M5 mid/ask/bid
fixtures for both pairs (July 1–29) to this branch. Measured spreads:
GBP_USD London-session median 1.90 / p95 2.10 pips — the 2.0-pip sizing
assumption is nearly exact (tail excess on a stopped trade ≈0.4%, now
measured); EUR_USD 1.60/1.70 — the flat assumption over-charges EUR;
rollover blowout to 20 pips (~10×) reproduces F-5 exactly. Feed-robustness
check (champion, identical parameters, 21 shared July sessions): 19/21
per-session agreement on both pairs, but every disagreement is a marginal
trigger flipped by sub-pip feed differences, and EUR's July net changes
SIGN between feeds (+$0.72 FMP vs −$2.26 OANDA) — feed noise exceeds any
measured edge, quantifying why nothing at this sample size is evidence
(§12.6). Decision: OANDA practice fixtures are the canonical replay feed
going forward (the venue paper/live will execute against); FMP remains the
deep-history and cross-validation source. Spread-aware replay (per-bar
bid/ask instead of the flat assumption) registered as framework work.
run_replay.py now reads both fixture formats. PR #2 closed as superseded.
Report: `reports/validation/2026-07-30-oanda-fixtures-spreads-feed-robustness.md`.

**2026-07-30 · Spread-aware replay delivered (framework work, no §12.4
spend).** Replay execution now charges measured per-bar spreads from MAB
fixtures (`SpreadSeries`, fail-closed on gaps) while sizing keeps the flat
assumption — mirroring what live would experience and surfacing realized-
vs-approved risk drift, which is now unit-tested in both directions
(±1 pip measured drift moves a $2.50 approved-risk stop to −$2.56/−$2.44).
On the July broker-feed fixtures, measured costs recover $0.21 (GBP) and
$0.33 (EUR) vs the flat assumption with zero trade-outcome changes: the
flat-spread results were cost-biased, not path-biased. The 2.0-pip sizing
assumption is retained deliberately — erring conservative on size is
correct (§3). Suite: 211. Report addendum:
`reports/validation/2026-07-30-oanda-fixtures-spreads-feed-robustness.md`.

**2026-07-30 · PR #1 merged on owner instruction ("merge them"); v1.1.3 is
governing law on `main`.** Merge commit 6645600 (merge method chosen to
preserve the full 30-commit audit trail). Everything from design review
through Phase 5 and the first real-data research cycle is now on the
default branch — which also closes the governance gap the PR #2 episode
exposed: every fresh session now inherits CLAUDE.md, the hooks, and the
constitutional schema from its first clone. `live_allowed` remains empty
everywhere; nothing in the merge changes promotion state (§12.5, §24).

**2026-07-30 · Broker-feed fixtures extended to full history; first
complete canonical-feed replay.** An owner-directed session extended the
OANDA practice fixtures to mirror FMP coverage (GBP_USD 2026-03-30→07-29,
25,337 M5 candles; EUR_USD 2026-06-08→07-29, 10,943; July files verified
as strict subsets and removed) — the fixture-extension standing item is
done. Full-sample replay on the canonical feed with measured per-bar
costs: GBP_USD 65 trades 31W/34L net −$9.02 PF 0.78 maxDD $17.06; EUR_USD
18 trades 11W/7L net +$0.67 PF 1.07. The champion's costs-eat-edge verdict
hardens on the venue's own feed, and FMP's earlier EUR optimism (PF 1.57
on 11 trades) shrinks toward noise — consistent with the feed-noise
finding. Larger GBP trade count vs FMP (65 vs 48) reflects the broker
feed's more complete session coverage. NOT validation; still below §12.6
thresholds (§0.5).

**2026-07-30 · asian_range_sweep_reversal v0.1.0 implemented; baseline
replayed (headless session, owner authorization "continue completely
headless").** The research queue's second strategy gained deterministic
rule logic (sweep 3–25 pips beyond an Asian extreme, close back inside
within 3 bars, stop beyond the sweep extreme, opposing-liquidity target;
first-guess parameters declared in the manifest before any replay). Engine
addition: entry-at-close signals start exit checks the bar after entry, so
pre-entry price action can never exit a trade. The F-1 margin overlay binds
these tighter-stop trades before the tier does — golden case: 16-pip stop
margin-capped to $1.79 approved risk, stopped trade loses exactly that.
Baseline on the canonical feed with measured costs: GBP_USD 27 trades
12W/15L net +$1.48 PF 1.11 (flatten share 22% vs the champion's 79% —
decision-driven exits); EUR_USD 3 trades in 45 sessions (no meaningful
sample at these thresholds). Single pre-declared parameter set, no
selection event → no §12.4 test spent; recorded as the strategy's single
first look. NOT validation (§12.6); status research, permissions false.
Suite: 219. Also this session: PR #3 merged after green CI; the Phase 4
practice order-lifecycle run was delegated to a fresh session
(practice-only guarded script) — its evidence will arrive on branch
claude/practice-lifecycle-evidence. Report:
`reports/validation/2026-07-30-sweep-reversal-v0.1.0-baseline.md`.

**2026-07-30 · london_continuation v0.1.0 implemented; research roster
complete (headless).** The third declared strategy gained rules built as a
one-variable experiment: identical champion mechanics plus a single
trend-alignment filter (prior London-window |net move| ≥ 20 pips, from the
new no-lookahead structure_features_v1; fail closed when no prior data).
First-guess parameters declared before any replay. Baseline on the
canonical feed with measured costs: GBP_USD 9 trades (14% of the
champion's 65 on identical data) 6W/3L net +$1.94 PF 1.72 maxDD $2.00;
EUR_USD 2 trades. 9 trades decides nothing — recorded as a registered
hypothesis (trend-aligned breakouts may be the good breakouts) and the
strategy's single first look; the GBP sample's cumulative §12.4 ledger now
reads: breakout baseline + 3 spent exit tests + sweep first look +
continuation first look. Suite: 228. Also: lifecycle attempt 1 produced no
push; attempt 2 of 2 fired ~14:18 UTC with push-evidence-first
instructions. Report:
`reports/validation/2026-07-30-london-continuation-v0.1.0-baseline.md`.

**2026-07-30 · Phase 4 practice order-lifecycle run attempted; FAILED
CLOSED (no token, no network contact).** The delegated fresh session ran
the pre-run gate (219 tests green from a clean `main` checkout) and then
checked for `OANDA_DEMO_API_TOKEN`: not set, and no untracked `.env`
present. Per the run directive no token was requested and the chat-exposed
rotation-list token was not used; the guarded script was invoked once and
refused before any network I/O (`RuntimeError: OANDA_DEMO_API_TOKEN not
set`, 2026-07-30T15:03:46Z) — 0/7 lifecycle checks reached the broker, and
the fail-closed guard itself behaved exactly as designed. Evidence:
`docs/audits/2026-07-30-practice-order-lifecycle.md` (branch
`claude/practice-lifecycle-evidence`). The standing to-do remains open;
prerequisites unchanged (rotated practice token in the environment, egress
policy allowing the practice host). ROOT CAUSE for the owner: the
environment's variables do not include `OANDA_DEMO_API_TOKEN` — adding it
(rotated value) makes the run a one-command re-fire.

**2026-07-30 · Adversarial review of the RESEARCH layer; critical fill
defect found and corrected; published tables superseded.** The research code
written headless this session was merged without peer review — so it got the
same treatment the execution layer got. A 13-agent workflow (5 independent
lenses, refutation-default verifiers) raised 21 candidate defects; 6 survived
adversarial verification, 2 were refuted, 13 lower-severity ones are recorded
unverified in the review output. CRITICAL, found independently by three
lenses: replay filled stop-order entries at the strategy's trigger price even
when the first ACTIVE bar had already OPENED beyond it. Because the Asian
range freezes at 07:30 while entries open at 08:00, every break inside that
blackout booked an unobtainable price — in 5 of 14 affected trades, a price
outside the trigger bar's entire range. Worse than the fictitious profit: the
candidate reached the risk engine carrying the TRIGGER as its entry, so
sizing measured a stop distance the trade never had and a stopped trade could
exceed approved risk — the one guarantee this framework exists to provide.
Also confirmed and fixed: session_features accepted a partially-covered Asian
window (phantom first-session trades, now fails closed §0.10); sweep_reversal
could emit a signal whose target sat BEHIND the entry, scored by replay as a
TARGET win. Fix: entry clamps to the adverse side of the trigger bar's open
(the gap fill a broker would give) and the candidate is built from that
achievable price, so the risk engine sizes reality; R-targets and the
breakeven trail anchor on the real entry. Regression tests pin both
directions and assert the risk-cap property across gap sizes — the mutation
audit had found the SHORT paths entirely untested. CORRECTED RESULTS: every
published figure moved, two changed SIGN (london_breakout EUR +$0.67 →
−$0.24; london_continuation EUR +$0.30 → −$0.70); london_breakout GBP −$9.02
→ −$11.53; continuation GBP +$1.94 → +$1.44; sweep GBP +$1.48 → +$2.05. The
exit-challenger REJECTED verdict survives and strengthens (no variant now
eligible at all). No strategy status changes — nothing was promoted on the
bad numbers — and no §12.4 test is refunded or newly spent: correcting an
already-recorded look is not a new look. Superseded reports carry pointer
banners and are preserved unedited (§0.11). Suite: 228 → 236. LESSON: the
execution layer's review yielded 21 defects and this one yielded a critical
that made losing strategies look profitable. Silent backtest optimism is more
dangerous than a crash — it is persuasive and it survives a green suite.
Adversarial review is now mandatory for RESEARCH code before any number it
produces is published, not only for order-path code. Correction:
`reports/validation/2026-07-30-CORRECTION-achievable-fills.md`.

**2026-07-30 · Second adversarial pass: 9 of 13 lower-severity findings
confirmed; denominators and data-quality blindness corrected.** The first
review left 13 claims unverified; a 10-agent refutation-default pass settled
them — 9 confirmed, 1 REFUTED (the sweep-reversal golden-number comment
reproduces exactly; no change made — recording refutations matters as much
as findings, since acting on an unverified claim is how correct code gets
"fixed" into incorrect code). No P&L figure moved; two things the tables
CLAIMED about their own evidence did. (1) Denominators counted Sunday-reopen
dates that can never produce features, inflating every rate ~19%: GBP 105 →
88, EUR 45 → 38 tradeable sessions. `tradeable_session_dates()` now derives
the denominator from whether a date's Asian window holds data, used by both
scripts. (2) The market-data quality control was structurally blind to whole
missing days — `_assemble` flagged only sub-24h gaps, so the largest class of
data loss could never fire. The committed FMP GBP fixture is missing 15
weekdays (fortnightly Mon+Tue pairs plus the week of 06-22, a fetch artifact)
and emitted ZERO events about it; the §12.4 challenger split described date
ranges ~20% more complete than its data. The detector now reports absent
weekdays and stays silent on ordinary weekends — 6 events on that fixture, 0
on the canonical OANDA fixtures, which are verified complete, so no corrected
headline number is affected. Fail-closed gaps closed: prior_session_structure
accepted a single-bar prior day as "validated structure"; at-close entries
could fill exactly AT the 10:30 cutoff, outside the §14 half-open window.
Mutation testing proved four paths unguarded — the entire SHORT side of
ExitPolicy, SHORT breakout stop-cap construction, same-bar stop priority, and
the spread-field reader — and that test_stop_never_widens asserted a bound
its own setup guaranteed (it named the §0.7 iron rule and tested nothing).
All now pinned by exact value. data/research/README.md documents the FMP
holes. Suite: 236 → 255. Correction report updated with a second-pass
section.

**2026-07-30 · Spec amended to v1.1.4 — amendment A-1 ratified by the owner:
research code is publication-gated (§12.7).** Recommended by the implementer
after the achievable-fill defect showed that a green 236-test suite can sit
on top of research code that publishes fictitious results and breaches the §3
risk cap; the owner authorized the change the same day ("i authorize you to
make the change"), which is the §28 ratification the amendment required — the
implementer proposed it and did NOT self-approve it. Substance: §12.4 gains a
review bullet; new §12.7 states (1) a publication gate — no research number
may enter a validation report, promotion record, or §12.6 evidence count
until its code paths pass adversarial review; (2) independence from the author
and a refutation-default posture; (3) minimum coverage — look-ahead, fill
realism/cost model, rule-vs-manifest fidelity, claim-vs-computation
recomputation, and mutation-tested invariants; (4) refutations recorded
alongside confirmations, because acting on an unverified claim is itself a
defect vector; (5) re-review triggered by any change to the fill model, cost
model, feature boundaries, or rule logic; (6) honest denominators and
disclosed coverage holes — a report overstating its own evidence violates
§12.4 even when every P&L figure is correct; (7) audit trail in this log.
§21 gains fill-realism and mutation-coverage test requirements. Ratification
recorded in §28.3; changelist row added to §28.1; governing pointers updated
across CLAUDE.md, README, constitution, config and source headers. Prior
versions are retained unedited — v1.1.4 is a new file, not an edit of v1.1.3
(§0.11).

**2026-07-30 · Phase 4 lifecycle attempt 2 — failed closed on a placeholder
credential; a 401-misdiagnosis defect found and fixed.** The owner reported
"Oanda token added to environment". Both `OANDA_DEMO_API_TOKEN` and
`OANDA_DEMO_ACCOUNT_ID` were indeed present — holding the literal placeholder
notation from the usage docstring (`<practice token>`-shaped, 16 chars; `<id>`,
4 chars), inspected by length and pattern only and never printed. So the
to-do's second prerequisite is still open and no token has been rotated. Its
first prerequisite is now **met**: the practice host answered an unauthenticated
probe with a genuine OANDA 401 (`Server: cloudflare`, OANDA's error schema, no
proxy `Via`), so egress works and attempt 1's "no network" condition is gone.
The attempt itself is the value: run pre-fix, it failed with **"no practice
accounts on this token"** — a rejected credential reported as a missing
account, which would send an operator to create a practice account they already
have. Root cause: `_request` preserved every HTTP error body as an ordinary
response, right for order rejections carrying `orderRejectTransaction`
(finding 5) but wrong for auth failures, so a 401 became a valid-looking empty
account list. Fixed on three fronts: (1) 401/403 now raise `BrokerAuthError`,
which subclasses `TransportFailureError` so every existing handler keeps its
fail-closed UNKNOWN routing — safe here because a rejected credential also
fails the confirmed-absent lookups `resubmit_safe` demands, so the path cannot
resubmit; (2) new `execution/credentials.py` refuses placeholders, empty and
whitespace-bearing values before any network I/O, and rules out only what is
locally impossible — judging a well-formed token stays the broker's job;
(3) the transport now honors the documented `OANDA_DEMO_ACCOUNT_ID` pin, which
it had silently ignored while always taking `accounts[0]` — a wrong-account
risk on any token holding several practice accounts. `oanda_transport.py` had
**zero** test coverage; it now has 20 tests, and all three invariants were
mutation-tested (neutering each fix fails the suite). No credential value
appears in code, tests, logs, or evidence (§0 iron rule 5). Suite: 255 → 275.
Phase 4's lifecycle run remains outstanding. Evidence appended as attempt 2 to
`docs/audits/2026-07-30-practice-order-lifecycle.md`; attempt 1 unedited
(§0.11).

**2026-07-30 · Phase 4 demo order-lifecycle test PASSED — the §22 Phase 4
deliverable is complete.** With a real token supplied, `verify_oanda_demo.py`
returned **11/11** and `broker_sandbox_lifecycle.py --confirm-demo-order`
returned **6/6** on practice account `101-001-…-001` at 17:59:07Z: a 1-unit
EUR_USD order filled (open 1.15291), the broker-held stop was confirmed active
server-side (`STOP_LOSS` id 6 at 1.14768, GTC, state PENDING) rather than held
locally (§0.9), the trade closed (1.15276, realized −0.0002 USD — the spread),
and three independent counters confirmed the account flat
(`openTradeCount`/`openPositionCount`/`pendingOrderCount` all 0). Opened and
closed within ~3s, far from the 21:00 UTC rollover (§14, F-5). **Audit F-1
re-confirmed live:** GBP_USD's per-instrument margin rate is 5% against the
account's 2%, so sizing on the account rate would oversize GBP_USD by 2.5×
(§3.2). This validates order *mechanics* only — nothing about fill quality,
edge, or §13 promotion readiness; no trade went through the §2 candidate path
and `live_allowed` stays empty everywhere.

Two things worth recording. (1) **Credential handling.**
`OANDA_DEMO_API_TOKEN` arrived holding a valid 65-char token, a space, and the
fragment `OANDA_DEMO_ACCOUNT_ID=<id>` — two settings collapsed into one value.
The preflight added earlier the same day caught it ("contains whitespace…
Nothing was sent") instead of sending a mangled header. The run used the token
extracted in-process for that command only; it was never written to disk, put
on a command line, or committed, and the variable itself still needs fixing.
No trimming heuristic was added to the scripts — silently repairing a
credential would mask exactly this paste error. Whether the supplied token is
the rotated one or the chat-exposed one cannot be determined from this side,
so the rotation to-do stays open. (2) **§17 gap closed.** The lifecycle
script printed raw broker responses, and every OANDA transaction envelope
echoes `accountID`, so an unredacted account id reached stdout and would have
entered the audit record verbatim; `verify_oanda_demo.py` has redacted since
Phase 0. The script now applies the same redaction, pinned by two tests
(scrubbed id; prices and trade ids preserved, since redaction that ate them
would make evidence unverifiable). Suite: 275 → 277. Evidence appended as
attempt 3 to `docs/audits/2026-07-30-practice-order-lifecycle.md`; attempts 1
and 2 unedited (§0.11).

**2026-07-30 · OANDA practice token rotation confirmed by the owner.** The
lifecycle evidence recorded that the supplied token could not be told apart
from the chat-exposed setup token from this side; the owner confirmed the same
day that it **is** the rotated one. So the credential that ran the Phase 4
lifecycle test is a rotated one, and the token that passed through chat during
setup is no longer in use. This closes the OANDA half of the rotation to-do;
the **FMP** token rotation is untouched by this confirmation and stays open.
Recorded as an addendum to attempt 3 rather than an edit to it — the original
statement was accurate when written (§0.11).

**2026-07-30 · Correction banners extended to name the denominator defect
(§12.7(6) applied).** The six superseded reports carried banners naming only
the achievable-fill defect, so a reader could reasonably have trusted the
`sessions` counts printed beneath them — which were inflated ~19% by
Sunday-reopen dates. Each banner now names both defects and states the honest
counts (88 GBP / 38 EUR, not 105/45) plus a pointer to the documented FMP
coverage holes. This is the first application of the newly ratified
§12.7(6): a report that overstates its own evidence violates §12.4 even where
its P&L is correct. Report bodies remain unedited — only the annotation
banners changed (§0.11).

**2026-07-30 · `OANDA_DEMO_API_TOKEN` repaired; connection audit reproduced
unassisted (11/11).** Attempt 3 recorded a reproducibility caveat: the variable
held a valid token with `OANDA_DEMO_ACCOUNT_ID=<id>` concatenated onto it, so
that run required extracting the token in-process and could not be reproduced
by simply invoking the script. The owner corrected the variable and reports
`scripts/verify_oanda_demo.py` returning **11/11, exit 0**, with no files
changed — no in-process repair, no arguments. The caveat is therefore closed
and the Phase 4 tooling is reproducible from a clean session.

Evidence provenance, stated plainly per §12.7's independence posture: attempt
3's numbers were observed directly by the implementer; **this 11/11 is
owner-reported and was not independently observed here.** The session that
found the malformed value still carries the pre-repair environment — a
container inherits its variables at start, so an environment change reaches
only newly created sessions, and re-checking from the old one returned a
byte-identical value (same length, same segment split, same digest). That is
evidence of a stale container, not of a failed repair; confirmation
necessarily came from a fresh session. The owner's report also independently
re-derives two things already in this log and in attempt 3 — F-1 (GBP_USD 5%
per-instrument vs 2% account-level; sizing on the account rate would oversize
GBP_USD by 2.5×, §3.2) and the scope limit (connectivity and account shape
only; nothing about fill quality or edge; `live_allowed` remains empty
everywhere, §12.5/§24). Both readings are correct and unchanged.

Noted for a future session, not acted on: `CLAUDE.md` and `.env.example`
describe holding tokens in an untracked `.env`, but nothing in the repo loads
one — `credentials.py` and both scripts read `os.environ` only, and there is no
dotenv dependency. An operator who follows the documented guidance literally
would still have to export the variables by hand. Either wire up `.env`
loading or reword the guidance; leaving both as they are invites exactly the
class of misconfiguration this week produced twice.

**2026-07-30 · FMP token rotated (owner-reported); credential-hygiene
to-dos closed.** The owner rotated the FMP API key that passed through chat
during D-7 setup. With the OANDA practice token rotated earlier the same day
and `OANDA_DEMO_API_TOKEN` repaired, every credential exposed during setup has
been replaced and no chat-exposed secret remains in use. Nothing in the repo
referenced either value — tokens have only ever been read from the
environment (§17) — so no code or config change was required; this entry is
the audit record (§0.6). Note for future sessions: research fetches through
the FMP connector will use the new key transparently; if a connector-backed
fetch begins returning auth errors, the rotation is the first thing to check.

**2026-07-30 · The `.env` mismatch found and closed; root cause of every
failed-closed run today.** `.env.example` instructs the owner to copy
secrets into `.env`, but nothing in the repo ever read that file — all
three credential-reading entry points call `os.environ.get` directly and
there is no dotenv dependency. A correctly filled-in `.env` therefore did
nothing, and the scripts failed closed with "token not set" while the
token sat on disk. Fixed with a dependency-free loader
(`src/trading_firm/env_file.py`) wired into `fetch_oanda_candles.py`,
`verify_oanda_demo.py`, and `broker_sandbox_lifecycle.py`. Design follows
§17 and §0 iron rule 5: the real environment always wins over the file
(exported/session values take precedence over a stale file), values are
never logged, parse errors cite a line number and never echo line content,
and an absent file is not an error — callers still fail closed. Seven unit
tests build credential-shaped values at runtime so the secret-scan hook
stays green. Suite 255 → 262. `.env` remains gitignored and unblessed:
§17 still prefers the OS keychain.

**2026-07-30 · Broker-feed fixtures now symmetric: EUR_USD extended to
2026-03-30.** EUR_USD refetched over the full span via the governed
read-only script; verified a strict superset of the 2026-06-08 file (every
candle present, values identical) before that file was removed. Both
instruments now cover 2026-03-30 → 2026-07-29 — GBP_USD 25,337 candles /
6 quality events, EUR_USD 25,343 / 1, all of them the usual Sunday ~21:00
UTC weekend-open gaps. Cross-pair research no longer has to restrict to
EUR's shorter window. The fixture-extension standing item is now fully
closed for both pairs. Spread-report postscript and coverage note updated;
no measurement is re-stated.

**2026-07-30 · Phase 4 practice order-lifecycle run PASSED 6/6 — the
standing to-do is satisfied.** With the rotated token reaching the session
environment, `scripts/broker_sandbox_lifecycle.py --confirm-demo-order`
ran once at 18:26:43Z after a green pre-run gate (262 tests, ruff clean):
account reachable, pricing fetched, 1-unit EUR_USD market order filled,
broker-held stop confirmed active and price-exact (STOP_LOSS @ 1.14760 =
bid 1.15260 − 50 pips, GTC, PENDING, bound to the opened trade), trade
closed, account flat. Evidence with account ids redacted:
`docs/audits/2026-07-30-practice-order-lifecycle.md` (Attempt 2; the
failed-closed Attempt 1 is preserved unedited per §0.11). Significance:
§0.9 stop attachment is now confirmed against the real venue rather than
the fake broker — precisely the integration truth the 21-finding
adversarial review warned unit tests against a friendly fake could not
supply. Scope is transport and order mechanics only: not a strategy trade,
no §12.4 test spent, nothing claimed about fill quality or slippage (F-5),
and the F-2 live re-audit remains a Phase 7 gate. Token hygiene: the
credential was verified by hash to differ from the one that passed through
chat; that earlier token stays on the rotation list below.

**2026-07-30 · All standing work items closed.** With the EUR_USD fixture
extension merged, every item that has appeared on this list during the build
is done: OANDA network access, the Phase 4 practice order-lifecycle run
(6/6 PASS against the real venue), OANDA practice token rotation, the
`OANDA_DEMO_API_TOKEN` repair, the `.env` loader that was the root cause of
the failed-closed runs, FMP token rotation, and symmetric broker-feed
coverage for both instruments. No credential exposed during setup remains in
use. Phases 1–5 are delivered under governing spec v1.1.4; `live_allowed` is
empty everywhere and unchanged since the first commit. The next milestone is
Phase 6 (shadow, then paper), which §22 places on the owner's trading laptop
rather than in a build session — it is owner-initiated work, not a pending
implementer task.

**2026-07-30 · Governing spec replaced: Adaptive Handoff v2.1.0 (owner
instruction; merge ratified).** The owner supplied
`CLAUDE_ADAPTIVE_TRADING_FIRM_MASTER_HANDOFF_v2.md` (v2.0.0) as the new source
of truth — a substantial upgrade making the firm opportunity-driven rather than
strategy-driven: an independent Senior Trader Alpha/Beta pair above the
specialist bench, a checksum-enforced Market State Packet, the Adaptive Trade
Thesis Schema, novelty classes N0–N3, evidence classes E0–E5 replacing the
opaque edge score, an approved feature/indicator registry, and an adaptive
policy manifest. REVIEW FINDING: v2.0.0's header reads "Supersedes: Version
1.0.0" — it was drafted from the ORIGINAL spec and therefore carried none of
the amendments ratified since. Adopting it verbatim would have silently deleted
seven protections that are enforced in code and backed by evidence. Presented
to the owner, who ratified the merge and directed governance-first sequencing.
Restored in v2.1.0, each tagged inline and registered in §29: London-anchored
session times (R: C-2 — verified that Chicago-anchored 02:00 resolves to London
07:00 on 27 calendar days in 2026, an hour before the open and inside the Asian
range window); owner-approved pending tier promotion (D-2/C-3, v2 §4.2 had
reverted to automatic); deposits never advance milestones (D-3, v2 had softened
it); per-instrument margin rate and utilization overlay (F-1); 21:00 UTC
rollover blackout and inviolate flatten (F-5); §12.6 minimum-evidence
thresholds (D-5/M-8, v2 said only "a predefined sample"); §12.7 research
publication gate (A-1, ratified hours earlier). Section numbering is otherwise
identical to v2.0.0 and aligned with v1.1.4 for §0–§26 — critically the §0
iron-rule list is unchanged in order, so all ~110 positional §0.N citations
stayed valid; only §27→§28 and §28.x→§29.x were remapped, and §12.6/§12.7 were
re-added at their original numbers so 50 existing references kept resolving.
A coupling audit found 857 §-references across 97 files, including inside the
ValueError messages 18 config validators raise for operators — with nothing
verifying any of them. `scripts/check_spec_refs.py` now fails CI on an
unresolvable reference (562 checked, all resolve); append-only historical
records are skipped by design since they cite the spec in force when written.
Pass 1 delivered: novelty/evidence permission tables as TYPE constraints
(`adaptive.py`) following the M-1 precedent — an N2 thesis with E5 evidence
still yields tier 0, unrepresentable rather than merely rejected; the Adaptive
Thesis Schema with a narrative-only rejection validator; `adaptive_trading` and
`feature_registry` config sections with seven new violation-injection cases;
and a DST regression asserting the London anchor holds on every one of the 27
divergence days. Suite 284 → 305. Pass 2 (Alpha/Beta agents, packet runtime,
Arbiter, analog engine, experiment ledger) is scoped separately. v2.0.0 is
committed verbatim (SHA-256 96633f32…) and v1.1.4 preserved unedited (§0.11).

**2026-07-30 · Return target clarified as a GOAL, not a hard deadline
(owner).** Earlier in the session the owner described the firm's mandate as a
5–6 figure return within 30–45 days, framed as existential. The implementer
answered with the arithmetic: from $250 that is a 40x–400x compound return,
requiring roughly 12–19% per session sustained; at the Exceptional tier's 10%
risk with 1.5R targets it demands a win rate above 90%, and above 100% —
literally impossible — for the 30-day case. Measured champion win rate is
48.4% with negative expectancy, and the F-1 margin overlay caps deployable
risk near $1.80 on a 16-pip stop at this equity. The owner has now clarified
the target is aspirational, not a hard constraint.

Recorded because the distinction is load-bearing for behavior, not merely
morale. A hard deadline creates pressure toward exactly the actions §3.5
prohibits — forcing setups to reach a target, increasing frequency in a quiet
session, continuing to trade because profit is below a desired amount, and
expanding risk after gains — and toward the §12.x shortcuts (skipping the
probation sample, trusting a flattering number) that the achievable-fill
defect showed are easy to fall into. With the target held as a goal, the
firm's operating posture is unchanged and unambiguous: §3.5's no-profit-target
doctrine governs, "no trade" remains a preferred outcome (§0 rule 6), and no
risk limit, evidence threshold, or promotion gate flexes for a calendar date.
No configuration or code change follows from this entry; it exists so a future
session reading the earlier framing does not infer license to trade harder.

**2026-07-30 · A-2 ratified: conviction discipline. Spec v2.1.0 -> v2.2.0
(owner).** The owner directed a refinement of the goal framing recorded in the
entry above: agents "should be encouraged to trade harder with achieving the
goal in mind when they have found an edge in sessions. Never just blindly out
of pressure of reaching a target." The implementer proposed A-2 in
`docs/design/2026-07-30-v2-pass-2-scope.md`; the owner ratified it, and set the
Pass 2 agent roster at nine files.

The design problem is that conviction-driven and pressure-driven sizing produce
the same action. They are distinguishable only by their inputs, so A-2
separates them by input class rather than by instruction. Evidence — a function
of the market: evidence and novelty class, registry feature values, analog
statistics, regime fit, execution conditions — may raise the ceiling the risk
gate considers. Firm state — a function of us: equity, elapsed days, session
and cumulative P&L, trades taken, time left in the window — may only lower it.
That reduces the owner's distinction to a property test: classification must be
a pure function of the Market State Packet, bit-identical across firm states
including one far behind any aspiration. §21 now requires it as both a unit
test and an acceptance criterion. §6A's packet mixes the two classes, so Pass 2
splits it into MarketState and FirmState under one checksum, with the
classifier signature admitting only the former — the M-1 move that made
tier-raising unrepresentable rather than merely prohibited.

The reach half was the part that needed building, because the firm's incentive
gradient was one-sided. Over-sizing is already structurally impossible: the
risk engine only ever lowers a tier, `TierAdjustment.adjustment` is
`Field(le=0)`, and `profit_target: None` is a type, so the firm cannot
represent a target and cannot compute that it is behind one. Under-sizing was
invisible — holding E5 evidence and filing E3 produced no error, no audit
anomaly, and no scored penalty, while §6.6 forbade only the mirror failure of
rewarding more trades. Free caution is not neutral; it is a systematic negative
bias on expectancy that nothing detected. A-2 scores under-classification
symmetrically with over-classification, adds a `thesis_ceiling` audit field so
the record distinguishes a gate-bound decision from a thesis-bound one, and
fences the expectation with five absolute bounds: a correct no-trade is never a
miss, a correct NOT_APPLICABLE is never a miss, uncertainty resolves downward,
scoring is post-session only (an in-session signal would itself be a pressure
input), and classification stays pressure-invariant.

Recorded explicitly because the entry above closes with the line that a future
session must not infer license to trade harder. A-2 refines that entry and does
not reverse it. It grants no permission and adds no input to the risk gate:
`risk/engine.py` is unchanged. It unlocks nothing at ratification, since all
three manifests carry `risk_permissions` false, so the route to larger size
runs through §12.5 promotion and the §12.6 thresholds and nowhere else. §3.5,
§0 rule 6, and §0 rule 7 take precedence wherever they and §6.6 appear to
conflict, and that precedence is written into the spec text rather than left to
inference. v2.2.0 tags A-2 inline in §3.5, §5.1, §6.6, §21, §25 and records it
in §29; a diff against v2.1.0 shows no provision removed from §0-§28. v2.1.0 is
preserved unedited (§0.11).

Roster decision: nine agent files, not the §6 roster of twenty-one — the
existing six rewritten against v2.2.0 plus Alpha, Beta, and the Arbiter, with
§6.4/§6.5 roles staying consolidated into Chief Quant and Context Analyst. A
deliberate deviation from the §6 letter in service of §6's own instruction to
"use the smallest number of high-quality agents that produces genuine
specialization" and not to "create agents merely to simulate a large firm".

**2026-07-30 · v2 Adoption Pass 2 delivered; adversarial review found 30
defects in 3 of 5 modules.** All twelve workstreams shipped: Market State
Packet with the A-2 market/firm split, the §6.2 independence protocol, the
Arbiter, the specialist bench and context aggregation, the historical-analog
engine, the experiment/multiple-testing ledger, the §11 adaptive policy
manifest, the A-2 classification machinery and thesis ceiling, the nine agent
files, end-to-end §21 acceptance tests, and the updated model-routing policy.
Suite 305 -> 837.

Five modules were built by parallel agents; each was paired with an independent
refutation-default reviewer. **Three of three reviewed modules came back
DEFECTIVE** — 30 findings, 4 critical, every one verified by execution or
mutation rather than asserted. Two reviewers died on an account spend limit, so
`analogs.py` and the nine agent files were reviewed directly instead; both are
sound, and `analogs.py`'s §12.7 gate is the strongest control in the codebase
(clearance requires an AdversarialReview record with reviewer != author, full
coverage, and a decision-log reference, and the formatter re-checks the record
so an `object.__setattr__` bypass of the flag still refuses).

The findings share one shape, and it is worth naming because it will recur:
**a guarantee asserted in a docstring that the code did not deliver.** A guard
matching one name and called comprehensive. An invariant comparing three
caller-supplied values to each other and called unrepresentable. A frozen model
holding a mutable dict. A holdout documented as inspected-once and enforced by
nothing. A `may_support_confirmation` property with no caller. In a codebase
where the guards ARE the product, a guard that cannot fail is the most
expensive thing in it, because it manufactures the confidence that stops anyone
looking again.

The most serious finding was against the A-2 guard itself — the control this
amendment was ratified to create. It matched the single literal `FirmSnapshot`,
and a reviewer defeated it by importing `AccountState` instead and making the
significance threshold triple when `session_realized_loss > 0`: a firm losing
money would need LESS evidence to call a result significant, and all 65 tests
stayed green. Reproduced before fixing. The guard now lives once in
`tests/a2_guard.py` over the whole firm-state vocabulary; it had been copied
into five test files, which multiplied the blind spot rather than the
protection. No live violation existed — the defect was that the guard would not
have noticed one.

Two process facts recorded because they change what "verified" means here.
`scripts/check_spec_refs.py` was **never wired into CI**, while an earlier entry
in this log claimed it "now fails CI on an unresolvable reference" — it had been
run by hand throughout. And `check_spec_refs.py` structurally cannot catch a
misattributed quote: it proves §N resolves to a real heading, not that the
section says what the code claims. That gap let `bench.py` attribute two §1
sentences to §6.3 with CI green, and it is the same shape as the six agent files
that passed CI for three spec versions while pointing at v1.1.3. Both checkers
now run in CI, and the new `scripts/check_spec_quotes.py` closes the attribution
gap — it immediately found three more misattributions in `arbiter.py` and
`bench.py`. That checker failed to catch its own motivating example twice before
it worked (a word-count threshold, then docstring quote-pairing); writing a
guard is no protection against writing it wrong.

**Nothing was unlocked.** `live_allowed` is empty, no strategy status moved, no
`risk_permissions` flag flipped, and `allowed_novelty_classes_live` is empty in
the adaptive policy manifest. A-2 granted no permission, exactly as §29.0 said:
the route to larger size runs through §12.5 promotion and the §12.6 thresholds
and nowhere else.

**Limits carried forward, not closed.** Pre-registration backdating is narrowed
— the witness clock cannot detect it on a fresh ledger, and closing it needs an
external witness. The A-2 and analog direction guards are denylists over the
vocabulary this codebase uses. The model-routing policy is not machine-enforced
and cannot be. Each is stated in the code that carries it rather than left for a
future reader to discover.

**2026-07-31 · Two parallel Telegram implementations consolidated into one
(§18/§19).** Two sessions, unable to see each other's work, built the owner
notification path twice: `notifications/` on this branch (typed §19
notification set, halt-only remote-command surface with an import-time guard,
chat-id/token shape validation, cause-separated failure diagnosis) and
`notify/` on PR #18 from a fresh container (stdlib transport with injectable
test seam, bounded deterministic retry, 4096-char truncation, secret-scrubbed
results — and the end-to-end evidence: a real message delivered, message_id=8,
HTTP 200, `docs/audits/2026-07-31-telegram-notify-e2e.md`).

Consolidated by role rather than by picking a winner. `notify/telegram.py`
keeps the transport role because it is the code the e2e evidence describes;
its transport paths are byte-identical to the verified commit. The policy
layer moved to `notify/surface.py`; the duplicate transport in
`notifications/` is deleted, because two code paths to the same API drift
apart silently and the §17 guarantees only hold on the one that is
maintained. PR #18's commit is merged into this branch unchanged, so its
authorship and evidence survive in history and GitHub will mark the PR merged
when this branch lands.

One modification to the verified module, stated rather than slipped in:
`preflight()` gains the shape checks. The transport's generic credential
check passed a bot's @username configured as the chat id — the misconfiguration
actually present in this session's environment, not a hypothetical — and a
runtime caller records the resulting 400 as a failed NotifyResult and moves
on, which is a §19 risk-halt alert dying silently. Shape validation is
pre-I/O, so the delivery evidence is unaffected.

Also carried over from the duplicate before deletion: the remedy mapping that
distinguishes an unreachable host from a bad token from a wrong destination,
added after this session's first preflight run told the operator to check
credentials for what was an egress-policy denial. It lives in the policy layer
(`remedy_for`), so the mapping can improve without touching verified transport.

The canonical verifier is `scripts/verify_telegram.py` (strict preflight,
§19 surface assertions, getMe, one real send); `verify_telegram_notify.py`
remains as a forwarding stub because the audit instructs the operator to
re-run it on the trading laptop, and an audit whose instruction dangles
teaches people to stop following audits.

**Standing owner to-dos:** none outstanding. Implementer is building v2
Adoption Pass 2 in the order set in `docs/design/2026-07-30-v2-pass-2-scope.md`
part 5 (W1 packet, W8 adaptive policy manifest, then the agent layer). Owner-side
next action remains Phase 6 shadow operation on the trading laptop when ready
(§22, §13).
Before any new strategy research, note that §12.4's multiple-testing ledger
against the GBP sample already carries a breakout baseline, three spent
exit-variant tests, and one first look each for sweep-reversal and
continuation — the clean path is post-2026-07-29 data. Research code is
publication-gated (§12.7): no number may be published until its code paths
pass an independent, refutation-default adversarial review.

**2026-07-31 · §18 Telegram notification path built and verified
end-to-end.** The owner added `api.telegram.org` to the Claude Code
environment's network allowlist and supplied `TELEGRAM_BOT_TOKEN` /
`TELEGRAM_CHAT_ID` as environment settings (a fresh session was required —
network-policy changes only reach new containers). Implemented
`src/trading_firm/notify/telegram.py`: stdlib-only, deterministic, advisory
(`send()`/`get_me()` return a result and never raise — a notification
channel must not be able to crash the process it reports on), with every
error path sanitized because Telegram's API puts the bot token in the
request URL. Credential preflight is shared with the OANDA path:
`execution/credentials.py`'s validator is now public
(`validate_credential`) so the placeholder vocabulary cannot drift between
the two. End-to-end verification **PASSED 2/2** at 2026-07-31T02:37Z —
`getMe` resolved the live bot and `sendMessage` delivered `message_id=8` to
the redacted owner chat `50…33`
(`docs/audits/2026-07-31-telegram-notify-e2e.md`). The notify package
imports no broker code and carries no order capability (§0.3); unit tests
pin fail-closed preflight, token-leak containment, the bounded
fixed-delay retry policy, truncation at Telegram's 4096-char limit, and
chat-id redaction (862 total passing). Limits stated: this validates the
channel from the remote environment, not from the trading laptop, and no
runtime caller is wired yet — incident/watchdog integration is future
work. Nothing was unlocked; `live_allowed` remains empty everywhere.

**2026-07-31 · §18 supervisor observability, deployment correctness, and
notification delivery confirmation.** The §18 supervisor was installed on the
trading laptop and reported "Installed and started" while dying on import every
60 seconds. Three independent defects made that possible, and each is now closed
by a mechanism rather than by care.

*Deployment.* The plist resolved `/usr/bin/env python3`, but launchd runs with
`PATH=/usr/bin:/bin:/usr/sbin:/sbin` — `/usr/local/bin` is absent — so it
selected the macOS system Python 3.9.6: below the §23 floor, without the
project's dependencies, and without the TLS trust store repaired on the 3.11
build. The plist now pins an absolute venv interpreter. `install.sh` gained
guards for a missing venv, an uninstalled project, and a failing runtime check
(`scripts/check_runtime.py`: Python >= 3.11 and a bare TLS handshake to the
practice host, SNI only, no credential read or transmitted). Separately,
`launchctl bootout` proved to be ASYNCHRONOUS: bootstrapping into a domain still
holding the old job fails with EIO(5), which made reinstall intermittently fail
and succeed for reasons unrelated to the change being installed. The installer
now waits for teardown and treats a rejected bootstrap as a failure.

*Observability.* `run_supervisor.py` wrote nothing on a healthy start, so the
logs could not distinguish "running" from "hung" — only a crash produced output.
`runner/liveness.py` adds a structured startup event written BEFORE the `.env`
load and config validation (a record that only exists once initialisation
succeeds cannot describe a start that never got that far), plus a heartbeat per
sleep slice. `scripts/supervisor_status.py` resolves launchd state, heartbeat
freshness, and startup counts into exactly four states — healthy, stale,
stopped, crash-looping — via a pure `diagnose()`, so every transition is tested
without launchd, a clock, or a process. The crash-loop check runs BEFORE the
running/not-running split, because a fast-respawning job is "running" at
whichever instant you look. `launchctl bootstrap` returning 0 means launchd
accepted the job, not that it survived, so the installer now polls and verifies
before claiming success.

*Notification delivery.* The startup message discarded its `NotifyResult` and
stamped a marker on ATTEMPT, recording a failed delivery as a success. The
marker is now split in two, because it was answering two questions at once: a
delivery marker written ONLY on confirmed delivery (governs dedup), and an
attempt ledger written on every outcome (governs a 300s retry interval and a
bound of 5). That split is what lets a failed delivery stay eligible for retry
while a crash loop still cannot flood — verified against the real wiring at 60
restarts with Telegram down: 5 sends, not 60. Both outcomes append to the events
log. `NotificationKind` gained `SUPERVISOR_STARTUP_HEALTH`; because §19 sets a
MINIMUM, additions are permitted but are now registered explicitly
(`SPEC_MINIMUM_KINDS` / `OPERATIONAL_KINDS`), replacing a `len() == 11` assertion
that would have been satisfied by deleting one kind and adding another.

*Owner conditions (approved 2026-07-31).* Process health and notifier health are
INDEPENDENT axes: `diagnose()` takes no notification argument, and a dead
notifier never makes a running supervisor report unhealthy. Installation may
succeed with a degraded notifier — uninstalling a genuinely running supervisor
is the wrong remedy — but prints a prominent warning naming the consequence.
Live readiness is stricter: `governance/strategy-promotion-policy.md` now
requires `supervisor_status.py --require-notify-confirmed` to exit 0 for the §25
definition of done, probation start, or any owner activation. Retry-episode
state persists on disk across restarts and resets on confirmed success, never on
process restart — an in-memory counter would reset on exactly the event it must
suppress. The previous attempt-stamped marker migrates ONCE into an explicit
`legacy_assumed_confirmation` with a finite 1-hour TTL and its own event record;
it is never represented as a delivery and does not satisfy the readiness gate.

Verification: 1041 tests passing (from 929), ruff clean, 1951 §-references
resolve, 36 attributed quotes verified. Found and fixed during the work: the two
§-checkers scanned the new in-tree `.venv` and failed on a vendored pygments
lexer, so `.venv`/`venv`/`site-packages` joined `node_modules` in `SKIP_DIRS`;
and a test fixture that patched four path constants but not a fifth wrote a
tmp-derived assumption into the repository's real `state/ops` directory, now
guarded by a fixture assertion that fails on any unredirected state path.

Scope limits, stated rather than implied: this is process supervision and
observability. No file under `config/` was touched, `live_allowed` appears
nowhere in the change, and the supervisor still cannot place an order (§0 iron
rule 1, asserted by the unchanged no-order-path acceptance test). System-level
changes made outside the repository and NOT captured here: `certifi` installed
into `/usr/local/bin/python3` and a `cert.pem` symlink created under the 3.11
framework — the manual repair is documented in `deploy/macos/README.md`, and the
installer deliberately never performs it.

**2026-07-31 · §7.2 `.env` reclassified as an owner-managed credential file;
the contradictory hook message corrected.** The §17 secret scanner told
operators that secrets "belong in the OS keychain or an untracked .env — never
in repository files" while simultaneously blocking every write to `.env`. The
guidance and the enforcement pointed in opposite directions: an owner following
the message to the letter received a hard block naming no remedy. This surfaced
in practice this session, when creating the owner's `.env` had to be handed back
to the owner as a shell command because the tool path was blocked by the very
check that recommended the destination.

The contradiction concealed a real gap. `.env` was blocked only *incidentally* —
because its contents happened to match a credential regex — not because any rule
named it. A `.env` written with a short or unusually-shaped value passed straight
through. A 12-case behavioural harness run against the pre-change hook confirms
four such holes: a benign `.env`, a benign `.env` under owner override,
`.env.local`, and a nested `deploy/.env` were all **allowed**.

The remedy deliberately does **not** exempt `.env`; it does the opposite. A new
`_is_owner_managed_env` check adds an explicit, unconditional prohibition on
`.env` and every `.env.<suffix>` variant, matched on basename so the rule holds at
any depth — mirroring how `.gitignore` already treats these paths. It is
evaluated *before* `OWNER_APPROVED_PROTECTED_EDIT` is read, so an owner approval
granted for a protected production path can never be spent unlocking a credential
file. `.env.example` remains the single writable member of the family: tracked,
value-free, and the place an agent adds a new variable name with an empty value.

Both block messages now name the remedy instead of contradicting it. Each points
at `scripts/check_env.py`, a structure-only validator reporting existence, the
expected variable set, per-variable format, git-ignore status, and file mode as
pass/fail, and never printing a value. That closes the loop the old message left
open: an agent forbidden to write the file can still confirm the file is correct.

Verification: the proposed hook passes all 12 harness cases, including the four
the current hook fails; the patch applies cleanly via `git apply --check`.
Operationally, the owner's `.env` was created manually on 2026-07-31 and
validated 8/8 — three expected variables, no extras, formats correct, git-ignored,
untracked, mode `0600`. No credential value entered the repository, any log, or
any agent-visible output at any point.

Scope limits, stated rather than implied: this changes hook *messaging* and adds
a prohibition. It unlocks nothing. No agent gains any ability to read or write a
credential, `Read(.env)` and `Read(.env.*)` remain denied in
`.claude/settings.json`, and `live_allowed` remains empty everywhere. The hook
remains fast feedback, not the security boundary — OS permissions and startup
hash verification are the enforcement layers (§7.3, §17).

**2026-07-31 · GMIS-001 ratified: the Global Market Intelligence and
Surveillance Division is adopted as amendment A-3, targeting spec v2.3.0.**
The owner uploaded an additive implementation handoff ("Global Market
Intelligence and Surveillance Division", amendment ID GMIS-001, its own
version 2.1.0) and instructed: "we made an oversight and i would like to add
these agents." The document is preserved verbatim at
`docs/spec/CLAUDE_ADDITIVE_HANDOFF_GLOBAL_MARKET_INTELLIGENCE_SURVEILLANCE_v2.1.0.md`
(SHA-256 `36e72f8e4b30b77c3bb0eebc1fe6467cf01a0a669a920010a60fa9c57be36bbe`).
It adds ten surveillance agent roles, a versioned Market State Object, a
source registry, an event/alert architecture, thesis monitoring plans, and
options-ready boundaries — everything behind `surveillance.enabled: false`,
observe-only, additive-only by its own §0.2 preservation rules.

Adoption mechanics follow the A-1/A-2 precedent exactly: one amendment, one
spec version, one new file. The document's own section numbering is never
citable from repo code — it targets a spec filename that does not exist here
and its internal §-numbers would silently mis-resolve against the governing
spec (its §4 would read as the capital-tier system), which is the precise
failure mode the two §-checkers were built to close. Its normative content
therefore lands as new section §30 of Master Handoff v2.3.0, and code cites
§30.x only. The uploaded document itself lives in `docs/spec/`, which both
checkers deliberately skip.

Owner decisions recorded this session, each asked and answered explicitly:
(1) **Roster.** All ten agents land as separate role files — asked again
after the review found that four of the ten re-split roles consolidated
into `context-analyst` on 2026-07-30; the owner confirmed. The roster
becomes nineteen, and the boundary is documented in both places:
context-analyst owns the pre-session context packet, the monitors own
intra-session surveillance. This supersedes the nine-file roster decision
by explicit owner choice, not by drift. (2) **Phone alerts are severe-only.**
Only MATERIAL and CRITICAL surveillance alerts may reach the Telegram
surface; INFO and WATCH stay in the local event log and the daily report.
(3) **Options scaffolding is prose plus asset-class-neutral fields.** No
stub modules for a broker (OANDA US, spot-FX RFED) that cannot trade
options; the reserved boundaries and the nine future options agents are
documented in §30, and a future options amendment defines everything else.
(4) **Branch.** The build lands on
`claude/add-global-market-intelligence-surveillance` with its own draft PR,
so the open supervisor PR is not silently changed by seventy-five new files.

Two conflicts were resolved against the amendment text in favour of ratified
protections, under the amendment's own instruction to adapt to the existing
architecture "without weakening its controls": the open-position
contradiction packet it places inside the senior traders' first-pass packet
is carried post-entry on the firm side instead, because A-2 makes firm state
unreachable from classification as a type constraint; and its Chicago
control-timezone framing yields to the London anchoring of C-2 — no naive
local-time string enters any immutable object, and briefing checkpoints bind
to the existing session boundaries. The Phase A audit required by the
amendment's §22 — all fifteen items — is delivered at
`docs/audits/2026-07-31-gmis-phase-a-audit.md` before any production code.

Scope limits, stated rather than implied: ratification unlocks nothing. All
surveillance flags ship false, every influence flag is false,
`live_allowed` remains empty everywhere, the Telegram command surface
remains halt-only, no new data vendor is engaged, and the live config layer
is not created — it is a protected path reserved for Phase H with owner
sign-off. Numbers produced by Phase F/G shadow and calibration runs remain
publication-gated by §12.7 before they can support any Phase H decision.

**2026-08-01 · GMIS-001 build complete: the surveillance division exists,
disabled, observe-only, on its dedicated branch.** Thirteen commits on
`claude/add-global-market-intelligence-surveillance` deliver the whole of
amendment A-3's build scope: spec v2.3.0 with §30 as the citable form; the
surveillance package (Market State Objects with checksum identity, source
and feature registries with no runtime add, the event outbox, per-component
freshness, deterministic technical surveillance with no look-ahead, source
health with the six missing-news states, alert discipline with an
unthrottleable severe class, invocation budgets, the supervisor-injected
sweep, the senior-trader packet with no field a contradiction could travel
in, unwired risk-gate preconditions, and thesis monitoring whose exit rules
are unrepresentable outside the registered vocabulary); migration 0002 with
verified backup and restore; ten agent role files taking the roster to
nineteen; and a test suite grown from 1,075 to 1,337 with the golden replay
pinning that observe-only surveillance changes no strategy result. The
amendment's own required reports bracket the work:
`docs/audits/2026-07-31-gmis-phase-a-audit.md` before any code and
`docs/audits/2026-08-01-gmis-final-implementation-report.md` after all of it.

Scope limits, stated rather than implied: nothing activated. The master
switch, every influence flag, all ingestion domains, agent invocation, and
the options scaffold remain off; the live surveillance config layer does not
exist; `live_allowed` is empty everywhere; the Telegram surface remains
halt-only with surveillance delivery gated MATERIAL-and-above; and the
recurring cost delta is zero. The next rollout step that changes any of
this requires its own documented approval (§30.12: no step may be skipped
without documented approval).
