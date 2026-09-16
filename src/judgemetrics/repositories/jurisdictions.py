# src/judgemetrics/repositories/jurisdictions.py
"""Jurisdiction queries."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Jurisdiction
from judgemetrics.repositories.common import paginate


def list_jurisdictions(
    session: Session, *, limit: int, offset: int
) -> tuple[list[Jurisdiction], int]:
    stmt = select(Jurisdiction).order_by(Jurisdiction.name, Jurisdiction.id)
    return paginate(session, stmt, limit=limit, offset=offset)


def get_jurisdiction(session: Session, jurisdiction_id: uuid.UUID) -> Jurisdiction | None:
    return session.get(Jurisdiction, jurisdiction_id)
