# src/judgemetrics/repositories/metrics.py
"""Metric queries: a subject's current observations, and the compare page.

``subject_observations`` is one statement: the current observations
(``superseded_at IS NULL``) of a judge or court joined to their
definition (slug, name, kind, unit, version, outcome, threshold), their
source (key, type, coverage window, observable outcomes — the synthetic
flag is ``source.source_type = 'synthetic'``, the same rule as
``repositories.provenance.synthetic_flag``), and their snapshot's hash;
``get_subject`` is the one-statement lookup that settles a 404 first.

``compare_page`` is the one page statement of ``GET /metrics/compare``:
the judges with a service record at the court (or at a court of the
jurisdiction — the linkage the ``/judges?court_id=`` filter uses) that
carry a current observation of the metric's current definition and
window, each row with the judge's court within the cohort (a ``LATERAL``
subquery: the latest service record there), the observation's figures,
its source's coverage, ``count(*) OVER ()`` for the total, and the
cohort's reference period — the period most rows of the *whole* cohort
share, computed with window functions in the same statement so a page
never has to see the others. Sorting by a figure uses a column that is
null whenever the row is suppressed, so the order of a page can never
leak a withheld number; nulls sort last in either direction, then the
judge's name and id. An empty page costs one more statement that returns
the total together with the court's or jurisdiction's existence (the
``list_judge_cases`` pattern), so an unknown cohort is a 404 without a
separate lookup.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, NamedTuple

from sqlalchemy import ColumnElement, Row, Select, case, func, null, select, true
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    SYNTHETIC_SOURCE_TYPE,
    Court,
    Judge,
    JudgeService,
    Jurisdiction,
    MetricDefinition,
    MetricObservation,
    MetricSnapshot,
    Source,
)
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.repositories.common import MAX_LIMIT
from judgemetrics.repositories.provenance import synthetic_flag, with_source

CompareSortKey = Literal["rate", "numerator", "denominator", "value", "name"]


class SubjectRow(NamedTuple):
    subject_type: str
    id: uuid.UUID
    canonical_name: str
    synthetic: bool


def get_subject(session: Session, subject_type: str, subject_id: uuid.UUID) -> SubjectRow | None:
    """The judge or court with its synthetic flag: one statement, ``None`` when unknown."""
    if subject_type == "judge":
        stmt = with_source(
            select(Judge.id, Judge.canonical_name, synthetic_flag()), Judge.source_record_id
        ).where(Judge.id == subject_id)
    elif subject_type == "court":
        stmt = with_source(
            select(Court.id, Court.canonical_name, synthetic_flag()), Court.source_record_id
        ).where(Court.id == subject_id)
    else:
        msg = f"unknown subject type {subject_type!r}"
        raise ValueError(msg)
    row = session.execute(stmt).one_or_none()
    if row is None:
        return None
    return SubjectRow(subject_type, row[0], str(row[1]), bool(row[2]))


def _observation_columns() -> Select[Any]:
    return (
        select(
            MetricObservation,
            MetricDefinition.slug.label("slug"),
            MetricDefinition.name.label("name"),
            MetricDefinition.kind.label("kind"),
            MetricDefinition.unit.label("unit"),
            MetricDefinition.version.label("definition_version"),
            MetricDefinition.outcome.label("outcome"),
            MetricDefinition.suppression_threshold.label("suppression_threshold"),
            Source.name.label("source_name"),
            (Source.source_type == SYNTHETIC_SOURCE_TYPE).label("synthetic"),
            Source.coverage_start.label("coverage_start"),
            Source.coverage_end.label("coverage_end"),
            Source.observable_outcomes.label("observable_outcomes"),
            MetricSnapshot.content_hash.label("snapshot_hash"),
        )
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .join(Source, Source.id == MetricObservation.source_id)
        .join(MetricSnapshot, MetricSnapshot.id == MetricObservation.snapshot_id)
        .where(MetricObservation.superseded_at.is_(None))
    )


def subject_observations(
    session: Session, subject_type: str, subject_id: uuid.UUID
) -> list[Row[Any]]:
    """Every current observation of the subject with its definition, source, and snapshot hash."""
    stmt = (
        _observation_columns()
        .where(
            MetricObservation.subject_type == SubjectType(subject_type),
            MetricObservation.subject_id == subject_id,
        )
        .order_by(
            MetricDefinition.slug,
            MetricObservation.window_days.nulls_first(),
            MetricObservation.dimension_value.nulls_first(),
            Source.name,
            MetricObservation.id,
        )
    )
    return list(session.execute(stmt).all())


# --- compare ------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompareCohortRow:
    """What the fallback statement (or any page row) says about the cohort."""

    court_id: uuid.UUID | None
    jurisdiction_id: uuid.UUID
    name: str


@dataclass(frozen=True, slots=True)
class ComparePageResult:
    rows: list[Row[Any]]
    total: int
    cohort: CompareCohortRow


def _figure(column: Any) -> ColumnElement[Any]:
    """``column`` for a row that is not suppressed, else null: a withheld number never sorts."""
    return case((MetricObservation.suppressed_flag.is_(True), null()), else_=column)


def compare_page(
    session: Session,
    *,
    slug: str,
    version: str,
    window_days: int | None,
    court_id: uuid.UUID | None,
    jurisdiction_id: uuid.UUID | None,
    period_start: date | None,
    period_end: date | None,
    sort: CompareSortKey,
    descending: bool,
    limit: int,
    offset: int,
) -> ComparePageResult | None:
    """One page of judges' observations of one metric within one cohort (module docstring).

    Exactly one of ``court_id`` and ``jurisdiction_id`` is given. ``None``
    means the court or jurisdiction does not exist.
    """
    if (court_id is None) == (jurisdiction_id is None):
        msg = "exactly one of court_id and jurisdiction_id is required"
        raise ValueError(msg)
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}"
        raise ValueError(msg)
    if offset < 0:
        msg = "offset must be non-negative"
        raise ValueError(msg)

    # The judge's court within the cohort: the latest service record at the
    # court (or at any court of the jurisdiction). Joining it also restricts
    # the rows to the cohort's judges.
    cohort_court = (
        select(
            Court.id.label("court_id"),
            Court.canonical_name.label("court_name"),
            Court.court_type.label("court_type"),
            Jurisdiction.id.label("jurisdiction_id"),
            Jurisdiction.name.label("jurisdiction_name"),
        )
        .select_from(JudgeService)
        .join(Court, Court.id == JudgeService.court_id)
        .join(Jurisdiction, Jurisdiction.id == Court.jurisdiction_id)
        .where(JudgeService.judge_id == Judge.id)
        .where(
            Court.id == court_id
            if court_id is not None
            else Court.jurisdiction_id == jurisdiction_id
        )
        .order_by(JudgeService.start_date.desc().nulls_last(), JudgeService.id)
        .limit(1)
        .lateral("cohort_court")
    )
    period_rows = (
        func.count()
        .over(partition_by=(MetricObservation.period_start, MetricObservation.period_end))
        .label("period_rows")
    )
    inner = (
        select(
            MetricObservation.id.label("observation_id"),
            Judge.id.label("judge_id"),
            Judge.canonical_name.label("judge_name"),
            cohort_court.c.court_id,
            cohort_court.c.court_name,
            cohort_court.c.court_type,
            cohort_court.c.jurisdiction_id,
            cohort_court.c.jurisdiction_name,
            Source.name.label("source_name"),
            (Source.source_type == SYNTHETIC_SOURCE_TYPE).label("synthetic"),
            Source.coverage_start.label("coverage_start"),
            Source.coverage_end.label("coverage_end"),
            Source.observable_outcomes.label("observable_outcomes"),
            MetricObservation.period_start,
            MetricObservation.period_end,
            MetricObservation.window_days,
            MetricObservation.dimension_value,
            MetricObservation.eligible_count,
            MetricObservation.cohort_size,
            MetricObservation.observed_count,
            MetricObservation.observed_rate,
            MetricObservation.value,
            MetricObservation.distribution,
            MetricObservation.lower_confidence_bound,
            MetricObservation.upper_confidence_bound,
            MetricObservation.suppressed_flag,
            MetricDefinition.suppression_threshold,
            MetricDefinition.kind.label("kind"),
            MetricDefinition.outcome.label("outcome"),
            _figure(MetricObservation.observed_rate).label("sort_rate"),
            _figure(MetricObservation.observed_count).label("sort_numerator"),
            _figure(MetricObservation.cohort_size).label("sort_denominator"),
            _figure(MetricObservation.value).label("sort_value"),
            period_rows,
        )
        .select_from(MetricObservation)
        .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
        .join(Judge, Judge.id == MetricObservation.subject_id)
        .join(cohort_court, true())
        .join(Source, Source.id == MetricObservation.source_id)
        .where(
            MetricObservation.superseded_at.is_(None),
            MetricObservation.subject_type == SubjectType.JUDGE,
            MetricDefinition.slug == slug,
            MetricDefinition.version == version,
        )
    )
    inner = (
        inner.where(MetricObservation.window_days == window_days)
        if window_days is not None
        else inner.where(MetricObservation.window_days.is_(None))
    )
    if period_start is not None:
        inner = inner.where(MetricObservation.period_start == period_start)
    if period_end is not None:
        inner = inner.where(MetricObservation.period_end == period_end)
    rows = inner.subquery("rows")

    # The reference period: the one most rows of the whole cohort share
    # (ties broken by the earliest period), carried on every row.
    reference = (rows.c.period_rows.desc(), rows.c.period_start, rows.c.period_end)
    sort_column = {
        "rate": rows.c.sort_rate,
        "numerator": rows.c.sort_numerator,
        "denominator": rows.c.sort_denominator,
        "value": rows.c.sort_value,
        "name": rows.c.judge_name,
    }[sort]
    ordered = sort_column.desc().nulls_last() if descending else sort_column.asc().nulls_last()
    stmt = (
        select(
            rows,
            func.first_value(rows.c.period_start).over(order_by=reference).label("cohort_start"),
            func.first_value(rows.c.period_end).over(order_by=reference).label("cohort_end"),
            func.count().over().label("total"),
        )
        .order_by(ordered, rows.c.judge_name, rows.c.judge_id, rows.c.dimension_value)
        .limit(limit)
        .offset(offset)
    )
    results = session.execute(stmt).all()
    if results:
        first = results[0]
        cohort = CompareCohortRow(
            court_id=court_id,
            jurisdiction_id=first.jurisdiction_id,
            name=str(first.court_name if court_id is not None else first.jurisdiction_name),
        )
        return ComparePageResult(list(results), int(first.total), cohort)
    total = select(func.count()).select_from(rows).scalar_subquery()
    if court_id is not None:
        found = session.execute(
            select(Court.id, Court.jurisdiction_id, Court.canonical_name, total).where(
                Court.id == court_id
            )
        ).one_or_none()
        if found is None:
            return None
        return ComparePageResult(
            [], int(found[3] or 0), CompareCohortRow(found[0], found[1], str(found[2]))
        )
    found = session.execute(
        select(Jurisdiction.id, Jurisdiction.name, total).where(Jurisdiction.id == jurisdiction_id)
    ).one_or_none()
    if found is None:
        return None
    return ComparePageResult(
        [], int(found[2] or 0), CompareCohortRow(None, found[0], str(found[1]))
    )
