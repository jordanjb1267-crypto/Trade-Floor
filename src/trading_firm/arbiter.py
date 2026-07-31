"""Market Opportunity Arbiter (§6.1 agent D) as enforceable code.

§6.1's agent D compares the two independently completed senior-trader theses
and decides whether *any* candidate deserves formal risk review. It is given
four rules and one power. Three of the four already have mechanisms elsewhere
and this module deliberately reuses them rather than re-deriving them:

- "Must not reveal Alpha's analysis to Beta or vice versa before both submit
  locked first-pass reports" — `IndependenceLedger.for_arbiter()` refuses to
  release either report until both exist (§6.2 rule 5).
- "Must distinguish independent agreement from duplicated evidence" —
  `Agreement.materially_independent` computes it from the two feature sets
  (§6.2 rule 7).
- "Cannot transform an E1 or E2 hypothesis into a high-risk live trade" —
  `EvidenceClass.max_edge_tier` maps E1 and E2 to tier 0, so the transformation
  is unrepresentable rather than merely forbidden (§5.2). This module routes its
  tier ceiling through that table and adds no second copy of it.

The fourth rule is the one with no prior mechanism, and it is the reason this
module exists:

**"Must not average two weak theses into one apparently strong thesis."**

Averaging is seductive because it feels like corroboration. Two traders both
saying "E2, long" reads as more than one trader saying it, and any code that
blends, sums, or scores the pair will quietly produce an E3 or E4 outcome from
two inputs that individually authorize nothing. §5.2 forbids that on its own
terms: an evidence class describes what the *data* supports — validation status,
analog depth, regime fit, execution conditions — and headcount is not one of
those dimensions. Agreement between two readers of the same packet adds no
analog samples and validates no rule.

So the Arbiter **selects**; it never synthesizes. The surviving thesis proceeds
with its own arbitrated class, and the invariant

    rank(arbitrated) <= max(rank(alpha), rank(beta))

is enforced in `ArbiterDecision.__post_init__`, not merely produced by the
selection path. A future caller that hand-builds an inflated decision fails to
construct one at all — the M-1 move applied to arbitration.

Agreement still earns something, but only downward and only where the spec
already priced it: §5.3 requires "independent structural confirmations are
present" before Exceptional. Two theses resting on an overlapping feature set
are one thesis counted twice (§6.2 rule 7), so they are not an independent
confirmation, and the arbitrated class is capped below E5 whenever
`independent_agreement` is false.

**Opposed directions are a no-trade, never a coin flip.** §6.1 explicitly grants
the power to reject both traders, and opposition is where it is owed. When the
two readings are materially independent, the packet genuinely supports both
directions; the firm's own evidence says the sign is undetermined, and a trade
in either direction is a coin flip whose expectancy after costs is negative,
which §5.3 requires to be positive. When the readings instead rest on the *same*
features, the disagreement is worse rather than better: identical evidence
produced opposite conclusions, so the interpretation is unstable and the class
the pair claimed is not reproducible. Both paths return no trade, with distinct
reasons, so post-session review can tell them apart.

**Pressure invariance (A-2, §5.1).** Nothing here reads firm state. The module
imports the market half of the packet and the deterministic `Classification`
built from it; the capacity-bearing half of the packet is not imported, named,
or reachable, so equity, session P&L, trades taken, or distance from any
aspiration cannot influence which thesis is selected or what class it carries.
Firm state reaches the risk gate instead, where §3.3 lets it only reduce.
`tests/unit/test_arbiter.py` pins that structurally, the way
`test_classification.py` pins it for the classifier.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from trading_firm.adaptive import AdaptiveThesis, EvidenceClass, NoveltyClass
from trading_firm.classification import Classification, classify
from trading_firm.independence import TRADERS, Agreement, IndependenceLedger
from trading_firm.packet import MarketSnapshot
from trading_firm.policy import AdaptivePolicyManifest

# Ranks are derived from each enum's declaration order — both are declared
# worst-to-best in `adaptive.py` — so there is no second copy of the §5.2 or
# §6.8 ladder here to drift out of step with the original. `test_arbiter.py`
# pins that the derived evidence order stays monotone in `max_edge_tier`, which
# is the property every comparison below relies on.
_EVIDENCE_RANK = {ev: i for i, ev in enumerate(EvidenceClass)}
_NOVELTY_RANK = {nv: i for i, nv in enumerate(NoveltyClass)}

# §5.3 lists "independent structural confirmations are present" among the gates
# that must ALL pass for Exceptional. Duplicated evidence is not a confirmation
# (§6.2 rule 7), so without it the arbitrated class stops one rung short of E5.
CONFIRMATION_REQUIRED_ABOVE = EvidenceClass.E4


def _cap(current: EvidenceClass, limit: EvidenceClass) -> EvidenceClass:
    return current if _EVIDENCE_RANK[current] <= _EVIDENCE_RANK[limit] else limit


@dataclass(frozen=True)
class ArbiterDecision:
    """One arbitration, recorded so §0.11 can reconstruct why it went that way.

    `selected` is `None` for a no-trade — the outcome §6.1 names as always
    available and §0.6 names as preferred. `alpha_evidence` and `beta_evidence`
    are the *effective* classes after the deterministic ceiling has clamped each
    trader's claim (§5.2), which is what makes the no-averaging invariant below
    a statement about evidence rather than about rhetoric.
    """

    market_id: str
    selected: AdaptiveThesis | None
    arbitrated: EvidenceClass
    alpha_evidence: EvidenceClass
    beta_evidence: EvidenceClass
    materially_independent: bool
    unresolved: tuple[str, ...]
    reasons: tuple[str, ...]

    def __post_init__(self) -> None:
        # §0.11: a frozen audit record must not hold a live mutable sequence.
        # The dataclass annotation says tuple, but a plain frozen dataclass does
        # no coercion, so a caller passing a list kept a handle it could clear
        # afterwards — emptying `reasons` on a record whose whole purpose is to
        # explain itself, and defeating the non-empty check three lines below.
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "unresolved", tuple(self.unresolved))

        if not self.reasons:
            raise ValueError(
                "an arbitration with no stated reason cannot be reviewed: the Arbiter must "
                "record why a thesis proceeds or why both were rejected (§6.1, §0.11)"
            )

        # THE §6.1 no-averaging rule, enforced on the value rather than on the
        # path that produced it. Two E2 theses cannot yield an E3 decision even
        # if a caller constructs one directly.
        best = max(self.alpha_evidence, self.beta_evidence, key=_EVIDENCE_RANK.__getitem__)
        if _EVIDENCE_RANK[self.arbitrated] > _EVIDENCE_RANK[best]:
            raise ValueError(
                f"arbitrated evidence {self.arbitrated.value} exceeds the better of the two "
                f"inputs (alpha {self.alpha_evidence.value}, beta {self.beta_evidence.value}): "
                f"the Arbiter must not average two weak theses into one apparently strong "
                f"thesis (§6.1, §5.2)"
            )

        if self.selected is None:
            if self.arbitrated is not EvidenceClass.E0:
                raise ValueError(
                    f"a no-trade arbitration carries evidence {self.arbitrated.value}: when no "
                    f"thesis proceeds the firm holds no arbitrated evidence for exposure, and "
                    f"E0 is what keeps the tier ceiling at zero (§5.2, §6.1)"
                )
            return

        trader = self.selected.trader_id
        if trader not in TRADERS:
            raise ValueError(
                f"arbitration selected {trader!r}: the independent pair is {TRADERS} and no "
                f"other author may reach the risk gate (§6.2)"
            )
        own = self.alpha_evidence if trader == "alpha" else self.beta_evidence
        if _EVIDENCE_RANK[self.arbitrated] > _EVIDENCE_RANK[own]:
            raise ValueError(
                f"arbitrated evidence {self.arbitrated.value} exceeds {trader}'s own "
                f"{own.value}: the surviving thesis is selected, never upgraded by the "
                f"opposing trader's agreement (§6.1, §6.2)"
            )

        # The checks above compare three caller-supplied values against each
        # other, which an adversarial review pointed out is mutual consistency,
        # not soundness: a caller could hand in a thesis claiming E2 alongside
        # alpha_evidence=E5 and construct an "arbitrated E5" record that no
        # evidence supports. The effective class is min(claimed, ceiling) by
        # construction in classification.py, so it can never EXCEED what the
        # thesis itself claimed — anchoring the record to the one value the
        # caller did not invent.
        claimed = self.selected.evidence_class
        if _EVIDENCE_RANK[own] > _EVIDENCE_RANK[claimed]:
            raise ValueError(
                f"{trader}'s effective evidence {own.value} exceeds what its thesis "
                f"actually claimed ({claimed.value}): an effective class is the claim after "
                f"the deterministic ceiling has clamped it, so it cannot be higher than the "
                f"claim. This record was assembled from values that do not describe the "
                f"thesis it carries (§5.2, §0.11)"
            )

    @property
    def is_no_trade(self) -> bool:
        return self.selected is None

    @property
    def selected_trader(self) -> str | None:
        return None if self.selected is None else self.selected.trader_id

    @property
    def max_edge_tier(self) -> int:
        """Tier ceiling the deterministic risk gate may consider (§5.2, §6.8).

        **This is the authoritative number. `self.selected.max_edge_tier` is
        not.** `selected` is the trader's own thesis, carrying the class it
        *claimed*; this record carries the class that survived the deterministic
        ceiling and arbitration. On a thin analog sample with both traders
        claiming E5, this property returns 0 while `selected.max_edge_tier`
        returns 4 — a consumer reaching through the record to the thesis gets
        the unclamped self-assessment and an EXCEPTIONAL ceiling for evidence
        that supports no live tier at all.

        The thesis is still exposed because the trade plan lives on it, so the
        hazard is closed downstream rather than by hiding it: `Candidate`
        carries `thesis_ceiling`, which is populated from HERE, and
        `risk/engine.py` reads only that. `test_the_unclamped_thesis_is_never_
        the_authoritative_number` pins the divergence so it stays visible.

        Mirrors `Classification.max_edge_tier` rather than reusing it, because
        the arbitrated class may sit *below* the selected trader's own and the
        tier must follow the arbitrated class. A no-trade returns 0, so a caller
        that forgets to check `selected` still fails closed (§0.10).
        """
        if self.selected is None:
            return 0
        novelty = self.selected.novelty_class
        ceiling = self.arbitrated.max_edge_tier
        if not novelty.may_receive_exceptional:
            ceiling = min(ceiling, 3)
        if not novelty.may_trade_live:
            ceiling = 0
        return ceiling

    @classmethod
    def no_trade(
        cls,
        *,
        market_id: str,
        reasons: Sequence[str],
        alpha_evidence: EvidenceClass = EvidenceClass.E0,
        beta_evidence: EvidenceClass = EvidenceClass.E0,
        materially_independent: bool = False,
        unresolved: Sequence[str] = (),
    ) -> ArbiterDecision:
        """§6.1: "may reject both traders and declare no trade" — always reachable.

        Declining must never be the expensive branch. Everything except the
        market identity and the reason defaults, so an Arbiter that distrusts
        the packet, cannot reconcile the pair, or simply sees nothing worth
        reviewing can decline in one call from any point in the workflow. §0.6
        makes that a preferred outcome, not a failure.
        """
        return cls(
            market_id=market_id,
            selected=None,
            arbitrated=EvidenceClass.E0,
            alpha_evidence=alpha_evidence,
            beta_evidence=beta_evidence,
            materially_independent=materially_independent,
            unresolved=tuple(unresolved),
            reasons=tuple(reasons),
        )


def _blocking(thesis: AdaptiveThesis, classification: Classification) -> str | None:
    """Why this thesis cannot proceed on its own, or None if it can."""
    if thesis.direction == "none":
        return f"{thesis.trader_id} recommends no trade (§0.6)"
    if classification.effective is EvidenceClass.E0:
        return (
            f"{thesis.trader_id}'s evidence classifies E0 — missing, stale, contradictory, "
            f"or malformed — which rejects outright (§5.2, §0.10)"
        )
    return None


def _unresolved(
    alpha_thesis: AdaptiveThesis,
    alpha: Classification,
    beta_thesis: AdaptiveThesis,
    beta: Classification,
) -> tuple[str, ...]:
    """Disagreements the Arbiter records rather than resolves (§6.1).

    §6.1 asks the Arbiter to "identify genuine agreement and unresolved
    disagreement". Recording the second half matters as much as the first: a
    thesis that proceeds while the adversarial reviewer disputed its evidence
    class should reach risk review carrying that dispute, not laundered of it.
    """
    items: list[str] = []
    if alpha_thesis.instrument != beta_thesis.instrument:
        items.append(
            f"instrument: alpha {alpha_thesis.instrument} vs beta {beta_thesis.instrument} (§6A)"
        )
    if alpha_thesis.direction != beta_thesis.direction:
        items.append(
            f"direction: alpha {alpha_thesis.direction} vs beta {beta_thesis.direction} (§6.1)"
        )
    if alpha.effective is not beta.effective:
        items.append(
            f"evidence class: alpha {alpha.effective.value} vs beta {beta.effective.value} (§5.2)"
        )
    if alpha.novelty is not beta.novelty:
        items.append(
            f"novelty class: alpha {alpha.novelty.value} vs beta {beta.novelty.value} (§6.8)"
        )
    return tuple(items)


def _selection_key(
    thesis: AdaptiveThesis, classification: Classification, own_features: int
) -> tuple[int, int, int, int]:
    """Deterministic ordering over two advanceable theses (higher wins).

    Ordered by what §5.2 and §6.8 actually price: how much the data supports
    (evidence class), then how validated the logic is (novelty — N0 outranks
    N1), then how much evidence this trader contributed that the other did not.
    The final element is a fixed convention, not a judgment; it exists so the
    same pair always arbitrates the same way and any systematic lean is visible
    to post-session review (§6.6) instead of being reshuffled each session.
    """
    return (
        _EVIDENCE_RANK[classification.effective],
        -_NOVELTY_RANK[classification.novelty],
        own_features,
        0 if thesis.trader_id == "alpha" else -1,
    )


def _agreement_between(alpha_thesis: AdaptiveThesis, beta_thesis: AdaptiveThesis) -> Agreement:
    """Agreement recomputed from the theses (§6.2 rule 7).

    Deliberately duplicates `IndependenceLedger.agreement()`'s rule rather than
    calling it, because `compare()` may be reached without a ledger. A test
    asserts the two agree on the same inputs, so the duplication cannot drift.
    """
    a_features = {f.feature_id for f in alpha_thesis.selected_features}
    b_features = {f.feature_id for f in beta_thesis.selected_features}
    return Agreement(
        same_direction=alpha_thesis.direction == beta_thesis.direction,
        shared_features=tuple(sorted(a_features & b_features)),
        alpha_only=tuple(sorted(a_features - b_features)),
        beta_only=tuple(sorted(b_features - a_features)),
    )


def compare(
    alpha_thesis: AdaptiveThesis,
    alpha: Classification,
    beta_thesis: AdaptiveThesis,
    beta: Classification,
    agreement: Agreement,
) -> ArbiterDecision:
    """Arbitrate two already-classified theses (§6.1).

    Takes deterministic `Classification` results rather than the traders' raw
    claims, so an over-claim has already been clamped by §5.2 before any
    comparison happens: the Arbiter weighs evidence, never persuasiveness.
    """
    if alpha_thesis.trader_id != "alpha" or beta_thesis.trader_id != "beta":
        raise ValueError(
            f"compare() received {alpha_thesis.trader_id!r} and {beta_thesis.trader_id!r}: the "
            f"independent pair is {TRADERS} in that order (§6.2)"
        )
    if alpha.market_id != beta.market_id:
        raise ValueError(
            f"alpha was classified against market {alpha.market_id} and beta against "
            f"{beta.market_id}: both senior traders must receive the exact same packet "
            f"checksum, so these two theses are not comparable (§6A, §0.10)"
        )

    # §6.2 rule 7: the Agreement is the ONLY gate between E4 and E5, so a
    # caller-supplied one is a caller-supplied Exceptional. An adversarial
    # review passed a mismatched Agreement claiming disjoint features for two
    # theses resting on the identical feature and moved the arbitrated class
    # from E4 to E5. Recomputed here from the theses this function already
    # holds; a supplied Agreement that disagrees is a bug, not a preference.
    derived = _agreement_between(alpha_thesis, beta_thesis)
    if (
        agreement.materially_independent != derived.materially_independent
        or agreement.same_direction != derived.same_direction
    ):
        raise ValueError(
            f"the supplied Agreement claims materially_independent="
            f"{agreement.materially_independent}, same_direction={agreement.same_direction}, "
            f"but the two theses give {derived.materially_independent} and "
            f"{derived.same_direction}. Agreement earns value only from materially "
            f"independent evidence, and that is a property of the theses, not an "
            f"assertion about them (§6.2 rule 7, §6.1)"
        )
    agreement = derived

    market_id = alpha.market_id
    unresolved = _unresolved(alpha_thesis, alpha, beta_thesis, beta)
    common = dict(
        market_id=market_id,
        alpha_evidence=alpha.effective,
        beta_evidence=beta.effective,
        materially_independent=agreement.materially_independent,
        unresolved=unresolved,
    )

    if alpha_thesis.instrument != beta_thesis.instrument:
        # Not a disagreement to weigh — the pair did not review the same
        # opportunity, so there is nothing to compare. Fail closed (§0.10).
        return ArbiterDecision.no_trade(
            reasons=[
                f"alpha analysed {alpha_thesis.instrument} and beta analysed "
                f"{beta_thesis.instrument}: the pair did not review the same opportunity, "
                f"so no comparison exists to arbitrate (§6A, §0.10)",
            ],
            **common,
        )

    alpha_block = _blocking(alpha_thesis, alpha)
    beta_block = _blocking(beta_thesis, beta)

    if alpha_block is not None and beta_block is not None:
        return ArbiterDecision.no_trade(
            reasons=[alpha_block, beta_block, "neither thesis is advanceable: no trade (§6.1)"],
            **common,
        )

    both_advanceable = alpha_block is None and beta_block is None
    if both_advanceable and alpha_thesis.direction != beta_thesis.direction:
        if agreement.materially_independent:
            conflict = (
                f"alpha reads {alpha_thesis.direction} and beta reads {beta_thesis.direction} "
                f"from materially independent evidence (alpha {list(agreement.alpha_only)}, "
                f"beta {list(agreement.beta_only)}): the packet supports both readings, so the "
                f"sign is undetermined rather than contested (§6.2)"
            )
        else:
            conflict = (
                f"alpha reads {alpha_thesis.direction} and beta reads {beta_thesis.direction} "
                f"from overlapping evidence {list(agreement.shared_features)}: the same "
                f"features produced opposite conclusions, so the interpretation is not "
                f"reproducible (§6.2)"
            )
        return ArbiterDecision.no_trade(
            reasons=[
                conflict,
                "both traders rejected; a directional coin flip has negative expectancy after "
                "costs, which §5.3 requires to be positive (§6.1, §0.6)",
            ],
            **common,
        )

    reasons: list[str] = []
    if beta_block is not None:
        chosen_thesis, chosen = alpha_thesis, alpha
        reasons.append(f"{beta_block}; alpha's thesis stands alone (§6.1)")
    elif alpha_block is not None:
        chosen_thesis, chosen = beta_thesis, beta
        reasons.append(f"{alpha_block}; beta's thesis stands alone (§6.1)")
    else:
        alpha_key = _selection_key(alpha_thesis, alpha, len(agreement.alpha_only))
        beta_key = _selection_key(beta_thesis, beta, len(agreement.beta_only))
        if alpha_key[:3] == beta_key[:3]:
            reasons.append(
                "alpha and beta are indistinguishable on evidence class, novelty, and "
                "independently contributed evidence; alpha is taken by fixed convention so "
                "the arbitration is reproducible and any systematic lean is visible to "
                "post-session review (§6.6)"
            )
        if alpha_key > beta_key:
            chosen_thesis, chosen = alpha_thesis, alpha
        else:
            chosen_thesis, chosen = beta_thesis, beta
        reasons.append(
            f"{chosen_thesis.trader_id}'s thesis is selected on its own merits "
            f"(alpha {alpha.effective.value}/{alpha.novelty.value}, "
            f"beta {beta.effective.value}/{beta.novelty.value}); the two are not merged (§6.1)"
        )

    # A counterpart that cannot itself advance — it declined, or its own evidence
    # classified E0 — is not a confirmation of anything, however disjoint its
    # feature set. Requiring `both_advanceable` closes that route to E5.
    corroborated = both_advanceable and agreement.independent_agreement

    arbitrated = chosen.effective
    if corroborated:
        reasons.append(
            f"both traders independently reached {chosen_thesis.direction} on materially "
            f"independent evidence (alpha {list(agreement.alpha_only)}, beta "
            f"{list(agreement.beta_only)}): corroboration is recorded, and it does not raise "
            f"the evidence class, which describes the data and not the headcount (§6.2, §5.2)"
        )
    else:
        arbitrated = _cap(arbitrated, CONFIRMATION_REQUIRED_ABOVE)
        reasons.append(
            f"no materially independent confirmation of {chosen_thesis.trader_id}'s "
            f"{chosen_thesis.direction} read (shared evidence "
            f"{list(agreement.shared_features)}): the arbitrated class may not exceed "
            f"{CONFIRMATION_REQUIRED_ABOVE.value}, because §5.3 requires independent "
            f"structural confirmations before Exceptional (§6.2)"
        )

    reasons.append(
        f"arbitrated evidence {arbitrated.value} is taken from {chosen_thesis.trader_id}'s own "
        f"classification and never from the pair (§6.1, §5.2)"
    )
    reasons.extend(chosen.reasons)

    return ArbiterDecision(
        selected=chosen_thesis,
        arbitrated=arbitrated,
        reasons=tuple(reasons),
        **common,
    )


def arbitrate(
    ledger: IndependenceLedger,
    market: MarketSnapshot,
    policy: AdaptivePolicyManifest,
) -> ArbiterDecision:
    """The §6A workflow entry point: compare the pair once both have locked.

    `for_arbiter()` is what enforces §6.2 rule 5 — it raises until both
    first-pass reports exist — so there is no ordering for this function to
    re-check and no way for it to read one trader's reasoning early.
    """
    # §6A: the pair must have analysed THIS market, not merely the same one as
    # each other. Without this the independence gates all report healthy while
    # the Arbiter re-classifies both theses against unrelated evidence.
    ledger.verify_market(market)

    alpha_report, beta_report = ledger.for_arbiter()
    agreement = ledger.agreement()

    for report in (alpha_report, beta_report):
        if report.thesis.instrument != market.instrument:
            # The packet is per-instrument (§6A). A thesis about something else
            # was not built from the evidence being arbitrated.
            return ArbiterDecision.no_trade(
                market_id=market.checksum,
                reasons=[
                    f"{report.trader_id} submitted a thesis on "
                    f"{report.thesis.instrument} against a {market.instrument} packet: the "
                    f"thesis was not built from the evidence under arbitration (§6A, §0.10)",
                ],
            )

    return compare(
        alpha_report.thesis,
        classify(alpha_report.thesis, market, policy),
        beta_report.thesis,
        classify(beta_report.thesis, market, policy),
        agreement,
    )
