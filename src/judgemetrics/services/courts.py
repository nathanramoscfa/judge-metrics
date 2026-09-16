# src/judgemetrics/services/courts.py
"""Court responses assembled from the repository rows."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from judgemetrics.repositories.courts import get_court, list_courts
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.courts import CourtDetail, CourtSummary
from judgemetrics.services.provenance import provenance_for


def courts_page(
    session: Session,
    *,
    jurisdiction_id: uuid.UUID | None,
    court_type: str | None,
    limit: int,
    offset: int,
) -> Page[CourtSummary]:
    rows, total = list_courts(
        session, jurisdiction_id=jurisdiction_id, court_type=court_type, limit=limit, offset=offset
    )
    items = [CourtSummary.model_validate(row) for row in rows]
    return Page[CourtSummary].build(items, total=total, limit=limit, offset=offset)


def court_detail(session: Session, court_id: uuid.UUID) -> CourtDetail | None:
    court = get_court(session, court_id)
    if court is None:
        return None
    return CourtDetail.from_row(court, provenance=provenance_for(session, [court.source_record_id]))
