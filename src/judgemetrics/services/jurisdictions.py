# src/judgemetrics/services/jurisdictions.py
"""Jurisdiction responses assembled from the repository rows."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from judgemetrics.repositories.jurisdictions import get_jurisdiction, list_jurisdictions
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.jurisdictions import JurisdictionDetail, JurisdictionSummary
from judgemetrics.services.provenance import provenance_for


def jurisdictions_page(session: Session, *, limit: int, offset: int) -> Page[JurisdictionSummary]:
    rows, total = list_jurisdictions(session, limit=limit, offset=offset)
    items = [JurisdictionSummary.model_validate(row) for row in rows]
    return Page[JurisdictionSummary].build(items, total=total, limit=limit, offset=offset)


def jurisdiction_detail(session: Session, jurisdiction_id: uuid.UUID) -> JurisdictionDetail | None:
    jurisdiction = get_jurisdiction(session, jurisdiction_id)
    if jurisdiction is None:
        return None
    provenance = provenance_for(session, [jurisdiction.source_record_id])
    return JurisdictionDetail.from_row(jurisdiction, provenance=provenance)
