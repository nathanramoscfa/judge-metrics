# src/judgemetrics/api/routes/cases.py
"""``/api/v1/cases``: the case detail and its timeline."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from judgemetrics.api.deps import SessionDep, StrictQuery, cache_public
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.schemas.cases import CaseDetail, Timeline
from judgemetrics.services.cases import case_detail, case_timeline

router = APIRouter(prefix="/cases", tags=["cases"], dependencies=[Depends(cache_public)])


def _not_found(case_id: uuid.UUID) -> ApiError:
    return ApiError(status_code=404, code="not_found", message=f"case {case_id} not found")


@router.get(
    "/{case_id}",
    response_model=CaseDetail,
    responses=error_responses(404, 422),
    summary="Case detail: parties, assignments, charges, decisions, sentences, provenance",
    dependencies=[Depends(StrictQuery())],
)
def get_case(case_id: uuid.UUID, session: SessionDep) -> CaseDetail:
    detail = case_detail(session, case_id)
    if detail is None:
        raise _not_found(case_id)
    return detail


@router.get(
    "/{case_id}/timeline",
    response_model=Timeline,
    responses=error_responses(404, 422),
    summary="Every dated fact of a case in chronological order, each citing its artifact",
    dependencies=[Depends(StrictQuery())],
)
def get_case_timeline(case_id: uuid.UUID, session: SessionDep) -> Timeline:
    timeline = case_timeline(session, case_id)
    if timeline is None:
        raise _not_found(case_id)
    return timeline
