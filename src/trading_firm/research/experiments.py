"""Experiment and multiple-testing ledger (§12.4) — research environment only.

§12.4 requires a "multiple-testing record" and "trial-count tracking across
indicators, parameter sets, strategies, and agent-generated variants". §22
Phase 3 lists the ledger as an outstanding deliverable. Until now the firm kept
that record in prose: `governance/decision-log.md` carries a breakout baseline,
three spent exit-variant tests, and one first look each for sweep-reversal and
continuation — six looks at a single six-week GBP_USD sample, recorded as
paragraphs a human has to remember.

A count that lives in a paragraph fails silently. At α = 0.05 the twentieth
hypothesis tested against one sample is *expected* to produce one spurious
"significant" result whether or not any edge exists, and that result reads
exactly like the first one's. Nothing in a green test suite objects. §12.7 was
ratified after precisely this class of failure — persuasive, silent, and
survives every test. This module makes the correction **computed rather than
remembered**: the ledger holds the trial count, and the threshold a new result
must clear is derived from it.

**Which correction, and when (§12.4).**

*Bonferroni* (`required_p_value`, `bonferroni_threshold`) controls the
family-wise error rate — the probability of *any* false positive among m tests.
It is the correction that governs a promotion decision. §12.5 promotion moves a
strategy toward real capital, §12.6 sets the evidence a promotion needs, and one
false positive there is a live losing strategy. When a single mistake is the
thing you cannot afford, control the probability of a single mistake. Bonferroni
also makes no independence assumption, which matters here: three exit variants
replayed over one trade set are massively dependent tests.

*Benjamini-Hochberg* (`benjamini_hochberg`) controls the false discovery rate —
the expected *proportion* of false positives among results declared significant.
It is the right tool for screening: ranking twenty candidate features or regimes
to decide which two deserve a confirmation sample, where tolerating a known
fraction of duds is cheaper than missing every real effect. It must never be
used to justify a promotion. BH's guarantee also assumes independent or
positively-dependent tests; variant sweeps over one sample violate that, so a BH
result on this firm's historical GBP sample is indicative at best. Both are
provided, and the docstrings say which is which, because the failure mode is not
using the wrong formula — it is quietly picking whichever one clears.

**Exhaustion.** Correction alone is not enough. Past some trial count the
required threshold falls below what the sample can resolve at all, and the
honest answer stops being "adjust the p-value" and becomes "get new data".
`SampleStatus.exhausted` says so, and `assert_not_exhausted` fails closed
(§0.10) rather than returning a number that would be published.

**Pre-registration (§12.4).** "Pre-registered hypothesis or experiment record
before confirmation testing" is a requirement, not a label. A hypothesis fitted
after seeing the result and then described as pre-registered is the single
cheapest way to launder an overfit. So the ledger only calls an experiment
pre-registered when it witnessed the registration before any result existed:
`register()` refuses a p-value, `record_result()` cannot change the registration
class, and a completed pre-registered record inserted directly through `add()`
must cite the governance record that proves prior registration (§0.11).
`record_post_hoc()` is the only other way in, and it stamps POST_HOC.

**Publication gate (§12.7 / A-1).** Everything here is research code, so no
number it produces may enter a validation report, a promotion record, or a
§12.6 evidence count until the paths producing it have passed an independent,
refutation-default adversarial review. `publication_table()` raises unless the
ledger was constructed with an explicit clearance and a review reference. No
code path in this package sets that flag.

**Pressure invariance (A-2, §5.1).** This module never imports or references
`FirmSnapshot`. Statistical significance is a property of the data and the
number of times it has been interrogated. It does not move because the firm is
behind on the month, and firm state must not be able to reach a threshold
computation even by accident. `tests/unit/test_experiments.py` pins that at
source level.
"""

from __future__ import annotations

import datetime as dt
import enum
from dataclasses import dataclass
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# §12.4 does not fix a significance level; 0.05 is the conventional default the
# ledger corrects FROM. Every public method takes an override so a stricter
# promotion review can raise the bar without editing this module.
DEFAULT_ALPHA = Decimal("0.05")

