# src/judgemetrics/main.py
"""FastAPI application factory.

``create_app()`` wires settings, logging, the request-id and access-log
middleware, the error handlers, the app-bound engine and session factory,
the ``/search`` rate limiter, and the versioned routers under ``/api/v1``.
The module-level ``app`` is what uvicorn serves (``judgemetrics serve``).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.openapi.utils import get_openapi

from judgemetrics import __version__
from judgemetrics.api import API_PREFIX, REQUEST_ID_HEADER
from judgemetrics.api.errors import install_exception_handlers
from judgemetrics.api.identity import API_KEY_HEADER
from judgemetrics.api.ratelimit import TokenBucketLimiter
from judgemetrics.api.routes import cases, courts, coverage, health, judges, jurisdictions, search
from judgemetrics.config import Settings, get_settings
from judgemetrics.db.session import make_engine, make_session_factory
from judgemetrics.logging import configure_logging, get_logger

__all__ = ["API_PREFIX", "REQUEST_ID_HEADER", "app", "create_app"]

API_DESCRIPTION = (
    "Read-only, versioned access to JudgeMetrics' canonical data: judges, courts, "
    "jurisdictions, cases with their timelines, source coverage, and search, each with "
    "the provenance of the raw source artifacts behind it and a `synthetic` flag on "
    "every row derived from the in-repo demo dataset. Lists are paginated "
    "(`limit` ≤ 100), filters are validated strictly (unknown parameters are 422), "
    "persons appear only as pseudonymous public keys, and every error is an "
    "`ErrorBody`. See docs/API.md."
)
API_KEY_SCHEME = "ApiKey"  # pragma: allowlist secret - the OpenAPI scheme name
# An incoming request id is echoed into logs and headers, so it is accepted
# only when it is short and printable-safe; anything else is replaced.
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

Next = Callable[[Request], Awaitable[Response]]


def _request_id_from(request: Request) -> str:
    incoming = request.headers.get(REQUEST_ID_HEADER, "")
    if _SAFE_REQUEST_ID.match(incoming):
        return incoming
    return str(uuid.uuid4())


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API. ``settings`` defaults to the cached process settings."""
    settings = settings or get_settings()
    configure_logging(settings)
    access_log = get_logger("judgemetrics.access")

    app = FastAPI(
        title="JudgeMetrics API",
        version=__version__,
        description=API_DESCRIPTION,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    # Creating an engine does not connect; the readiness probe is the first user.
    # Routes open sessions from this factory (api.deps.get_session), so an app
    # built with explicit settings never touches the process-wide engine.
    app.state.engine = make_engine(settings.database_url)
    app.state.session_factory = make_session_factory(app.state.engine)
    app.state.search_limiter = (
        TokenBucketLimiter(
            per_minute=settings.search_rate_limit_per_minute,
            burst=settings.search_rate_limit_burst,
        )
        if settings.effective_search_rate_limit_enabled
        else None
    )
    install_exception_handlers(app)

    # Middleware added later wraps middleware added earlier, so the request-id
    # binder (added last) runs outermost and the access log sees the id.
    @app.middleware("http")
    async def access_log_middleware(request: Request, call_next: Next) -> Response:
        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        access_log.info(
            "http.request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Next) -> Response:
        request_id = _request_id_from(request)
        request.state.request_id = request_id
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        try:
            response = await call_next(request)
        finally:
            structlog.contextvars.clear_contextvars()
        response.headers[REQUEST_ID_HEADER] = request_id
        return response

    app.include_router(health.router, prefix=API_PREFIX)
    app.include_router(judges.router, prefix=API_PREFIX)
    app.include_router(courts.router, prefix=API_PREFIX)
    app.include_router(jurisdictions.router, prefix=API_PREFIX)
    app.include_router(cases.router, prefix=API_PREFIX)
    app.include_router(search.router, prefix=API_PREFIX)
    app.include_router(coverage.router, prefix=API_PREFIX)
    app.openapi = lambda: _openapi(app)  # type: ignore[method-assign]
    return app


def _openapi(app: FastAPI) -> dict[str, Any]:
    """The generated document plus the optional API-key scheme (ROADMAP.md §1.4).

    ``security: [{}, {ApiKey: []}]`` declares the scheme optional for every
    operation: anonymous requests are the only tier until Phase 9 issues keys.
    """
    if app.openapi_schema:
        return app.openapi_schema
    document = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    document.setdefault("components", {}).setdefault("securitySchemes", {})[API_KEY_SCHEME] = {
        "type": "apiKey",
        "in": "header",
        "name": API_KEY_HEADER,
        "description": (
            "Optional. No keys are issued yet; a request without one is served as the "
            "anonymous tier, rate limited by client address."
        ),
    }
    document["security"] = [{}, {API_KEY_SCHEME: []}]
    app.openapi_schema = document
    return document


app = create_app()
