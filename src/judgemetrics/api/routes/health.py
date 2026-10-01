# src/judgemetrics/api/routes/health.py
"""``/api/v1/health`` and ``/api/v1/ready``.

``/health`` is a liveness probe: it never touches the database and exposes
only the package version, the build's git SHA, and the migration head the
code expects — no configuration values, hostnames, or credentials.
``/ready`` is the readiness probe: 200 when the database answers ``SELECT 1``
and its applied revision equals the head, 503 with a short reason otherwise;
its ``metrics`` block names the latest exported snapshot (hash, export
time, methodology version) from one statement over ``metric_snapshot``,
or is null before the first ``metrics compute``. Phase 4 Step 3 adds
``metrics.models``: that snapshot's expected-outcome models — ``fitted``
(status fitted), ``unavailable`` (every other status), ``spec_version``,
``model_version`` — from one more statement (null when the snapshot has
none); counts and versions only, never a model hash or an artifact path.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from judgemetrics import __version__
from judgemetrics.config import Settings
from judgemetrics.db.migrations import current_revision, head_revision
from judgemetrics.logging import get_logger
from judgemetrics.repositories.coverage import latest_snapshot, snapshot_models

router = APIRouter(tags=["health"])
log = get_logger(__name__)


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str
    git_sha: str
    alembic_head: str | None


class ModelsReadiness(BaseModel):
    """The latest snapshot's expected-outcome models: counts and versions, never a hash."""

    fitted: int = Field(ge=0, description="Models with status fitted.")
    unavailable: int = Field(
        ge=0, description="Models without coefficients (too few events, or not converged)."
    )
    spec_version: int = Field(description="The outcome model specification version.")
    model_version: str = Field(description="The model family and feature set.")


class MetricsReadiness(BaseModel):
    """The latest exported snapshot: what the metrics routes currently serve from."""

    snapshot_hash: str
    exported_at: datetime
    methodology_version: str
    models: ModelsReadiness | None = Field(
        description="The snapshot's expected-outcome models; null before any is fitted."
    )


class ReadyResponse(BaseModel):
    status: Literal["ready"]
    database: Literal["ok"]
    alembic_current: str | None
    metrics: MetricsReadiness | None


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
    with Session(request.app.state.engine) as session:
        snapshot = latest_snapshot(session)
        models = None if snapshot is None else snapshot_models(session, snapshot.content_hash)
    ok = ReadyResponse(
        status="ready",
        database="ok",
        alembic_current=current,
        metrics=(
            None
            if snapshot is None
            else MetricsReadiness(
                snapshot_hash=snapshot.content_hash,
                exported_at=snapshot.exported_at,
                methodology_version=snapshot.methodology_version,
                models=(
                    None
                    if models is None
                    else ModelsReadiness(
                        fitted=models.fitted,
                        unavailable=models.unavailable,
                        spec_version=models.spec_version,
                        model_version=models.model_version,
                    )
                ),
            )
        ),
    )
    return JSONResponse(status_code=200, content=ok.model_dump(mode="json"))
