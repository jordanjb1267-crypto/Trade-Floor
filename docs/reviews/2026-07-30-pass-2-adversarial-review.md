# Adversarial review — Pass 2 modules W3, W4/W5, W7

**Date:** 2026-07-30  
**Method:** refutation-default review, one independent reviewer per module, each
instructed that SOUND is the exceptional outcome. Reviewers verified findings by
execution and by mutation testing against scratch copies; the repository was not
modified during review.

**Coverage gap — stated up front.** Five modules were built; only three were
reviewed. The reviewers for `analogs.py` (W6) and the nine agent files (W9) both
died on an account spend limit before reporting. Those two modules are therefore
**unreviewed**, and under §12.7 that matters specifically for `analogs.py`, which
is research code: no number it produces may enter a validation report, a promotion
record, or a §12.6 evidence count until its code paths have passed this review.
The publication gate in that module is not a formality pending review — it is the
only thing standing in for the review that did not happen.

## Verdicts

| Module | Verdict | Critical | Major | Minor |
|---|---|---:|---:|---:|
| `agents/bench.py — specialist bench (W4, §6.3` | **DEFECTIVE** | 1 | 4 | 5 |
| `trading_firm.arbiter` | **DEFECTIVE** | 1 | 4 | 4 |
| `research.experiments` | **DEFECTIVE** | 2 | 7 | 2 |
| `research/analogs.py` (W6) | *reviewer died — unreviewed* | — | — | — |
| nine agent files (W9) | *reviewer died — unreviewed* | — | — | — |

---

## agents/bench.py — specialist bench (W4, §6.3) and context/evidence aggregation (W5, §6.4)

### 1. [CRITICAL] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** `SpecialistConsultation.declared_domain` is a caller/agent-supplied field that is never reconciled against `BENCH`, so a specialist declares, per answer, the domain that decides whether it is `in_domain` — which drives `scored`, `manufactured_signal`, `in_domain_support`, and `tier_delta`. This falsifies the module's headline claim that a specialist "has no vocabulary here for anything that could raise risk" and the `SpecialistDomain` docstring's claim that the domain is "declared up front and independently of any thesis" because "a domain declared after seeing the market would make that scoring circular". Nothing prevents exactly that.

**Verified failure.** Verified by execution. Compression tape, breakout specialist REJECTs. With `declared_domain=bench_domain('london_breakout_specialist')` (regimes compression/expansion) the round yields `tier_delta == -1`. Re-submit the identical REJECT with `declared_domain=SpecialistDomain(domain_id='london_breakout', regimes=(RegimeLabel.TREND,), description='narrowed after seeing the tape')` and the same round yields `tier_delta == 0`. The specialist neutralised its own risk reduction by editing one field of its own payload — an LLM-derived input raising the tier the deterministic gate may consider, which §5.1 forbids in that exact direction. The mirror case also works: on trend tape a breakout specialist that declares `regimes=(TREND,)` flips from `manufactured_signals == 1, scored_records == ()` to `manufactured_signals == 0, scored_records == 1`, so §6.3 bullet 4's scoring population is agent-chosen rather than a fact about the market. No test in tests/unit/test_bench.py ever passes a `declared_domain` other than `bench_domain(specialist_id)`.

### 2. [MAJOR] `/home/user/Trade-Floor/tests/unit/test_bench.py`

**Claim.** `test_the_bench_cannot_be_extended_at_runtime` is guarantee theatre. `BENCH` is genuinely a MappingProxyType, but no production code path reads it: `consult()`, `ConsultationRound.__post_init__`, `RecordedConsultation`, and `assess_relevance` never touch it, and the only reader, `bench_domain()`, is called nowhere in src/ outside its own definition — a repo-wide grep shows its only callers are the test helper. The mapping the test protects is decorative.

**Verified failure.** Verified by execution. `BENCH['scalping_specialist'] = ...` raises TypeError (test green), but `consult('t-1', market(), [SpecialistConsultation(specialist_id='scalping_specialist', declared_domain=SpecialistDomain(domain_id='scalping', regimes=(RegimeLabel.COMPRESSION,), description='invented mid-session'), thesis_id='t-1', verdict=SUPPORT, rationale='tape is tight')])` returns a round in which the invented specialist is recorded with `in_domain=True` and `scored=True`. Extending the bench is impossible; extending a *round* — the thing that actually feeds scoring and `tier_delta` — takes one dict literal. The docstring's "the bench is a fixed set under §11 promotion control, not something a session can extend" is false of every path a session uses.

