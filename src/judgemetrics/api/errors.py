# src/judgemetrics/api/errors.py
"""The error envelope and the handlers that guarantee it.

Every non-2xx response is an ``ErrorBody`` (``code``, ``message``,
``request_id``). Validation failures (FastAPI's ``RequestValidationError``)
become 422 with the offending parameters named; ``ApiError`` carries its
own code (``not_found``, ``rate_limited``); a database error is 503 with
its class name logged and nothing of its text returned (the text can embed
SQL); anything else is 500 ``internal_error``. No handler ever returns a
stack trace, a query, or a configuration value.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException, RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from judgemetrics.api import REQUEST_ID_HEADER
from judgemetrics.logging import get_logger
from judgemetrics.schemas.common import ErrorBody

log = get_logger(__name__)

# Codes for HTTP exceptions raised without an explicit code (Starlette's own
# 404 for an unknown path, 405, ...).
_CODES_BY_STATUS = {404: "not_found", 422: "validation_error", 429: "rate_limited"}


class ApiError(HTTPException):
    """An HTTP error with a stable machine-readable ``code``."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(status_code=status_code, detail=message, headers=dict(headers or {}))
        self.code = code


def request_id_of(request: Request) -> str:
    """The id the middleware bound, or ``unknown`` if the request never reached it."""
    return str(getattr(request.state, "request_id", "unknown"))


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body = ErrorBody(code=code, message=message, request_id=request_id_of(request))
    response = JSONResponse(status_code=status_code, content=body.model_dump())
    for name, value in (headers or {}).items():
        response.headers[name] = value
    # The request-id middleware does not see a response that an exception
    # short-circuited, so the header is set here as well.
    response.headers[REQUEST_ID_HEADER] = body.request_id
    return response


# Descriptions for the documented error responses (`responses=` on a route).
_DESCRIPTIONS = {
    404: "The resource does not exist.",
    422: "A parameter is invalid, or a query parameter is not one the route declares.",
    429: "Rate limit exceeded; `Retry-After` gives the wait in seconds.",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """The ``responses`` entries that document ``ErrorBody`` for ``status_codes``."""
    return {code: {"model": ErrorBody, "description": _DESCRIPTIONS[code]} for code in status_codes}


def _describe(error: Mapping[str, Any]) -> str:
    location = ".".join(str(part) for part in error.get("loc") or () if part != "query")
    return f"{location}: {error.get('msg', 'invalid')}" if location else str(error.get("msg"))


async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    message = "; ".join(_describe(error) for error in exc.errors())
    return error_response(
        request, status_code=422, code="validation_error", message=message or "invalid request"
    )


async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    code = exc.code if isinstance(exc, ApiError) else _CODES_BY_STATUS.get(exc.status_code)
    return error_response(
        request,
        status_code=exc.status_code,
        code=code or "http_error",
        message=str(exc.detail),
        headers=exc.headers,
    )


async def _database_error(request: Request, exc: SQLAlchemyError) -> JSONResponse:
    # The exception text may embed the statement or the DSN; log its class only.
    log.error("http.database_error", error_type=type(exc).__name__)
    return error_response(
        request, status_code=503, code="database_unavailable", message="database unavailable"
    )


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    log.exception("http.unhandled_error", error_type=type(exc).__name__)
    return error_response(
        request, status_code=500, code="internal_error", message="internal server error"
    )


def install_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation_error)  # type: ignore[arg-type]
    app.add_exception_handler(StarletteHTTPException, _http_error)  # type: ignore[arg-type]
    app.add_exception_handler(SQLAlchemyError, _database_error)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, _unhandled_error)
