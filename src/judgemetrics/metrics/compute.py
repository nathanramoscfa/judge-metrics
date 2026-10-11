# src/judgemetrics/metrics/compute.py
"""The compute dispatch: every registry metric for every subject of every source.

``compute_all(snapshot, registry, subjects=None)`` iterates the snapshot's
sources with case data (a source without a declared coverage window is
skipped and named in the result: nothing can be right-censored for it),
builds the source's ``Frame``, enumerates its subjects — every judge with
an assignment, decision, sentence, or disposed charge in the source, every
court with a case — and, for each registry metric whose ``subject_types``
include the subject type, dispatches on ``kind`` to one pure function over
the frame and the Step 1 helpers:

- ``compute_count``: the population rows the rule attributes, the
  ``counted`` conditions applied; ``eligible_cases`` counts distinct
  cases (a duplicate source record is already one row) and
  ``eligible_defendants`` the distinct resolved persons named by those
  cases' charges, decisions, and sentences (its members are the cases —
  a member is never a person id);
- ``compute_share``: numerator over denominator with a Wilson interval;
- ``compute_windowed_rate``: the index events of the metric's kind, their
  exposure, the first qualifying outcome, and one observation per window
  (``eligible_count`` the whole cohort, ``cohort_size`` the followed
  members, ``observed_count`` the followed members with the outcome);
- ``compute_survival``: the Kaplan-Meier cumulative incidence ``1 - S(w)``
  per window over the whole cohort (``observed_count`` the events at or
  before ``w``, the interval from the Greenwood standard error);
- ``compute_distribution``: one observation per final disposition of the
  vocabulary (``final_charge_disposition``; zero counts included) with the
  whole map in ``distribution``;
- ``compute_median``: the median of the measure over the rows with a
  value (``cohort_size`` is that ``n``; ``eligible_count`` every
  attributed row), grouped by the offense category of the case's lead
  convicted charge — most severe by the vocabulary's severity order, ties
  broken by the source's charge id — when the dimension says so. A case the
  source disposes before its filing date has no ``days_to_disposition``.

Members are not listed per observation: every draft of one definition and subject
points at one shared ``members.MemberFamily`` - the population rows (or index events)
once, each with its calendar year, dimension value, and per-window ``counted`` and
``followed`` flags - and ``draft.members`` expands the observation's own multiset from
it (Phase 5 Step 6; docs/DATA_MODEL.md "Member families").

Periods (registry version 3, ``metrics.periods``): a population's rows enter
only when their anchor (``registry.POPULATION_ANCHORS``) lies inside the
coverage window; each kind computes the whole window and then, for every
calendar year (UTC) in which its population has an anchor, the same figure
over that year's rows (``ObservationDraft.calendar_year``). An adjusted ratio
is whole-window only.

A windowed metric whose outcome — or, for a revocation, whose revocation scope
— the source cannot document returns ``NotObservable``; for a judge subject a
metric whose assignment gate the source does not record
(``Frame.capabilities.judge_gates``) returns ``NotAttributable``, checked
first. The result lists both: no observation, never a zero; a court subject
is never not attributable. Every rate is rounded to six decimals at the
boundary (``intervals.round6``); every count is an integer. Shares, rates, and
survival estimates fill ``observed_rate``; medians fill ``value``;
distributions fill ``distribution``. Members are ``(kind, id, counted,
followed)`` over the canonical rows behind the number: the population rows of
a count, share, distribution, or median (``followed`` and ``counted`` mark
the denominator and numerator), the index events of a windowed metric.
Suppression (``suppression.apply``) is applied to every draft before it is
returned, and a suppressed draft carries its ``suppression_reason``.

``observed_expected`` (Phase 4 Step 3) is not a per-subject computation:
its expected counts come from one model fitted over every eligible event of
the source and its pooling shape from every judge, so ``compute_frame``
hands each such definition to ``adjustment.ratios.adjusted_observations``
once per source, with the source's fitted models (``models``, read from
their artifacts by the caller), and keeps the drafts of the requested
judges. The kinds a call computes are explicit: ``kinds`` defaults to the
descriptive kinds (what pipeline step 13 recomputes), and asking for
``observed_expected`` without the models is an error. A court subject has
no adjusted observation; a judge of a source that does not record the
ratio's gate has none either (``NotAttributable``).
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import median
from typing import TYPE_CHECKING, Any

import polars as pl

from judgemetrics.logging import get_logger
from judgemetrics.metrics.attribution import (
    COURT,
    JUDGE,
    AttributionRule,
    Subject,
    attributed_cases,
    attributed_charges,
    attributed_decisions,
    attributed_sentences,
)
from judgemetrics.metrics.censoring import (
    fixed_window_rates,
    kaplan_meier,
)
from judgemetrics.metrics.exposure import with_exposure
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import (
    DISPOSITION_AT,
    MEMBER_CASE,
    MEMBER_DECISION,
    MEMBER_KIND_OF_INDEX,
    MEMBER_SENTENCE,
    disposed_cases,
    disposed_charges,
    index_events,
)
from judgemetrics.metrics.intervals import round6, wilson
from judgemetrics.metrics.members import (
    BELONGS_TO,
    COUNTED_IN,
    PLAIN,
    Member,
    MemberFamily,
    atoms,
)
from judgemetrics.metrics.periods import Period, split, within_coverage
from judgemetrics.metrics.registry import (
    COURT_OF_CASE,
    DESCRIPTIVE_KINDS,
    OBSERVED_EXPECTED,
    POPULATION_ANCHORS,
    MetricDefinitionSpec,
    Registry,
)
from judgemetrics.metrics.snapshot import Snapshot, SnapshotError, SourceRow
from judgemetrics.metrics.windows import FIRST_OUTCOME_AT, first_outcomes, not_observable
from judgemetrics.normalization import vocabulary

if TYPE_CHECKING:
    from judgemetrics.metrics.adjustment.expected import ModelParameters

    # A source's fitted models by (target, window), and every source's by source id.
    SourceModels = Mapping[tuple[str, int | None], ModelParameters]

log = get_logger(__name__)

FINAL_DISPOSITION_KIND = "final_charge_disposition"
MEMBER_CHARGE = "charge"
UNKNOWN_CATEGORY = "unknown"
CONVICTED_DISPOSITIONS: frozenset[str] = frozenset({"convicted_plea", "convicted_verdict"})
POPULATION_MEMBER_KIND: dict[str, str] = {
    "cases": MEMBER_CASE,
    "defendants": MEMBER_CASE,
    "pretrial_decisions": MEMBER_DECISION,
    "disposed_charges": MEMBER_CHARGE,
    "disposed_cases": MEMBER_CASE,
    "sentences": MEMBER_SENTENCE,
}
MEASURE_COLUMN: dict[str, str] = {
    "days_to_disposition": "_days_to_disposition",
    "incarceration_days": "incarceration_days",
    "probation_days": "probation_days",
}
LEAD_CATEGORY = "_lead_category"
SEVERITY_RANK = "_severity_rank"
HAS_VALUE = "_has_value"
EVENT_BY_WINDOW = "_event_by_window"
INDEX_AT = "index_at"

ObservationKey = tuple[str, str, str, str, date, date, int | None, str | None, int | None]


class ComputeError(RuntimeError):
    """A registry entry cannot be computed as stated (a registry or engine defect)."""


@dataclass(frozen=True, slots=True)
class ObservationDraft:
    """One observation before it is stored: the columns of ``metric_observation`` plus members."""

    slug: str
    version: str
    subject_type: str
    subject_id: str
    source_id: str
    period_start: date
    period_end: date
    window_days: int | None
    dimension_value: str | None
    eligible_count: int
    cohort_size: int
    observed_count: int
    observed_rate: float | None
    value: float | None
    distribution: dict[str, int] | None
    lower: float | None
    upper: float | None
    # The canonical rows behind the figure, shared by every draft of one definition and
    # subject: this observation's own members are a filter of it (``members``).
    family: MemberFamily | None = None
    suppressed_flag: bool = False
    # Why a suppressed draft is withheld (suppression.apply sets it with the flag).
    suppression_reason: str | None = None
    # observed_expected only (docs/DATA_MODEL.md "metric_observation by kind"): E, E / n,
    # the pooled ratio, E / (E + alpha), and the content hash of the model they came from.
    expected_count: float | None = None
    expected_rate: float | None = None
    standardized_ratio: float | None = None
    pooling_weight: float | None = None
    model_hash: str | None = None
    # The calendar year (UTC) a year observation covers; None for the whole window.
    calendar_year: int | None = None

    @property
    def key(self) -> ObservationKey:
        """What ``uq_metric_observation_key`` keys on, less the snapshot."""
        return (
            self.slug,
            self.subject_type,
            self.subject_id,
            self.source_id,
            self.period_start,
            self.period_end,
            self.window_days,
            self.dimension_value,
            self.calendar_year,
        )

    @property
    def subject(self) -> Subject:
        return Subject(self.subject_type, self.subject_id)

    @property
    def members(self) -> tuple[Member, ...]:
        """This observation's member multiset, expanded from the family (tests, small data)."""
        if self.family is None:
            return ()
        return self.family.members(
            year=self.calendar_year, window=self.window_days, dimension=self.dimension_value
        )

    def sorted_members(self) -> tuple[tuple[str, str, bool, bool], ...]:
        return tuple(sorted(member.as_tuple() for member in self.members))


