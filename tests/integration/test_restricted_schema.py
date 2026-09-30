# tests/integration/test_restricted_schema.py
"""The ``restricted`` schema is unreachable for the app role and usable by the ingest role.

Revision 0008 grants ``USAGE`` on ``restricted`` to the ingest and admin
roles only. In the scratch test database (the one every database test
migrates) and in the configured database (the developer's ``.env``
database, once it is at revision 0008): as ``judgemetrics_app``, naming
the schema's table raises ``InsufficientPrivilege`` and
``has_schema_privilege`` answers false; as ``judgemetrics_ingest``, the
table can be read, and an insert, update, and delete that touch no row
pass the privilege check — PostgreSQL checks the privilege before it
evaluates the ``WHERE false``, so no fixture rows are needed and nothing
is written. The scratch database is also the one ``03-test-database.sql``
re-grants ``SELECT ON ALL TABLES`` in on every ``uv run poe up``; its
re-revoke keeps the schema closed, which this test observes.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError

from judgemetrics.config import Settings
from judgemetrics.db.session import make_engine

pytestmark = pytest.mark.integration

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
WRITES = (
    "INSERT INTO restricted.party_attribute "
    "(case_party_id, attribute, value, source_record_id) "
    "SELECT id, 'age_band', 'unknown', source_record_id FROM case_party WHERE false",
    "UPDATE restricted.party_attribute SET value = value WHERE false",
    "DELETE FROM restricted.party_attribute WHERE false",
)


def _configured() -> Settings:
    settings = Settings()
    if "database_url" not in settings.model_fields_set:
        pytest.skip("no database URL is configured")
    return settings


@pytest.fixture(params=["scratch", "configured"])
def role_urls(
    request: pytest.FixtureRequest, test_settings: Settings, migrated_database: Engine
) -> Iterator[tuple[str, str]]:
    """``(app URL, ingest URL)`` of the scratch or the configured database."""
    settings = test_settings if request.param == "scratch" else _configured()
    ingest = settings.ingest_database_url
    if ingest is None:
        pytest.skip("no ingest-role URL is configured (CI runs every role as the owner)")
    yield settings.database_url, ingest


def _current_user(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT current_user")).scalar())


def _schema_exists(engine: Engine) -> bool:
    with engine.connect() as connection:
        return bool(
            connection.execute(
                text("SELECT 1 FROM pg_namespace WHERE nspname = 'restricted'")
            ).scalar()
        )


def test_the_app_role_cannot_use_the_restricted_schema(role_urls: tuple[str, str]) -> None:
    app_url, _ = role_urls
    engine = make_engine(app_url)
    try:
        if _current_user(engine) != APP_ROLE:
            pytest.skip("the app URL does not connect as judgemetrics_app")
        if not _schema_exists(engine):
            pytest.skip("this database is not at revision 0008 yet (`uv run poe migrate`)")
        with engine.connect() as connection:
            assert (
                connection.execute(
                    text("SELECT has_schema_privilege('restricted', 'USAGE')")
                ).scalar()
                is False
            )
            with pytest.raises(ProgrammingError) as caught:
                connection.execute(text("SELECT 1 FROM restricted.party_attribute LIMIT 1"))
            assert isinstance(caught.value.orig, InsufficientPrivilege)
            assert "permission denied for schema restricted" in str(caught.value.orig)
    finally:
        engine.dispose()


def test_the_ingest_role_reads_and_writes_the_restricted_table(
    role_urls: tuple[str, str],
) -> None:
    _, ingest_url = role_urls
    engine = make_engine(ingest_url)
    try:
        if _current_user(engine) != INGEST_ROLE:
            pytest.skip("the ingest URL does not connect as judgemetrics_ingest")
        if not _schema_exists(engine):
            pytest.skip("this database is not at revision 0008 yet (`uv run poe migrate`)")
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                assert (
                    connection.execute(
                        text("SELECT count(*) FROM restricted.party_attribute")
                    ).scalar()
                    is not None
                )
                for statement in WRITES:
                    connection.execute(text(statement))
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
