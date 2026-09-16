# src/judgemetrics/main.py
"""FastAPI application factory.

``create_app()`` wires settings, logging, the request-id and access-log
middleware, and the versioned routers under ``/api/v1``. The module-level
``app`` is what uvicorn serves (``judgemetrics serve``).
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Awaitable, Callable

import structlog
from fastapi import FastAPI, Request, Response

from judgemetrics import __version__
from judgemetrics.api.routes import health
from judgemetrics.config import Settings, get_settings
from judgemetrics.db.session import make_engine
from judgemetrics.logging import configure_logging, get_logger

API_PREFIX = "/api/v1"
REQUEST_ID_HEADER = "X-Request-ID"
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
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    app.state.settings = settings
    # Creating an engine does not connect; the readiness probe is the first user.
    app.state.engine = make_engine(settings.database_url)

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
    return app


app = create_app()
