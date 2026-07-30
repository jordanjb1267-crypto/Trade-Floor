"""Historical analog and base-rate engine (§6.4 agent N; §22 Phase 3 deliverable).

§6.4's Historical Analog and Base-Rate Agent must report seven things: search
definition, number of analogs, similarity method, outcome distribution after
costs, regime breakdown, sensitivity to similarity thresholds, and data
limitations. Every one of them is a REQUIRED field of `AnalogReport`. None has
a default. An analog report that omits its data limitations is not a shorter
report — it is a report that overstates its own evidence, which §12.7 rule 6
classifies as a §12.4 violation even when every number in it is correct.

**The central hazard, and why the shape of this module defeats it.**

§6.4 states the failure mode directly: the engine "must not cherry-pick a
favorable analog set after seeing the desired trade direction." Stated as a
prohibition it is unenforceable — a researcher who widens one tolerance,
re-runs, and keeps the friendlier answer leaves no trace, and the resulting
report is *more* persuasive than an honest one because it has better numbers.

Three structural properties remove the move rather than forbidding it:

1. **The query carries no direction.** `AnalogQuery` has no direction, side, or
   bias field, and `_reject_direction_fields()` fails at IMPORT time if anyone
   adds one. `search_analogs()` likewise takes no direction argument. There is
   nothing to condition the search on.
2. **The query is content-hashed and committed before it runs.** `commit_query()`
   freezes a query into a `CommittedQuery` whose `query_id` is the hash of the
   search definition. `search_analogs()` demands the caller pass the hash it
   pre-registered; a tolerance nudged after the fact changes the hash and the
   run is refused, not silently repeated. Re-querying is still possible — it is
   supposed to be — but it now costs a second committed query_id, which is the
   §12.4 multiple-testing record the practice was previously invisible to.
3. **Both directions are always reported.** There is no way to ask how longs did
   here. `OutcomeDistribution` carries `long_outcomes` and `short_outcomes`
   together, computed from the same analog set and the same signed forward move.
   This is what makes point 2 bite: because the two sides are derived from one
   set, a query cannot be favorable to one direction without being unfavorable
   to the other. Costs make that sharper than a mirror — every analog is charged
   the round-trip cost on BOTH sides, so `sum_long + sum_short == -2 * cost * n`
   exactly. A set that looks good long and good short is arithmetically
   impossible, so "search until something looks good" has no fixed point.

**Publication gate (§12.7 / amendment A-1).** This is research code, and §12.7
rule 1 is unconditional: no number produced by research code may be published in
a validation report, cited in a promotion record, or counted toward §12.6
minimum evidence until the code paths that produced it have passed an
independent, refutation-default adversarial review. `publication_cleared`
defaults False, `format_for_publication()` raises `PublicationGateError` while
it is False, and `supports()` reports insufficient evidence for every use while
it is False. Setting the flag True is not enough on its own: it additionally
requires an `AdversarialReview` whose reviewer is not the author (§12.7 rule 2),
whose coverage includes every §12.7 rule 3 area, and which points at a
decision-log entry (§12.7 rule 7). Nothing in this module sets the flag.
`preview()` exists so a researcher can look at the numbers without being able
to publish them.

**Minimum evidence (§12.6).** The ratified thresholds are encoded in
`MINIMUM_SAMPLE`. The sample this engine reports against them is
`independent_sample` — the number of distinct session dates among the analogs,
not the number of analogs. Twenty overlapping observations of one London session
are one session's worth of evidence, and counting them twenty times is the
cheapest way to manufacture a §12.6 pass. Challenger promotion has no numeric
threshold because §12.6 requires "a separate confirmation sample per §12.4",
which a single report cannot be, so `supports()` always answers no for it.

**Amendment A-2 (§5.1, §6.6).** A base rate is a property of history. It is not
a property of our equity, our session P&L, how many trades we have taken, or how
far we are from anything. `FirmSnapshot` is neither imported nor referenced in
this module — not even transitively through `trading_firm.packet`, which is why
the canonical-serialization helper below is a local duplicate rather than an
import. `tests/unit/test_analogs.py` pins that at source level.

Research environment only (§12.1): nothing here places, modifies, or cancels an
order, and no number it produces implies profitability (§0.5).
"""

from __future__ import annotations

import datetime as dt
import enum
import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from trading_firm.models import Direction

UTC = dt.UTC

# Participates in every query hash: a change to how similarity or costs are
# applied must invalidate previously committed query_ids rather than silently
# change what they mean (§12.7 rule 5 re-review trigger).
ANALOG_ENGINE_VERSION = "analog_base_rate_v1"

# Statistics are quantized, never risk amounts, so ROUND_HALF_EVEN is correct
# here. `models.cents` rounds DOWN because rounding risk up is dangerous; for a
# reported expectancy, rounding down means rounding a negative mean toward zero,
# i.e. flattering the result. A descriptive statistic must be unbiased in both
# directions (§0.5).
PIP_QUANT = Decimal("0.01")
RATE_QUANT = Decimal("0.0001")
DISTANCE_QUANT = Decimal("0.000001")

# A distance of exactly 1.0 tolerance unit is the boundary of the search box.
PRIMARY_THRESHOLD_SCALE = Decimal("1")

# §6.4 requires "sensitivity to similarity thresholds". One threshold has no
# sensitivity and two is a line through two points; three is the minimum at
# which a result can be seen to be stable or not.
MIN_THRESHOLD_SCALES = 3

# Field names that would let a search be conditioned on the answer it is meant
# to produce. Checked against the model at import time, not at call time.
FORBIDDEN_QUERY_FIELDS = frozenset(
    {
        "direction",
        "side",
        "bias",
        "long",
        "short",
        "desired_direction",
        "trade_direction",
        "expected_direction",
        "hypothesized_direction",
    }
)

