# src/judgemetrics/api/routes/courts.py
"""``/api/v1/courts``: the list and the detail."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from judgemetrics.api.deps import PAGE_PARAMS, PageDep, SessionDep, StrictQuery, cache_public
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.courts import CourtDetail, CourtSummary
from judgemetrics.services.courts import court_detail, courts_page

router = APIRouter(prefix="/courts", tags=["courts"], dependencies=[Depends(cache_public)])


@router.get(
    "",
    response_model=Page[CourtSummary],
    responses=error_responses(422),
    summary="List courts",
    dependencies=[Depends(StrictQuery("jurisdiction_id", "court_type", *PAGE_PARAMS))],
)
def list_courts(
    session: SessionDep,
    page: PageDep,
    jurisdiction_id: Annotated[
        uuid.UUID | None, Query(description="Only courts of this jurisdiction.")
    ] = None,
    court_type: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=64,
            pattern=r"^[a-z][a-z0-9_]*$",
            description="Exact court type: district, appeals, supreme, other (federal, Phase 1).",
        ),
    ] = None,
) -> Page[CourtSummary]:
    return courts_page(
        session,
        jurisdiction_id=jurisdiction_id,
        court_type=court_type,
        limit=page.limit,
        offset=page.offset,
    )


@router.get(
    "/{court_id}",
    response_model=CourtDetail,
    responses=error_responses(404, 422),
    summary="Court detail with provenance",
    dependencies=[Depends(StrictQuery())],
)
def get_court(court_id: uuid.UUID, session: SessionDep) -> CourtDetail:
    detail = court_detail(session, court_id)
    if detail is None:
        raise ApiError(status_code=404, code="not_found", message=f"court {court_id} not found")
    return detail
