# src/judgemetrics/api/deps.py
"""FastAPI dependencies shared by the v1 routes.

- ``get_settings`` / ``get_session``: the app's settings and one session per
  request from the app's own engine (``create_app`` builds both), so a test
  app constructed with different settings never reaches for the
  process-wide engine.
- ``PageParams``: ``limit`` (default 25, at most 100) and ``offset`` (≥ 0).
- ``StrictQuery``: reject query parameters a route does not declare, so a
  misspelt filter is a 422 rather than a silently unfiltered list.
- ``cache_public``: ``Cache-Control: public, max-age=60`` on successful
  list and detail responses.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Query, Request, Response
from sqlalchemy.orm import Session

from judgemetrics.api.errors import ApiError
from judgemetrics.config import Settings
from judgemetrics.repositories.common import DEFAULT_LIMIT, MAX_LIMIT

CACHE_CONTROL = "public, max-age=60"


def get_settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def get_session(request: Request) -> Iterator[Session]:
    """One read-only session per request, always closed (and so rolled back)."""
    session: Session = request.app.state.session_factory()
    try:
        yield session
    finally:
        session.close()


class PageParams:
    """The pagination query parameters, validated before any query runs."""

    def __init__(
        self,
        limit: Annotated[
            int, Query(ge=1, le=MAX_LIMIT, description=f"Page size, at most {MAX_LIMIT}.")
        ] = DEFAULT_LIMIT,
        offset: Annotated[int, Query(ge=0, description="Rows to skip.")] = 0,
    ) -> None:
        self.limit = limit
        self.offset = offset


PAGE_PARAMS = ("limit", "offset")


class StrictQuery:
    """A dependency that rejects any query parameter not in ``allowed`` with 422.

    The allow-list is explicit rather than derived from FastAPI internals;
    ``tests/unit/test_openapi.py`` checks it against the parameters the
    OpenAPI document declares for the route.
    """

    def __init__(self, *allowed: str) -> None:
        self.allowed = frozenset(allowed)

    def __call__(self, request: Request) -> None:
        unknown = sorted(set(request.query_params) - self.allowed)
        if unknown:
            raise ApiError(
                status_code=422,
                code="validation_error",
                message=f"unknown query parameter(s): {', '.join(unknown)}",
            )


def cache_public(response: Response) -> None:
    response.headers["Cache-Control"] = CACHE_CONTROL


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
PageDep = Annotated[PageParams, Depends()]