# Below this, a p-value is not a measurement. With the sample sizes §12.6
# contemplates (30 signals, 50 trades) nothing distinguishes p = 0.0008 from
# p = 0.003; a required threshold under the floor means the sample has been
# asked more questions than it can answer.
DEFAULT_RESOLUTION_FLOOR = Decimal("0.001")


class SampleRole(enum.StrEnum):
    """§12.4: "separate discovery and confirmation samples"."""

    DISCOVERY = "discovery"  # where hypotheses may be generated and refined
    CONFIRMATION = "confirmation"  # tests a hypothesis fixed before the split
    HOLDOUT = "holdout"  # §12.4 immutable holdout: inspected once, ever


class Registration(enum.StrEnum):
    """Whether the hypothesis existed before the result did (§12.4).

    Kept as an enum rather than a bool so that "we never established this"
    cannot be spelled the same way as False and read as "post-hoc, and we
    checked".
    """

    PRE_REGISTERED = "pre_registered"
    POST_HOC = "post_hoc"

    @property
    def may_support_confirmation(self) -> bool:
        """§12.4 requires a pre-registered record *before* confirmation testing.

        A post-hoc hypothesis can motivate the next experiment. It can never be
        the confirmation of itself.
        """
        return self is Registration.PRE_REGISTERED


class ExperimentOutcome(enum.StrEnum):
    """What the experiment did to the sample, not whether the firm liked it."""

    PENDING = "pending"  # registered, not yet run — no look at the data
    SUPPORTED = "supported"
    REFUTED = "refuted"
    INCONCLUSIVE = "inconclusive"
    ABANDONED = "abandoned"  # registered then dropped without running

    @property
    def consumed_the_sample(self) -> bool:
        """True when the sample was actually interrogated.

        A refuted or inconclusive test costs exactly as much multiplicity as a
        supported one. Counting only the wins is how a trial count silently
        under-reports (§12.4).
        """
        return self in (
            ExperimentOutcome.SUPPORTED,
            ExperimentOutcome.REFUTED,
            ExperimentOutcome.INCONCLUSIVE,
        )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Sample(_Strict):
    """A named body of data that experiments are run against.

    Samples are declared before use so that "which data" is never implicit.
    Two strategies replayed over the same six weeks of GBP_USD M5 bars are
    testing the same sample however differently their reports are titled, and
    the multiplicity is shared whether or not anyone noticed.
    """

    sample_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    instrument: str = Field(min_length=1)
    role: SampleRole
    first_session: dt.date
    last_session: dt.date
    # §12.7 requirement 6, honest denominators: sessions actually capable of
    # producing features, not calendar days in the range.
    sessions: int = Field(ge=0)
    known_coverage_holes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _dates_ordered(self) -> Sample:
        if self.last_session < self.first_session:
            raise ValueError(
                f"sample {self.sample_id!r} ends {self.last_session} before it begins "
                f"{self.first_session}: a sample's range must be stated honestly (§12.7)"
            )
        return self