### 3. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** `ContextPacket.verify_against()` checks only `market_id` and `regime`, but `ExecutionConditions.spread_pips`, `EventRiskReading.blackout_active`, `ContextPacket.analog_sample_size` and `ContextPacket.observed_at` are all restatements of values already computed in `MarketSnapshot` (`spread_pips`, `high_impact_event_active`, `analog_sample_size`, `observed_at`). They go unchecked — and they are precisely the fields that drive `blocking_conditions` (§0.10, §5.3) and, via `analog_sample_size`, the E2 cap in classification.py. The method's own error text ("an agent may not restate a computed value as something else") states the rule it enforces for one field and skips for four.

**Verified failure.** Verified by execution. A `MarketSnapshot` with `spread_pips=Decimal('9.0')`, `high_impact_event_active=True`, `analog_sample_size=3`, observed a day earlier. A `ContextPacket` bound to that exact checksum but reporting `execution.spread_pips=1.2`, `max_spread_pips=2.5`, `event_risk.blackout_active=False` with a fresh calendar, `analog_sample_size=400`, and today's `observed_at`. `verify_against(hostile)` raises nothing, `blocking_conditions == ()` and `entries_permitted is True` — the advisory context tells the agents the market is clean while the deterministic packet says the spread is 3.6x the limit and a high-impact event is live. The §6A binding the docstring claims ("context must be bound to the packet the traders received") is satisfied by a checksum that the contradicting fields are not derived from.

### 4. [MAJOR] `/home/user/Trade-Floor/tests/unit/test_bench.py`

**Claim.** `SpecialistVerdict.surfaces` and `SpecialistVerdict.counts_as_support` are dead code — grep confirms nothing in src/ reads either; `surfaced_concerns` iterates `self.rejections`/`self.qualifications` directly and `ConsultationRound.supports` calls `by_verdict(SUPPORT)`. The two tests that assert them (`test_only_risk_reducing_verdicts_surface`, `test_only_support_counts_as_support`) therefore read as guarding the support/reject asymmetry while guarding nothing that executes.

**Verified failure.** Verified by mutation against a scratch copy of src (repo untouched). Mutant: `ConsultationRound.supports` returns `tuple(r for r in self.records if r.verdict in (SUPPORT, QUALIFY))` — QUALIFY now counts as support, inverting exactly what `test_only_support_counts_as_support` reads as preventing, and contaminating `in_domain_support`, the field whose docstring says it exists "so the Arbiter can tell a domain expert's endorsement from a bystander's". Result: 82/82 pass. Second mutant: `surfaced_concerns` prepends a `SUPPORT ...` line for every support, inverting `test_only_risk_reducing_verdicts_surface`; that test still passes (other tests catch it, but not the one that claims to). Both properties can be deleted or inverted with the property tests green.

### 5. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** `RegimeReading.measures` is a mutable `dict[str, Decimal]` inside a `frozen=True` pydantic model. Pydantic's frozen flag blocks attribute rebinding but not in-place mutation, so the `_grounded_in_deterministic_measures` validator — the module's stated §6.4 enforcement that measures "must name features from the approved registry, not describe them" — holds only at construction time. Every other collection in the module (`SpecialistDomain.regimes`, `EventRiskReading.entries`, `ContextPacket.structure`) is a tuple; `measures` is the sole mutable one. It also silently makes `RegimeReading` and `ContextPacket` unhashable despite `frozen=True`.

**Verified failure.** Verified by execution. `rr = RegimeReading(regime=COMPRESSION, feature_version='session_features_v1', measures={'session_features_v1.asian_width_pips': Decimal('38')})` validates. `rr.regime = TREND` raises ValidationError (frozen works), but `rr.measures['the tape just looks tight to me'] = Decimal('1')` and `rr.measures['session_features_v1.asian_width_pips'] = Decimal('999')` both succeed, leaving the packet holding the chart prose the validator exists to reject and a fabricated indicator value (§6.4 / §1 "may not invent an indicator value that was not deterministically calculated"). This survives `ContextPacket.verify_against()`, which does not re-examine measures. `hash(rr)` raises TypeError: unhashable type: 'dict'.

### 6. [MINOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** `ConsultationRound.records` is annotated `tuple[RecordedConsultation, ...]` but `ConsultationRound` is a plain frozen dataclass with no coercion, so a `list` is accepted and stored as a list. The `__post_init__` duplicate-specialist and thesis-binding checks then run once and can be bypassed by mutating the list afterwards.

