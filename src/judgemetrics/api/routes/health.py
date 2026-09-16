# src/judgemetrics/api/routes/health.py
"""``/api/v1/health`` and ``/api/v1/ready``.

``/health`` is a liveness probe: it never touches the database and exposes
only the package version, the build's git SHA, and the migration head the
code expects — no configuration values, hostnames, or credentials.
``/ready`` is the readiness probe: 200 when the database answers ``SELECT 1``
and its applied revision equals the head, 503 with a short reason otherwise.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError

from judgemetrics import __version__
from judgemetrics.config import Settings
from judgemetrics.db.migrations import current_revision, head_revision
from judgemetrics.logging import get_logger

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    git_sha: str
    alembic_head: str | None


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    database: Literal["ok"]
    alembic_current: str | None


class NotReadyResponse(BaseModel):
    status: Literal["not_ready"]
    reason: str


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    settings = _settings(request)
    return HealthResponse(
        status="ok",
        version=__version__,
        git_sha=settings.resolved_git_sha(),
        alembic_head=head_revision(),
    )


@router.get(
    "/ready",
    response_model=ReadyResponse,
    responses={503: {"model": NotReadyResponse}},
)
def ready(request: Request) -> JSONResponse:
    head = head_revision()
    try:
        current = current_revision(request.app.state.engine)
    except SQLAlchemyError as exc:
        # The exception text may embed the DSN; log its class only.
        log.warning("readiness.database_unreachable", error_type=type(exc).__name__)
        body = NotReadyResponse(status="not_ready", reason="database unreachable")
        return JSONResponse(status_code=503, content=body.model_dump())
    if current != head:
        body = NotReadyResponse(
            status="not_ready",
            reason=f"migration {current or 'none'} applied, {head} expected",
        )
        return JSONResponse(status_code=503, content=body.model_dump())
    ok = ReadyResponse(status="ready", database="ok", alembic_current=current)
    return JSONResponse(status_code=200, content=ok.model_dump())
