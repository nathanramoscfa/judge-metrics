# src/judgemetrics/repositories/coverage.py
"""Coverage v0: per-source row counts, filing window, and the latest run.

Two statements whatever the number of sources: one over ``source`` with a
correlated count per canonical table (rows whose ``source_record`` belongs
to that source; persons exclude merged rows) and the filing-date span of
its cases, and one ``DISTINCT ON`` over ``ingest_run`` for the most recent
completed run of each source.
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


class LastRun(NamedTuple):
    source: str
    run_id: uuid.UUID
    completed_at: datetime | None
    status: IngestRunStatus


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
    ).order_by(Source.name)
    counts: list[SourceCounts] = []
    for row in session.execute(stmt).tuples():
        name, source_type, synthetic, jurisdictions, courts, judges, cases, persons, lo, hi = row
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