@dataclass(frozen=True, slots=True)
class NotObservableRecord:
    """A metric the source cannot document for a subject: no observation is published."""

    slug: str
    version: str
    subject_type: str
    subject_id: str
    source_id: str
    outcome: str
    reason: str


@dataclass(frozen=True, slots=True)
class NotAttributableRecord:
    """A judge metric whose gate the source does not record: no observation is published."""

    slug: str
    version: str
    subject_type: str
    subject_id: str
    source_id: str
    gate: str
    reason: str


@dataclass(slots=True)
class ComputeResult:
    drafts: list[ObservationDraft] = field(default_factory=list)
    not_observable: list[NotObservableRecord] = field(default_factory=list)
    not_attributable: list[NotAttributableRecord] = field(default_factory=list)
    # Sources with case data but no declared coverage window (nothing computed).
    sources_skipped: list[str] = field(default_factory=list)
    subjects: list[Subject] = field(default_factory=list)

    @property
    def suppressed(self) -> int:
        return sum(1 for draft in self.drafts if draft.suppressed_flag)

    def extend(self, other: ComputeResult) -> None:
        self.drafts.extend(other.drafts)
        self.not_observable.extend(other.not_observable)
        self.not_attributable.extend(other.not_attributable)
        self.subjects.extend(other.subjects)