# §12.7 rule 3: the minimum coverage an adversarial review must have before it
# can clear any research number for publication.
REQUIRED_REVIEW_COVERAGE = frozenset(
    {
        "lookahead_and_leakage",
        "fill_and_cost_model",
        "rule_logic_vs_manifest",
        "claim_vs_computation",
        "test_adequacy_including_mutation",
    }
)


class EvidenceUse(enum.StrEnum):
    """The §12.6 decisions that carry a ratified minimum sample."""

    PROBATION_EXIT_REVIEW = "probation_exit_review"
    TIER_QUALIFICATION_ABOVE_STANDARD = "tier_qualification_above_standard"
    CHALLENGER_PROMOTION = "challenger_promotion"
    EDGE_SCORE_RECALIBRATION = "edge_score_recalibration"


# §12.6, ratified 2026-07-29. `None` means "no count satisfies this from one
# report": challenger promotion requires a SEPARATE confirmation sample (§12.4).
MINIMUM_SAMPLE: Mapping[EvidenceUse, int | None] = {
    EvidenceUse.PROBATION_EXIT_REVIEW: 30,
    EvidenceUse.TIER_QUALIFICATION_ABOVE_STANDARD: 50,
    EvidenceUse.CHALLENGER_PROMOTION: None,
    EvidenceUse.EDGE_SCORE_RECALIBRATION: 100,
}


class PublicationGateError(RuntimeError):
    """A research number was asked to leave the research environment (§12.7)."""


class QueryCommitmentError(RuntimeError):
    """A search was attempted against a definition that was not the committed one.

    Separate from ValueError because this is the §6.4 anti-cherry-pick control
    failing, not a malformed input: an operator reading a log needs to see the
    difference between "you typed a bad tolerance" and "the query that ran is
    not the query that was pre-registered".
    """


class SimilarityMethod(enum.StrEnum):
    """How tolerance-normalized feature distances combine into one distance.

    Both methods measure distance in TOLERANCE UNITS, so a threshold scale of
    1.0 means "inside the declared tolerances" under either, and the sensitivity
    sweep has the same meaning across methods.
    """

    # Every feature must be inside its tolerance (Chebyshev). Strictest.
    TOLERANCE_BOX = "tolerance_box"
    # Mean normalized deviation: one feature may run wide if others are tight.
    NORMALIZED_L1 = "normalized_l1"


def _reject_float(value: object) -> object:
    """House rule: Decimal for all price math, never float (§10.3 discipline).

    Pydantic will happily coerce 0.1 into a Decimal carrying the binary error it
    was born with. Refusing the coercion at the edge keeps every tolerance,
    target, and cost exactly what the researcher wrote.
    """
    if isinstance(value, float):
        raise ValueError(
            f"{value!r} is a float; analog queries take Decimal or str so a tolerance "
            f"means exactly what was written (house rule, §12.4 reproducibility)"
        )
    return value


def _canonical(value: object) -> object:
    """Deterministic serialization for the query hash: same query, same bytes.

    Deliberately a local duplicate of the packet module's helper rather than an
    import. `trading_firm.packet` defines `FirmSnapshot`, and importing from it
    would put firm state one attribute access away from a base-rate calculation
    (A-2, §5.1). The base-rate engine holds no reference to that module at all.
    """
    if isinstance(value, Decimal):
        return f"{value.normalize():f}"  # Decimal("1") and Decimal("1.0") agree
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            raise ValueError("query datetimes must be timezone-aware (§10.3)")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, enum.Enum):
        return str(value.value)
    if isinstance(value, bool | int | str) or value is None:
        return value
    if isinstance(value, Mapping):
        return {str(k): _canonical(v) for k, v in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_canonical(v) for v in value]
    raise TypeError(f"query field type is not canonically serializable: {type(value)!r}")


def _digest(payload: Mapping[str, object]) -> str:
    blob = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode()).hexdigest()


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FeatureTolerance(_Strict):
    """One dimension of the search box: "feature X, near this value, this wide"."""

    feature_id: str = Field(min_length=1)
    target: Decimal
    tolerance: Decimal = Field(gt=0)

    _no_floats = field_validator("target", "tolerance", mode="before")(_reject_float)


class CostModel(_Strict):
    """§12.4 requires an explicit transaction-cost model. Charged to BOTH sides.

    A base rate quoted before costs is the single most common way a research
    number flatters a strategy that cannot be traded, which is why every outcome
    in this module is net and why a zero-cost model is rejected outright rather
    than treated as a conservative default.
    """

    spread_pips: Decimal = Field(ge=0)
    slippage_pips: Decimal = Field(ge=0)
    commission_pips: Decimal = Field(ge=0)

    _no_floats = field_validator(
        "spread_pips", "slippage_pips", "commission_pips", mode="before"
    )(_reject_float)

    @property
    def round_trip_cost_pips(self) -> Decimal:
        return self.spread_pips + self.slippage_pips + self.commission_pips

    @model_validator(mode="after")
    def _costs_must_be_real(self) -> CostModel:
        if self.round_trip_cost_pips <= 0:
            raise ValueError(
                "cost model totals 0 pips: §12.4 requires an EXPLICIT transaction-cost "
                "model, and a costless round trip is not one — quote the spread, "
                "slippage, and commission the analog would actually have paid"
            )
        return self