class Experiment(_Strict):
    """One recorded test of one hypothesis against one sample (§12.4).

    `variants_tested` is the multiplicity this single record carries. A
    selection event over three exit variants is three tests, not one, because
    the best of three was chosen — that is exactly the trial count §12.4 asks
    to be tracked "across indicators, parameter sets, strategies, and
    agent-generated variants".
    """

    hypothesis_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    sample_id: str = Field(min_length=1)
    metric: str = Field(min_length=1)  # which §12.3 metric the test was on
    registration: Registration
    registered_at: dt.datetime
    outcome: ExperimentOutcome
    tested_at: dt.datetime | None = None
    p_value: Decimal | None = Field(default=None, ge=0, le=1)
    variants_tested: int = Field(default=1, ge=1)
    report_reference: str | None = None
    provenance: str | None = None  # governance record proving prior registration
    notes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _timestamps_aware(self) -> Experiment:
        if self.registered_at.tzinfo is None:
            raise ValueError(
                f"{self.hypothesis_id}: registered_at must be timezone-aware — a naive "
                f"registration time cannot be shown to precede a test (§12.4, §10.3)"
            )
        if self.tested_at is not None and self.tested_at.tzinfo is None:
            raise ValueError(
                f"{self.hypothesis_id}: tested_at must be timezone-aware (§12.4, §10.3)"
            )
        return self

    @model_validator(mode="after")
    def _registration_precedes_test(self) -> Experiment:
        # The whole value of a pre-registration is its position in time. A
        # record claiming registration after the test is a retro-fit.
        if self.tested_at is not None and self.registered_at > self.tested_at:
            raise ValueError(
                f"{self.hypothesis_id}: registered_at {self.registered_at.isoformat()} is after "
                f"tested_at {self.tested_at.isoformat()} — a hypothesis recorded after its own "
                f"result is post-hoc by definition and must be filed as POST_HOC (§12.4)"
            )
        return self

    @model_validator(mode="after")
    def _outcome_matches_evidence(self) -> Experiment:
        if self.outcome.consumed_the_sample:
            if self.tested_at is None:
                raise ValueError(
                    f"{self.hypothesis_id}: outcome {self.outcome.value} without a tested_at — "
                    f"an experiment cannot have a result it was never run to produce (§12.4)"
                )
        else:
            if self.tested_at is not None or self.p_value is not None:
                raise ValueError(
                    f"{self.hypothesis_id}: outcome {self.outcome.value} carries a test time or "
                    f"p-value — a pending or abandoned experiment has not looked at the sample, "
                    f"and recording one that has understates the trial count (§12.4)"
                )
        return self

    @property
    def tests_spent(self) -> int:
        """Multiplicity this record contributes to its sample.

        Zero until the experiment is actually run: a registration that was never
        executed took no look at the data. Registering many and running few is
        not penalized; running many and reporting one is.
        """
        return self.variants_tested if self.outcome.consumed_the_sample else 0

    @property
    def is_selection_event(self) -> bool:
        """True when a winner was chosen among variants — the classic overfit."""
        return self.tests_spent > 1


@dataclass(frozen=True)
class BHDecision:
    """One row of a Benjamini-Hochberg step-up procedure."""

    hypothesis_id: str
    p_value: Decimal
    rank: int  # 1-based, ascending p
    critical_value: Decimal  # (rank / m) * alpha
    significant: bool


@dataclass(frozen=True)
class SampleStatus:
    """The state of one sample's multiplicity budget (§12.4)."""

    sample_id: str
    role: SampleRole
    alpha: Decimal
    tests_recorded: int
    selection_events: int
    pending_registrations: int
    bonferroni_threshold: Decimal  # applies to the tests already recorded
    next_test_threshold: Decimal  # what a NEW result must clear
    expected_false_positives: Decimal  # tests_recorded * alpha
    exhausted: bool
    reasons: tuple[str, ...]

    @property
    def headroom(self) -> bool:
        return not self.exhausted


