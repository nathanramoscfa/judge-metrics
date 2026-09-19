# src/judgemetrics/repositories/coverage.py
"""Coverage: per-source row counts, filing window, coverage window, the latest run,
and the latest metric snapshot.

Three statements whatever the number of sources: one over ``source`` with
a correlated count per canonical table (rows whose ``source_record``
belongs to that source; persons exclude merged rows), the filing-date
span of its cases, and its declared coverage window and observable
outcomes (Phase 3); one ``DISTINCT ON`` over ``ingest_run`` for the most
recent completed run of each source; and one ``DISTINCT ON`` over the
current observations for the most recently exported snapshot each
source's numbers come from (Phase 3 Step 3: coverage v1).
``latest_snapshot`` is the one-statement form ``/api/v1/ready`` uses:
the newest snapshot of all.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Mapped, Session

from judgemetrics.db.models import (
    SYNTHETIC_SOURCE_TYPE,
    Case,
    Court,
    IngestRun,
    IngestRunStatus,
    Judge,
    Jurisdiction,
    MetricObservation,
    MetricSnapshot,
    Person,
    Source,
    SourceRecord,
)
from judgemetrics.entity_resolution.merge import unmerged


class SourceCounts(NamedTuple):
    source: str
    source_type: str
    synthetic: bool
    jurisdictions: int
    courts: int
    judges: int
    cases: int
    persons: int
    earliest_filed: date | None
    latest_filed: date | None
    coverage_start: date | None
    coverage_end: date | None
    observable_outcomes: list[str]


class LastRun(NamedTuple):
    source: str
    run_id: uuid.UUID
    completed_at: datetime | None
    status: IngestRunStatus


class LatestSnapshot(NamedTuple):
    content_hash: str
    exported_at: datetime
    methodology_version: str


def _count(source_record_id: Mapped[Any], *extra: ColumnElement[bool]) -> ColumnElement[int]:
    """Rows of ``source_record_id``'s table whose artifact belongs to the enclosing source."""
    stmt = (
        select(func.count(source_record_id))
        .join(SourceRecord, SourceRecord.id == source_record_id)
        .where(SourceRecord.source_id == Source.id, *extra)
    )
    return stmt.scalar_subquery()


def _filed(aggregate: Callable[[Any], Any]) -> ColumnElement[date | None]:
    """``aggregate`` over the filing dates of the enclosing source's cases."""
    stmt = (
        select(aggregate(Case.filed_date))
        .join(SourceRecord, SourceRecord.id == Case.source_record_id)
        .where(SourceRecord.source_id == Source.id)
    )
    return stmt.scalar_subquery()


def source_counts(session: Session) -> list[SourceCounts]:
    """Every registered source with its counts and filing window, by name: one statement."""
    stmt = select(
        Source.name,
        Source.source_type,
        Source.source_type == SYNTHETIC_SOURCE_TYPE,
        _count(Jurisdiction.source_record_id),
        _count(Court.source_record_id),
        _count(Judge.source_record_id),
        _count(Case.source_record_id),
        _count(Person.source_record_id, unmerged()),
        _filed(func.min),
        _filed(func.max),
        Source.coverage_start,
        Source.coverage_end,
        Source.observable_outcomes,
    ).order_by(Source.name)
    counts: list[SourceCounts] = []
    for row in session.execute(stmt).tuples():
        (
            name,
            source_type,
            synthetic,
            jurisdictions,
            courts,
            judges,
            cases,
            persons,
            lo,
            hi,
            coverage_start,
            coverage_end,
            observable,
        ) = row
        counts.append(
            SourceCounts(
                source=name,
                source_type=source_type,
                synthetic=bool(synthetic),
                jurisdictions=int(jurisdictions),
                courts=int(courts),
                judges=int(judges),
                cases=int(cases),
                persons=int(persons),
                earliest_filed=lo,
                latest_filed=hi,
                coverage_start=coverage_start,
                coverage_end=coverage_end,
                observable_outcomes=sorted(str(item) for item in (observable or [])),
            )
        )
    return counts


def last_runs(session: Session) -> dict[str, LastRun]:
    """The most recent completed run per source, keyed by source name: one statement."""
    stmt = (
        select(Source.name, IngestRun.id, IngestRun.completed_at, IngestRun.status)
        .join(Source, Source.id == IngestRun.source_id)
        .where(IngestRun.completed_at.is_not(None))
        .distinct(IngestRun.source_id)
        .order_by(IngestRun.source_id, IngestRun.completed_at.desc(), IngestRun.id)
    )
    return {
        name: LastRun(name, run_id, completed_at, status)
        for name, run_id, completed_at, status in session.execute(stmt).tuples()
    }


def latest_snapshots(session: Session) -> dict[str, LatestSnapshot]:
    """The newest snapshot behind each source's current observations, by source name: one statement."""
    stmt = (
        select(
            Source.name,
            MetricSnapshot.content_hash,
            MetricSnapshot.exported_at,
            MetricSnapshot.methodology_version,
        )
        .select_from(MetricObservation)
        .join(Source, Source.id == MetricObservation.source_id)
        .join(MetricSnapshot, MetricSnapshot.id == MetricObservation.snapshot_id)
        .where(MetricObservation.superseded_at.is_(None))
        .distinct(MetricObservation.source_id)
        .order_by(MetricObservation.source_id, MetricSnapshot.exported_at.desc(), MetricSnapshot.id)
    )
    return {
        name: LatestSnapshot(content_hash, exported_at, methodology_version)
        for name, content_hash, exported_at, methodology_version in session.execute(stmt).tuples()
    }


def latest_snapshot(session: Session) -> LatestSnapshot | None:
    """The most recently exported snapshot of all, or ``None`` before the first compute."""
    stmt = (
        select(
            MetricSnapshot.content_hash,
            MetricSnapshot.exported_at,
            MetricSnapshot.methodology_version,
        )
        .order_by(MetricSnapshot.exported_at.desc(), MetricSnapshot.id)
        .limit(1)
    )
    row = session.execute(stmt).first()
    return None if row is None else LatestSnapshot(str(row[0]), row[1], str(row[2]))
