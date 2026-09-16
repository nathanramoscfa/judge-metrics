# src/judgemetrics/logging.py
"""Structured logging (structlog) with sensitive-value scrubbing.

Every log line carries an ISO-8601 UTC timestamp, the level, the logger
name, the event, and whatever context is bound for the request (the request
id, see ``judgemetrics.main``). Rendering is JSON when
``JUDGEMETRICS_LOG_FORMAT=json`` (one object per line, for production and
CI) and a coloured console otherwise. Standard-library loggers (uvicorn,
SQLAlchemy) are routed through the same processor chain so the scrubber
sees them too.

The scrubber is the logging half of ROADMAP.md §5 "Logging / audit: no
person identifiers or secrets in logs". Values whose key matches the
denylist below are replaced with ``[redacted]`` recursively through dicts,
lists, and tuples; the keys themselves are kept so a log line still shows
*what* was omitted.
"""

from __future__ import annotations

import logging as stdlib_logging
import sys
from collections.abc import Mapping, MutableMapping
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from judgemetrics.config import Settings

REDACTED = "[redacted]"

# Documented denylist. A key matches when its normalized form (casefold,
# `-` and `.` folded to `_`) contains any entry as a substring, so
# `db_password`, `X-API-Key`, `aws_secret_access_key`, and
# `Authorization` are all caught. Over-redaction is the safe failure mode.
SENSITIVE_KEYS: frozenset[str] = frozenset(
    {
        # credentials and session material
        "password",
        "passwd",
        "secret",
        "token",
        "authorization",
        "api_key",
        "access_key",
        "cookie",
        # person-level identifiers (ROADMAP.md §5 data classification)
        "person_id",
        "case_participant_id",
        "identifier_value",
        "encrypted_value",
        "requester_contact",
    }
)


def _normalize_key(key: object) -> str:
    return str(key).casefold().replace("-", "_").replace(".", "_")


def is_sensitive_key(key: object) -> bool:
    normalized = _normalize_key(key)
    return any(entry in normalized for entry in SENSITIVE_KEYS)


def scrub_value(value: Any) -> Any:
    """Return ``value`` with every sensitive mapping entry redacted, recursively."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if is_sensitive_key(key) else scrub_value(inner)
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(scrub_value(item) for item in value)
    return value


def scrub_sensitive(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> MutableMapping[str, Any]:
    """structlog processor: redact denylisted keys anywhere in the event dict."""
    for key in list(event_dict.keys()):
        if is_sensitive_key(key):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = scrub_value(event_dict[key])
    return event_dict


def _shared_processors() -> list[Processor]:
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
        scrub_sensitive,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]


class _Handler(stdlib_logging.StreamHandler):  # type: ignore[type-arg]
    """Marker subclass so reconfiguration replaces only this handler."""


def _renderer(settings: Settings) -> Processor:
    if settings.log_format == "json":
        return structlog.processors.JSONRenderer(sort_keys=True)
    return structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the standard library from ``settings``.

    Idempotent: calling it again reconfigures with the new settings.
    """
    shared = _shared_processors()
    renderer = _renderer(settings)
    level = stdlib_logging.getLevelNamesMapping().get(
        settings.log_level.upper(), stdlib_logging.INFO
    )

    structlog.configure(
        processors=[
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # `extra={...}` on stdlib records enters the event dict before scrubbing.
        foreign_pre_chain=[structlog.stdlib.ExtraAdder(), *shared],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )
    handler = _Handler(sys.stderr)
    handler.setFormatter(formatter)
    root = stdlib_logging.getLogger()
    # Replace only our own previous handler; leave pytest's and others' alone.
    for existing in list(root.handlers):
        if isinstance(existing, _Handler):
            root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)
    # uvicorn installs its own handlers and formats; route them through ours.
    for name in ("uvicorn", "uvicorn.error"):
        server_logger = stdlib_logging.getLogger(name)
        server_logger.handlers.clear()
        server_logger.propagate = True
    # The request-id-bound access-log middleware replaces uvicorn's access log.
    access = stdlib_logging.getLogger("uvicorn.access")
    access.handlers.clear()
    access.propagate = False
    # Alembic announces its context at INFO on every readiness probe.
    stdlib_logging.getLogger("alembic.runtime.migration").setLevel(stdlib_logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """A named structlog logger bound to the configured processor chain."""
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name)
    return logger
