# src/judgemetrics/api/routes/metrics.py
"""``/api/v1/metrics``: the registry, the compare table, and an observation's provenance.

The judge- and court-level observation routes live beside their subjects
(``/judges/{id}/metrics`` in ``judges.py``, ``/courts/{id}/metrics`` in
``courts.py``); the shared handler is ``subject_metrics_route`` below.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from judgemetrics.api.deps import (
    PAGE_PARAMS,
    PageDep,
    SessionDep,
    SettingsDep,
    StrictQuery,
    cache_public,
)
from judgemetrics.api.errors import ApiError, error_responses
from judgemetrics.config import Settings
from judgemetrics.schemas.metrics import (
    ComparePage,
    ObservationProvenance,
    Registry,
    SubjectMetrics,
)
from judgemetrics.services.metrics import (
    compare,
    observation_provenance,
    registry_response,
    subject_metrics,
)

router = APIRouter(prefix="/metrics", tags=["metrics"], dependencies=[Depends(cache_public)])

COMPARE_PARAMS = (
    "metric",
    "window",
    "court_id",
    "jurisdiction_id",
    "period_start",
    "period_end",
    "sort",
    "order",
    *PAGE_PARAMS,
)


def subject_metrics_route(
    session: Session, settings: Settings, subject_type: str, subject_id: uuid.UUID
) -> SubjectMetrics:
    """The shared handler of ``/judges/{id}/metrics`` and ``/courts/{id}/metrics``."""
    found = subject_metrics(session, settings, subject_type, subject_id)
    if found is None:
        raise ApiError(
            status_code=404, code="not_found", message=f"{subject_type} {subject_id} not found"
        )
    return found


@router.get(
    "",
    response_model=Registry,
    responses=error_responses(422),
    summary="The metric registry: definitions, versions, thresholds, known limitations",
    dependencies=[Depends(StrictQuery())],
)
def get_registry(settings: SettingsDep) -> Registry:
    return registry_response(settings)


@router.get(
    "/compare",
    response_model=ComparePage,
    responses=error_responses(404, 422),
    summary="One metric and window for the judges of a court or jurisdiction, sorted and paginated",
    dependencies=[Depends(StrictQuery(*COMPARE_PARAMS))],
)
def get_compare(
    session: SessionDep,
    settings: SettingsDep,
    page: PageDep,
    metric: Annotated[
        str,
        Query(
            min_length=1,
            max_length=64,
            pattern=r"^[a-z][a-z0-9_]*$",
            description="A registry metric slug (`GET /metrics`).",
        ),
    ],
    window: Annotated[
        int | None,
        Query(
            ge=1,
            le=3650,
            description="The follow-up window in days; required for, and one of, the metric's windows.",
        ),
    ] = None,
    court_id: Annotated[
        uuid.UUID | None, Query(description="Judges with a service record at this court.")
    ] = None,
    jurisdiction_id: Annotated[
        uuid.UUID | None,
        Query(description="Judges with a service record at a court of this jurisdiction."),
    ] = None,
    period_start: Annotated[
        date | None, Query(description="Only observations whose period starts on this date.")
    ] = None,
    period_end: Annotated[
        date | None, Query(description="Only observations whose period ends on this date.")
    ] = None,
    sort: Annotated[
        Literal["rate", "numerator", "denominator", "value", "name"],
        Query(description="Sort key; a suppressed row sorts as if its figure were null."),
    ] = "rate",
    order: Annotated[Literal["asc", "desc"], Query(description="Sort direction.")] = "desc",
) -> ComparePage:
    if (court_id is None) == (jurisdiction_id is None):
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="court_id: exactly one of court_id and jurisdiction_id is required",
        )
    if period_start is not None and period_end is not None and period_end < period_start:
        raise ApiError(
            status_code=422,
            code="validation_error",
            message="period_end: must not be earlier than period_start",
        )
    result = compare(
        session,
        settings,
        slug=metric,
        window_days=window,
        court_id=court_id,
        jurisdiction_id=jurisdiction_id,
        period_start=period_start,
        period_end=period_end,
        sort=sort,
        order=order,
        limit=page.limit,
        offset=page.offset,
    )
    if result is None:
        what = "court" if court_id is not None else "jurisdiction"
        raise ApiError(
            status_code=404,
            code="not_found",
            message=f"{what} {court_id if court_id is not None else jurisdiction_id} not found",
        )
    return result


@router.get(
    "/{observation_id}/provenance",
    response_model=ObservationProvenance,
    responses=error_responses(404, 422),
    summary="The provenance chain of a current observation, from its number to the raw artifacts",
    dependencies=[Depends(StrictQuery())],
)
def get_observation_provenance(
    observation_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> ObservationProvenance:
    found = observation_provenance(session, settings, observation_id)
    if found is None:
        raise ApiError(
            status_code=404, code="not_found", message=f"observation {observation_id} not found"
        )
    return found