**Verified failure.** Verified by execution. `r = ConsultationRound(thesis_id='t', market_id='deadbeef', records=[rec]); r.records.append(rec)` gives a round holding the same specialist twice — `[x.specialist_id for x in r.records] == ['london_breakout_specialist', 'london_breakout_specialist']` — which is the state `__post_init__` raises "appears twice ... a repeated opinion counts as two (§6.3)" to prevent. The same append can add a record whose `consultation.thesis_id` is a different thesis, defeating the §0.11 audit binding. `hash(r)` also raises TypeError.

### 7. [MINOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** `tier_delta`'s docstring claims the value is "non-positive by construction", but the only thing making it non-positive is the literal `-1` bound to a plain module-level global. There is no `Final`, no `min(0, ...)` clamp, and no `Field(le=0)`-style bound — unlike the house idiom in agents/schemas.py, where `TierAdjustment.adjustment: int = Field(le=0)` is described as "M-1 as a type: raising is unrepresentable".

**Verified failure.** Verified by execution. `import trading_firm.agents.bench as bench; bench.REJECTION_TIER_DELTA = 2` — the property reads the global at call time, so the identical in-domain REJECT round that returned -1 now returns +2, and a specialist's rejection raises the tier the gate considers. The exhaustive `test_no_arrangement_of_verdicts_produces_a_positive_tier_delta` cannot see this because it never rebinds the constant. (The exhaustive test is otherwise sound: adding `+ sum(1 for r in self.supports if r.in_domain)` to `tier_delta` makes it and three other tests fail, so the arithmetic asymmetry itself is genuinely guarded.)

### 8. [MINOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** Three validator branches are redundant or untested. (a) `SpecialistDomain._regimes_are_unique` has no test at all. (b) `_domain_is_not_universal`'s `set(self.regimes) >= assessable` is equivalent to `==`, because `_domain_excludes_distortion` runs first and removes the only label that is not in `assessable`, so `set(self.regimes)` is always a subset. (c) `assess_relevance`'s `label is RegimeLabel.EVENT_DISTORTED` branch cannot change the `relevant` result — a validated domain can never contain EVENT_DISTORTED, so the fallthrough "outside the declared domain" branch already returns `relevant=False`; the branch only alters the reason string.

**Verified failure.** Verified by mutation on a scratch copy. Replacing `if len(set(self.regimes)) != len(self.regimes):` with `if False:` — i.e. deleting the uniqueness rule entirely — leaves all 82 tests passing, so `SpecialistDomain(domain_id='london_breakout', regimes=(COMPRESSION, COMPRESSION), ...)` becoming legal would be caught by nothing. For (c), removing the EVENT_DISTORTED branch changes only `finding.reason`, which is why `test_event_distorted_tape_makes_the_whole_bench_irrelevant` has to assert on the string rather than on behaviour.

### 9. [MINOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** Two spec quotes are attributed to the wrong section. `relevant_specialists`'s docstring says 'The bench members §6.3 says are "consulted by default" in this state', and the module docstring says §6.3 demotes the playbooks "with 'no trade quota and no automatic capital allocation'". Both quoted sentences are in §1 ("Initial specialist playbooks", spec line 73), not §6.3. §6.3 contains neither phrase.

**Verified failure.** An operator or auditor following the citation during an incident opens §6.3 and does not find the rule the code says it is implementing, which is the exact failure scripts/check_spec_refs.py was written to prevent — and the script cannot catch it, because it only verifies that §6.3 resolves to a real heading, never that the heading says what the citation claims. `python3 scripts/check_spec_refs.py` reports OK on all 1635 references.

### 10. [MINOR] `/home/user/Trade-Floor/src/trading_firm/agents/bench.py`

**Claim.** `assess_relevance()` ignores `MarketSnapshot.high_impact_event_active`, while `SpecialistDomain._domain_excludes_distortion` invokes precisely that §5.3 rationale to forbid a domain from claiming distorted tape ("§5.3 disqualifies a high-impact event from exceptional treatment for the same reason ... a specialist that claims competence there is claiming it on data no one has"). The module applies the argument to the declared domain and not to the live market. Builder-disclosed, but it is an internal inconsistency, not just an open question.

