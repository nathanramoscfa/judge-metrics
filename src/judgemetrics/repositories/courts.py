# src/judgemetrics/repositories/courts.py
"""Court queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Court
from judgemetrics.repositories.common import paginate_rows
from judgemetrics.repositories.provenance import synthetic_flag, with_source


def list_courts(
    session: Session,
    *,
    jurisdiction_id: uuid.UUID | None,
    court_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Court, bool]], int]:
    """One page of courts, each with its synthetic flag, in one statement."""
    stmt = with_source(select(Court, synthetic_flag()), Court.source_record_id).order_by(
        Court.canonical_name, Court.id
    )
    if jurisdiction_id is not None:
        stmt = stmt.where(Court.jurisdiction_id == jurisdiction_id)
    if court_type is not None:
        stmt = stmt.where(Court.court_type == court_type)
    rows, total = paginate_rows(session, stmt, limit=limit, offset=offset)
    return [(row[0], bool(row[1])) for row in rows], total


def get_court(session: Session, court_id: uuid.UUID) -> tuple[Court, bool] | None:
    """The court with its synthetic flag: one statement."""
    stmt = with_source(select(Court, synthetic_flag()), Court.source_record_id).where(
        Court.id == court_id
    )
    row = session.execute(stmt).one_or_none()
    return None if row is None else (row[0], bool(row[1]))
