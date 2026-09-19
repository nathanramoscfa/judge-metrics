# src/judgemetrics/main.py
"""FastAPI application factory.

``create_app()`` wires settings, logging, the request-id and access-log
middleware, the error handlers, the app-bound engine and session factory,
the ``/search`` and ``/corrections`` rate limiters, and the versioned
routers under ``/api/v1``. Outside the test environment it refuses to
build without a usable ``JUDGEMETRICS_CORRECTION_CONTACT_KEY``
(``security.crypto.require_contact_key``), so a deployment that cannot
encrypt a correction fails at startup rather than answering 503 later.
The module attribute ``app`` is what uvicorn serves (``judgemetrics
serve``, ``judgemetrics.main:app``); it is built lazily on first access
(PEP 562 ``__getattr__``), so importing this module for ``create_app``
never constructs the process-wide app or reads its settings.
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
from judgemetrics.api.routes import (
    cases,
    corrections,
    courts,
    coverage,
    health,
    judges,
    jurisdictions,
    metrics,
    search,
)
from judgemetrics.config import Settings, get_settings
from judgemetrics.db.session import make_engine, make_session_factory
from judgemetrics.logging import configure_logging, get_logger
from judgemetrics.security.crypto import require_contact_key

__all__ = ["API_PREFIX", "REQUEST_ID_HEADER", "app", "create_app"]  # noqa: F822 - `app` is lazy

API_DESCRIPTION = (
    "Versioned access to JudgeMetrics' canonical data and published metrics: judges, "
    "courts, jurisdictions, cases with their timelines, source coverage, search, the "
    "versioned metric registry, every current metric observation of a judge or court with "
    "its numerator, denominator, date range, coverage, sample size, interval, suppression, "
    "and methodology link, a compare table per metric and cohort, and the provenance chain "
    "from any observation back to the raw source artifacts — each with the provenance of "
    "the raw source artifacts behind it and a `synthetic` flag on every row derived from "
    "the in-repo demo dataset. The one write path, `POST /corrections`, accepts a data "
    "correction request whose contact is encrypted at rest. Lists are paginated "
    "(`limit` ≤ 100), filters are validated strictly (unknown parameters are 422), "
    "persons appear only as pseudonymous public keys and never in a metrics response, "
    "and every error is an `ErrorBody`. See docs/API.md."
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
    if settings.env != "test":
        # Fail fast: a correction that cannot be encrypted must never be stored.
        require_contact_key(settings)
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
    app.state.corrections_limiter = (
        TokenBucketLimiter(
            per_hour=settings.corrections_rate_limit_per_hour,
            burst=settings.corrections_rate_limit_burst,
        )
        if settings.effective_corrections_rate_limit_enabled
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
    app.include_router(metrics.router, prefix=API_PREFIX)
    app.include_router(corrections.router, prefix=API_PREFIX)
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


_process_app: FastAPI | None = None


def _module_app() -> FastAPI:
    """The process-wide app (``judgemetrics.main:app``), built once on first access."""
    global _process_app  # noqa: PLW0603 - the lazily built module attribute
    if _process_app is None:
        _process_app = create_app()
    return _process_app


def __getattr__(name: str) -> Any:
    if name == "app":
        return _module_app()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