class AnalogQuery(_Strict):
    """The search definition (§6.4 item 1), hashed and committed before it runs.

    There is no direction field here and there never may be — see
    `_reject_direction_fields()`, which runs at import. The search is defined by
    what the market looked like, not by what we hope it did next.
    """

    query_label: str = Field(min_length=1)
    # §12.4: "pre-registered hypothesis or experiment record before confirmation
    # testing". Written into the hash, so the hypothesis cannot be adjusted to
    # match the result without invalidating the commitment.
    pre_registered_hypothesis: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    data_source_id: str = Field(min_length=1)
    similarity_method: SimilarityMethod
    tolerances: tuple[FeatureTolerance, ...] = Field(min_length=1)
    start_date: dt.date
    end_date: dt.date
    as_of_utc: dt.datetime
    horizon_minutes: int = Field(gt=0)
    embargo_days: int = Field(ge=0)
    threshold_scales: tuple[Decimal, ...]
    cost_model: CostModel
    regime_filter: tuple[str, ...] = ()
    # Required with no default: §12.7 rule 6 wants coverage holes DISCLOSED, and
    # an optional field with a default of () is a field that gets skipped. An
    # empty tuple is a legitimate answer, but it has to be given.
    known_coverage_gaps: tuple[str, ...]

    @field_validator("as_of_utc")
    @classmethod
    def _aware(cls, value: dt.datetime) -> dt.datetime:
        if value.tzinfo is None:
            raise ValueError("as_of_utc must be timezone-aware (§10.3)")
        return value

    @field_validator("threshold_scales", mode="before")
    @classmethod
    def _scales_are_decimal(cls, value: object) -> object:
        if isinstance(value, list | tuple):
            for item in value:
                _reject_float(item)
        return value

    @field_validator("threshold_scales")
    @classmethod
    def _sensitivity_is_not_optional(cls, value: tuple[Decimal, ...]) -> tuple[Decimal, ...]:
        if any(scale <= 0 for scale in value):
            raise ValueError("threshold scales must be positive multiples of the tolerance")
        if len(value) < MIN_THRESHOLD_SCALES:
            raise ValueError(
                f"threshold_scales has {len(value)} entries; §6.4 requires the report to "
                f"show sensitivity to similarity thresholds, which needs at least "
                f"{MIN_THRESHOLD_SCALES} — a single threshold hides whether the result "
                f"survives a slightly wider or tighter box"
            )
        if list(value) != sorted(set(value)):
            raise ValueError(
                "threshold_scales must be strictly ascending and distinct so the "
                "sensitivity table reads as one sweep (§6.4)"
            )
        if PRIMARY_THRESHOLD_SCALE not in value:
            raise ValueError(
                f"threshold_scales must include the primary scale "
                f"{PRIMARY_THRESHOLD_SCALE} — the headline analog count is the one at "
                f"the declared tolerances, and omitting it lets the headline be chosen "
                f"from the sweep after the fact (§6.4)"
            )
        return value

    @field_validator("tolerances")
    @classmethod
    def _one_dimension_each(
        cls, value: tuple[FeatureTolerance, ...]
    ) -> tuple[FeatureTolerance, ...]:
        ids = [t.feature_id for t in value]
        duplicates = sorted({i for i in ids if ids.count(i) > 1})
        if duplicates:
            raise ValueError(
                f"features {duplicates} appear twice in the search box: a repeated "
                f"feature silently double-weights that dimension of the similarity "
                f"metric (§6.4, §12.4)"
            )
        return value

    @model_validator(mode="after")
    def _window_precedes_as_of(self) -> AnalogQuery:
        if self.end_date < self.start_date:
            raise ValueError(
                f"date range ends {self.end_date} before it starts {self.start_date}"
            )
        as_of_date = self.as_of_utc.astimezone(UTC).date()
        if self.end_date > as_of_date:
            raise ValueError(
                f"date range ends {self.end_date}, after the as-of date {as_of_date}: a "
                f"search whose own window reaches past the decision moment is future "
                f"leakage by construction (§12.4)"
            )
        return self

    @property
    def content_hash(self) -> str:
        """The identity of this search definition (§6.4, §0.11).

        Every field participates. Widening a tolerance, moving a date bound,
        swapping the similarity method, or editing the pre-registered hypothesis
        all produce a different query — which is the point: the change becomes a
        new, separately recorded trial rather than a silent revision.
        """
        return _digest(
            {
                "engine": ANALOG_ENGINE_VERSION,
                "query_label": self.query_label,
                "pre_registered_hypothesis": self.pre_registered_hypothesis,
                "instrument": self.instrument,
                "data_source_id": self.data_source_id,
                "similarity_method": self.similarity_method,
                "tolerances": [
                    {"feature_id": t.feature_id, "target": t.target, "tolerance": t.tolerance}
                    for t in self.tolerances
                ],
                "start_date": self.start_date,
                "end_date": self.end_date,
                "as_of_utc": self.as_of_utc,
                "horizon_minutes": self.horizon_minutes,
                "embargo_days": self.embargo_days,
                "threshold_scales": list(self.threshold_scales),
                "cost_model": {
                    "spread_pips": self.cost_model.spread_pips,
                    "slippage_pips": self.cost_model.slippage_pips,
                    "commission_pips": self.cost_model.commission_pips,
                },
                "regime_filter": list(self.regime_filter),
                "known_coverage_gaps": list(self.known_coverage_gaps),
            }
        )


# The exact field set `AnalogQuery` is registered to have. A denylist of
# direction-shaped names catches `side` and `direction`, but not `favourable_only`
# or `bullish` — and the field that defeats this control will not be named
# something a denylist author thought of. Pinning the whole set inverts the
# burden: ANY new field trips the guard until someone deliberately registers it
# and, in doing so, states that it is not a direction in disguise.
REGISTERED_QUERY_FIELDS = frozenset(
    {
        "as_of_utc",
        "cost_model",
        "data_source_id",
        "embargo_days",
        "end_date",
        "horizon_minutes",
        "instrument",
        "known_coverage_gaps",
        "pre_registered_hypothesis",
        "query_label",
        "regime_filter",
        "similarity_method",
        "start_date",
        "threshold_scales",
        "tolerances",
    }
)