**Verified failure.** A compression-regime packet with `high_impact_event_active=True` (classification.py caps evidence at E3 for exactly this) still returns `relevant_specialists(...) == ('asian_range_sweep_reversal_specialist', 'london_breakout_specialist')`. Both are then `scored=True`, so §6.3 bullet 4's evaluation population includes tape the module's own reasoning says no playbook was validated on, and an in-domain SUPPORT there is recorded as a domain expert's endorsement rather than a manufactured signal.

---

## trading_firm.arbiter

### 1. [CRITICAL] `src/trading_firm/arbiter.py`

**Claim.** arbitrate() binds nothing between the IndependenceLedger's packet and the MarketSnapshot it re-classifies both locked theses against, so §6A's 'both senior traders receive the exact same packet checksum' is enforced only between the two traders and never between the traders and the packet actually arbitrated. The only cross-check is thesis.instrument != market.instrument. compare()'s alpha.market_id != beta.market_id guard is structurally unreachable from arbitrate() (both classify() calls receive the same object), so no market-identity check executes on the workflow path at all.

**Verified failure.** Verified empirically. Alpha and Beta lock first-pass reports against packet A (checksum 98c66f89..., 2026-07-30, regime=compression, vol=low), recorded in IndependenceLedger(packet_id=A.checksum). The orchestrator then calls arbitrate(ledger, B, policy) with an unrelated snapshot B (227a8b93..., 2026-06-01, regime=trend, vol=high) -- a refreshed or stale packet. Result: PROCEEDS, selected=alpha, arbitrated=E5, max_edge_tier=4 (EXCEPTIONAL), market_id recorded as 227a8b93... -- a packet neither trader ever saw -- and no reason string mentions 'packet' or 'checksum'. The ledger's packet_id sits unread one attribute away. §0.10 requires this to fail closed; it fails open and silently.

### 2. [MAJOR] `tests/unit/test_arbiter.py`

**Claim.** test_arbitration_is_identical_across_firm_states (TestPressureInvariance) is guarantee theatre: it cannot fail. MarketStatePacket.market returns the identical object it was constructed with, so `decide(..., packet.market)` is byte-for-byte the same call as the baseline `decide(..., snapshot)`. The FIRM_STATES dict, the FirmSnapshot construction and the MarketStatePacket wrapper are all discarded before arbitrate() is reached. The loop body is `assert f(x) == f(x)` three times, i.e. it asserts only that arbitrate is deterministic. Its failure message 'arbitration moved under firm state: {label}' is unreachable.

**Verified failure.** Proved two ways. (1) MarketStatePacket(market=snapshot, firm=f).market is snapshot -> True for all three FIRM_STATES entries, so the three loop iterations are identical invocations. (2) Mutation test: I widened arbitrate() in a scratch copy of the package to `arbitrate(ledger, market, policy, firm: object | None = None)` with a live firm-state branch reading getattr(firm, 'session_' + 'realized_loss'), i.e. a module that genuinely violates A-2. All 116 tests still pass, including this one. Only test_arbiter_module_never_references_firm_state catches the non-obfuscated variant (firm.closed_equity), and it is a literal-string denylist. The claimed A-2 property test contributes zero constraint; the module is protected by a source grep alone.

### 3. [MAJOR] `src/trading_firm/arbiter.py`

**Claim.** compare() never validates the caller-supplied Agreement against the two theses it already holds, yet Agreement.materially_independent is the sole gate between E4 and E5/EXCEPTIONAL (CONFIRMATION_REQUIRED_ABOVE). §6.2 rule 7 -- 'agreement earns value only when based on materially independent evidence' -- is therefore trusted from a free parameter. compare() holds alpha_thesis.selected_features and beta_thesis.selected_features and could recompute the sets exactly as IndependenceLedger.agreement() does (two set comprehensions), but does not.

**Verified failure.** Verified empirically. Two theses resting on the IDENTICAL single feature session_features_v1.asian_width_pips (genuinely duplicated evidence). With the honest Agreement(shared=(W,), alpha_only=(), beta_only=()) compare() correctly returns arbitrated=E4, max_edge_tier=3. With a mismatched Agreement(alpha_only=('x',), beta_only=('y',)) -- exactly what you get from a stale agreement computed before a revise(), one built from a different ledger, or one reused across candidates in a loop -- the same two duplicated theses return arbitrated=E5, max_edge_tier=4 (EXCEPTIONAL). The test file itself demonstrates the decoupling pattern: test_two_instruments_are_not_a_comparison constructs a separate ledger purely to source an Agreement.

