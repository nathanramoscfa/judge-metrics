# src/judgemetrics/api/routes/jurisdictions.py
"""``/api/v1/jurisdictions``: the list and the detail."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from judgemetrics.api.deps import PAGE_PARAMS, PageDep, SessionDep, StrictQuery, cache_public
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.jurisdictions import JurisdictionDetail, JurisdictionSummary
from judgemetrics.services.jurisdictions import jurisdiction_detail, jurisdictions_page

router = APIRouter(
    prefix="/jurisdictions", tags=["jurisdictions"], dependencies=[Depends(cache_public)]
)


@router.get(
    "",
    response_model=Page[JurisdictionSummary],
    responses=error_responses(422),
    summary="List jurisdictions",
    dependencies=[Depends(StrictQuery(*PAGE_PARAMS))],
)
def list_jurisdictions(session: SessionDep, page: PageDep) -> Page[JurisdictionSummary]:
    return jurisdictions_page(session, limit=page.limit, offset=page.offset)


@router.get(
    "/{jurisdiction_id}",
    response_model=JurisdictionDetail,
    responses=error_responses(404, 422),
    summary="Jurisdiction detail with provenance",
    dependencies=[Depends(StrictQuery())],
)
def get_jurisdiction(jurisdiction_id: uuid.UUID, session: SessionDep) -> JurisdictionDetail:
    detail = jurisdiction_detail(session, jurisdiction_id)
    if detail is None:
        raise ApiError(
            status_code=404, code="not_found", message=f"jurisdiction {jurisdiction_id} not found"
        )
    return detail
