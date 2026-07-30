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

**Standing owner to-dos:** extend the OANDA broker-feed fixtures backward
(Apr–Jun EUR_USD) before any new strategy research spends a §12.4 test — in
progress via a delegated session. **Cleared 2026-07-30:** OANDA network
access, the Phase 4 demo lifecycle run (6/6 PASS), OANDA practice token
rotation, the `OANDA_DEMO_API_TOKEN` repair, and FMP token rotation. No
credential exposed during setup remains in use.