@dataclass(slots=True)
class SubjectResult:
    """Everything computed for one subject of one source: what a publish consumes at a time."""

    subject: Subject
    drafts: list[ObservationDraft] = field(default_factory=list)
    not_observable: list[NotObservableRecord] = field(default_factory=list)
    not_attributable: list[NotAttributableRecord] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class _Context:
    """What every compute function needs beside the frame and the definition."""

    frame: Frame
    definition: MetricDefinitionSpec
    subject: Subject
    source_id: str
    rule: AttributionRule
    # Whether the metric publishes calendar years beside the whole window.
    by_year: bool = True

    def draft(
        self,
        *,
        period: Period,
        eligible_count: int,
        cohort_size: int,
        observed_count: int,
        family: MemberFamily,
        window_days: int | None = None,
        dimension_value: str | None = None,
        observed_rate: float | None = None,
        value: float | None = None,
        distribution: dict[str, int] | None = None,
        lower: float | None = None,
        upper: float | None = None,
    ) -> ObservationDraft:
        return ObservationDraft(
            slug=self.definition.slug,
            version=self.definition.version,
            subject_type=self.subject.subject_type,
            subject_id=str(self.subject.subject_id),
            source_id=self.source_id,
            period_start=period.start,
            period_end=period.end,
            window_days=window_days,
            dimension_value=dimension_value,
            eligible_count=int(eligible_count),
            cohort_size=int(cohort_size),
            observed_count=int(observed_count),
            observed_rate=observed_rate,
            value=value,
            distribution=distribution,
            lower=lower,
            upper=upper,
            family=family,
            calendar_year=period.calendar_year,
        )

    def periods(self, rows: pl.DataFrame, anchor: str) -> list[tuple[Period, pl.DataFrame]]:
        """The whole window's rows, then each calendar year's (when the metric has years)."""
        return split(self.frame, rows, anchor, by_year=self.by_year)


# --- subjects ----------------------------------------------------------------------------


def subjects_of(frame: Frame) -> list[Subject]:
    """Every judge with an assignment, decision, sentence, or disposed charge; every court."""
    judges = (
        set(frame.assignments["judge_id"].drop_nulls().to_list())
        | set(frame.decisions["judge_id"].drop_nulls().to_list())
        | set(frame.sentences["judge_id"].drop_nulls().to_list())
        | set(frame.charges["judge_id"].drop_nulls().to_list())
    )
    courts = set(frame.cases["court_id"].drop_nulls().to_list())
    return [Subject(JUDGE, judge) for judge in sorted(judges)] + [
        Subject(COURT, court) for court in sorted(courts)
    ]


def parse_subject(text: str) -> Subject:
    """``judge:<id>`` or ``court:<id>`` (the ``--subject`` option)."""
    subject_type, separator, subject_id = text.partition(":")
    if not separator or subject_type not in (JUDGE, COURT) or not subject_id:
        msg = f"a subject is judge:<uuid> or court:<uuid>; got {text!r}"
        raise ComputeError(msg)
    return Subject(subject_type, subject_id)


# --- populations ---------------------------------------------------------------------------


def _counted_filter(definition: MetricDefinitionSpec) -> pl.Expr:
    expression = pl.lit(True)
    for column, value in definition.counted:
        expression = expression & (pl.col(column) == value)
    return expression


def population_rows(context: _Context) -> tuple[pl.DataFrame, str, str, str]:
    """``(rows, member kind, id column, anchor column)`` of the definition's population.

    Only the rows whose anchor lies inside the coverage window.
    """
    frame, definition, subject, rule = (
        context.frame,
        context.definition,
        context.subject,
        context.rule,
    )
    population = definition.population
    kind = POPULATION_MEMBER_KIND.get(population)
    if kind is None:
        msg = f"{definition.slug}: population {population!r} has no compute path"
        raise ComputeError(msg)
    anchor = POPULATION_ANCHORS[population]
    if population in ("cases", "defendants"):
        rows = attributed_cases(frame, rule, subject)
    elif population == "pretrial_decisions":
        rows = attributed_decisions(frame, rule, subject)
    elif population == "disposed_charges":
        attributed = attributed_charges(frame, rule, subject)
        disposed = disposed_charges(frame).select(pl.col("id"))
        rows = attributed.join(disposed, on="id", how="semi")
    elif population == "disposed_cases":
        rows = attributed_cases(
            frame, rule, subject, rows=disposed_cases(frame), time_column=DISPOSITION_AT
        )
    elif population == "sentences":
        rows = attributed_sentences(frame, rule, subject)
    else:  # pragma: no cover - POPULATION_MEMBER_KIND lists every computable population
        msg = f"{definition.slug}: population {population!r} is not computable here"
        raise ComputeError(msg)
    return within_coverage(frame, rows, anchor), kind, "id", anchor


