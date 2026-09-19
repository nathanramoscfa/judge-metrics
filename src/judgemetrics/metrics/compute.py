# src/judgemetrics/metrics/compute.py
"""The compute dispatch: every registry metric for every subject of every source.

``compute_all(snapshot, registry, subjects=None)`` iterates the snapshot's
sources with case data (a source without a declared coverage window is
skipped and named in the result: nothing can be right-censored for it),
builds the source's ``Frame``, enumerates its subjects — every judge with
an assignment, decision, or sentence in the source, every court with a
case — and, for each registry metric whose ``subject_types`` include the
subject type, dispatches on ``kind`` to one pure function over the frame
and the Step 1 helpers:

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
- ``compute_distribution``: one observation per vocabulary value of the
  dimension (zero counts included) with the whole map in ``distribution``;
- ``compute_median``: the median of the measure over the rows with a
  value (``cohort_size`` is that ``n``; ``eligible_count`` every
  attributed row), grouped by the offense category of the case's lead
  convicted charge — most severe by the vocabulary's severity order, ties
  broken by the source's charge id — when the dimension says so.

A windowed metric whose outcome the source cannot document returns
``NotObservable`` and the result lists it: no observation, never a zero.
Every rate is rounded to six decimals at the boundary (``intervals.round6``);
every count is an integer. Shares, rates, and survival estimates fill
``observed_rate``; medians fill ``value``; distributions fill
``distribution``. Members are ``(kind, id, counted, followed)`` over the
canonical rows behind the number: the population rows of a count, share,
distribution, or median (``followed`` and ``counted`` mark the
denominator and numerator), the index events of a windowed metric.
Suppression (``suppression.apply``) is applied to every draft before it
is returned.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from statistics import median
from typing import Any

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
    member_windows,
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
from judgemetrics.metrics.registry import MetricDefinitionSpec, Registry
from judgemetrics.metrics.snapshot import Snapshot, SnapshotError, SourceRow
from judgemetrics.metrics.windows import FIRST_OUTCOME_AT, first_outcomes, not_observable
from judgemetrics.normalization import vocabulary

log = get_logger(__name__)

PENDING = "pending"
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

ObservationKey = tuple[str, str, str, str, date, date, int | None, str | None]


class ComputeError(RuntimeError):
    """A registry entry cannot be computed as stated (a registry or engine defect)."""


@dataclass(frozen=True, slots=True)
class Member:
    """A canonical row behind an observation: ``(kind, id, counted, followed)``."""

    kind: str
    id: str
    counted: bool
    followed: bool

    def as_tuple(self) -> tuple[str, str, bool, bool]:
        return (self.kind, self.id, self.counted, self.followed)


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
    members: tuple[Member, ...]
    suppressed_flag: bool = False

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
        )

    @property
    def subject(self) -> Subject:
        return Subject(self.subject_type, self.subject_id)

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


@dataclass(slots=True)
class ComputeResult:
    drafts: list[ObservationDraft] = field(default_factory=list)
    not_observable: list[NotObservableRecord] = field(default_factory=list)
    # Sources with case data but no declared coverage window (nothing computed).
    sources_skipped: list[str] = field(default_factory=list)
    subjects: list[Subject] = field(default_factory=list)

    @property
    def suppressed(self) -> int:
        return sum(1 for draft in self.drafts if draft.suppressed_flag)


@dataclass(frozen=True, slots=True)
class _Context:
    """What every compute function needs beside the frame and the definition."""

    frame: Frame
    definition: MetricDefinitionSpec
    subject: Subject
    source_id: str
    rule: AttributionRule

    def draft(
        self,
        *,
        eligible_count: int,
        cohort_size: int,
        observed_count: int,
        members: Iterable[Member],
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
            period_start=self.frame.coverage_start,
            period_end=self.frame.coverage_end,
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
            members=tuple(members),
        )


# --- subjects ----------------------------------------------------------------------------


def subjects_of(frame: Frame) -> list[Subject]:
    """Every judge with an assignment, decision, or sentence and every court with a case."""
    judges = (
        set(frame.assignments["judge_id"].drop_nulls().to_list())
        | set(frame.decisions["judge_id"].drop_nulls().to_list())
        | set(frame.sentences["judge_id"].drop_nulls().to_list())
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


def population_rows(context: _Context) -> tuple[pl.DataFrame, str, str]:
    """``(rows, member kind, id column)`` of the definition's population for the subject."""
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
    if population in ("cases", "defendants"):
        return attributed_cases(frame, rule, subject), kind, "id"
    if population == "pretrial_decisions":
        return attributed_decisions(frame, rule, subject), kind, "id"
    if population == "disposed_charges":
        rows = attributed_charges(frame, rule, subject)
        disposed = disposed_charges(frame).select(pl.col("id"))
        return rows.join(disposed, on="id", how="semi"), kind, "id"
    if population == "disposed_cases":
        rows = attributed_cases(
            frame, rule, subject, rows=disposed_cases(frame), time_column=DISPOSITION_AT
        )
        return rows, kind, "id"
    if population == "sentences":
        return attributed_sentences(frame, rule, subject), kind, "id"
    msg = f"{definition.slug}: population {population!r} is not computable here"  # pragma: no cover
    raise ComputeError(msg)


