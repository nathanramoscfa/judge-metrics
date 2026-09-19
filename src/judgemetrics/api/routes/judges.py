# src/judgemetrics/api/routes/judges.py
"""``/api/v1/judges``: the list, the detail, the service records, the judge's cases, and metrics."""

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
from judgemetrics.api.routes.metrics import subject_metrics_route
from judgemetrics.schemas.cases import CaseSummary
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.judges import JudgeDetail, JudgeStatus, JudgeSummary, ServiceRecord
from judgemetrics.schemas.metrics import SubjectMetrics
from judgemetrics.services.cases import judge_cases_page
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
            description=(
                "Name to match by trigram similarity (normalized before matching): a single "
                "word by word similarity, several words by whole-name similarity."
            ),
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
        word_threshold=settings.search_word_similarity_threshold,
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


@router.get(
    "/{judge_id}/metrics",
    response_model=SubjectMetrics,
    responses=error_responses(404, 422),
    summary="Every current metric observation of a judge, grouped by metric",
    dependencies=[Depends(StrictQuery())],
)
def get_judge_metrics(
    judge_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> SubjectMetrics:
    return subject_metrics_route(session, settings, "judge", judge_id)


VOCABULARY_VALUE = r"^[a-z][a-z0-9_]*$"


@router.get(
    "/{judge_id}/cases",
    response_model=Page[CaseSummary],
    responses=error_responses(404, 422),
    summary="Cases assigned to a judge, newest filing first",
    dependencies=[
        Depends(StrictQuery("filed_from", "filed_to", "status", "case_type", *PAGE_PARAMS))
    ],
)
def list_judge_cases(
    judge_id: uuid.UUID,
    session: SessionDep,
    page: PageDep,
    filed_from: Annotated[
        date | None, Query(description="Only cases filed on or after this date (ISO 8601).")
    ] = None,
    filed_to: Annotated[
        date | None, Query(description="Only cases filed on or before this date (ISO 8601).")
    ] = None,
    status: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=32,
            pattern=VOCABULARY_VALUE,
            description="Exact case status: `open` or `closed` (data/reference/case_vocabulary.yaml).",
        ),
    ] = None,
    case_type: Annotated[
        str | None,
        Query(
            min_length=1,
            max_length=64,
            pattern=VOCABULARY_VALUE,
            description="Exact case type: `felony` or `misdemeanor` (case_vocabulary.yaml).",
        ),
    ] = None,
) -> Page[CaseSummary]:
    if filed_from is not None and filed_to is not None and filed_to < filed_from:
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="filed_to: must not be earlier than filed_from",
        )
    cases = judge_cases_page(
        session,
        judge_id,
        filed_from=filed_from,
        filed_to=filed_to,
        status=status,
        case_type=case_type,
        limit=page.limit,
        offset=page.offset,
    )
    if cases is None:
        raise _not_found(judge_id)
    return cases
