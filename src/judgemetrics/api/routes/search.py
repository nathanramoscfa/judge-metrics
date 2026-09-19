# src/judgemetrics/api/routes/search.py
"""``/api/v1/search``: trigram search over judges and courts, rate limited."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from judgemetrics.api.deps import SessionDep, SettingsDep, StrictQuery
from judgemetrics.api.errors import error_responses
from judgemetrics.api.ratelimit import search_rate_limit
from judgemetrics.repositories.common import DEFAULT_LIMIT, MAX_LIMIT
from judgemetrics.schemas.search import SearchResponse
from judgemetrics.services.search import search

router = APIRouter(prefix="/search", tags=["search"])


@router.get(
    "",
    response_model=SearchResponse,
    responses=error_responses(422, 429),
    summary="Search judges and courts by name",
    # The limiter runs before the query parameters are validated, so an
    # over-limit client is refused without touching the database.
    dependencies=[Depends(search_rate_limit), Depends(StrictQuery("q", "limit"))],
)
def search_names(
    session: SessionDep,
    settings: SettingsDep,
    q: Annotated[
        str,
        Query(
            min_length=1,
            max_length=200,
            description=(
                "Name to match, normalized like judge names before matching: a single word "
                "by word similarity (a surname alone), several words by whole-name similarity."
            ),
        ),
    ],
    limit: Annotated[
        int, Query(ge=1, le=MAX_LIMIT, description=f"Results to return, at most {MAX_LIMIT}.")
    ] = DEFAULT_LIMIT,
) -> SearchResponse:
    return search(
        session,
        q,
        limit,
        threshold=settings.search_similarity_threshold,
        word_threshold=settings.search_word_similarity_threshold,
    )