def _population_family(
    rows: pl.DataFrame,
    kind: str,
    id_column: str,
    anchor: str,
    *,
    counted: pl.Expr,
    followed: pl.Expr,
    dimension: pl.Expr | None = None,
    mode: str = PLAIN,
) -> MemberFamily:
    """The family of a population: one atom per row, in the metric's single flag slot."""
    return MemberFamily(
        kind,
        mode,
        (None,),
        atoms(
            rows,
            member_id=id_column,
            anchor=anchor,
            counted=[counted],
            followed=[followed],
            dimension=dimension,
        ),
    )


def _case_persons(frame: Frame) -> pl.DataFrame:
    """``(case_id, person_id)`` of every person named by a charge, decision, or sentence, distinct."""
    return frame.derived(
        "case_persons",
        lambda: pl.concat(
            [
                table.select("case_id", "person_id").drop_nulls()
                for table in (frame.charges, frame.decisions, frame.sentences)
            ]
        ).unique(),
    )


def _distinct_persons(frame: Frame, case_ids: pl.Series) -> int:
    cases = pl.DataFrame({"case_id": case_ids.cast(pl.String)}).unique()
    return _case_persons(frame).join(cases, on="case_id", how="semi")["person_id"].n_unique()


# --- kinds ---------------------------------------------------------------------------------


def compute_count(context: _Context) -> list[ObservationDraft]:
    population, kind, id_column, anchor = population_rows(context)
    counted = _counted_filter(context.definition)
    family = _population_family(
        population, kind, id_column, anchor, counted=counted, followed=pl.lit(True)
    )
    drafts: list[ObservationDraft] = []
    for period, rows in context.periods(population, anchor):
        matching = rows.filter(counted)
        if context.definition.population == "defendants":
            observed = _distinct_persons(context.frame, matching[id_column])
        else:
            observed = matching.height
        drafts.append(
            context.draft(
                period=period,
                eligible_count=rows.height,
                cohort_size=rows.height,
                observed_count=observed,
                family=family,
            )
        )
    return drafts


def compute_share(context: _Context) -> list[ObservationDraft]:
    population, kind, id_column, anchor = population_rows(context)
    counted = _counted_filter(context.definition)
    family = _population_family(
        population, kind, id_column, anchor, counted=counted, followed=pl.lit(True)
    )
    drafts: list[ObservationDraft] = []
    for period, rows in context.periods(population, anchor):
        numerator = rows.filter(counted).height
        denominator = rows.height
        lower, upper = wilson(numerator, denominator)
        drafts.append(
            context.draft(
                period=period,
                eligible_count=denominator,
                cohort_size=denominator,
                observed_count=numerator,
                observed_rate=None if denominator == 0 else round6(numerator / denominator),
                lower=lower,
                upper=upper,
                family=family,
            )
        )
    return drafts


def _cohort(context: _Context) -> tuple[pl.DataFrame, str]:
    definition = context.definition
    if definition.index_event is None or definition.outcome is None:
        msg = f"{definition.slug}: a {definition.kind} needs an index event and an outcome"
        raise ComputeError(msg)
    index = index_events(context.frame, definition.index_event, context.rule, context.subject)
    cohort = with_exposure(context.frame, index, definition.index_event)
    return cohort, MEMBER_KIND_OF_INDEX[definition.index_event]


def _blocked(context: _Context) -> NotObservableRecord | None:
    definition = context.definition
    blocked = not_observable(context.frame, definition.outcome or "", definition.revocation_scope)
    if blocked is None:
        return None
    return _not_observable(context, blocked.outcome, blocked.reason)


def _window_exprs(
    end: datetime, windows: Sequence[int], *, survival: bool
) -> tuple[list[pl.Expr], list[pl.Expr]]:
    """Per window: the ``counted`` and ``followed`` expressions over a cohort with first outcomes.

    A fixed-window rate counts the followed members with an outcome in the window
    (``censoring.member_windows``); a survival estimate follows every member and counts
    those whose first outcome came before the coverage end and within the window.
    """
    first = pl.col(FIRST_OUTCOME_AT)
    start = pl.col("exposure_start")
    limit = pl.lit(end)  # one literal: a time-zone-aware one is converted when it is built
    counted: list[pl.Expr] = []
    followed: list[pl.Expr] = []
    for window in windows:
        reach = start + pl.duration(days=window)
        if survival:
            counted.append(first.is_not_null() & (first < limit) & (first <= reach))
            followed.append(pl.lit(True))
        else:
            counted.append(first.is_not_null() & (first <= reach) & (reach < limit))
            followed.append(reach < limit)
    return counted, followed


