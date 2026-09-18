# src/judgemetrics/api/routes/coverage.py
"""``/api/v1/coverage``: what each source contributes, and whether any of it is synthetic."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from judgemetrics.api.deps import SessionDep, StrictQuery, cache_public
from judgemetrics.api.errors import error_responses
from judgemetrics.schemas.coverage import Coverage
from judgemetrics.services.coverage import coverage

router = APIRouter(prefix="/coverage", tags=["coverage"], dependencies=[Depends(cache_public)])


@router.get(
    "",
    response_model=Coverage,
    responses=error_responses(422),
    summary="Coverage per source: counts, filing window, last run, synthetic flag",
    dependencies=[Depends(StrictQuery())],
)
def get_coverage(session: SessionDep) -> Coverage:
    return coverage(session)
