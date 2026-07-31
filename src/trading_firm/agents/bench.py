"""Specialist bench (§6.3) and the context/evidence aggregation (§6.4).

Two workstreams that share one governing idea, so they share one module.

**The bench (§6.3).** In v1 the three named strategies *were* the firm: a
session either produced a london_breakout, an asian_range_sweep_reversal, or a
london_continuation candidate, or it produced nothing. v2 §1 makes the firm
market-opportunity driven, and §6.3 demotes those three from mandate to bench —
"experts but no longer define the firm's boundaries". §1 is where the firm says
they receive "no trade quota and no automatic capital allocation" — quoted from
§1 rather than §6.3, because an auditor following a citation during an incident
must find the sentence where the code says it is. `check_spec_refs.py` verifies
that §6.3 resolves to a real heading; it cannot verify that §6.3 says this.
The operating rule is four bullets:

1. a specialist may support, reject, or qualify a senior-trader thesis;
2. a specialist may not force the firm to trade its playbook;
3. an irrelevant specialist returns ``NOT_APPLICABLE`` rather than manufacturing
   a signal;
4. specialist performance is evaluated only on opportunities inside its
   declared domain.

Bullets 2 and 3 are the ones that need code. Stated as prose they invert under
ordinary incentive pressure: a specialist that is never consulted is never
scored, never right, and eventually retired, so the cheapest survival strategy
for a bench agent is to find its own pattern in every market. Bullet 3 has to
be *free* — abstention must cost nothing and require nothing — or the bench
re-acquires by habit the standing claim on capital that §1 took away from it.

**Why SUPPORT and REJECT are asymmetric.** A ``REJECT`` surfaces as a concern
the Arbiter must answer and carries a bounded, non-positive tier delta. A
``SUPPORT`` carries nothing: it is recorded, it is auditable, and it moves no
number anywhere. That is not an oversight in this module's API, it is the
mechanism for §6.3 bullet 2. If support could add anything, consulting three
specialists and collecting three supports would be enough to trade a playbook
because the bench said so rather than because the market did — §6.3 bullet 2
defeated by arithmetic. §5.1 says the same thing from the other direction: every
evidence dimension is a property of the market, and a specialist's opinion is
not one, so support is not evidence of edge. LLM-derived input may lower the
tier the risk gate considers and never raise it.

**Scoring (§6.3 bullet 4, §6.6 / A-2).** Relevance is computed here, not
claimed, so "inside its declared domain" is a deterministic fact about the
market rather than a post-hoc judgement about the outcome. An out-of-domain
consultation is unscored in both directions — a correct ``NOT_APPLICABLE``
outside the domain "is never a miss" (§6.6), and an out-of-domain ``SUPPORT``
earns no credit either, though it is flagged as a manufactured signal for
post-session process review.

**Context and evidence (§6.4).** Agents K, L, M and O produce the deterministic
substrate a thesis is built on. Every field below is machine-checkable data:
§6.4's Liquidity and Structure Analyst must express levels as "reproducible data
where possible rather than subjective chart prose", which is enforced here by
requiring an identifier-shaped derivation reference that a sentence cannot
satisfy. Prose may accompany the data in ``note`` but can never replace it — the
same split §6.7 imposes on the thesis schema. Agent L fails closed: a calendar
that is missing or stale permits no new entries (§0.10). Agent N (Historical
Analog) belongs to another workstream; its sample size is carried here as an
input field only, so the evidence basis of a round is auditable in one place.

**A-2 applies to this whole module.** Specialists and context agents assess the
market; none of them may see the firm's equity, session P&L, trade count, or
progress toward anything. ``FirmSnapshot`` is neither imported nor referenced
here, and ``tests/unit/test_bench.py`` pins that at source level, exactly as
``test_classification.py`` does for the classifier. A specialist that could see
the firm was behind would be a pressure input wearing an expert's badge.
"""

from __future__ import annotations

import datetime as dt
import enum
import re
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from types import MappingProxyType
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_firm.agents.schemas import RegimeLabel
from trading_firm.packet import MarketSnapshot

# A reproducible identifier: lowercase, underscore- and dot-separated. The point
# is not the character set, it is that a sentence cannot match. §6.4 wants levels
# and measures expressed as "reproducible data ... rather than subjective chart
# prose", and prose is exactly what this pattern rejects.
_REPRODUCIBLE_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+)*$")