def _cohort_family(
    cohort: pl.DataFrame, member_kind: str, end: datetime, windows: Sequence[int], *, survival: bool
) -> MemberFamily:
    """The family of a windowed cohort: one atom per index event, one flag slot per window."""
    counted, followed = _window_exprs(end, windows, survival=survival)
    return MemberFamily(
        member_kind,
        PLAIN,
        tuple(windows),
        atoms(cohort, member_id="member_id", anchor=INDEX_AT, counted=counted, followed=followed),
    )


def compute_windowed_rate(context: _Context) -> list[ObservationDraft] | NotObservableRecord:
    blocked = _blocked(context)
    if blocked is not None:
        return blocked
    definition = context.definition
    cohort, member_kind = _cohort(context)
    firsts = first_outcomes(context.frame, cohort, definition.outcome or "")
    end = context.frame.coverage_end_exclusive_at
    windows = definition.windows_days or ()
    family = _cohort_family(firsts, member_kind, end, windows, survival=False)
    drafts: list[ObservationDraft] = []
    for period, members_of_period in context.periods(firsts, INDEX_AT):
        drafts.extend(
            context.draft(
                period=period,
                window_days=rate.window_days,
                eligible_count=rate.eligible,
                cohort_size=rate.followed,
                observed_count=rate.numerator,
                observed_rate=rate.value,
                lower=rate.lower,
                upper=rate.upper,
                family=family,
            )
            for rate in fixed_window_rates(members_of_period, end, windows)
        )
    return drafts


def compute_survival(context: _Context) -> list[ObservationDraft] | NotObservableRecord:
    blocked = _blocked(context)
    if blocked is not None:
        return blocked
    definition = context.definition
    cohort, member_kind = _cohort(context)
    firsts = first_outcomes(context.frame, cohort, definition.outcome or "")
    end = context.frame.coverage_end_exclusive_at
    windows = definition.windows_days or ()
    # An event at or before the window's end (a first outcome before the censoring
    # instant) is counted; every member contributes time at risk.
    family = _cohort_family(firsts, member_kind, end, windows, survival=True)
    drafts: list[ObservationDraft] = []
    for period, members_of_period in context.periods(firsts, INDEX_AT):
        drafts.extend(
            context.draft(
                period=period,
                window_days=point.window_days,
                eligible_count=point.eligible,
                cohort_size=point.eligible,
                observed_count=point.events,
                observed_rate=point.cumulative_incidence,
                lower=point.lower,
                upper=point.upper,
                family=family,
            )
            for point in kaplan_meier(members_of_period, end, windows)
        )
    return drafts


def compute_distribution(context: _Context) -> list[ObservationDraft]:
    definition = context.definition
    if definition.dimension != "disposition":
        msg = f"{definition.slug}: distribution dimension {definition.dimension!r} is unsupported"
        raise ComputeError(msg)
    population, kind, id_column, anchor = population_rows(context)
    # The final values only (vocabulary 3): a non-final disposition ends no charge
    # on its merits, so it is never a value of the distribution.
    values = list(vocabulary.values(FINAL_DISPOSITION_KIND))
    # Every row belongs to each value's observation and counts in the one of its own
    # disposition: the family keeps that disposition as the row's dimension value.
    family = _population_family(
        population,
        kind,
        id_column,
        anchor,
        counted=pl.lit(False),
        followed=pl.lit(True),
        dimension=pl.col("disposition"),
        mode=COUNTED_IN,
    )
    drafts: list[ObservationDraft] = []
    for period, rows in context.periods(population, anchor):
        counts = {value: rows.filter(pl.col("disposition") == value).height for value in values}
        for value in values:
            drafts.append(
                context.draft(
                    period=period,
                    dimension_value=value,
                    eligible_count=rows.height,
                    cohort_size=rows.height,
                    observed_count=counts[value],
                    distribution=dict(counts),
                    family=family,
                )
            )
    return drafts


def _with_measure(rows: pl.DataFrame, measure: str) -> tuple[pl.DataFrame, str]:
    column = MEASURE_COLUMN.get(measure)
    if column is None:
        msg = f"measure {measure!r} has no compute path"
        raise ComputeError(msg)
    if measure == "days_to_disposition":
        days = (
            (pl.col(DISPOSITION_AT).dt.date() - pl.col("filed_at").dt.date())
            .dt.total_days()
            .cast(pl.Int64)
        )
        # A case the source disposes before its filing date has no duration (methodology 1.1).
        rows = rows.with_columns(pl.when(days >= 0).then(days).otherwise(None).alias(column))
    return rows, column


def lead_categories(frame: Frame) -> pl.DataFrame:
    """``(case_id, _lead_category)``: the offense category of each case's lead convicted charge.

    Most severe by the vocabulary's severity order, ties broken by the
    source's charge id (``source_row_id``) and then the canonical id.
    """
    return frame.derived("lead_categories", lambda: _lead_categories(frame))


