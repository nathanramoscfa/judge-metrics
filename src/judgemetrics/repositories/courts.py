# src/judgemetrics/repositories/courts.py
"""Court queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Court
from judgemetrics.repositories.common import paginate


def list_courts(
    session: Session,
    *,
    jurisdiction_id: uuid.UUID | None,
    court_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Court], int]:
    stmt = select(Court).order_by(Court.canonical_name, Court.id)
    if jurisdiction_id is not None:
        stmt = stmt.where(Court.jurisdiction_id == jurisdiction_id)
    if court_type is not None:
        stmt = stmt.where(Court.court_type == court_type)
    return paginate(session, stmt, limit=limit, offset=offset)


def get_court(session: Session, court_id: uuid.UUID) -> Court | None:
    return session.get(Court, court_id)