def _reject_direction_fields() -> None:
    """Fail at import if `AnalogQuery`'s field set changes at all.

    §6.4's prohibition — "must not cherry-pick a favorable analog set after
    seeing the desired trade direction" — is only structural while the query
    cannot express a direction. A reviewer might not notice a `side: str` field
    added to a 20-field model; this notices before the module finishes loading.

    Two checks, deliberately overlapping. The denylist gives a precise, readable
    error for the obvious case. The registered-set check is the one that
    actually closes the hole, because it does not depend on anyone having
    guessed the offending name in advance.
    """
    actual = set(AnalogQuery.model_fields)

    present = FORBIDDEN_QUERY_FIELDS & actual
    if present:
        raise RuntimeError(
            f"AnalogQuery declares {sorted(present)}: an analog search may not be "
            f"conditioned on the direction it is being used to justify (§6.4). The "
            f"outcome distribution is reported for BOTH directions instead."
        )

    added = actual - REGISTERED_QUERY_FIELDS
    removed = REGISTERED_QUERY_FIELDS - actual
    if added or removed:
        raise RuntimeError(
            f"AnalogQuery's field set changed (added={sorted(added)}, "
            f"removed={sorted(removed)}). An analog search is only free of the §6.4 "
            f"cherry-pick hazard while its definition cannot encode the answer it is "
            f"meant to produce, so every field is registered explicitly. If the new "
            f"field genuinely cannot express a trade direction or a favourability "
            f"filter, add it to REGISTERED_QUERY_FIELDS and say so in the commit."
        )


_reject_direction_fields()


@dataclass(frozen=True)
class CommittedQuery:
    """A query pinned to its hash before anyone has seen a result (§6.4, §12.4)."""

    query: AnalogQuery
    query_id: str
    committed_at: dt.datetime
    committed_by: str

    def __post_init__(self) -> None:
        if self.committed_at.tzinfo is None:
            raise ValueError("committed_at must be timezone-aware (§10.3)")
        if not self.committed_by.strip():
            raise ValueError("committed_by must name the agent or operator (§0.11)")

    def verify(self) -> None:
        """Fail closed if the definition moved after commitment (§0.10, §6.4)."""
        actual = self.query.content_hash
        if actual != self.query_id:
            raise QueryCommitmentError(
                f"analog query was altered after commitment: committed {self.query_id}, "
                f"the supplied definition hashes to {actual}. Re-commit the changed "
                f"search as a NEW query so the extra trial is on the record (§6.4, §12.4)"
            )


def commit_query(query: AnalogQuery, *, at: dt.datetime, by: str) -> CommittedQuery:
    """Pre-register a search definition. Must happen before the search runs."""
    return CommittedQuery(
        query=query,
        query_id=query.content_hash,
        committed_at=at,
        committed_by=by,
    )


@dataclass(frozen=True)
class HistoricalObservation:
    """One historical moment and what the market did next, direction-free.

    `forward_move_pips` is SIGNED and measured up-positive. It is not "the
    profit" — there is no position here. Long and short outcomes are both
    derived from it, which is what lets the report answer for both directions
    from one stored fact and makes a direction-selective analog set impossible
    to assemble (§6.4).

    Injected rather than fetched: the engine is a pure function of the sequence
    it is given, so a test, a replay, and a live briefing all exercise the same
    code path (§12.1, §21).
    """

    observation_id: str
    instrument: str
    observed_at: dt.datetime
    session_date: dt.date
    regime: str
    horizon_minutes: int
    forward_move_pips: Decimal
    outcome_observed_at: dt.datetime
    features: Mapping[str, Decimal] = field(default_factory=dict)
    data_complete: bool = True

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.outcome_observed_at.tzinfo is None:
            raise ValueError(
                f"observation {self.observation_id}: timestamps must be timezone-aware (§10.3)"
            )
        if self.outcome_observed_at <= self.observed_at:
            raise ValueError(
                f"observation {self.observation_id}: the forward outcome is timestamped "
                f"{self.outcome_observed_at.isoformat()}, at or before the observation "
                f"itself — an outcome that precedes its own observation is look-ahead "
                f"data, not history (§12.4)"
            )
        if self.horizon_minutes <= 0:
            raise ValueError(f"observation {self.observation_id}: horizon must be positive")
        object.__setattr__(self, "features", dict(self.features))


@dataclass(frozen=True)
class DirectionalOutcomes:
    """Net-of-cost outcome statistics for one side of the same analog set."""

    direction: Direction
    count: int
    wins: int
    losses: int
    scratches: int
    sum_net_pips: Decimal
    mean_net_pips: Decimal | None
    median_net_pips: Decimal | None
    win_rate: Decimal | None
    best_net_pips: Decimal | None
    worst_net_pips: Decimal | None


@dataclass(frozen=True)
class OutcomeDistribution:
    """§6.4 item 4: outcome distribution after costs — for BOTH directions.

    Constructing one side without the other is not possible: both fields are
    required. That is the whole defence. A caller reads the pair; it cannot ask
    for the side it wants and never see the side it does not, and because both
    sides come from one analog set and one signed forward move, the pair is
    self-checking — `sum_net_pips` on the two sides must add to
    `-2 * cost * count` exactly.
    """

    long_outcomes: DirectionalOutcomes
    short_outcomes: DirectionalOutcomes
    cost_pips_per_trade: Decimal

    def __post_init__(self) -> None:
        if self.long_outcomes.count != self.short_outcomes.count:
            raise ValueError(
                f"long side has {self.long_outcomes.count} analogs and short side "
                f"{self.short_outcomes.count}: both directions must be reported over "
                f"the SAME analog set, or the set was selected per direction (§6.4)"
            )
        expected = -2 * self.cost_pips_per_trade * self.long_outcomes.count
        actual = self.long_outcomes.sum_net_pips + self.short_outcomes.sum_net_pips
        if actual != expected:
            raise ValueError(
                f"long and short net totals sum to {actual}, not {expected}: the two "
                f"sides are not the same analogs charged the same costs (§6.4, §12.4)"
            )


@dataclass(frozen=True)
class RegimeSlice:
    """§6.4 item 5: one regime's share of the analogs and its own base rates."""

    regime: str
    analog_count: int
    independent_sample: int
    distribution: OutcomeDistribution