### 4. [MAJOR] `src/trading_firm/arbiter.py`

**Claim.** The headline claim that an inflated decision is 'unrepresentable even for a caller that hand-builds one -- the M-1 idiom applied to arbitration' is false. __post_init__ compares arbitrated only against alpha_evidence/beta_evidence, which the same caller supplies; it checks the mutual consistency of three caller-chosen numbers, not the decision against any evidence. The record holds `selected`, whose evidence_class is the trader's own claim, and Classification guarantees effective = min(claimed, ceiling) <= claimed -- so `arbitrated <= selected.evidence_class` is a real invariant checkable from data the record already carries, and it is not checked.

**Verified failure.** Verified empirically. (a) ArbiterDecision(market_id='m', selected=<thesis whose evidence_class is E2>, arbitrated=E5, alpha_evidence=E5, beta_evidence=E5, materially_independent=True, unresolved=(), reasons=('looks fine',)) constructs without error and reports max_edge_tier=4. (b) The realistic trigger: Classification exposes .claimed and .effective as adjacent fields; a caller wiring alpha_evidence=alpha.claimed instead of alpha.effective on a packet with analog_sample_size=3 (deterministic ceiling E2, claimed E5) constructs an ArbiterDecision with arbitrated=E5 and max_edge_tier=4. The §5.2 clamp is fully bypassed and no validator fires.

### 5. [MAJOR] `src/trading_firm/arbiter.py`

**Claim.** ArbiterDecision re-exposes the unclamped self-assessment through identically-named properties on the object a consumer must reach for to get the thesis. The record carries `selected: AdaptiveThesis` but not the selected trader's Classification, and AdaptiveThesis.max_edge_tier / .may_trade_live compute from the trader's CLAIMED evidence_class. A consumer holding the decision has no clamped view of the thesis, and the two properties differ by name only.

**Verified failure.** Verified empirically on a packet with analog_sample_size=3 (deterministic ceiling E2) and both traders claiming E5: decision.arbitrated=E2 and decision.max_edge_tier=0 (correct, no live tier), while on the same record decision.selected.evidence_class=E5, decision.selected.max_edge_tier=4 (EXCEPTIONAL) and decision.selected.may_trade_live=True. Any downstream code that reads decision.selected.max_edge_tier -- the natural expression for 'the tier this thesis may unlock' -- gets 4 instead of 0, which is precisely the E1/E2-to-high-risk transformation §6.1 agent D is forbidden to perform. test_arbitration_weighs_clamped_evidence_not_the_claim asserts result.max_edge_tier == 0 and never touches the sibling property that returns 4.

### 6. [MINOR] `src/trading_firm/arbiter.py`

**Claim.** __post_init__ enforces that reasons is non-empty but never coerces or type-checks it, so the frozen §0.11 audit record can hold a live mutable list. Only no_trade() and compare() apply tuple(); the public constructor does not. The declared annotation is tuple[str, ...].

**Verified failure.** Verified empirically. ArbiterDecision(market_id='m', selected=None, arbitrated=E0, alpha_evidence=E0, beta_evidence=E0, materially_independent=False, unresolved=[], reasons=['declined']) constructs, then decision.reasons.clear() leaves reasons == [] on a frozen record -- defeating at runtime the exact no-empty-reasons check __post_init__ performed at construction, and breaking §0.11's 'immutable audit trail'. Separately, reasons='declined' (a bare str) is truthy, passes the check, and then iterates as individual characters in every `any(... for r in result.reasons)` consumer.

### 7. [MINOR] `tests/unit/test_arbiter.py`

**Claim.** The selection tie-break is unpinned and its deciding factor is absent from the recorded reasons. Mutation testing: replacing _selection_key's third element (own_features) with a constant kills ZERO tests, and inverting the alpha/beta convention from `0 if alpha else -1` to `-1 if alpha else 0` -- so beta wins every tie -- also kills ZERO tests. No test asserts alpha wins a symmetric tie, and no test asserts the 'fixed convention ... visible to post-session review (§6.6)' reason string is ever emitted, so the §6.6 detectability mechanism the builder describes as the justification for the convention is entirely untested.

**Verified failure.** Verified empirically. alpha cites [asian_width_pips], beta cites [compression_ratio, asian_high]; both classify E3/N0. alpha_only=1 vs beta_only=2, so the third key element alone selects beta. The recorded reasons contain only: "beta's thesis is selected on its own merits (alpha E3/N0, beta E3/N0); the two are not merged (§6.1)" -- a statement that shows the two as identical on both dimensions it names and gives no ground for preferring beta. Post-session review (§0.11, §6.6) cannot reconstruct why beta won. It also creates an unstated incentive for a Senior Trader to pad selected_features with marginal approved-registry features to win every tie, which no §6.6 scoring rule covers.