# §6.3 bullet 2 as a number: the single non-positive value a consultation round
# may hand the risk gate. One tier, not one per rejecting specialist — stacking
# advisory opinions into a large reduction would make the bench's aggregate
# opinion load-bearing again, in the other direction. The real force of a
# rejection is that it surfaces and must be answered.
REJECTION_TIER_DELTA = -1


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_aware(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        raise ValueError("naive datetimes are forbidden in agent payloads (§10.3)")
    return value


# ------------------------------------------------------------------- verdicts


class SpecialistVerdict(enum.StrEnum):
    """§6.3: the complete set of things a specialist may say about a thesis.

    ``NOT_APPLICABLE`` is a first-class member, not an error path. §21 requires
    that "irrelevant specialists can return NOT_APPLICABLE without causing
    workflow failure", so it must flow through a round without raising, without
    being counted as support, and without being counted against the specialist.
    """

    SUPPORT = "SUPPORT"
    QUALIFY = "QUALIFY"
    REJECT = "REJECT"
    NOT_APPLICABLE = "NOT_APPLICABLE"

    @property
    def requires_rationale(self) -> bool:
        """Only a claim needs justifying. Silence does not.

        Demanding a rationale for ``NOT_APPLICABLE`` would make abstention the
        most expensive verdict available, and a specialist that must write a
        paragraph to say nothing will find something to say instead (§6.3).
        """
        return self is not SpecialistVerdict.NOT_APPLICABLE

    @property
    def counts_as_support(self) -> bool:
        """True only for ``SUPPORT``. ``QUALIFY`` restricts; it does not endorse."""
        return self is SpecialistVerdict.SUPPORT

    @property
    def surfaces(self) -> bool:
        """Whether the Arbiter must be shown and must answer this verdict.

        Rejections and qualifications surface because both point away from risk
        (§0.6: "no trade" is always a valid and preferred outcome). Support does
        not surface as a concern because there is nothing to answer.
        """
        return self in (SpecialistVerdict.REJECT, SpecialistVerdict.QUALIFY)


# ------------------------------------------------------------------- domains


class SpecialistDomain(_Strict):
    """The market states a bench specialist claims validated competence over.

    Declared up front and independently of any thesis, because §6.3 bullet 4
    scores a specialist only on opportunities inside this set. A domain declared
    after seeing the market would make that scoring circular.
    """

    domain_id: str = Field(min_length=1)
    regimes: tuple[RegimeLabel, ...] = Field(min_length=1)
    description: str = Field(min_length=1)

    @field_validator("domain_id")
    @classmethod
    def _identifier_shaped(cls, value: str) -> str:
        if not _REPRODUCIBLE_ID.match(value):
            raise ValueError(
                f"domain_id {value!r} is not an identifier: a declared domain must name a "
                f"strategy family that exists in config/research/strategies (§6.3, §11)"
            )
        return value

    @model_validator(mode="after")
    def _domain_excludes_distortion(self) -> SpecialistDomain:
        # A bench domain is a *validated* domain. Nothing was validated on
        # event-distorted tape, and §5.3 disqualifies a high-impact event from
        # exceptional treatment for the same reason. A specialist that claims
        # competence there is claiming it on data no one has.
        if RegimeLabel.EVENT_DISTORTED in self.regimes:
            raise ValueError(
                f"{self.domain_id} declares the event_distorted regime: no bench playbook "
                f"is validated on event-distorted tape, so it cannot be a declared domain "
                f"(§6.3, §5.3)"
            )
        return self

    @model_validator(mode="after")
    def _domain_is_not_universal(self) -> SpecialistDomain:
        # A specialist relevant everywhere is scored everywhere and constrained
        # nowhere, which empties §6.3 bullet 4 and makes NOT_APPLICABLE
        # unreachable — the exact outcome bullet 3 exists to keep available.
        assessable = {label for label in RegimeLabel if label is not RegimeLabel.EVENT_DISTORTED}
        if set(self.regimes) >= assessable:
            raise ValueError(
                f"{self.domain_id} declares every assessable regime: a domain that covers "
                f"everything makes 'evaluated only on opportunities within its declared "
                f"domain' meaningless (§6.3)"
            )
        return self

    @model_validator(mode="after")
    def _regimes_are_unique(self) -> SpecialistDomain:
        if len(set(self.regimes)) != len(self.regimes):
            raise ValueError(f"{self.domain_id} lists a regime twice (§6.3)")
        return self


LONDON_BREAKOUT_DOMAIN = SpecialistDomain(
    domain_id="london_breakout",
    regimes=(RegimeLabel.COMPRESSION, RegimeLabel.EXPANSION),
    description="validated breakout variants out of an overnight compression",
)

ASIAN_RANGE_SWEEP_REVERSAL_DOMAIN = SpecialistDomain(
    domain_id="asian_range_sweep_reversal",
    regimes=(RegimeLabel.BALANCE, RegimeLabel.COMPRESSION),
    description="liquidity-sweep and failed-acceptance reversal out of a balanced range",
)

LONDON_CONTINUATION_DOMAIN = SpecialistDomain(
    domain_id="london_continuation",
    regimes=(RegimeLabel.TREND, RegimeLabel.EXPANSION),
    description="validated directional continuation of an established move",
)

# §6.3 agents H, I and J. A mapping, not a registry with an add() — the bench is
# a fixed set under §11 promotion control, not something a session can extend.
BENCH: Mapping[str, SpecialistDomain] = MappingProxyType(
    {
        "london_breakout_specialist": LONDON_BREAKOUT_DOMAIN,
        "asian_range_sweep_reversal_specialist": ASIAN_RANGE_SWEEP_REVERSAL_DOMAIN,
        "london_continuation_specialist": LONDON_CONTINUATION_DOMAIN,
    }
)


def bench_domain(specialist_id: str) -> SpecialistDomain:
    """The declared domain of a bench specialist, or a §6.3-citing error."""
    try:
        return BENCH[specialist_id]
    except KeyError:
        raise ValueError(
            f"unknown bench specialist {specialist_id!r}: the bench is "
            f"{sorted(BENCH)} (§6.3)"
        ) from None


# ------------------------------------------------------------------ relevance


@dataclass(frozen=True)
class RelevanceFinding:
    """Whether a specialist's declared domain covers the current market.

    Deterministic and computed from the market half of the packet alone, so a
    specialist cannot argue itself into relevance and the Learning Director can
    reproduce the scoring population months later (§6.3, §5.1).
    """

    domain_id: str
    relevant: bool
    reason: str


def assess_relevance(domain: SpecialistDomain, market: MarketSnapshot) -> RelevanceFinding:
    """Deterministic relevance classifier (§6.3).

    Consulting a specialist outside this is not a bug — the answer is
    ``NOT_APPLICABLE`` and that answer is *correct*, scored as neither a hit nor
    a miss (§6.6). The classifier exists so that correctness is a property of
    the market rather than of whoever reviews the transcript afterwards.

    It fails closed. On stale prices, incomplete bars, or unknown calendar
    state, no domain is established, because the regime label those conditions
    produced cannot be trusted (§0.10). The safe direction for relevance is
    "not relevant": it removes a voice, and no voice removed can add risk.
    """
    if not market.data_fresh:
        return RelevanceFinding(domain.domain_id, False, "market data not fresh (§0.10)")
    if not market.bars_complete:
        return RelevanceFinding(domain.domain_id, False, "bar series incomplete (§0.10)")
    if not market.calendar_state_known:
        return RelevanceFinding(
            domain.domain_id, False, "economic-calendar state unknown (§0.10)"
        )

    try:
        label = RegimeLabel(market.regime)
    except ValueError:
        return RelevanceFinding(
            domain.domain_id,
            False,
            f"regime {market.regime!r} is outside the deterministic regime vocabulary (§6.4)",
        )

    if label is RegimeLabel.EVENT_DISTORTED:
        return RelevanceFinding(
            domain.domain_id,
            False,
            "regime is event_distorted: no bench playbook is validated there (§6.3, §5.3)",
        )

    if label in domain.regimes:
        return RelevanceFinding(
            domain.domain_id,
            True,
            f"regime {label.value} is inside the declared domain "
            f"{[r.value for r in domain.regimes]} (§6.3)",
        )
    return RelevanceFinding(
        domain.domain_id,
        False,
        f"regime {label.value} is outside the declared domain "
        f"{[r.value for r in domain.regimes]} (§6.3)",
    )


def relevant_specialists(market: MarketSnapshot) -> tuple[str, ...]:
    """The bench members §1 says are "consulted by default" in this state.

    Everyone else may still be consulted; they are simply expected to abstain.
    """
    return tuple(
        sorted(sid for sid, domain in BENCH.items() if assess_relevance(domain, market).relevant)
    )


# -------------------------------------------------------------- consultations


class SpecialistConsultation(_Strict):
    """One specialist's answer about one senior-trader thesis (§6.3).

    Note what this schema cannot express: there is no score, no confidence, no
    size, no tier, and no evidence-class field. A specialist has no vocabulary
    here for anything that could raise risk, which is §6.3 bullet 2 enforced by
    the type rather than by review — the M-1 move used throughout this package.
    """

    specialist_id: str = Field(min_length=1)
    thesis_id: str = Field(min_length=1)
    verdict: SpecialistVerdict
    # Optional by default so that NOT_APPLICABLE constructs with nothing but a
    # verdict. A specialist may still explain an abstention; it is never
    # required to (§6.3 bullet 3).
    rationale: str = ""
    qualification: str | None = None

    @model_validator(mode="after")
    def _specialist_is_on_the_bench(self) -> SpecialistConsultation:
        # The domain is NOT a field. An earlier version let the caller supply
        # `declared_domain` alongside `specialist_id`, which meant a specialist
        # chose, per answer, the domain that decides whether its answer is
        # in-domain — and in-domain drives whether it is scored (§6.3 bullet 4)
        # and whether its REJECT surfaces. A specialist could therefore duck
        # accountability for a wrong call by widening its declared domain after
        # the fact, or suppress its own rejection by narrowing it. §6.3 evaluates
        # a specialist "only on opportunities within its declared domain", which
        # is a claim the BENCH makes about the specialist, not one the specialist
        # makes about itself. Looking it up here makes the two impossible to
        # disagree.
        bench_domain(self.specialist_id)  # raises with a §6.3 citation if unknown
        return self

    @property
    def declared_domain(self) -> SpecialistDomain:
        """The bench's declaration about this specialist, not its own."""
        return bench_domain(self.specialist_id)

    @model_validator(mode="after")
    def _claims_are_justified_silence_is_not(self) -> SpecialistConsultation:
        # SUPPORT, QUALIFY and REJECT are claims about the market and must cite
        # their basis. NOT_APPLICABLE is the absence of a claim; requiring a
        # justification for it is how a bench learns to manufacture signals
        # (§6.3 bullet 3).
        if self.verdict.requires_rationale and not self.rationale.strip():
            raise ValueError(
                f"{self.specialist_id} returned {self.verdict.value} with no rationale: a "
                f"specialist claim must state its basis, though NOT_APPLICABLE needs none "
                f"(§6.3)"
            )
        return self

    @model_validator(mode="after")
    def _qualification_belongs_to_qualify(self) -> SpecialistConsultation:
        if self.verdict is SpecialistVerdict.QUALIFY and not (self.qualification or "").strip():
            raise ValueError(
                f"{self.specialist_id} returned QUALIFY with no qualification: a "
                f"qualification must name the condition it attaches to the thesis, or it "
                f"is a support in disguise (§6.3)"
            )
        if self.verdict is not SpecialistVerdict.QUALIFY and self.qualification is not None:
            raise ValueError(
                f"{self.specialist_id} attached a qualification to a "
                f"{self.verdict.value} verdict: conditions travel with QUALIFY only, so "
                f"that the trade plan carries every condition it must satisfy (§6.3)"
            )
        return self


@dataclass(frozen=True)
class RecordedConsultation:
    """A consultation paired with the deterministic relevance finding for it."""

    consultation: SpecialistConsultation
    relevance: RelevanceFinding

    @property
    def specialist_id(self) -> str:
        return self.consultation.specialist_id

    @property
    def verdict(self) -> SpecialistVerdict:
        return self.consultation.verdict

    @property
    def in_domain(self) -> bool:
        return self.relevance.relevant

    @property
    def scored(self) -> bool:
        """§6.3 bullet 4: performance is evaluated only inside the declared domain."""
        return self.relevance.relevant

    @property
    def correct_abstention(self) -> bool:
        """§6.6 / A-2, absolute bound: never a miss, in either direction."""
        return not self.relevance.relevant and self.verdict is SpecialistVerdict.NOT_APPLICABLE

    @property
    def in_domain_abstention(self) -> bool:
        """Abstaining *inside* the declared domain — a post-session signal only.

        This is the bench's version of the A-2 under-claim: a specialist holding
        a relevant read that filed nothing. It is recorded, never acted on, and
        scored by the Learning Director against reconciled data. §6.6 is
        explicit that an in-session under-classification signal would itself
        become a pressure input, so nothing in this module consumes it.
        """
        return self.relevance.relevant and self.verdict is SpecialistVerdict.NOT_APPLICABLE

    @property
    def manufactured_signal(self) -> bool:
        """An out-of-domain SUPPORT: §6.3 bullet 3's named failure.

        Only ``SUPPORT`` qualifies. An out-of-domain ``REJECT`` or ``QUALIFY``
        points away from risk, and §0.6 makes that direction always available to
        anyone; it is unscored, but it is not a manufactured signal.
        """
        return not self.relevance.relevant and self.verdict is SpecialistVerdict.SUPPORT


@dataclass(frozen=True)
class ConsultationRound:
    """Every specialist answer about one thesis, plus what the firm may do with it.

    Aggregation only. The round answers questions — does anyone reject? did any
    support come from inside a declared domain? — and hands the risk gate a
    single number that is non-positive by construction.
    """

    thesis_id: str
    market_id: str
    records: tuple[RecordedConsultation, ...]

    def __post_init__(self) -> None:
        # §0.11: coerce before the duplicate-specialist and thesis-binding
        # checks below, so a caller cannot pass a list, pass the checks, and
        # then append a second consultation from the same specialist.
        object.__setattr__(self, "records", tuple(self.records))
        seen: set[str] = set()
        for record in self.records:
            sid = record.specialist_id
            if sid in seen:
                raise ValueError(
                    f"{sid} appears twice in the round for {self.thesis_id}: a specialist "
                    f"speaks once, or a repeated opinion counts as two (§6.3)"
                )
            seen.add(sid)
            if record.consultation.thesis_id != self.thesis_id:
                raise ValueError(
                    f"{sid} answered thesis {record.consultation.thesis_id} but the round "
                    f"is for {self.thesis_id}: a consultation is bound to the thesis it "
                    f"assessed (§6.3, §0.11)"
                )

    # --- what happened ---------------------------------------------------

    def by_verdict(self, verdict: SpecialistVerdict) -> tuple[RecordedConsultation, ...]:
        return tuple(r for r in self.records if r.verdict is verdict)

    @property
    def supports(self) -> tuple[RecordedConsultation, ...]:
        return self.by_verdict(SpecialistVerdict.SUPPORT)

    @property
    def qualifications(self) -> tuple[RecordedConsultation, ...]:
        return self.by_verdict(SpecialistVerdict.QUALIFY)

    @property
    def rejections(self) -> tuple[RecordedConsultation, ...]:
        return self.by_verdict(SpecialistVerdict.REJECT)

    @property
    def abstentions(self) -> tuple[RecordedConsultation, ...]:
        return self.by_verdict(SpecialistVerdict.NOT_APPLICABLE)

    @property
    def any_rejection(self) -> bool:
        """Any rejection at all, in or out of domain. A rejection is safe-direction."""
        return bool(self.rejections)

    @property
    def in_domain_rejections(self) -> tuple[RecordedConsultation, ...]:
        return tuple(r for r in self.rejections if r.in_domain)

    @property
    def in_domain_support(self) -> bool:
        """Did any support come from a specialist whose domain covers this market?

        Informational. A ``True`` here authorizes nothing and raises nothing; it
        exists so the Arbiter can tell a domain expert's endorsement from a
        bystander's, and so the two are not silently equivalent in the audit
        record (§6.3, §5.1).
        """
        return any(r.in_domain for r in self.supports)

    @property
    def manufactured_signals(self) -> tuple[RecordedConsultation, ...]:
        """Out-of-domain supports — surfaced for §6.6 process review, never scored."""
        return tuple(r for r in self.records if r.manufactured_signal)

    @property
    def in_domain_abstentions(self) -> tuple[RecordedConsultation, ...]:
        """A-2 post-session input only (see ``RecordedConsultation``)."""
        return tuple(r for r in self.records if r.in_domain_abstention)

    @property
    def scored_records(self) -> tuple[RecordedConsultation, ...]:
        return tuple(r for r in self.records if r.scored)

    # --- what the firm may do with it ------------------------------------

    @property
    def surfaced_concerns(self) -> tuple[str, ...]:
        """Everything the Arbiter must be shown and must answer (§6.3, §0.6).

        Rejections first: an unanswered rejection is the failure this whole
        structure exists to prevent. Supports never appear here — there is
        nothing to answer, and listing them alongside concerns would let a
        column of endorsements visually outweigh a single objection.
        """
        lines: list[str] = []
        for record in self.rejections:
            scope = "in-domain" if record.in_domain else "out-of-domain"
            lines.append(
                f"REJECT ({scope}) {record.specialist_id}: {record.consultation.rationale}"
            )
        for record in self.qualifications:
            scope = "in-domain" if record.in_domain else "out-of-domain"
            lines.append(
                f"QUALIFY ({scope}) {record.specialist_id}: {record.consultation.qualification}"
            )
        return tuple(lines)

    @property
    def conditions(self) -> tuple[str, ...]:
        """Qualifications the trade plan must carry if the thesis proceeds (§6.3)."""
        return tuple(
            r.consultation.qualification
            for r in self.qualifications
            if r.consultation.qualification is not None
        )

    @property
    def tier_delta(self) -> int:
        """The only number this round hands the deterministic risk gate.

        Non-positive by construction: the sole non-zero branch reads
        ``in_domain_rejections``, and no branch reads supports at all. No
        arrangement of ``SUPPORT`` verdicts — three of them, thirty of them —
        can make this positive, because §5.1 permits an LLM-derived input to
        lower the tier the gate considers and never to raise it, and §6.3
        bullet 2 forbids the bench from forcing a trade.
        """
        return REJECTION_TIER_DELTA if self.in_domain_rejections else 0

    @property
    def requires_arbiter_response(self) -> bool:
        """A rejection or qualification may not be closed by silence (§6.3, §0.11)."""
        return bool(self.surfaced_concerns)


def consult(
    thesis_id: str,
    market: MarketSnapshot,
    consultations: tuple[SpecialistConsultation, ...] | list[SpecialistConsultation],
) -> ConsultationRound:
    """Run one consultation round and bind it to the market it was run against.

    §21 acceptance criterion: "irrelevant specialists can return NOT_APPLICABLE
    without causing workflow failure". Abstention takes no special path here —
    it is recorded like any other verdict, and a round in which every specialist
    abstains, or in which nobody was consulted at all, returns normally.
    """
    records = tuple(
        RecordedConsultation(
            consultation=c,
            relevance=assess_relevance(c.declared_domain, market),
        )
        for c in consultations
    )
    return ConsultationRound(
        thesis_id=thesis_id,
        market_id=market.checksum,
        records=records,
    )


# ------------------------------------------------- §6.4 context and evidence


class RegimeReading(_Strict):
    """Agent K, Regime Analyst (§6.4).

    §6.4 asks for a "deterministic-data-grounded regime packet". The label alone
    is a conclusion; ``measures`` is the grounding, and a regime call with no
    measure behind it is chart prose with an enum attached, so it is rejected.
    """

    regime: RegimeLabel
    feature_version: str = Field(min_length=1)
    # Mapping, not dict: pydantic's frozen flag blocks attribute rebinding but
    # not in-place mutation, so a plain dict left the grounding validator
    # bypassable — `reading.measures['the tape looks tight to me'] = ...` after
    # construction put unvalidated prose into a record the validator exists to
    # keep free of it. Frozen below so the field is what it was checked as.
    measures: Mapping[str, Decimal]
    note: str | None = None

    @model_validator(mode="after")
    def _grounded_in_deterministic_measures(self) -> RegimeReading:
        if not self.measures:
            raise ValueError(
                f"regime {self.regime.value} was reported with no deterministic measure: "
                f"a regime packet must be data-grounded, and an agent may not invent an "
                f"indicator value (§6.4, §6A)"
            )
        prose = sorted(k for k in self.measures if not _REPRODUCIBLE_ID.match(k))
        if prose:
            raise ValueError(
                f"regime measures {prose} are not feature identifiers: measures must name "
                f"features from the approved registry, not describe them (§6.4, §11)"
            )
        object.__setattr__(self, "measures", MappingProxyType(dict(self.measures)))
        return self


class CalendarEntry(_Strict):
    """One scheduled event as Agent L reports it (§6.4)."""

    time_utc: dt.datetime
    currency: str = Field(min_length=3, max_length=3)
    impact: Literal["High", "Medium", "Low"]
    name: str = Field(min_length=1)
    blackout: bool

    _aware = field_validator("time_utc")(_require_aware)


class EventRiskReading(_Strict):
    """Agent L, Macro and Event Risk Analyst (§6.4).

    "Missing or stale calendar data causes fail-closed behavior." That is §0.10
    verbatim for this agent, and it is not expressed as a raise: the reading has
    to be *constructible* in the failed state, or the firm cannot record why it
    stood down. It is expressed as ``entries_permitted`` being False, with no
    path to True that does not run through a fresh calendar.
    """

    calendar_state: Literal["fresh", "stale", "missing"]
    as_of_utc: dt.datetime | None = None
    entries: tuple[CalendarEntry, ...] = ()
    blackout_active: bool = False
    unavailable_reason: str | None = None

    @field_validator("as_of_utc")
    @classmethod
    def _aware_as_of(cls, value: dt.datetime | None) -> dt.datetime | None:
        return _require_aware(value) if value is not None else None

    @model_validator(mode="after")
    def _freshness_must_be_evidenced(self) -> EventRiskReading:
        if self.calendar_state == "fresh" and self.as_of_utc is None:
            raise ValueError(
                "calendar_state 'fresh' with no as_of_utc: freshness is a claim about a "
                "timestamp, and without one there is nothing to check it against (§0.10)"
            )
        if self.calendar_state != "fresh" and not (self.unavailable_reason or "").strip():
            raise ValueError(
                f"calendar_state {self.calendar_state!r} with no unavailable_reason: the "
                f"operator halting the session needs to know what failed (§0.10, §0.11)"
            )
        return self

    @classmethod
    def unavailable(cls, reason: str) -> EventRiskReading:
        """The fail-closed reading, so a caller cannot forget how to build one."""
        return cls(calendar_state="missing", unavailable_reason=reason)

    def age_at(self, now: dt.datetime) -> dt.timedelta | None:
        """How old the calendar is, for a caller applying its own staleness limit."""
        if self.as_of_utc is None:
            return None
        return _require_aware(now) - self.as_of_utc

    @property
    def high_impact_entries(self) -> tuple[CalendarEntry, ...]:
        return tuple(e for e in self.entries if e.impact == "High")

    @property
    def entries_permitted(self) -> bool:
        """§0.10: only a fresh calendar outside a blackout window permits entries."""
        return self.calendar_state == "fresh" and not self.blackout_active


class StructuralLevelReading(_Strict):
    """Agent M, Liquidity and Structure Analyst (§6.4).

    §6.4 requires levels "as reproducible data where possible rather than
    subjective chart prose". ``derivation_id`` is what makes that checkable: it
    must be an identifier naming the computation that produced the price, and no
    sentence can satisfy the pattern. "The obvious level everyone is watching"
    fails to construct; ``asian_session.range_high`` does not. Prose is still
    welcome in ``note`` — §6.7's rule that free-form text may accompany a schema
    but never replace it applies here too.
    """

    level_id: str = Field(min_length=1)
    price: Decimal = Field(gt=0)
    level_type: str = Field(min_length=1)
    timeframe: str = Field(min_length=1)
    derivation_id: str = Field(min_length=1)
    sample_bars: int = Field(ge=1)
    note: str | None = None

    @field_validator("level_id", "level_type", "derivation_id")
    @classmethod
    def _reproducible(cls, value: str, info) -> str:  # noqa: ANN001
        if not _REPRODUCIBLE_ID.match(value):
            raise ValueError(
                f"{info.field_name} {value!r} is chart prose, not a reproducible reference: "
                f"structural levels must be expressed as data another process can "
                f"recompute (§6.4)"
            )
        return value


class ExecutionConditions(_Strict):
    """Agent O, Execution Conditions Agent (§6.4).

    §6.4 asks it to assess "whether the expected edge survives current costs",
    which is a subtraction, not an opinion — so both sides of it are fields and
    the verdict is derived. §13 and audit F-5 are the reason this exists at all:
    paper and shadow validate spread-aware costs, not fill quality, and a thesis
    whose edge lives entirely inside the spread has to be visible before the
    order path, not after the fill.
    """

    spread_pips: Decimal = Field(ge=0)
    max_spread_pips: Decimal = Field(gt=0)
    expected_slippage_pips: Decimal = Field(ge=0)
    commission_usd: Decimal = Field(ge=0)
    liquidity_state: Literal["normal", "thin", "disorderly"]
    expected_gross_r: Decimal
    expected_cost_r: Decimal = Field(ge=0)
    broker_healthy: bool = True

    @property
    def expected_net_r(self) -> Decimal:
        return self.expected_gross_r - self.expected_cost_r

    @property
    def survives_costs(self) -> bool:
        """Strictly positive: a break-even expectancy pays for risk with nothing."""
        return self.expected_net_r > 0

    @property
    def spread_within_limits(self) -> bool:
        return self.spread_pips <= self.max_spread_pips


class ContextPacket(_Strict):
    """The deterministic outputs of agents K, L, M and O for one market (§6.4).

    One object, one market checksum, so an audit can establish months later
    exactly what context a thesis was built on (§0.11). It holds no firm state
    and no thesis: context is what the market is, not what we need from it or
    what we intend to do about it (A-2, §5.1).

    ``analog_sample_size`` is agent N's output, carried rather than computed —
    N belongs to its own workstream. It sits here so the evidence basis of a
    session is legible in one place.
    """

    market_id: str = Field(min_length=1)
    observed_at: dt.datetime
    regime: RegimeReading
    event_risk: EventRiskReading
    structure: tuple[StructuralLevelReading, ...] = ()
    execution: ExecutionConditions
    analog_sample_size: int = Field(default=0, ge=0)
    analog_query_id: str | None = None

    _aware = field_validator("observed_at")(_require_aware)

    @model_validator(mode="after")
    def _levels_are_distinct(self) -> ContextPacket:
        ids = [level.level_id for level in self.structure]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"structural levels {duplicates} are reported twice: a duplicated level "
                f"double-counts as structural confirmation (§6.4, §5.1)"
            )
        return self

    @property
    def blocking_conditions(self) -> tuple[str, ...]:
        """Every reason no new entry may be taken in this context (§0.10).

        Reported as a list rather than a single flag because the operator who
        reads this during an incident needs to know which condition to clear,
        and because a second cause hiding behind the first is how a system
        appears to recover while still broken.
        """
        reasons: list[str] = []
        if self.event_risk.calendar_state != "fresh":
            reasons.append(
                f"economic-calendar state is {self.event_risk.calendar_state}: "
                f"{self.event_risk.unavailable_reason} — no new entries (§0.10)"
            )
        if self.event_risk.blackout_active:
            reasons.append("event blackout window is active: no new entries (§0.10, §5.3)")
        if not self.execution.broker_healthy:
            reasons.append("broker connection is not healthy: no new entries (§0.10)")
        if not self.execution.spread_within_limits:
            reasons.append(
                f"spread {self.execution.spread_pips} pips exceeds the "
                f"{self.execution.max_spread_pips} limit (§5.3)"
            )
        if self.execution.liquidity_state == "disorderly":
            reasons.append("liquidity is disorderly: no new entries (§0.10)")
        if not self.execution.survives_costs:
            reasons.append(
                f"expected net edge {self.execution.expected_net_r}R does not survive "
                f"current costs (§6.4, §12.3)"
            )
        return tuple(reasons)

    @property
    def entries_permitted(self) -> bool:
        """Fail closed: True only when nothing at all is blocking (§0.10)."""
        return not self.blocking_conditions

    def verify_against(self, market: MarketSnapshot) -> None:
        """Bind this context to the packet it claims to describe (§6A, §0.10).

        Two ways a context report can be about a different market than the one
        the traders were given: a stale checksum, or a regime label that does
        not match the deterministic packet. Both are caught here rather than
        being discovered in the post-session audit.
        """
        if self.market_id != market.checksum:
            raise ValueError(
                f"context packet describes market {self.market_id} but the session issued "
                f"{market.checksum}: context must be bound to the packet the traders "
                f"received (§6A, §0.10)"
            )
        if self.regime.regime.value != market.regime:
            raise ValueError(
                f"regime analyst reported {self.regime.regime.value} but the deterministic "
                f"packet says {market.regime!r}: an agent may not restate a computed value "
                f"as something else (§6A, §6.4)"
            )
        # Every OTHER value this packet restates from the snapshot, checked the
        # same way. Binding the checksum and the regime alone left a context
        # report free to contradict the packet on spread, event state, analog
        # depth, and observation time — the four inputs that set the evidence
        # ceiling in classification.py — while passing verification. A report
        # that disagrees with the packet it cites is worse than one that omits
        # the value, because it looks corroborating.
        restated = (
            ("execution.spread_pips", self.execution.spread_pips, market.spread_pips),
            (
                "event_risk.blackout_active",
                self.event_risk.blackout_active,
                market.high_impact_event_active,
            ),
            ("analog_sample_size", self.analog_sample_size, market.analog_sample_size),
            ("observed_at", self.observed_at, market.observed_at),
        )
        disagreements = [
            f"{name}={reported!r} vs packet {computed!r}"
            for name, reported, computed in restated
            if reported != computed
        ]
        if disagreements:
            raise ValueError(
                f"context packet contradicts the market packet it cites: "
                f"{'; '.join(disagreements)}. These values set the evidence ceiling "
                f"(§5.3), so a context report may restate them but never revise them "
                f"(§6A, §6.4, §0.10)"
            )
