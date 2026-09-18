# tests/unit/test_scratch_database.py
"""The scratch test database wiring in ``tests/conftest.py`` (Phase 2 Step 5).

``scratch_settings`` points every database URL at the scratch database:
the admin URL is the scratch URL itself (its owner runs the migrations),
the app and ingest URLs keep their configured roles and passwords and are
retargeted at the scratch host, port, and database, and an unset ingest
URL falls back to the owner. Without a scratch URL the settings come
back unchanged and the session fixture warns once, naming the variable.
No database is touched.
"""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from judgemetrics.config import Settings
from tests.conftest import (
    FALLBACK_WARNING,
    TEST_DATABASE_VARIABLE,
    ScratchDatabaseUnsetWarning,
    scratch_settings,
)

pytestmark = pytest.mark.unit

APP = "postgresql+psycopg://judgemetrics_app:app-pw@localhost:5440/judgemetrics"  # pragma: allowlist secret
ADMIN = "postgresql+psycopg://judgemetrics_admin:admin-pw@localhost:5440/judgemetrics"  # pragma: allowlist secret
INGEST = "postgresql+psycopg://judgemetrics_ingest:ingest-pw@localhost:5440/judgemetrics"  # pragma: allowlist secret
SCRATCH = "postgresql+psycopg://judgemetrics:owner-pw@db.internal:5441/judgemetrics_test"  # pragma: allowlist secret


def test_every_role_url_is_retargeted_at_the_scratch_database() -> None:
    settings = Settings(
        env="test",
        database_url=APP,
        admin_database_url=ADMIN,
        ingest_database_url=INGEST,
        test_database_url=SCRATCH,
    )
    scratch = scratch_settings(settings)
    assert scratch.effective_admin_database_url == SCRATCH
    app = make_url(scratch.database_url)
    assert (app.username, app.password) == ("judgemetrics_app", "app-pw")
    assert (app.host, app.port, app.database) == ("db.internal", 5441, "judgemetrics_test")
    ingest = make_url(scratch.effective_ingest_database_url)
    assert (ingest.username, ingest.password) == ("judgemetrics_ingest", "ingest-pw")
    assert (ingest.host, ingest.port, ingest.database) == ("db.internal", 5441, "judgemetrics_test")
    # The original settings are untouched and the rest is carried over.
    assert settings.database_url == APP and settings.admin_database_url == ADMIN
    assert scratch.env == "test" and scratch.test_database_url == SCRATCH


def test_an_unset_ingest_url_falls_back_to_the_scratch_owner() -> None:
    settings = Settings(env="test", database_url=APP, test_database_url=SCRATCH)
    scratch = scratch_settings(settings)
    assert scratch.effective_ingest_database_url == SCRATCH
    assert scratch.effective_admin_database_url == SCRATCH
    assert make_url(scratch.database_url).database == "judgemetrics_test"


def test_without_a_scratch_url_the_settings_are_returned_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # CI exports the variable for the suite; this test needs it absent.
    monkeypatch.delenv(TEST_DATABASE_VARIABLE, raising=False)
    settings = Settings(env="test", database_url=APP, admin_database_url=ADMIN)
    assert settings.test_database_url is None
    assert scratch_settings(settings) is settings


def test_the_fallback_warning_names_the_variable() -> None:
    assert TEST_DATABASE_VARIABLE == "JUDGEMETRICS_TEST_DATABASE_URL"
    assert TEST_DATABASE_VARIABLE in FALLBACK_WARNING
    assert "judgemetrics_test" in FALLBACK_WARNING
    assert issubclass(ScratchDatabaseUnsetWarning, UserWarning)