def _lead_categories(frame: Frame) -> pl.DataFrame:
    order = {severity: rank for rank, severity in enumerate(vocabulary.values("severity"))}
    convicted = frame.charges.filter(pl.col("disposition").is_in(sorted(CONVICTED_DISPOSITIONS)))
    if convicted.height == 0:
        return pl.DataFrame(
            schema={"case_id": frame.id_dtype, LEAD_CATEGORY: pl.String()}, orient="row"
        )
    ranked = convicted.with_columns(
        pl.col("severity").replace_strict(order, default=len(order)).alias(SEVERITY_RANK)
    )
    return (
        ranked.sort([SEVERITY_RANK, "source_row_id", "id"], nulls_last=True)
        .unique(subset=["case_id"], keep="first", maintain_order=True)
        .select("case_id", pl.col("offense_category").alias(LEAD_CATEGORY))
    )


def _median_draft(
    context: _Context,
    period: Period,
    rows: pl.DataFrame,
    column: str,
    dimension_value: str | None,
    family: MemberFamily,
) -> ObservationDraft:
    values = [int(v) for v in rows[column].drop_nulls().to_list()]
    return context.draft(
        period=period,
        dimension_value=dimension_value,
        eligible_count=rows.height,
        cohort_size=len(values),
        observed_count=len(values),
        value=None if not values else float(median(values)),
        family=family,
    )


def compute_median(context: _Context) -> list[ObservationDraft]:
    definition = context.definition
    if definition.measure is None:
        msg = f"{definition.slug}: a median needs a measure"
        raise ComputeError(msg)
    population, kind, id_column, anchor = population_rows(context)
    population, column = _with_measure(population, definition.measure)
    has_value = pl.col(column).is_not_null()
    if definition.dimension is None:
        family = _population_family(
            population, kind, id_column, anchor, counted=has_value, followed=has_value
        )
        return [
            _median_draft(context, period, rows, column, None, family)
            for period, rows in context.periods(population, anchor)
        ]
    if definition.dimension != "offense_category":
        msg = f"{definition.slug}: median dimension {definition.dimension!r} is unsupported"
        raise ComputeError(msg)
    categorized = population.join(
        lead_categories(context.frame), on="case_id", how="left"
    ).with_columns(pl.col(LEAD_CATEGORY).fill_null(UNKNOWN_CATEGORY))
    # A row belongs to the observation of its case's lead offense category only.
    family = _population_family(
        categorized,
        kind,
        id_column,
        anchor,
        counted=has_value,
        followed=has_value,
        dimension=pl.col(LEAD_CATEGORY),
        mode=BELONGS_TO,
    )
    drafts: list[ObservationDraft] = []
    for period, rows in context.periods(categorized, anchor):
        present = sorted(
            rows.filter(pl.col(column).is_not_null())[LEAD_CATEGORY].unique().to_list()
        )
        drafts.extend(
            _median_draft(
                context,
                period,
                rows.filter(pl.col(LEAD_CATEGORY) == category),
                column,
                str(category),
                family,
            )
            for category in present
        )
    return drafts


def _not_observable(context: _Context, outcome: str, reason: str) -> NotObservableRecord:
    return NotObservableRecord(
        slug=context.definition.slug,
        version=context.definition.version,
        subject_type=context.subject.subject_type,
        subject_id=str(context.subject.subject_id),
        source_id=context.source_id,
        outcome=outcome,
        reason=reason,
    )


def not_attributable(
    frame: Frame, definition: MetricDefinitionSpec, subject: Subject, source_id: str
) -> NotAttributableRecord | None:
    """``NotAttributableRecord`` when the source does not record the judge metric's gate."""
    gate = definition.attribution.assignment_gate
    if subject.subject_type != JUDGE or gate == COURT_OF_CASE:
        return None
    if frame.capabilities.records_gate(gate):
        return None
    return NotAttributableRecord(
        slug=definition.slug,
        version=definition.version,
        subject_type=subject.subject_type,
        subject_id=str(subject.subject_id),
        source_id=source_id,
        gate=gate,
        reason=f"the source does not record the {gate.replace('_', ' ')} ({gate})",
    )


# --- dispatch ------------------------------------------------------------------------------

ComputedMetric = list[ObservationDraft] | NotObservableRecord | NotAttributableRecord