def _row_members(
    rows: pl.DataFrame, kind: str, id_column: str, counted: pl.Expr, followed: pl.Expr
) -> list[Member]:
    flagged = rows.select(
        pl.col(id_column).alias("_id"), counted.alias("_counted"), followed.alias("_followed")
    )
    return [
        Member(kind=kind, id=str(row[0]), counted=bool(row[1]), followed=bool(row[2]))
        for row in flagged.iter_rows()
    ]


def _distinct_persons(frame: Frame, case_ids: pl.Series) -> int:
    cases = pl.DataFrame({"case_id": case_ids.cast(pl.String)}).unique()
    persons: set[str] = set()
    for table in (frame.charges, frame.decisions, frame.sentences):
        named = table.select("case_id", "person_id").join(cases, on="case_id", how="semi")
        persons.update(str(value) for value in named["person_id"].drop_nulls().to_list())
    return len(persons)


# --- kinds ---------------------------------------------------------------------------------


def compute_count(context: _Context) -> ObservationDraft:
    rows, kind, id_column = population_rows(context)
    counted = _counted_filter(context.definition)
    matching = rows.filter(counted)
    if context.definition.population == "defendants":
        observed = _distinct_persons(context.frame, matching[id_column])
    else:
        observed = matching.height
    return context.draft(
        eligible_count=rows.height,
        cohort_size=rows.height,
        observed_count=observed,
        members=_row_members(rows, kind, id_column, counted, pl.lit(True)),
    )


def compute_share(context: _Context) -> ObservationDraft:
    rows, kind, id_column = population_rows(context)
    counted = _counted_filter(context.definition)
    numerator = rows.filter(counted).height
    denominator = rows.height
    lower, upper = wilson(numerator, denominator)
    return context.draft(
        eligible_count=denominator,
        cohort_size=denominator,
        observed_count=numerator,
        observed_rate=None if denominator == 0 else round6(numerator / denominator),
        lower=lower,
        upper=upper,
        members=_row_members(rows, kind, id_column, counted, pl.lit(True)),
    )


def _cohort(context: _Context) -> tuple[pl.DataFrame, str]:
    definition = context.definition
    if definition.index_event is None or definition.outcome is None:
        msg = f"{definition.slug}: a {definition.kind} needs an index event and an outcome"
        raise ComputeError(msg)
    index = index_events(context.frame, definition.index_event, context.rule, context.subject)
    cohort = with_exposure(context.frame, index, definition.index_event)
    return cohort, MEMBER_KIND_OF_INDEX[definition.index_event]