### 8. [MINOR] `src/trading_firm/arbiter.py`

**Claim.** Dead validator branch and subsumed conditions. (1) ArbiterDecision.__post_init__'s `if trader not in TRADERS` can never execute: AdaptiveThesis.trader_id carries pattern=r'^(alpha|beta)$', so no AdaptiveThesis can hold another id (confirmed -- pydantic ValidationError on trader_id='gamma'). (2) At `corroborated = both_advanceable and agreement.independent_agreement`, the same_direction conjunct inside independent_agreement is already subsumed: both_advanceable implies neither direction is 'none', and the opposed-direction branch above has already returned no_trade for unequal directions. (3) compare()'s alpha.market_id != beta.market_id raise and its instrument-mismatch branch are both unreachable from arbitrate().

**Verified failure.** No runtime failure -- these are unreachable paths, so the error messages they carry can never be seen during an incident. The cost is that the §6.2 'no other author may reach the risk gate' guard reads as an active control while contributing nothing, and item (3) means the module's advertised §6A same-checksum enforcement never runs on the workflow entry path (see the critical finding above); the only route to those checks is a direct compare() call, which the workflow does not make.

### 9. [MINOR] `src/trading_firm/arbiter.py`

**Claim.** arbitrate()'s instrument-mismatch no-trade discards evidence it already computed. It calls ArbiterDecision.no_trade(market_id=..., reasons=[...]) and takes the defaults, so alpha_evidence/beta_evidence record E0 (not the traders' actual effective classes), materially_independent records False regardless of the agreement it computed one line earlier, and unresolved is () even though _unresolved() would have recorded the instrument disagreement.