@dataclass(frozen=True)
class SensitivityPoint:
    """§6.4 item 6: the same query at a wider or tighter similarity threshold."""

    threshold_scale: Decimal
    analog_count: int
    independent_sample: int
    distribution: OutcomeDistribution


@dataclass(frozen=True)
class DataLimitations:
    """§6.4 item 7, and the honest denominator §12.7 rule 6 requires.

    Every exclusion is counted separately. "We found 12 analogs" means nothing
    without "out of how many, and what did we throw away" — a search that
    silently dropped 400 observations for missing features is describing a
    different population than the one the reader assumes.
    """

    observations_supplied: int
    excluded_wrong_instrument: int
    excluded_outside_date_range: int
    excluded_horizon_mismatch: int
    excluded_lookahead: int
    excluded_by_embargo: int
    excluded_incomplete_data: int
    excluded_missing_features: int
    excluded_by_regime_filter: int
    eligible_population: int
    distinct_session_dates_eligible: int
    known_coverage_gaps: tuple[str, ...]
    notes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.notes:
            raise ValueError(
                "data limitations carry no notes: §6.4 requires data limitations to be "
                "reported, and a report that states none is asserting the data is "
                "perfect (§12.7 rule 6)"
            )


@dataclass(frozen=True)
class AdversarialReview:
    """A completed §12.7 review of the code paths that produced a report.

    Existence of this record is the ONLY thing that lets `publication_cleared`
    be True. §12.7 rule 2 requires independence and a refutation default; rule 3
    fixes the minimum coverage; rule 4 requires refuted findings to be logged
    alongside confirmed ones; rule 7 requires the outcome to live in the
    decision log. All four are checked here, so flipping a boolean is not a
    route around the review.
    """

    review_record_id: str
    reviewer_id: str
    author_id: str
    reviewed_at: dt.datetime
    covered_areas: frozenset[str]
    findings_confirmed: tuple[str, ...]
    findings_refuted: tuple[str, ...]
    decision_log_ref: str

    def __post_init__(self) -> None:
        if self.reviewed_at.tzinfo is None:
            raise ValueError("reviewed_at must be timezone-aware (§10.3)")
        if not self.review_record_id.strip():
            raise ValueError("review_record_id is required (§12.7 rule 7)")
        if self.reviewer_id.strip() == self.author_id.strip():
            raise ValueError(
                f"{self.reviewer_id} reviewed its own research code: §12.7 rule 2 "
                f"requires the review to be independent of the code's author"
            )
        missing = sorted(REQUIRED_REVIEW_COVERAGE - set(self.covered_areas))
        if missing:
            raise ValueError(
                f"adversarial review {self.review_record_id} did not cover {missing}: "
                f"§12.7 rule 3 fixes the minimum coverage and a review may extend it "
                f"but never shorten it"
            )
        if not self.decision_log_ref.strip():
            raise ValueError(
                f"adversarial review {self.review_record_id} has no decision-log "
                f"reference: the outcome, including refuted findings, is recorded in "
                f"governance/decision-log.md (§12.7 rule 7, §0.11)"
            )


@dataclass(frozen=True)
class EvidenceSufficiency:
    """Whether a report may be counted toward one §12.6 decision. Never a number."""

    use: EvidenceUse
    required: int | None
    actual: int
    sufficient: bool
    reasons: tuple[str, ...]


PREVIEW_BANNER = (
    "RESEARCH PREVIEW — NOT PUBLISHABLE. These code paths have not passed the §12.7 "
    "adversarial review, so no number below may enter a validation report, a promotion "
    "record, or a §12.6 evidence count. Base rates describe history under one data "
    "source; they are not a forecast and imply no profitability (§0.5)."
)