def compute_windowed_rate(context: _Context) -> list[ObservationDraft] | NotObservableRecord:
    definition = context.definition
    outcome = definition.outcome or ""
    blocked = not_observable(context.frame, outcome)
    if blocked is not None:
        return _not_observable(context, blocked.outcome, blocked.reason)
    cohort, member_kind = _cohort(context)
    firsts = first_outcomes(context.frame, cohort, outcome)
    end = context.frame.coverage_end_exclusive_at
    windows = definition.windows_days or ()
    flags = member_windows(firsts, end, windows)
    drafts: list[ObservationDraft] = []
    for rate in fixed_window_rates(firsts, end, windows):
        rows = flags.filter(pl.col("window_days") == rate.window_days)
        members = [
            Member(kind=member_kind, id=str(row[0]), counted=bool(row[1]), followed=bool(row[2]))
            for row in rows.select("member_id", "counted", "followed").iter_rows()
        ]
        drafts.append(
            context.draft(
                window_days=rate.window_days,
                eligible_count=rate.eligible,
                cohort_size=rate.followed,
                observed_count=rate.numerator,
                observed_rate=rate.value,
                lower=rate.lower,
                upper=rate.upper,
                members=members,
            )
        )
    return drafts


def compute_survival(context: _Context) -> list[ObservationDraft] | NotObservableRecord:
    definition = context.definition
    outcome = definition.outcome or ""
    blocked = not_observable(context.frame, outcome)
    if blocked is not None:
        return _not_observable(context, blocked.outcome, blocked.reason)
    cohort, member_kind = _cohort(context)
    firsts = first_outcomes(context.frame, cohort, outcome)
    end = context.frame.coverage_end_exclusive_at
    windows = definition.windows_days or ()
    drafts: list[ObservationDraft] = []
    for point in kaplan_meier(firsts, end, windows):
        # An event at or before the window's end (a first outcome before the
        # censoring instant) is counted; every member contributes time at risk.
        flagged = firsts.select(
            pl.col("member_id"),
            (
                pl.col(FIRST_OUTCOME_AT).is_not_null()
                & (pl.col(FIRST_OUTCOME_AT) < pl.lit(end))
                & (
                    pl.col(FIRST_OUTCOME_AT)
                    <= pl.col("exposure_start") + pl.duration(days=point.window_days)
                )
            )
            .fill_null(False)
            .alias(EVENT_BY_WINDOW),
        )
        members = [
            Member(kind=member_kind, id=str(row[0]), counted=bool(row[1]), followed=True)
            for row in flagged.iter_rows()
        ]
        drafts.append(
            context.draft(
                window_days=point.window_days,
                eligible_count=point.eligible,
                cohort_size=point.eligible,
                observed_count=point.events,
                observed_rate=point.cumulative_incidence,
                lower=point.lower,
                upper=point.upper,
                members=members,
            )
        )
    return drafts


def compute_distribution(context: _Context) -> list[ObservationDraft]:
    definition = context.definition
    if definition.dimension != "disposition":
        msg = f"{definition.slug}: distribution dimension {definition.dimension!r} is unsupported"
        raise ComputeError(msg)
    rows, kind, id_column = population_rows(context)
    values = [v for v in vocabulary.values("charge_disposition") if v != PENDING]
    counts = {value: rows.filter(pl.col("disposition") == value).height for value in values}
    drafts: list[ObservationDraft] = []
    for value in values:
        counted = pl.col("disposition") == value
        drafts.append(
            context.draft(
                dimension_value=value,
                eligible_count=rows.height,
                cohort_size=rows.height,
                observed_count=counts[value],
                distribution=dict(counts),
                members=_row_members(rows, kind, id_column, counted, pl.lit(True)),
            )
        )
    return drafts


def _with_measure(rows: pl.DataFrame, measure: str) -> tuple[pl.DataFrame, str]:
    column = MEASURE_COLUMN.get(measure)
    if column is None:
        msg = f"measure {measure!r} has no compute path"
        raise ComputeError(msg)
    if measure == "days_to_disposition":
        rows = rows.with_columns(
            (pl.col(DISPOSITION_AT).dt.date() - pl.col("filed_at").dt.date())
            .dt.total_days()
            .cast(pl.Int64)
            .alias(column)
        )
    return rows, column


def lead_categories(frame: Frame) -> pl.DataFrame:
    """``(case_id, _lead_category)``: the offense category of each case's lead convicted charge.

    Most severe by the vocabulary's severity order, ties broken by the
    source's charge id (``source_row_id``) and then the canonical id.
    """
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
    rows: pl.DataFrame,
    kind: str,
    id_column: str,
    column: str,
    dimension_value: str | None,
) -> ObservationDraft:
    values = [int(v) for v in rows[column].drop_nulls().to_list()]
    has_value = pl.col(column).is_not_null()
    return context.draft(
        dimension_value=dimension_value,
        eligible_count=rows.height,
        cohort_size=len(values),
        observed_count=len(values),
        value=None if not values else float(median(values)),
        members=_row_members(rows, kind, id_column, has_value, has_value),
    )


