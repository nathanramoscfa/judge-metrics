# src/judgemetrics/api/routes/judges.py
"""``/api/v1/judges``: the list, the detail, and the service records."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from judgemetrics.api.deps import (
    PAGE_PARAMS,
    PageDep,
    SessionDep,
    SettingsDep,
    StrictQuery,
    cache_public,
)
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.judges import JudgeDetail, JudgeStatus, JudgeSummary, ServiceRecord
from judgemetrics.services.judges import judge_detail, judge_service, judges_page

router = APIRouter(prefix="/judges", tags=["judges"], dependencies=[Depends(cache_public)])


def _not_found(judge_id: uuid.UUID) -> ApiError:
    return ApiError(status_code=404, code="not_found", message=f"judge {judge_id} not found")


@router.get(
    "",
    response_model=Page[JudgeSummary],
    responses=error_responses(422),
    summary="List judges",
    dependencies=[Depends(StrictQuery("q", "court_id", "active_on", "status", *PAGE_PARAMS))],
)
def list_judges(
    session: SessionDep,
    settings: SettingsDep,
    page: PageDep,
    q: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=200,
            description="Name to match by trigram similarity (normalized before matching).",
        ),
    ] = None,
    court_id: Annotated[
        uuid.UUID | None, Query(description="Only judges with a service record at this court.")
    ] = None,
    active_on: Annotated[
        date | None,
        Query(description="Only judges whose service interval covers this date (ISO 8601)."),
    ] = None,
    status: Annotated[JudgeStatus | None, Query(description="Exact status.")] = None,
) -> Page[JudgeSummary]:
    return judges_page(
        session,
        q=q,
        court_id=court_id,
        active_on=active_on,
        status=status,
        limit=page.limit,
        offset=page.offset,
        threshold=settings.search_similarity_threshold,
    )


@router.get(
    "/{judge_id}",
    response_model=JudgeDetail,
    responses=error_responses(404, 422),
    summary="Judge detail with service records and provenance",
    dependencies=[Depends(StrictQuery())],
)
def get_judge(judge_id: uuid.UUID, session: SessionDep) -> JudgeDetail:
    detail = judge_detail(session, judge_id)
    if detail is None:
        raise _not_found(judge_id)
    return detail


@router.get(
    "/{judge_id}/service",
    response_model=list[ServiceRecord],
    responses=error_responses(404, 422),
    summary="Service records of a judge, oldest first",
    dependencies=[Depends(StrictQuery())],
)
def get_judge_service(judge_id: uuid.UUID, session: SessionDep) -> list[ServiceRecord]:
    service = judge_service(session, judge_id)
    if service is None:
        raise _not_found(judge_id)
    return service