@dataclass(frozen=True)
class AnalogReport:
    """All seven §6.4 disclosures, every one of them mandatory.

    `publication_cleared` is the §12.7 / A-1 gate and defaults False. It is not a
    formality: while it is False, `format_for_publication()` refuses and
    `supports()` answers no for every §12.6 use, so an unreviewed number cannot
    reach a validation report by any path this type offers.
    """

    query: AnalogQuery
    query_id: str
    similarity_method: SimilarityMethod
    analog_count: int
    independent_sample: int
    outcome_distribution: OutcomeDistribution
    regime_breakdown: tuple[RegimeSlice, ...]
    threshold_sensitivity: tuple[SensitivityPoint, ...]
    data_limitations: DataLimitations
    cost_model: CostModel
    generated_at: dt.datetime
    publication_cleared: bool = False
    review: AdversarialReview | None = None

    def __post_init__(self) -> None:
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone-aware (§10.3)")
        if self.query_id != self.query.content_hash:
            raise QueryCommitmentError(
                f"report cites query {self.query_id} but its search definition hashes "
                f"to {self.query.content_hash}: the reported numbers do not belong to "
                f"the committed query (§6.4, §0.11)"
            )
        if self.similarity_method is not self.query.similarity_method:
            raise ValueError(
                f"report declares similarity method {self.similarity_method.value} but "
                f"the query committed {self.query.similarity_method.value} (§6.4)"
            )
        swept = tuple(p.threshold_scale for p in self.threshold_sensitivity)
        if swept != self.query.threshold_scales:
            raise ValueError(
                f"threshold sensitivity covers {list(swept)} but the query committed "
                f"{list(self.query.threshold_scales)}: §6.4 requires sensitivity to be "
                f"reported over the thresholds that were pre-registered, not a subset "
                f"chosen after the results were seen"
            )
        if self.publication_cleared and self.review is None:
            raise PublicationGateError(
                "publication_cleared is True with no adversarial review attached: "
                "§12.7 rule 1 permits publication only after the code paths that "
                "produced the numbers have passed an independent, refutation-default "
                "review (A-1). Attach the AdversarialReview record or leave the gate shut"
            )
        if self.independent_sample > self.analog_count:
            raise ValueError(
                f"independent_sample {self.independent_sample} exceeds analog_count "
                f"{self.analog_count}: the independent sample is a subset by definition"
            )

    @property
    def evidence_sample_size(self) -> int:
        """The count §12.6 is measured against: distinct sessions, not analogs.

        Overlapping observations of one session are correlated to the point of
        being one draw. Counting them individually is the cheapest available way
        to manufacture a §12.6 pass, so the engine refuses to offer that number
        as the evidence count at all.
        """
        return self.independent_sample

    def supports(self, use: EvidenceUse) -> EvidenceSufficiency:
        """Whether this report may be counted toward a §12.6 decision.

        Answers no while the publication gate is shut, no matter how large the
        sample: §12.7 rule 1 bars an unreviewed number from a §12.6 evidence
        count explicitly.
        """
        required = MINIMUM_SAMPLE[use]
        actual = self.evidence_sample_size
        reasons: list[str] = []

        if not self.publication_cleared:
            reasons.append(
                "publication gate is shut: these code paths have not passed the §12.7 "
                "adversarial review, so this number may not be counted toward §12.6 "
                "minimum evidence (A-1)"
            )
        if required is None:
            reasons.append(
                f"{use.value} requires a separate confirmation sample per §12.4; one "
                f"analog report is a single sample and can never satisfy it (§12.6)"
            )
        elif actual < required:
            reasons.append(
                f"independent sample {actual} is below the §12.6 minimum of {required} "
                f"for {use.value}: a sample below this threshold is not evidence of "
                f"edge regardless of its profit factor"
            )

        return EvidenceSufficiency(
            use=use,
            required=required,
            actual=actual,
            sufficient=not reasons,
            reasons=tuple(reasons),
        )

    def preview(self) -> str:
        """Render the report for a researcher's own eyes, stamped unpublishable.

        A gate researchers cannot see past gets worked around. This returns the
        full picture under a banner naming exactly what it may not be used for,
        so the §12.7 gate constrains publication rather than inspection.
        """
        return self._render(PREVIEW_BANNER)

    def format_for_publication(self) -> str:
        """Render for a validation report or promotion record. Gated (§12.7).

        Raises while `publication_cleared` is False. This is the single place a
        research number is allowed to leave the research environment, which is
        why the check lives here rather than in the caller (§12.1, §12.7 rule 1).
        """
        if not self.publication_cleared:
            raise PublicationGateError(
                f"analog report for query {self.query_id} is not cleared for "
                f"publication: §12.7 rule 1 (amendment A-1) forbids publishing, citing "
                f"in a promotion record, or counting toward §12.6 evidence any number "
                f"whose code paths have not passed an independent, refutation-default "
                f"adversarial review. Use preview() to inspect the numbers, and record "
                f"the review in governance/decision-log.md before publishing them"
            )
        review = self.review
        if review is None:  # unreachable: __post_init__ rejects it. Belt and braces.
            raise PublicationGateError(
                "publication_cleared without an adversarial review record (§12.7 rule 1)"
            )
        banner = (
            f"PUBLICATION-CLEARED under adversarial review {review.review_record_id} "
            f"(reviewer {review.reviewer_id}; decision log {review.decision_log_ref}; "
            f"§12.7). Re-review is required if the cost model, feature boundaries, or "
            f"similarity logic change (§12.7 rule 5)."
        )
        return self._render(banner)

    def _render(self, banner: str) -> str:
        q = self.query
        d = self.outcome_distribution
        lines = [
            banner,
            "",
            f"Search definition   : {q.query_label} [{self.query_id[:16]}…]",
            f"  hypothesis        : {q.pre_registered_hypothesis}",
            f"  instrument/source : {q.instrument} via {q.data_source_id}",
            f"  window            : {q.start_date} .. {q.end_date} "
            f"(as of {q.as_of_utc.astimezone(UTC).isoformat()}, embargo {q.embargo_days}d)",
            f"  horizon           : {q.horizon_minutes} minutes",
            f"  regime filter     : {list(q.regime_filter) or 'none (all regimes)'}",
            f"Similarity method   : {self.similarity_method.value} over "
            f"{len(q.tolerances)} feature tolerance(s)",
            f"Number of analogs   : {self.analog_count} "
            f"(independent sessions: {self.independent_sample})",
            f"Costs charged       : {self.cost_model.round_trip_cost_pips} pips per trade, "
            f"both directions",
            "Outcome distribution after costs (same analog set, both directions):",
            f"  {_side_line(d.long_outcomes)}",
            f"  {_side_line(d.short_outcomes)}",
            "Regime breakdown:",
        ]
        lines += [
            f"  {s.regime:<20} n={s.analog_count:<4} sessions={s.independent_sample:<4} "
            f"long_mean={s.distribution.long_outcomes.mean_net_pips} "
            f"short_mean={s.distribution.short_outcomes.mean_net_pips}"
            for s in self.regime_breakdown
        ] or ["  (no analogs)"]
        lines.append("Sensitivity to similarity threshold:")
        lines += [
            f"  scale {str(p.threshold_scale):<6} n={p.analog_count:<4} "
            f"sessions={p.independent_sample:<4} "
            f"long_mean={p.distribution.long_outcomes.mean_net_pips} "
            f"short_mean={p.distribution.short_outcomes.mean_net_pips}"
            for p in self.threshold_sensitivity
        ]
        lines.append("Data limitations:")
        lines += [f"  - {note}" for note in self.data_limitations.notes]
        lines += [
            f"  - known coverage gap: {gap}"
            for gap in self.data_limitations.known_coverage_gaps
        ] or ["  - no additional coverage gaps were declared for this data source"]
        return "\n".join(lines)


def _side_line(side: DirectionalOutcomes) -> str:
    return (
        f"{side.direction.value:<6} n={side.count:<4} mean={side.mean_net_pips} "
        f"median={side.median_net_pips} win_rate={side.win_rate} "
        f"best={side.best_net_pips} worst={side.worst_net_pips}"
    )


# ------------------------------------------------------------------ statistics