def compute_median(context: _Context) -> list[ObservationDraft]:
    definition = context.definition
    if definition.measure is None:
        msg = f"{definition.slug}: a median needs a measure"
        raise ComputeError(msg)
    rows, kind, id_column = population_rows(context)
    rows, column = _with_measure(rows, definition.measure)
    if definition.dimension is None:
        return [_median_draft(context, rows, kind, id_column, column, None)]
    if definition.dimension != "offense_category":
        msg = f"{definition.slug}: median dimension {definition.dimension!r} is unsupported"
        raise ComputeError(msg)
    categorized = rows.join(lead_categories(context.frame), on="case_id", how="left").with_columns(
        pl.col(LEAD_CATEGORY).fill_null(UNKNOWN_CATEGORY)
    )
    present = sorted(
        categorized.filter(pl.col(column).is_not_null())[LEAD_CATEGORY].unique().to_list()
    )
    return [
        _median_draft(
            context,
            categorized.filter(pl.col(LEAD_CATEGORY) == category),
            kind,
            id_column,
            column,
            str(category),
        )
        for category in present
    ]


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


# --- dispatch ------------------------------------------------------------------------------


def compute_metric(
    frame: Frame, definition: MetricDefinitionSpec, subject: Subject, source_id: str
) -> list[ObservationDraft] | NotObservableRecord:
    """Every observation of one metric for one subject, suppression applied."""
    from judgemetrics.metrics.suppression import apply

    if subject.subject_type not in definition.subject_types:
        msg = f"{definition.slug} is not defined for a {subject.subject_type}"
        raise ComputeError(msg)
    context = _Context(
        frame=frame,
        definition=definition,
        subject=subject,
        source_id=source_id,
        rule=AttributionRule.from_spec(definition.attribution),
    )
    kind = definition.kind
    result: list[ObservationDraft] | NotObservableRecord
    if kind == "count":
        result = [compute_count(context)]
    elif kind == "share":
        result = [compute_share(context)]
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


def compute_frame(
    frame: Frame,
    registry: Registry,
    source_id: str,
    subjects: Sequence[Subject] | None = None,
) -> ComputeResult:
    """Every registry metric for the frame's subjects (or the given ones present in it)."""
    result = ComputeResult()
    present = subjects_of(frame)
    if subjects is not None:
        wanted = {(s.subject_type, str(s.subject_id)) for s in subjects}
        present = [s for s in present if (s.subject_type, str(s.subject_id)) in wanted]
    result.subjects = present
    for subject in present:
        for definition in registry.for_subject(subject.subject_type):
            computed = compute_metric(frame, definition, subject, source_id)
            if isinstance(computed, NotObservableRecord):
                result.not_observable.append(computed)
            else:
                result.drafts.extend(computed)
    return result


def compute_all(
    snapshot: Snapshot,
    registry: Registry,
    subjects: Sequence[Subject] | None = None,
) -> ComputeResult:
    """``compute_frame`` over every source of the snapshot with case data and a coverage window."""
    result = ComputeResult()
    for source in snapshot.sources_with_cases():
        if not source.has_coverage:
            result.sources_skipped.append(source.id)
            log.warning(
                "metrics.compute.source_skipped",
                snapshot=snapshot.content_hash,
                source=source.name,
                reason="no coverage window",
            )
            continue
        frame = _frame_of(snapshot, source)
        partial = compute_frame(frame, registry, source.id, subjects)
        result.drafts.extend(partial.drafts)
        result.not_observable.extend(partial.not_observable)
        result.subjects.extend(partial.subjects)
        log.info(
            "metrics.compute.source",
            snapshot=snapshot.content_hash,
            source=source.name,
            subjects=len(partial.subjects),
            observations=len(partial.drafts),
            not_observable=len(partial.not_observable),
        )
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