def compute_metric(
    frame: Frame,
    definition: MetricDefinitionSpec,
    subject: Subject,
    source_id: str,
    *,
    registry: Registry | None = None,
) -> ComputedMetric:
    """Every observation of one metric for one subject (whole window and years), suppressed.

    ``registry`` decides which kinds publish calendar years (the loaded registry
    when omitted).
    """
    from judgemetrics.metrics.registry import load_registry
    from judgemetrics.metrics.suppression import apply

    if subject.subject_type not in definition.subject_types:
        msg = f"{definition.slug} is not defined for a {subject.subject_type}"
        raise ComputeError(msg)
    if definition.kind == OBSERVED_EXPECTED:
        msg = (
            f"{definition.slug} is an {OBSERVED_EXPECTED}: it is computed for every judge of a "
            "source at once (compute_frame with its models), never for one subject"
        )
        raise ComputeError(msg)
    unattributed = not_attributable(frame, definition, subject, source_id)
    if unattributed is not None:
        return unattributed
    periods = (registry or load_registry()).periods
    context = _Context(
        frame=frame,
        definition=definition,
        subject=subject,
        source_id=source_id,
        rule=AttributionRule.from_spec(definition.attribution),
        by_year=periods.has_calendar_years(definition.kind),
    )
    kind = definition.kind
    result: list[ObservationDraft] | NotObservableRecord
    if kind == "count":
        result = compute_count(context)
    elif kind == "share":
        result = compute_share(context)
    elif kind == "windowed_rate":
        result = compute_windowed_rate(context)
    elif kind == "survival":
        result = compute_survival(context)
    elif kind == "distribution":
        result = compute_distribution(context)
    elif kind == "median":
        result = compute_median(context)
    else:  # pragma: no cover - the registry validates kinds
        msg = f"{definition.slug}: unknown kind {kind!r}"
        raise ComputeError(msg)
    if isinstance(result, NotObservableRecord):
        return result
    return [apply(draft, definition) for draft in result]


def _subjects_present(frame: Frame, subjects: Sequence[Subject] | None) -> list[Subject]:
    present = subjects_of(frame)
    if subjects is None:
        return present
    wanted = {(s.subject_type, str(s.subject_id)) for s in subjects}
    return [s for s in present if (s.subject_type, str(s.subject_id)) in wanted]


def _descriptive(
    frame: Frame,
    registry: Registry,
    source_id: str,
    subject: Subject,
    kinds: Collection[str],
) -> SubjectResult:
    """The descriptive kinds of ``kinds`` for one subject."""
    result = SubjectResult(subject)
    for definition in registry.for_subject(subject.subject_type):
        if definition.kind not in kinds or definition.kind == OBSERVED_EXPECTED:
            continue
        computed = compute_metric(frame, definition, subject, source_id, registry=registry)
        if isinstance(computed, NotObservableRecord):
            result.not_observable.append(computed)
        elif isinstance(computed, NotAttributableRecord):
            result.not_attributable.append(computed)
        else:
            result.drafts.extend(computed)
    return result


@dataclass(slots=True)
class _Adjusted:
    """The adjusted kind's output for one frame: drafts and records, in definition order."""

    drafts: list[ObservationDraft] = field(default_factory=list)
    not_observable: list[NotObservableRecord] = field(default_factory=list)
    not_attributable: list[NotAttributableRecord] = field(default_factory=list)


def _adjusted(
    frame: Frame,
    registry: Registry,
    source_id: str,
    present: Sequence[Subject],
    kinds: Collection[str],
    models: SourceModels | None,
) -> _Adjusted:
    """Every ``observed_expected`` metric over the judges of ``present`` (see ``compute_frame``)."""
    found = _Adjusted()
    adjusted = registry.of_kind(OBSERVED_EXPECTED) if OBSERVED_EXPECTED in kinds else ()
    judges = [subject for subject in present if subject.subject_type == JUDGE]
    for definition in adjusted:
        records = [not_attributable(frame, definition, judge, source_id) for judge in judges]
        found.not_attributable.extend(record for record in records if record is not None)
        attributable = [judge for judge, record in zip(judges, records, strict=True) if not record]
        if not attributable:
            continue
        if models is None:
            msg = f"computing {OBSERVED_EXPECTED} needs the source's fitted models"
            raise ComputeError(msg)
        from judgemetrics.metrics.adjustment.ratios import RatioError, adjusted_observations

        try:
            drafts, blocked = adjusted_observations(
                frame, definition, source_id=source_id, models=models, judges=attributable
            )
        except RatioError as exc:
            raise ComputeError(str(exc)) from exc
        found.drafts.extend(drafts)
        found.not_observable.extend(blocked)
    return found


def iter_frame(
    frame: Frame,
    registry: Registry,
    source_id: str,
    subjects: Sequence[Subject] | None = None,
    *,
    kinds: Collection[str] = DESCRIPTIVE_KINDS,
    models: SourceModels | None = None,
) -> Iterator[SubjectResult]:
    """``compute_frame`` one subject at a time: each subject's result is complete when yielded.

    The adjusted kind is computed for every judge at once, before the first subject
    (its expected counts and pooling shape need all of them); its drafts and records
    are then merged into their judge's result, so a publisher sees every kind of a
    subject together and a caller that drops each result frees its member families.
    """
    present = _subjects_present(frame, subjects)
    adjusted = _adjusted(frame, registry, source_id, present, kinds, models)
    drafts_of: dict[str, list[ObservationDraft]] = {}
    for draft in adjusted.drafts:
        drafts_of.setdefault(draft.subject_id, []).append(draft)
    blocked_of: dict[str, list[NotObservableRecord]] = {}
    for blocked in adjusted.not_observable:
        blocked_of.setdefault(blocked.subject_id, []).append(blocked)
    unattributed_of: dict[str, list[NotAttributableRecord]] = {}
    for record in adjusted.not_attributable:
        unattributed_of.setdefault(record.subject_id, []).append(record)
    for subject in present:
        result = _descriptive(frame, registry, source_id, subject, kinds)
        key = str(subject.subject_id)
        if subject.subject_type == JUDGE:
            result.drafts.extend(drafts_of.pop(key, ()))
            result.not_observable.extend(blocked_of.pop(key, ()))
            result.not_attributable.extend(unattributed_of.pop(key, ()))
        yield result