def _median(values: Sequence[Decimal]) -> Decimal | None:
    if not values:
        return None
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return ((ordered[mid - 1] + ordered[mid]) / 2).quantize(
        PIP_QUANT, rounding=ROUND_HALF_EVEN
    )


def _summarize(direction: Direction, nets: Sequence[Decimal]) -> DirectionalOutcomes:
    count = len(nets)
    wins = sum(1 for n in nets if n > 0)
    losses = sum(1 for n in nets if n < 0)
    total = sum(nets, Decimal("0"))
    return DirectionalOutcomes(
        direction=direction,
        count=count,
        wins=wins,
        losses=losses,
        scratches=count - wins - losses,
        sum_net_pips=total,
        mean_net_pips=(
            (total / count).quantize(PIP_QUANT, rounding=ROUND_HALF_EVEN) if count else None
        ),
        median_net_pips=_median(nets),
        win_rate=(
            (Decimal(wins) / Decimal(count)).quantize(RATE_QUANT, rounding=ROUND_HALF_EVEN)
            if count
            else None
        ),
        best_net_pips=max(nets) if nets else None,
        worst_net_pips=min(nets) if nets else None,
    )


def _distribution(
    analogs: Sequence[HistoricalObservation], cost: Decimal
) -> OutcomeDistribution:
    """Both directions from one set: long = +move - cost, short = -move - cost.

    The subtraction is exact Decimal arithmetic with no division, so the
    `OutcomeDistribution` cross-check (`sum_long + sum_short == -2*cost*n`) is an
    exact identity rather than a tolerance comparison — it fails loudly the day
    someone filters one side (§6.4).
    """
    longs = [a.forward_move_pips - cost for a in analogs]
    shorts = [-a.forward_move_pips - cost for a in analogs]
    return OutcomeDistribution(
        long_outcomes=_summarize(Direction.LONG, longs),
        short_outcomes=_summarize(Direction.SHORT, shorts),
        cost_pips_per_trade=cost,
    )


def _independent_sample(analogs: Sequence[HistoricalObservation]) -> int:
    return len({a.session_date for a in analogs})


# --------------------------------------------------------------------- search


def _distance(query: AnalogQuery, obs: HistoricalObservation) -> Decimal | None:
    """Distance in tolerance units, or None when a required feature is absent.

    Distances round UP (`ROUND_CEILING`). A borderline observation is therefore
    excluded rather than admitted: ambiguity should shrink the claimed evidence,
    never inflate it (§12.4, §0.10).
    """
    deviations: list[Decimal] = []
    for tol in query.tolerances:
        value = obs.features.get(tol.feature_id)
        if value is None:
            return None
        deviations.append(abs(value - tol.target) / tol.tolerance)
    if query.similarity_method is SimilarityMethod.TOLERANCE_BOX:
        raw = max(deviations)
    else:  # NORMALIZED_L1: mean normalized deviation
        raw = sum(deviations, Decimal("0")) / Decimal(len(deviations))
    return raw.quantize(DISTANCE_QUANT, rounding=ROUND_CEILING)


def search_analogs(
    committed: CommittedQuery,
    observations: Sequence[HistoricalObservation],
    *,
    expected_query_id: str,
    generated_at: dt.datetime,
) -> AnalogReport:
    """Run a pre-registered analog search over an injected history.

    `expected_query_id` is required and is the hash the caller wrote down BEFORE
    running. Passing it is what makes the commitment real: an engine that simply
    read `committed.query_id` would happily run a query re-committed thirty
    seconds ago with a friendlier tolerance. Here that attempt raises, and the
    only way forward is to record a second query_id — which is the §12.4
    multiple-testing record.

    There is no direction parameter, and there cannot be one: the returned
    distribution covers both directions over the same analog set (§6.4).
    """
    committed.verify()
    if expected_query_id != committed.query_id:
        raise QueryCommitmentError(
            f"refusing to run: the committed query is {committed.query_id} but the "
            f"caller pre-registered {expected_query_id}. An analog search runs only "
            f"against the definition committed before the result was seen (§6.4, §12.4)"
        )

    # Two observations sharing an id are two rows of history that the audit
    # trail cannot tell apart, and the second one silently overwrites the
    # first's similarity distance. Fail closed rather than report a count whose
    # provenance cannot be reconstructed (§0.10, §0.11).
    seen: set[str] = set()
    repeated: set[str] = set()
    for record in observations:
        if record.observation_id in seen:
            repeated.add(record.observation_id)
        seen.add(record.observation_id)
    if repeated:
        duplicates = sorted(repeated)
        raise ValueError(
            f"observations {duplicates} appear more than once: each historical "
            f"observation must be uniquely identified or the analog count cannot be "
            f"reconstructed from the source data (§0.11, §12.7 rule 3)"
        )

    query = committed.query
    as_of = query.as_of_utc.astimezone(UTC)
    embargo_start = as_of - dt.timedelta(days=query.embargo_days)
    regimes = set(query.regime_filter)

    wrong_instrument = out_of_range = horizon_mismatch = 0
    lookahead = embargoed = incomplete = missing_features = wrong_regime = 0
    eligible: list[HistoricalObservation] = []
    distances: dict[str, Decimal] = {}

    for obs in observations:
        if obs.instrument != query.instrument:
            wrong_instrument += 1
            continue
        if not (query.start_date <= obs.session_date <= query.end_date):
            out_of_range += 1
            continue
        if obs.horizon_minutes != query.horizon_minutes:
            horizon_mismatch += 1
            continue
        # §12.4 no future leakage: an analog whose outcome had not yet completed
        # at the decision moment was not knowable then and is not evidence now.
        if obs.outcome_observed_at > as_of:
            lookahead += 1
            continue
        if obs.outcome_observed_at > embargo_start:
            embargoed += 1
            continue
        if not obs.data_complete:
            incomplete += 1
            continue
        distance = _distance(query, obs)
        if distance is None:
            missing_features += 1
            continue
        if regimes and obs.regime not in regimes:
            wrong_regime += 1
            continue
        eligible.append(obs)
        distances[obs.observation_id] = distance

    def at_scale(scale: Decimal) -> list[HistoricalObservation]:
        return [o for o in eligible if distances[o.observation_id] <= scale]

    cost = query.cost_model.round_trip_cost_pips
    primary = at_scale(PRIMARY_THRESHOLD_SCALE)

    sensitivity: list[SensitivityPoint] = []
    for scale in query.threshold_scales:
        matched = at_scale(scale)
        sensitivity.append(
            SensitivityPoint(
                threshold_scale=scale,
                analog_count=len(matched),
                independent_sample=_independent_sample(matched),
                distribution=_distribution(matched, cost),
            )
        )

    regime_breakdown: list[RegimeSlice] = []
    for regime in sorted({o.regime for o in primary}):
        members = [o for o in primary if o.regime == regime]
        regime_breakdown.append(
            RegimeSlice(
                regime=regime,
                analog_count=len(members),
                independent_sample=_independent_sample(members),
                distribution=_distribution(members, cost),
            )
        )

    limitations = _limitations(
        query=query,
        observations_supplied=len(observations),
        wrong_instrument=wrong_instrument,
        out_of_range=out_of_range,
        horizon_mismatch=horizon_mismatch,
        lookahead=lookahead,
        embargoed=embargoed,
        incomplete=incomplete,
        missing_features=missing_features,
        wrong_regime=wrong_regime,
        eligible=eligible,
        primary=primary,
    )

    return AnalogReport(
        query=query,
        query_id=committed.query_id,
        similarity_method=query.similarity_method,
        analog_count=len(primary),
        independent_sample=_independent_sample(primary),
        outcome_distribution=_distribution(primary, cost),
        regime_breakdown=tuple(regime_breakdown),
        threshold_sensitivity=tuple(sensitivity),
        data_limitations=limitations,
        cost_model=query.cost_model,
        generated_at=generated_at,
    )


