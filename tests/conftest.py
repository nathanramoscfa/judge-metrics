# tests/conftest.py
"""Shared fixtures: settings, the scratch test database, engines, and a
per-test transactional session; the Hypothesis profiles.

Integration tests need a PostgreSQL reachable through
``JUDGEMETRICS_DATABASE_URL`` (the API's read-only role) and, for DDL and
writes, ``JUDGEMETRICS_ADMIN_DATABASE_URL`` (falls back to the former: CI
runs everything as the service container's owner). Locally the values come
from ``.env`` (``JUDGEMETRICS_ENV=local``); in CI from the job environment.
When no database URL is configured the integration tests are skipped with
a clear reason.

The scratch database (Phase 2 Step 5). Every database test — the
migration round trip, the fixture-ingesting integration tests, the
property tests, the golden suite — runs through ``test_settings``: when
``JUDGEMETRICS_TEST_DATABASE_URL`` is set, its admin and ingest URLs point
at that database (the owner's URL as given; the ingest role's configured
URL retargeted at the same host, port, and database) and its app URL is
the configured app-role URL retargeted the same way, so the role split is
still exercised. ``migrated_database`` then upgrades the scratch database
to head at session start and the suite never touches a live ingest. Unset,
the fixture returns the configured settings — today's behaviour — and
warns once, naming the variable.

Hypothesis profiles: ``ci`` (50 examples, no deadline) and ``dev`` (20
examples, no deadline: generating a dataset takes longer than the default
200 ms deadline), selected by ``HYPOTHESIS_PROFILE`` (CI sets ``ci``).

Pipeline step 13 (Phase 3 Step 2) is off for the whole suite:
``JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST=false`` is set in the process
environment before any ``Settings`` is built, so the fixture ingests do
not export snapshots or publish observations; the step-13 tests enable it
per test with ``Settings(metrics_recompute_on_ingest=True)`` and point
``snapshot_dir`` at a temporary directory.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Iterator

import pytest
from hypothesis import settings as hypothesis_settings
from sqlalchemy import Engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from judgemetrics.config import Settings, get_settings
from judgemetrics.db.session import make_engine

SKIP_REASON = (
    "JUDGEMETRICS_DATABASE_URL is unset; start the Compose services (`uv run poe up`) "
    "with a `.env`, or export the variable"
)
TEST_DATABASE_VARIABLE = "JUDGEMETRICS_TEST_DATABASE_URL"
FALLBACK_WARNING = (
    f"{TEST_DATABASE_VARIABLE} is unset: the database tests run against the configured "
    "database, so the migration round trip and the fixture ingests empty a local live "
    "ingest; set it to the scratch database (`uv run poe up` creates judgemetrics_test, "
    "see .env.example)"
)
# The fixed identifier pepper every test hashes with, so expected digests
# are reproducible; never a real deployment value.
TEST_IDENTIFIER_PEPPER = "test-pepper-not-a-secret"  # pragma: allowlist secret

hypothesis_settings.register_profile("ci", max_examples=50, deadline=None)
hypothesis_settings.register_profile("dev", max_examples=20, deadline=None)
hypothesis_settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "dev"))


class ScratchDatabaseUnsetWarning(UserWarning):
    """The suite fell back to the configured database (see the module docstring)."""


RECOMPUTE_VARIABLE = "JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST"


@pytest.fixture(autouse=True, scope="session")
def _test_identifier_pepper() -> Iterator[None]:
    """Every settings object in the suite sees the fixed test pepper and step 13 off."""
    previous = {
        name: os.environ.get(name)
        for name in ("JUDGEMETRICS_IDENTIFIER_PEPPER", RECOMPUTE_VARIABLE)
    }
    os.environ["JUDGEMETRICS_IDENTIFIER_PEPPER"] = TEST_IDENTIFIER_PEPPER
    os.environ[RECOMPUTE_VARIABLE] = "false"
    try:
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


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


def _retarget(url: str, scratch: str) -> str:
    """``url`` with the host, port, and database of ``scratch`` (its role and password kept)."""
    target = make_url(scratch)
    return (
        make_url(url)
        .set(host=target.host, port=target.port, database=target.database)
        .render_as_string(hide_password=False)
    )


def scratch_settings(settings: Settings) -> Settings:
    """``settings`` with every database URL pointed at the scratch test database.

    The admin URL is the scratch URL itself (the owner runs the migrations);
    the app and ingest URLs keep their configured roles and credentials and
    are retargeted at the scratch database (an ingest URL that is not
    configured falls back to the owner, as ``effective_ingest_database_url``
    does today). Returns ``settings`` unchanged when no scratch URL is set.
    """
    scratch = settings.test_database_url
    if scratch is None:
        return settings
    ingest = (
        _retarget(settings.ingest_database_url, scratch)
        if settings.ingest_database_url is not None
        else scratch
    )
    return settings.model_copy(
        update={
            "database_url": _retarget(settings.database_url, scratch),
            "admin_database_url": scratch,
            "ingest_database_url": ingest,
        }
    )


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """The settings every database test uses (see the module docstring)."""
    configured = _configured_settings()
    if configured.test_database_url is None:
        warnings.warn(FALLBACK_WARNING, ScratchDatabaseUnsetWarning, stacklevel=1)
        return configured
    return scratch_settings(configured)


@pytest.fixture(scope="session")
def admin_engine(test_settings: Settings) -> Iterator[Engine]:
    """Engine for the DDL/DML role used by migrations and write fixtures."""
    engine = make_engine(test_settings.effective_admin_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def app_engine(test_settings: Settings) -> Iterator[Engine]:
    """Engine for the API's read-only role."""
    engine = make_engine(test_settings.database_url)
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
