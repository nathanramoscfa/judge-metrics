# tests/conftest.py
"""Shared fixtures: settings, engines, and a per-test transactional session.

Integration tests need a PostgreSQL reachable through
``JUDGEMETRICS_DATABASE_URL`` (the API's read-only role) and, for DDL and
writes, ``JUDGEMETRICS_ADMIN_DATABASE_URL`` (falls back to the former: CI
runs everything as the service container's owner). Locally the values come
from ``.env`` (``JUDGEMETRICS_ENV=local``); in CI from the job environment.
When no database URL is configured the integration tests are skipped with
a clear reason.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from judgemetrics.config import Settings, get_settings
from judgemetrics.db.session import make_engine

SKIP_REASON = (
    "JUDGEMETRICS_DATABASE_URL is unset; start the Compose services (`uv run poe up`) "
    "with a `.env`, or export the variable"
)
# The fixed identifier pepper every test hashes with, so expected digests
# are reproducible; never a real deployment value.
TEST_IDENTIFIER_PEPPER = "test-pepper-not-a-secret"  # pragma: allowlist secret


@pytest.fixture(autouse=True, scope="session")
def _test_identifier_pepper() -> Iterator[None]:
    """Every settings object in the suite sees the fixed test pepper."""
    previous = os.environ.get("JUDGEMETRICS_IDENTIFIER_PEPPER")
    os.environ["JUDGEMETRICS_IDENTIFIER_PEPPER"] = TEST_IDENTIFIER_PEPPER
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("JUDGEMETRICS_IDENTIFIER_PEPPER", None)
        else:
            os.environ["JUDGEMETRICS_IDENTIFIER_PEPPER"] = previous


@pytest.fixture(autouse=True)
def _fresh_settings_cache() -> Iterator[None]:
    """No test observes settings cached by another test."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    """Settings from the process environment (and `.env` when local)."""
    return Settings()


def _configured_settings() -> Settings:
    settings = Settings()
    if "database_url" not in settings.model_fields_set:
        pytest.skip(SKIP_REASON)
    return settings


@pytest.fixture(scope="session")
def admin_engine() -> Iterator[Engine]:
    """Engine for the DDL/DML role used by migrations and write fixtures."""
    engine = make_engine(_configured_settings().effective_admin_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine() -> Iterator[Engine]:
    """Engine for the API's read-only role."""
    engine = make_engine(_configured_settings().database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_database(admin_engine: Engine) -> Engine:
    """The schema at head for the whole session (idempotent)."""
    from judgemetrics.db.migrations import upgrade

    upgrade(admin_engine.url.render_as_string(hide_password=False), "head")
    return admin_engine


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test."""
    connection = migrated_database.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