def _limitations(
    *,
    query: AnalogQuery,
    observations_supplied: int,
    wrong_instrument: int,
    out_of_range: int,
    horizon_mismatch: int,
    lookahead: int,
    embargoed: int,
    incomplete: int,
    missing_features: int,
    wrong_regime: int,
    eligible: Sequence[HistoricalObservation],
    primary: Sequence[HistoricalObservation],
) -> DataLimitations:
    """Assemble §6.4 item 7 from what the search actually discarded.

    The notes are computed, not authored, so they cannot be softened while the
    counts stay honest — and there is always at least one, because the standing
    caveat about what a base rate is applies to every report ever produced here.
    """
    notes: list[str] = [
        f"base rates are computed from {query.data_source_id} only; they describe what "
        f"this data source recorded, not the market, and imply no profitability (§0.5)",
    ]
    if lookahead:
        notes.append(
            f"{lookahead} observation(s) discarded: their forward outcome completes "
            f"after the as-of moment and was not knowable at decision time (§12.4)"
        )
    if embargoed:
        notes.append(
            f"{embargoed} observation(s) discarded by the {query.embargo_days}-day "
            f"embargo: outcomes overlapping the decision window are excluded (§12.4)"
        )
    if incomplete:
        notes.append(
            f"{incomplete} observation(s) discarded as incomplete data — a known "
            f"coverage hole in the eligible population (§12.7 rule 6)"
        )
    if missing_features:
        notes.append(
            f"{missing_features} observation(s) discarded for lacking at least one "
            f"queried feature; the eligible population is therefore biased toward "
            f"periods with complete feature coverage (§12.4)"
        )
    if horizon_mismatch:
        notes.append(
            f"{horizon_mismatch} observation(s) discarded for a forward horizon other "
            f"than {query.horizon_minutes} minutes; outcomes measured over different "
            f"horizons are not comparable"
        )
    if wrong_regime:
        notes.append(
            f"{wrong_regime} eligible observation(s) excluded by the regime filter "
            f"{list(query.regime_filter)}; the base rate is conditional on that filter"
        )
    distinct_primary = _independent_sample(primary)
    if len(primary) > distinct_primary:
        notes.append(
            f"{len(primary)} analogs come from only {distinct_primary} distinct "
            f"session(s): observations inside one session overlap, so the effective "
            f"sample is the session count and §12.6 is measured against it, not the "
            f"analog count"
        )
    if not primary:
        notes.append(
            "no analogs matched at the committed tolerances; this report establishes "
            "no base rate and cannot support any §12.6 decision"
        )
    return DataLimitations(
        observations_supplied=observations_supplied,
        excluded_wrong_instrument=wrong_instrument,
        excluded_outside_date_range=out_of_range,
        excluded_horizon_mismatch=horizon_mismatch,
        excluded_lookahead=lookahead,
        excluded_by_embargo=embargoed,
        excluded_incomplete_data=incomplete,
        excluded_missing_features=missing_features,
        excluded_by_regime_filter=wrong_regime,
        eligible_population=len(eligible),
        distinct_session_dates_eligible=_independent_sample(eligible),
        known_coverage_gaps=query.known_coverage_gaps,
        notes=tuple(notes),
    )


__all__ = [
    "ANALOG_ENGINE_VERSION",
    "MINIMUM_SAMPLE",
    "PRIMARY_THRESHOLD_SCALE",
    "REQUIRED_REVIEW_COVERAGE",
    "AdversarialReview",
    "AnalogQuery",
    "AnalogReport",
    "CommittedQuery",
    "CostModel",
    "DataLimitations",
    "DirectionalOutcomes",
    "EvidenceSufficiency",
    "EvidenceUse",
    "FeatureTolerance",
    "HistoricalObservation",
    "OutcomeDistribution",
    "PublicationGateError",
    "QueryCommitmentError",
    "RegimeSlice",
    "SensitivityPoint",
    "SimilarityMethod",
    "commit_query",
    "search_analogs",
]