class ExperimentLedger:
    """The firm's trial count, keyed by sample (§12.4, §22 Phase 3).

    Mutable by design — it accumulates registrations and results — but every
    record it hands back is frozen, and nothing it holds can be silently
    downgraded to a smaller trial count.
    """

    def __init__(
        self,
        alpha: Decimal = DEFAULT_ALPHA,
        resolution_floor: Decimal = DEFAULT_RESOLUTION_FLOOR,
        publication_cleared: bool = False,
        review_reference: str | None = None,
    ) -> None:
        if not (Decimal(0) < alpha < Decimal(1)):
            raise ValueError(
                f"alpha must lie strictly between 0 and 1, got {alpha}: a significance level "
                f"outside that range corrects nothing (§12.4)"
            )
        if not (Decimal(0) < resolution_floor < alpha):
            raise ValueError(
                f"resolution_floor {resolution_floor} must lie strictly between 0 and alpha "
                f"{alpha}: a floor at or above alpha would mark a sample exhausted before its "
                f"first test (§12.4)"
            )
        # Read-only for the same reason publication_cleared is: a correction
        # that can be loosened after the fact corrects nothing. `alpha = 0.9`
        # after six spent tests produced a "corrected" threshold looser than the
        # uncorrected one, and `resolution_floor = 0` permanently disabled the
        # exhaustion branch — both with a single assignment and no error.
        self._alpha_level = alpha
        self._resolution_floor = resolution_floor
        # §12.7 / A-1: defaults False and is never set True by library code.
        # Held privately behind read-only properties. A plain writable
        # attribute would let any caller flip the flag after construction and
        # walk an unreviewed number straight into a promotion record — the gate
        # has to be harder to open than the thing it guards is tempting.
        if publication_cleared and not (review_reference or "").strip():
            raise ValueError(
                "publication_cleared cannot be set True without a review_reference: §12.7 "
                "requirement 7 makes the review outcome an audit-trail entry, so a clearance "
                "with nothing to point at is not a clearance (§12.7, A-1)"
            )
        self._publication_cleared = publication_cleared
        self._review_reference = review_reference
        self._samples: dict[str, Sample] = {}
        self._experiments: dict[str, Experiment] = {}
        # §12.4: the latest moment this ledger has witnessed. A pre-registration
        # backdated behind it is not a pre-registration.
        self._latest_witnessed: dt.datetime | None = None

    @property
    def alpha(self) -> Decimal:
        """The uncorrected significance level. Fixed at construction (§12.4)."""
        return self._alpha_level

    @property
    def resolution_floor(self) -> Decimal:
        """Below this, a sample can no longer distinguish an edge from a
        coincidence. Fixed at construction (§12.4)."""
        return self._resolution_floor

    @property
    def publication_cleared(self) -> bool:
        """§12.7 gate. Read-only: clearance is granted at construction by a
        caller that has an adversarial-review record, never by assignment."""
        return self._publication_cleared

    @property
    def review_reference(self) -> str | None:
        return self._review_reference

    # ------------------------------------------------------------------ samples

    def add_sample(self, sample: Sample) -> Sample:
        if sample.sample_id in self._samples:
            raise ValueError(
                f"sample {sample.sample_id!r} is already declared: redeclaring a sample would "
                f"reset its trial count, which is the failure this ledger exists to prevent "
                f"(§12.4)"
            )
        self._samples[sample.sample_id] = sample
        return sample

    def sample(self, sample_id: str) -> Sample:
        try:
            return self._samples[sample_id]
        except KeyError:
            raise KeyError(
                f"sample {sample_id!r} was never declared: declare the data an experiment runs "
                f"against before recording the experiment, or its multiplicity attaches to "
                f"nothing (§12.4)"
            ) from None

    @property
    def sample_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._samples))

    # -------------------------------------------------------------- experiments

    def add(self, experiment: Experiment, provenance: str | None = None) -> Experiment:
        """Insert a fully-formed record.

        Used for importing history and for tests. A completed record that claims
        PRE_REGISTERED status must cite the governance record that proves the
        hypothesis was written down before the result existed (§0.11, §12.4);
        otherwise the honest paths are `register()` then `record_result()`, or
        `record_post_hoc()`.
        """
        self.sample(experiment.sample_id)  # raises if undeclared
        if experiment.hypothesis_id in self._experiments:
            raise ValueError(
                f"hypothesis {experiment.hypothesis_id!r} is already in the ledger: reusing an "
                f"id would overwrite a spent test and understate the trial count (§12.4)"
            )
        cited = provenance if provenance is not None else experiment.provenance
        if (
            experiment.registration is Registration.PRE_REGISTERED
            and experiment.outcome.consumed_the_sample
            and not (cited or "").strip()
        ):
            raise ValueError(
                f"{experiment.hypothesis_id}: a completed pre-registered result added directly "
                f"must cite the governance record proving the hypothesis was registered before "
                f"testing — without it the ledger is asserting a pre-registration it never "
                f"witnessed (§12.4, §0.11). Use register() then record_result(), or "
                f"record_post_hoc()."
            )
        stored = (
            experiment
            if cited == experiment.provenance
            else experiment.model_copy(update={"provenance": cited})
        )
        self._experiments[stored.hypothesis_id] = stored
        # Every dated event advances the witness clock, so a later
        # pre-registration cannot be backdated behind it (§12.4).
        self._witness(stored.registered_at)
        self._witness(stored.tested_at)
        return stored

    def register(
        self,
        hypothesis_id: str,
        description: str,
        sample_id: str,
        metric: str,
        registered_at: dt.datetime,
    ) -> Experiment:
        """Pre-register a hypothesis BEFORE testing it (§12.4).

        Takes no outcome and no p-value, and there is no parameter through which
        one could be supplied. That is the point: the ledger can only stamp
        PRE_REGISTERED on something it saw arrive empty.

        That alone was not enough. An adversarial review pointed out that a
        researcher who has already seen p=0.002 can call `register()` with a
        `registered_at` a month in the past and then `record_result()` — two
        ordinary calls, no provenance, and the record claims pre-registration.
        So the registration timestamp is now checked against the latest moment
        this ledger has witnessed: you cannot register a hypothesis as of a date
        earlier than events already on the books.

        **The limit of this guarantee, stated rather than glossed.** It makes
        backdating detectable only to the extent the ledger has already seen
        later events; a registration backdated on a fresh ledger is still
        accepted, because nothing here can witness what happened before it
        existed. A real pre-registration guarantee needs an external witness —
        a commit hash, a signed timestamp — and §12.4 compliance still rests on
        the researcher registering honestly. This narrows the hole; it does not
        close it, and the docstring should not pretend otherwise.
        """
        self._require_not_backdated(registered_at, "a hypothesis")
        experiment = Experiment(
            hypothesis_id=hypothesis_id,
            description=description,
            sample_id=sample_id,
            metric=metric,
            registration=Registration.PRE_REGISTERED,
            registered_at=registered_at,
            outcome=ExperimentOutcome.PENDING,
        )
        return self.add(experiment)

    def _require_not_backdated(self, moment: dt.datetime, what: str) -> None:
        """§12.4: reject a timestamp behind what this ledger already witnessed."""
        if moment.tzinfo is None:
            raise ValueError(f"{what} needs a timezone-aware timestamp (§10.3)")
        latest = self._latest_witnessed
        if latest is not None and moment < latest:
            raise ValueError(
                f"cannot register {what} as of {moment.isoformat()}: this ledger has "
                f"already witnessed events up to {latest.isoformat()}, so a registration "
                f"dated earlier is a reconstruction, not a pre-registration (§12.4)"
            )

    def _witness(self, moment: dt.datetime | None) -> None:
        if moment is None:
            return
        if self._latest_witnessed is None or moment > self._latest_witnessed:
            self._latest_witnessed = moment

    def record_result(
        self,
        hypothesis_id: str,
        outcome: ExperimentOutcome,
        tested_at: dt.datetime,
        p_value: Decimal | None = None,
        variants_tested: int = 1,
        report_reference: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> Experiment:
        """Attach a result to an already-registered hypothesis.

        The registration class is carried over untouched — a result cannot
        promote a post-hoc record to pre-registered, and a second result cannot
        overwrite the first and quietly refund the test that was already spent.
        """
        existing = self.experiment(hypothesis_id)
        if existing.outcome.consumed_the_sample:
            raise ValueError(
                f"{hypothesis_id} already has result {existing.outcome.value} recorded at "
                f"{existing.tested_at.isoformat() if existing.tested_at else 'unknown'}: a spent "
                f"test is never overwritten, because re-running it is a new test (§12.4, §0.11)"
            )
        if not outcome.consumed_the_sample and outcome is not ExperimentOutcome.ABANDONED:
            raise ValueError(
                f"{hypothesis_id}: record_result requires an outcome that reflects a run test or "
                f"ABANDONED, got {outcome.value} (§12.4)"
            )
        updated = Experiment(
            hypothesis_id=existing.hypothesis_id,
            description=existing.description,
            sample_id=existing.sample_id,
            metric=existing.metric,
            # Carried from the existing record, never recomputed: a result
            # cannot promote its own hypothesis to pre-registered. Mutating this
            # line to Registration.PRE_REGISTERED left all 65 tests green, so
            # `test_a_result_cannot_upgrade_a_post_hoc_registration` now pins it.
            registration=existing.registration,
            registered_at=existing.registered_at,
            outcome=outcome,
            tested_at=tested_at if outcome.consumed_the_sample else None,
            p_value=p_value if outcome.consumed_the_sample else None,
            variants_tested=variants_tested,
            report_reference=report_reference,
            provenance=existing.provenance,
            notes=notes,
        )
        self._experiments[hypothesis_id] = updated
        return updated

    def record_post_hoc(
        self,
        hypothesis_id: str,
        description: str,
        sample_id: str,
        metric: str,
        outcome: ExperimentOutcome,
        tested_at: dt.datetime,
        p_value: Decimal | None = None,
        variants_tested: int = 1,
        report_reference: str | None = None,
        notes: tuple[str, ...] = (),
    ) -> Experiment:
        """Record a hypothesis formed after seeing the result (§12.4).

        Legitimate and common — most good ideas start this way. It is recorded
        with the same trial cost as any other look at the sample and stamped
        POST_HOC, so a later reader cannot mistake it for confirmation. There is
        no argument to this method that makes it pre-registered.
        """
        experiment = Experiment(
            hypothesis_id=hypothesis_id,
            description=description,
            sample_id=sample_id,
            metric=metric,
            registration=Registration.POST_HOC,
            registered_at=tested_at,
            outcome=outcome,
            tested_at=tested_at if outcome.consumed_the_sample else None,
            p_value=p_value if outcome.consumed_the_sample else None,
            variants_tested=variants_tested,
            report_reference=report_reference,
            notes=notes,
        )
        return self.add(experiment)

    def experiment(self, hypothesis_id: str) -> Experiment:
        try:
            return self._experiments[hypothesis_id]
        except KeyError:
            raise KeyError(
                f"hypothesis {hypothesis_id!r} is not in the ledger: register it before "
                f"recording a result, or file it with record_post_hoc (§12.4)"
            ) from None

    def experiments(self, sample_id: str | None = None) -> tuple[Experiment, ...]:
        """Every recorded experiment, oldest registration first."""
        if sample_id is not None:
            self.sample(sample_id)
        rows = [
            e
            for e in self._experiments.values()
            if sample_id is None or e.sample_id == sample_id
        ]
        return tuple(sorted(rows, key=lambda e: (e.registered_at, e.hypothesis_id)))

    # ------------------------------------------------------------------ counting

    def tests_recorded(self, sample_id: str) -> int:
        """Total looks taken at this sample, variants included (§12.4)."""
        return sum(e.tests_spent for e in self.experiments(sample_id))

    def selection_events(self, sample_id: str) -> int:
        """Experiments that chose a winner among variants."""
        return sum(1 for e in self.experiments(sample_id) if e.is_selection_event)

    def pending_registrations(self, sample_id: str) -> int:
        """Pre-registered hypotheses not yet run against this sample."""
        return sum(
            1 for e in self.experiments(sample_id) if e.outcome is ExperimentOutcome.PENDING
        )

    # ---------------------------------------------------------------- correction

    def _alpha(self, alpha: Decimal | None) -> Decimal:
        resolved = self.alpha if alpha is None else alpha
        if not (Decimal(0) < resolved < Decimal(1)):
            raise ValueError(
                f"alpha must lie strictly between 0 and 1, got {resolved} (§12.4)"
            )
        return resolved

    def bonferroni_threshold(self, sample_id: str, alpha: Decimal | None = None) -> Decimal:
        """Family-wise-error threshold across the tests ALREADY recorded: α / m.

        Use this to re-read a published claim: a result reported at p = 0.04
        from the fourth of six tests against one sample never cleared 0.05/6.
        Bonferroni is the correction that governs promotion (§12.5) because it
        bounds the probability of *any* false positive and assumes nothing about
        independence — and variant sweeps over one trade set are not independent.

        With no tests recorded the denominator is 1: the first test faces the
        uncorrected level, which is correct rather than lenient.
        """
        a = self._alpha(alpha)
        m = max(self.tests_recorded(sample_id), 1)
        return a / Decimal(m)

    def required_p_value(self, sample_id: str, alpha: Decimal | None = None) -> Decimal:
        """The question that matters: what must the NEXT result clear?

        Given m tests already spent against this sample, a new result is the
        (m+1)-th member of the family, so the Bonferroni threshold is
        α / (m + 1). Six spent tests against the GBP sample means the seventh
        must clear 0.05/7 ≈ 0.00714, not 0.05 — and a strategy that reports
        p = 0.03 there has shown nothing.

        Pending registrations are deliberately excluded: a hypothesis written
        down but never run took no look at the data. It will cost its test when
        it is run, not before.
        """
        a = self._alpha(alpha)
        return a / Decimal(self.tests_recorded(sample_id) + 1)

    def benjamini_hochberg(
        self, sample_id: str, alpha: Decimal | None = None
    ) -> tuple[BHDecision, ...]:
        """Benjamini-Hochberg step-up over this sample's recorded p-values.

        Controls the false discovery rate — the expected proportion of false
        positives among the results declared significant. Appropriate for
        SCREENING: deciding which of many candidate features or regimes earns a
        confirmation sample (§12.4, "separate discovery and confirmation
        samples"). It is more powerful than Bonferroni and correspondingly more
        permissive, and that trade is only acceptable when a false discovery
        costs another experiment rather than live capital.

        Never use this to justify a promotion. §12.5 promotion is a single
        decision whose false-positive cost is a losing strategy with real money
        behind it; that is a family-wise-error problem, so `required_p_value` is
        the binding number there. BH additionally assumes independent or
        positively-dependent tests, which repeated variant sweeps over one trade
        set violate — treat a BH verdict on such a family as indicative only.

        The family size `m` is `tests_recorded`, NOT the number of p-values.

        An earlier version used `len(scored)`, which silently discarded
        `variants_tested`: a 19-variant sweep reporting only its best p-value
        counted as ONE member of the family, while Bonferroni over the same
        ledger counted twenty. An adversarial review showed the consequence — a
        19-variant sweep at p=0.02 plus one test at p=0.04 were BOTH declared
        significant, when the sweep is exactly the multiplicity BH exists to
        price. Experiments without a p-value are still excluded from the
        ranking, but they now inflate `m` as they should, which is what the
        phrase "their multiplicity is not lost" was always supposed to mean.
        """
        a = self._alpha(alpha)
        scored: list[tuple[Decimal, str]] = sorted(
            (e.p_value, e.hypothesis_id)
            for e in self.experiments(sample_id)
            if e.p_value is not None
        )
        if not scored:
            return ()
        # Never below len(scored): a family cannot be smaller than the number of
        # results drawn from it.
        m = Decimal(max(self.tests_recorded(sample_id), len(scored)))
        ranked = [
            (rank, p, hypothesis_id, (Decimal(rank) / m) * a)
            for rank, (p, hypothesis_id) in enumerate(scored, start=1)
        ]
        # Step-up: the LARGEST rank whose p-value is under its critical value
        # carries every smaller rank with it, including ranks that individually
        # fail their own threshold. Getting this backwards (rejecting only the
        # ranks that individually pass) is the common BH implementation bug and
        # is conservative in one direction, anti-conservative in the other.
        largest = 0
        for rank, p, _, critical in ranked:
            if p <= critical:
                largest = rank
        return tuple(
            BHDecision(
                hypothesis_id=hypothesis_id,
                p_value=p,
                rank=rank,
                critical_value=critical,
                significant=rank <= largest,
            )
            for rank, p, hypothesis_id, critical in ranked
        )

    # ---------------------------------------------------------------- exhaustion

    def status(self, sample_id: str, alpha: Decimal | None = None) -> SampleStatus:
        """Whether this sample can still answer a question honestly (§12.4)."""
        a = self._alpha(alpha)
        sample = self.sample(sample_id)
        m = self.tests_recorded(sample_id)
        next_threshold = a / Decimal(m + 1)
        expected_fp = Decimal(m) * a
        reasons: list[str] = []

        if sample.role is SampleRole.HOLDOUT and m >= 1:
            reasons.append(
                f"{sample_id} is an immutable holdout and has already been inspected {m} "
                f"time(s): a holdout answers one question, once (§12.4)"
            )
        if expected_fp >= Decimal(1):
            reasons.append(
                f"{m} tests at alpha {a} expect {expected_fp} spurious 'significant' results by "
                f"chance alone: this sample can no longer distinguish an edge from a coincidence "
                f"(§12.4)"
            )
        if next_threshold < self.resolution_floor:
            reasons.append(
                f"the next test would have to clear {next_threshold} — below the "
                f"{self.resolution_floor} resolution floor, which samples of the size §12.6 "
                f"contemplates cannot measure (§12.4, §12.6)"
            )

        return SampleStatus(
            sample_id=sample_id,
            role=sample.role,
            alpha=a,
            tests_recorded=m,
            selection_events=self.selection_events(sample_id),
            pending_registrations=self.pending_registrations(sample_id),
            bonferroni_threshold=a / Decimal(max(m, 1)),
            next_test_threshold=next_threshold,
            expected_false_positives=expected_fp,
            exhausted=bool(reasons),
            reasons=tuple(reasons),
        )

    def assert_not_exhausted(self, sample_id: str, alpha: Decimal | None = None) -> SampleStatus:
        """Fail closed before spending a test on a sample that cannot pay out.

        §0.10's posture applied to research: when the data can no longer answer,
        the correct output is a refusal naming the honest path — new data — not
        a corrected p-value nobody will read past.
        """
        state = self.status(sample_id, alpha)
        if state.exhausted:
            joined = "; ".join(state.reasons)
            raise ValueError(
                f"sample {sample_id!r} is exhausted after {state.tests_recorded} tests: {joined}. "
                f"No result from further testing of this sample should be trusted; the honest "
                f"path is new data (§12.4)"
            )
        return state

    # --------------------------------------------------------------- publication

    def _require_publication_clearance(self) -> None:
        """§12.7 / A-1 publication gate.

        A research number is order-path-adjacent in consequence: it decides
        which strategy advances toward real capital. Formatting one for a
        report is the act §12.7 gates, so the gate lives on the formatter and
        not on the arithmetic — the counts above stay available to reviewers
        while the report stays blocked.

        Only the flag is checked here. The companion requirement — that a
        clearance point at an actual review record (§12.7 requirement 7) — is
        enforced at construction instead, because both fields are read-only
        from then on. Re-checking it here would be unreachable code asserting a
        guarantee that already holds.
        """
        if not self.publication_cleared:
            raise ValueError(
                "publication_cleared is False: no number produced by research code may be "
                "published in a validation report, cited in a promotion record, or counted "
                "toward §12.6 minimum evidence until the code paths producing it have passed "
                "an independent, refutation-default adversarial review (§12.7, A-1)"
            )

    def publication_table(self, sample_id: str, alpha: Decimal | None = None) -> str:
        """Render this sample's multiple-testing record for a validation report.

        Gated by §12.7. Reports the honest denominator (sessions actually
        capable of producing features), known coverage holes, the trial count,
        and the corrected threshold, because §12.7 requirement 6 makes a report
        that overstates its own evidence a §12.4 violation even when every P&L
        figure is correct.
        """
        self._require_publication_clearance()
        state = self.status(sample_id, alpha)
        sample = self.sample(sample_id)
        holes = ", ".join(sample.known_coverage_holes) or "none disclosed"
        lines = [
            f"Multiple-testing record — {sample.sample_id} ({sample.role.value}) [§12.4]",
            f"  review: {self.review_reference}",
            f"  instrument: {sample.instrument}",
            f"  range: {sample.first_session} .. {sample.last_session}",
            f"  sessions capable of producing features: {sample.sessions}",
            f"  known coverage holes: {holes}",
            f"  tests recorded: {state.tests_recorded} "
            f"(selection events: {state.selection_events}, "
            f"pending registrations: {state.pending_registrations})",
            f"  alpha: {state.alpha}",
            f"  Bonferroni threshold across recorded tests: {state.bonferroni_threshold}",
            f"  threshold a NEW result must clear: {state.next_test_threshold}",
            f"  expected spurious results at nominal alpha: {state.expected_false_positives}",
            f"  exhausted: {state.exhausted}",
        ]
        lines.extend(f"    - {reason}" for reason in state.reasons)
        lines.append("  experiments:")
        for exp in self.experiments(sample_id):
            p = "n/a" if exp.p_value is None else str(exp.p_value)
            lines.append(
                f"    - {exp.hypothesis_id} [{exp.registration.value}] "
                f"{exp.outcome.value} on {exp.metric}: p={p}, "
                f"tests spent={exp.tests_spent}"
            )
        return "\n".join(lines)
