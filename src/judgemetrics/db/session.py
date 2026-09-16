# src/judgemetrics/db/session.py
"""Engine and session factory from settings.

The FastAPI dependency that opens a session per request lives in
``judgemetrics.api.deps`` and uses the factory ``create_app`` binds to the app.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from judgemetrics.config import get_settings

# Seconds psycopg waits for a TCP/TLS connection before giving up; the
# readiness probe must fail fast rather than hang on an unreachable host.
CONNECT_TIMEOUT_SECONDS = 5


def make_engine(url: str, *, connect_timeout: int = CONNECT_TIMEOUT_SECONDS) -> Engine:
    """An engine with ``pool_pre_ping`` so stale connections are replaced."""
    return create_engine(
        url,
        pool_pre_ping=True,
        future=True,
        connect_args={"connect_timeout": connect_timeout},
    )


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """The API's engine (read-only role); cached for the process."""
    return make_engine(get_settings().database_url)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())


# Conventional name for the process-wide factory: `SessionLocal()` opens a session.
def SessionLocal() -> Session:  # noqa: N802 - SQLAlchemy convention
    return get_session_factory()()


def reset_engine_cache() -> None:
    """Dispose and forget the cached engine (tests and settings reloads)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