**Verified failure.** Alpha and Beta both submit EUR_USD theses against a GBP_USD packet. arbitrate() returns a no-trade whose record states alpha_evidence=E0, beta_evidence=E0 and materially_independent=False -- three assertions that are not true of the session -- so post-session review (§0.11) reading the audit trail concludes the pair held no evidence and did not reach independent agreement, when in fact neither was assessed. The same condition routed through compare() produces the richer record via **common, so two paths to the same rejection leave materially different audit trails. No test asserts the unresolved content on either path (mutating _unresolved's instrument branch to a no-op kills zero tests).

---

## research.experiments

### 1. [CRITICAL] `/home/user/Trade-Floor/tests/unit/test_experiments.py`

**Claim.** The three TestPressureInvariance tests are name-matching on the single literal string "FirmSnapshot"; the full 65-test suite passes green with a live A-2 violation inside required_p_value(). The behavioural test test_the_correction_depends_only_on_the_trial_count (line 812) compares two ledgers built by the identical call spent_gbp_ledger() with nothing varied, so it cannot fail for any deterministic implementation. The reference idiom it was supposed to copy, tests/unit/test_classification.py::test_classification_is_bit_identical_across_firm_states, quantifies over five distinct FirmSnapshot states — the only one of the three guards that constrains behaviour — and was not carried over.

**Verified failure.** Proven by mutation (caches cleared, -B): add `from trading_firm.models import AccountState`, a `self.account` attribute, and `if self.account is not None and self.account.session_realized_loss > Decimal('0'): a = a * Decimal('3')` to required_p_value. Result: with a calm firm the bar is 0.05, with session_realized_loss=$40 it is 0.15 — the significance bar triples because the firm is losing, the exact pressure-driven behaviour A-2 forbids — and `pytest tests/unit/test_experiments.py` reports 65 passed. The import guard misses it (module name is trading_firm.models, not *packet*; identifier is AccountState, not FirmSnapshot), the signature guard misses it (firm state arrives as an attribute, not a parameter named equity/account), and the invariance test misses it because both its ledgers are identical.

### 2. [CRITICAL] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** The headline claim — "pre-registration is a witnessed fact, not a field a caller can assert" — is false. The add() provenance guard (line 393) fires only on records that arrive already-completed; a caller reaches the same end state in two ordinary calls with no provenance at all. register() also accepts any caller-supplied registered_at with no clock check.

**Verified failure.** A researcher who has already seen p=0.002 on 2026-08-02 calls ledger.register('h','...',sample,'profit_factor', datetime(2026,7,1,tzinfo=UTC)) then ledger.record_result('h', SUPPORTED, datetime(2026,8,2,tzinfo=UTC), p_value=Decimal('0.002')). Verified output: registration=pre_registered, provenance=None, registered_at=2026-07-01. The same works through add() of a PENDING PRE_REGISTERED Experiment (no provenance demanded because outcome does not consume the sample) followed by record_result — verified with registered_at=1999-01-01. register() also accepted registered_at=2099-01-01. publication_table() then prints the record as '[pre_registered]', indistinguishable from a genuine one, and test_a_completed_pre_registered_record_added_directly_must_cite_its_proof asserts this is impossible while only covering the one-step path.

### 3. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** benjamini_hochberg() computes m as the count of experiments carrying a p-value, discarding variants_tested entirely, while its docstring states that unscored experiments' "multiplicity is not lost". Every variant of a selection event is invisible to the FDR family the same ledger just counted for Bonferroni.

**Verified failure.** Record a 19-variant sweep reporting p=0.02 plus one other test at p=0.04 against one sample. Verified: tests_recorded=20 and bonferroni_threshold=0.0025, but benjamini_hochberg returns m=2 with critical values 0.025 and 0.05 and declares BOTH significant — the 19-variant sweep is called a discovery against a bar 8x looser than the family the ledger itself recorded one line earlier. A screening report generated from this promotes the sweep to a confirmation sample on the strength of pure selection.

### 4. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** alpha and resolution_floor are plain writable public attributes (lines 321-322) while publication_cleared was deliberately made read-only. _alpha() re-validates only 0<alpha<1 on read; the constructor's floor<alpha invariant is never re-checked, so both can be loosened after construction with a single assignment and no audit record.

**Verified failure.** After six spent tests, `ledger.alpha = Decimal('0.9')` makes required_p_value return 0.1285… — a 'corrected' threshold looser than the uncorrected 0.05 — with no error. `ledger.resolution_floor = Decimal('0')` permanently disables the floor exhaustion branch: verified at 60 recorded tests the status carries no resolution-floor reason, and the ledger then reports floor=0 with alpha=0.05, a state the constructor exists to reject. Both verified by direct attribute assignment.

### 5. [MAJOR] `/home/user/Trade-Floor/tests/unit/test_experiments.py`

**Claim.** Guarantee theatre: test_a_recorded_result_keeps_the_registration_class_it_was_filed_under (line 340) exercises only the PRE_REGISTERED→PRE_REGISTERED direction, which is safe by construction. The dangerous direction — record_result upgrading a POST_HOC record to PRE_REGISTERED — is asserted nowhere, and the builder cites this carry-over as a load-bearing integrity property.

**Verified failure.** Mutation M20 (verified with __pycache__ cleared and python -B): replace `registration=existing.registration` with `registration=Registration.PRE_REGISTERED` in record_result (line 471). Every one of the 65 tests still passes. The bug is reachable in the real API: record_post_hoc(..., outcome=PENDING) or add() of a POST_HOC PENDING Experiment produces a post-hoc record that record_result will accept, so under the mutation a hypothesis fitted after the fact is stamped pre-registered and no test objects.

### 6. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** §12.4's immutable holdout — "Immutable holdout periods that Senior Trader and research agents cannot inspect during development" — is modelled as an advisory status flag. Nothing in add(), record_result(), or record_post_hoc() consults status() or assert_not_exhausted(), so 'inspected once, ever' (line 99) is enforced at no write path, while the strictly weaker provenance rule IS hard-enforced in the same method.

**Verified failure.** Declare a Sample with role=SampleRole.HOLDOUT, then call record_post_hoc five times with p_values. Verified: all five writes are accepted, tests_recorded reaches 5. A researcher who never calls assert_not_exhausted mines the holdout until something clears, and the ledger's own record shows five inspections of a sample that answers one question once. test_an_immutable_holdout_is_exhausted_by_its_first_inspection only checks status()/assert_not_exhausted, never that a second write is refused.

### 7. [MAJOR] `/home/user/Trade-Floor/tests/unit/test_experiments.py`

**Claim.** The seeded exemplar declares an arithmetically impossible honest denominator and discloses the wrong coverage hole, and Sample has no validator that could catch either. gbp_sample() (line 53) declares first_session=2026-06-04, last_session=2026-07-15, sessions=31; that range contains only 30 weekdays, so 31 London sessions cannot have occurred in it. known_coverage_holes lists a timezone-pinning note — a provenance fact, not a coverage hole — and omits the one governance/decision-log.md records: the committed FMP GBP fixture 'is missing 15 weekdays … the §12.4 challenger split described date ranges ~20% more complete than its data'.

**Verified failure.** Sample's only honesty validator is _dates_ordered; nothing relates `sessions` to its own range. Verified: Sample(first_session=2026-06-04, last_session=2026-06-05, sessions=500) is accepted. test_a_cleared_table_states_its_own_denominator_and_trial_count then pins 'sessions capable of producing features: 31' and 'America/New_York' as the module's worked example of §12.7 requirement 6 — so the one demonstration of an honest denominator overstates its sample by at least one impossible session and hides the firm's largest documented data hole, which is the precise failure §12.7(6) was ratified to stop (decision-log entry 'Correction banners extended to name the denominator defect').

### 8. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** Registration.may_support_confirmation (line 113) has no caller anywhere in src/ or scripts/ — grep confirms it is referenced only by its own definition and by tests. §12.4's 'Pre-registered hypothesis or experiment record before confirmation testing' is therefore enforced by nothing: SampleRole.CONFIRMATION is a label the ledger never checks against a record's registration class.

**Verified failure.** Declare a Sample with role=SampleRole.CONFIRMATION and call record_post_hoc(..., outcome=SUPPORTED, p_value=Decimal('0.001')). Verified: the write is accepted, registration=post_hoc, may_support_confirmation=False, status().reasons==() and exhausted=False. A post-hoc hypothesis is thus recorded as the confirmation of itself against the confirmation sample, publication_table() renders it with no annotation, and the predicate written to prevent exactly this is never consulted.

### 9. [MAJOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** The ledger's headline number contradicts the only governance record on the subject, and the type system cannot express the governance category. governance/decision-log.md (2026-07-30, sweep-reversal entry) states 'Single pre-declared parameter set, no selection event → no §12.4 test spent'; the continuation entry enumerates the family as 'breakout baseline + 3 spent exit tests + sweep first look + continuation first look', calling only the exit variants spent. The ledger charges 1 for each first look and reports 6.

**Verified failure.** There is no representable 'executed look that spends no test'. Verified: filing the sweep-reversal look as PENDING is accepted but silently drops tested_at to None, so the ledger records an interrogation of the sample as never-run and loses the §0.11 audit fact; filing it as ABANDONED is rejected by _outcome_matches_evidence. An operator honouring the decision log must therefore either lie about the outcome or accept a count the log contradicts. test_the_seventh_test_must_clear_alpha_over_seven pins required_p_value=0.05/7≈0.00714 as a claim, while governance's own enumeration supports 0.05/4=0.0125 — a 1.75x difference in the bar a promotion must clear, asserted in a test before any governance ruling exists.

### 10. [MINOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** The two exhaustion criteria disagree on which test they describe and use inconsistent, untested boundaries. next_test_threshold looks forward (m+1, line 661) while expected_false_positives looks backward (m, line 662); exhausted mixes them. assert_not_exhausted is documented as failing closed 'before spending a test on a sample that cannot pay out' but permits the very test the module docstring names as expected-spurious.

**Verified failure.** Verified at m=19: expected_false_positives=0.95, exhausted=False, assert_not_exhausted returns cleanly — so the 20th test proceeds; only afterwards (m=20, expected 1.00) does the ledger say 'this sample can no longer distinguish an edge from a coincidence'. The refusal arrives one test too late, after the result is already in hand. Boundary conventions also disagree (expected_fp >= 1 inclusive vs next_threshold < floor exclusive), and mutation M5 flipping the floor comparison from < to <= survives all 65 tests, so neither boundary is pinned by any test.

### 11. [MINOR] `/home/user/Trade-Floor/src/trading_firm/research/experiments.py`

**Claim.** Experiment.p_value is typed Decimal but pydantic silently coerces a float, so a p-value computed in float arithmetic enters the ledger carrying binary-representation noise into an exact Decimal comparison against a BH critical value.

**Verified failure.** Experiment(..., p_value=0.1+0.2) is accepted and stores Decimal('0.30000000000000004'). A caller computing p = 1 - cdf in float and landing exactly on a critical value (e.g. rank/m*alpha == 0.03) can be declared non-significant by 1e-17 while the true value clears. Nothing in the model rejects a float, and no test covers float input.