def compute_frame(
    frame: Frame,
    registry: Registry,
    source_id: str,
    subjects: Sequence[Subject] | None = None,
    *,
    kinds: Collection[str] = DESCRIPTIVE_KINDS,
    models: SourceModels | None = None,
) -> ComputeResult:
    """Every registry metric of ``kinds`` for the frame's subjects (or the given ones in it).

    ``observed_expected`` needs ``models`` — the source's fitted models by
    ``(target, window)`` — and is computed over every judge of the frame,
    keeping the requested judges' drafts (see the module docstring). The result
    lists the descriptive drafts of every subject, then the adjusted ones; a
    publisher streams ``iter_frame`` instead.
    """
    result = ComputeResult()
    present = _subjects_present(frame, subjects)
    result.subjects = present
    for subject in present:
        part = _descriptive(frame, registry, source_id, subject, kinds)
        result.drafts.extend(part.drafts)
        result.not_observable.extend(part.not_observable)
        result.not_attributable.extend(part.not_attributable)
    adjusted = _adjusted(frame, registry, source_id, present, kinds, models)
    result.not_attributable.extend(adjusted.not_attributable)
    result.drafts.extend(adjusted.drafts)
    result.not_observable.extend(adjusted.not_observable)
    return result


def iter_all(
    snapshot: Snapshot,
    registry: Registry,
    subjects: Sequence[Subject] | None = None,
    *,
    kinds: Collection[str] = DESCRIPTIVE_KINDS,
    models: Mapping[str, SourceModels] | None = None,
    sources: Collection[str] | None = None,
    skipped: list[str] | None = None,
) -> Iterator[SubjectResult]:
    """``iter_frame`` over every source of the snapshot with case data and a coverage window.

    ``models`` maps a source id to its fitted models (``observed_expected`` only);
    ``sources`` (source ids) restricts the compute to those sources' frames; the ids of
    the sources skipped for want of a coverage window are appended to ``skipped``.
    """
    for source in snapshot.sources_with_cases():
        if sources is not None and source.id not in sources:
            continue
        if not source.has_coverage:
            if skipped is not None:
                skipped.append(source.id)
            log.warning(
                "metrics.compute.source_skipped",
                snapshot=snapshot.content_hash,
                source=source.name,
                because="no coverage window",
            )
            continue
        frame = _frame_of(snapshot, source)
        count = observations = blocked = unattributed = 0
        for result in iter_frame(
            frame,
            registry,
            source.id,
            subjects,
            kinds=kinds,
            models=None if models is None else models.get(source.id, {}),
        ):
            count += 1
            observations += len(result.drafts)
            blocked += len(result.not_observable)
            unattributed += len(result.not_attributable)
            yield result
        log.info(
            "metrics.compute.source",
            snapshot=snapshot.content_hash,
            source=source.name,
            subjects=count,
            observations=observations,
            not_observable=blocked,
            not_attributable=unattributed,
        )


def compute_all(
    snapshot: Snapshot,
    registry: Registry,
    subjects: Sequence[Subject] | None = None,
    *,
    kinds: Collection[str] = DESCRIPTIVE_KINDS,
    models: Mapping[str, SourceModels] | None = None,
    sources: Collection[str] | None = None,
) -> ComputeResult:
    """``compute_frame`` over every source of the snapshot with case data and a coverage window.

    ``models`` maps a source id to its fitted models (``observed_expected`` only);
    ``sources`` (source ids) restricts the compute to those sources' frames.
    """
    result = ComputeResult()
    for part in iter_all(
        snapshot,
        registry,
        subjects,
        kinds=kinds,
        models=models,
        sources=sources,
        skipped=result.sources_skipped,
    ):
        result.subjects.append(part.subject)
        result.drafts.extend(part.drafts)
        result.not_observable.extend(part.not_observable)
        result.not_attributable.extend(part.not_attributable)
    return result


def _frame_of(snapshot: Snapshot, source: SourceRow) -> Frame:
    try:
        return snapshot.frame(source.id)
    except SnapshotError as exc:
        msg = f"cannot build the frame of source {source.name}: {exc}"
        raise ComputeError(msg) from exc


def draft_summary(drafts: Iterable[ObservationDraft]) -> dict[str, Any]:
    """Counts by slug for a log line (never a value)."""
    counts: dict[str, int] = {}
    for draft in drafts:
        counts[draft.slug] = counts.get(draft.slug, 0) + 1
    return counts
