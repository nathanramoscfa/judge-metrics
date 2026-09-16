# tests/integration/test_migrations.py
"""The baseline migration: round trip, model constraints, and role grants.

Runs against the Compose / CI PostgreSQL through the admin URL; skipped
with a clear reason when no database URL is configured (tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from judgemetrics.db.migrations import current_revision, downgrade, head_revision, upgrade
from judgemetrics.db.models import (
    CANONICAL_TABLES,
    PG_ENUM_NAMES,
    RESTRICTED_TABLES,
    ActorType,
    Decision,
    IngestRun,
    IngestRunStatus,
    Source,
    SourceRecord,
)

pytestmark = pytest.mark.integration

EXPECTED_ENUMS = set(PG_ENUM_NAMES.values())


class Snapshot(NamedTuple):
    """Table, index, unique-constraint, enum, and extension names."""

    tables: list[str]
    indexes: dict[str, list[str]]
    uniques: dict[str, list[str]]
    enums: list[str]
    extensions: list[str]


def _snapshot(engine: Engine) -> Snapshot:
    """The shape the round trip must preserve."""
    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = sorted(inspector.get_table_names())
        indexes = {
            table: sorted(index["name"] or "" for index in inspector.get_indexes(table))
            for table in tables
        }
        uniques = {
            table: sorted(uc["name"] or "" for uc in inspector.get_unique_constraints(table))
            for table in tables
        }
        enums = sorted(
            row[0]
            for row in connection.execute(
                text("SELECT typname FROM pg_type WHERE typtype = 'e' ORDER BY typname")
            )
        )
        extensions = sorted(
            row[0] for row in connection.execute(text("SELECT extname FROM pg_extension"))
        )
    return Snapshot(tables, indexes, uniques, enums, extensions)


def _url(engine: Engine) -> str:
    return engine.url.render_as_string(hide_password=False)


def test_upgrade_creates_every_canonical_table_enum_and_index(migrated_database: Engine) -> None:
    snapshot = _snapshot(migrated_database)
    assert set(CANONICAL_TABLES) <= set(snapshot.tables)
    assert len(CANONICAL_TABLES) == 23
    assert EXPECTED_ENUMS <= set(snapshot.enums)
    assert "pg_trgm" in snapshot.extensions
    indexes = snapshot.indexes
    for table, column in (
        ("court", "jurisdiction_id"),
        ("judge_service", "judge_id"),
        ("judge_service", "court_id"),
        ("judge_service", "source_record_id"),
        ("court_case", "court_id"),
        ("court_case", "source_record_id"),
        ("case_party", "case_id"),
        ("case_party", "person_id"),
        ("judge_assignment", "judge_id"),
        ("charge", "person_id"),
        ("court_event", "event_at"),
        ("decision", "decision_at"),
        ("decision", "judge_id"),
        ("justice_event", "event_at"),
        ("justice_event", "person_id"),
        ("person_identifier", "person_id"),
        ("data_quality_issue", "source_record_id"),
    ):
        assert f"ix_{table}_{column}" in indexes[table], (table, column)
    assert "ix_judge_normalized_name_trgm" in indexes["judge"]
    assert "ix_judge_external_ids" in indexes["judge"]
    assert "uq_judge_external_ids_fjc_nid" in indexes["judge"]
    # Revision 0002: provenance references, natural keys, court.state_code.
    for table in ("jurisdiction", "court", "judge"):
        assert f"ix_{table}_source_record_id" in indexes[table], table
    assert "uq_jurisdiction_name_type" in indexes["jurisdiction"]
    assert "uq_court_canonical_name_court_type" in indexes["court"]
    assert "ix_court_state_code" in indexes["court"]
    assert "uq_judge_service_natural_key" in indexes["judge_service"]
    assert "uq_source_record_source_external_sha256" in indexes["source_record"]
    assert "ix_court_canonical_name_trgm" in indexes["court"]
    assert "ix_court_external_ids" in indexes["court"]
    assert "ix_metric_observation_subject_period" in indexes["metric_observation"]
    uniques = snapshot.uniques
    assert "court_case_number" in uniques["court_case"]
    assert "uq_person_public_person_key" in uniques["person"]
    assert current_revision(migrated_database) == head_revision() == "0002"


def test_upgrade_downgrade_upgrade_round_trip_is_identical(migrated_database: Engine) -> None:
    url = _url(migrated_database)
    before = _snapshot(migrated_database)
    downgrade(url, "base")
    stripped = _snapshot(migrated_database)
    assert stripped.tables == ["alembic_version"]
    assert stripped.enums == []
    assert current_revision(migrated_database) is None
    upgrade(url, "head")
    after = _snapshot(migrated_database)
    assert after == before
    assert current_revision(migrated_database) == head_revision()


def test_decision_requires_source_record(db_session: Session) -> None:
    decision = Decision(
        case_id=uuid.uuid4(),
        person_id=uuid.uuid4(),
        decision_type="pretrial_release",
        decision_at=datetime.now(tz=UTC),
        actor_type=ActorType.JUDGE,
        judicial_discretion_classification="discretionary",
        source_record_id=None,
    )
    db_session.add(decision)
    with pytest.raises(IntegrityError, match="source_record_id"):
        db_session.flush()


def test_source_record_chain_round_trips(db_session: Session) -> None:
    source = Source(
        name="test-source",
        owner="tests",
        source_type="fixture",
        access_method="in-memory",
    )
    db_session.add(source)
    db_session.flush()
    run = IngestRun(
        source_id=source.id,
        started_at=datetime.now(tz=UTC),
        status=IngestRunStatus.RUNNING,
        code_version="0" * 40,
        parser_version="1",
    )
    db_session.add(run)
    db_session.flush()
    record = SourceRecord(
        source_id=source.id,
        retrieved_at=datetime.now(tz=UTC),
        raw_object_path="raw/test-source/fixture.csv",
        raw_sha256="0" * 64,
        parser_version="1",
        ingest_run_id=run.id,
    )
    db_session.add(record)
    db_session.flush()
    assert record.id is not None
    assert record.created_at is not None
    assert db_session.get(SourceRecord, record.id) is record


@pytest.mark.parametrize("table", sorted(RESTRICTED_TABLES))
def test_app_role_cannot_read_restricted_tables(
    migrated_database: Engine, app_engine: Engine, table: str
) -> None:
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("JUDGEMETRICS_DATABASE_URL does not connect as judgemetrics_app")
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 - fixed name


def test_app_role_can_read_public_tables(migrated_database: Engine, app_engine: Engine) -> None:
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("JUDGEMETRICS_DATABASE_URL does not connect as judgemetrics_app")
        for table in ("judge", "court", "person", "metric_observation", "alembic_version"):
            connection.execute(text(f"SELECT count(*) FROM {table}"))  # noqa: S608 - fixed name
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(
                text("INSERT INTO person (public_person_key, resolution_status) VALUES ('x', 'y')")
            )
