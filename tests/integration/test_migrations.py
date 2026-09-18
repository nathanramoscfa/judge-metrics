# tests/integration/test_migrations.py
"""The migrations (0001–0003): round trip, model constraints, and role grants.

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
    # Revision 0003: case-level natural keys, person provenance, identifier indexes.
    for table in (
        "case_party",
        "judge_assignment",
        "charge",
        "court_event",
        "decision",
        "sentence",
    ):
        assert f"uq_{table}_case_source_row" in indexes[table], table
    assert "uq_justice_event_natural" in indexes["justice_event"]
    assert "ix_person_source_record_id" in indexes["person"]
    assert "uq_person_identifier_stable" in indexes["person_identifier"]
    assert "uq_person_identifier_person_type_hash" in indexes["person_identifier"]
    assert "ix_court_case_related_case_number_normalized" in indexes["court_case"]
    assert "uq_judge_external_ids_synthetic_judge_code" in indexes["judge"]
    uniques = snapshot.uniques
    assert "court_case_number" in uniques["court_case"]
    assert "uq_person_public_person_key" in uniques["person"]
    assert current_revision(migrated_database) == head_revision() == "0003"


def test_revision_0003_columns_and_partial_index_predicate(migrated_database: Engine) -> None:
    with migrated_database.connect() as connection:
        columns = {
            (table, column): (data_type, nullable == "YES")
            for table, column, data_type, nullable in connection.execute(
                text(
                    "SELECT table_name, column_name, data_type, is_nullable "
                    "FROM information_schema.columns WHERE table_schema = 'public'"
                )
            )
        }
        for table in (
            "case_party",
            "judge_assignment",
            "charge",
            "court_event",
            "decision",
            "sentence",
        ):
            assert columns[(table, "source_row_id")] == ("text", False), table
        assert columns[("person", "source_record_id")] == ("uuid", True)
        assert columns[("court_case", "related_case_number_normalized")] == ("text", True)
        assert columns[("charge", "disposition_actor")] == ("USER-DEFINED", True)
        assert ("person", "full_name") not in columns
        assert ("person", "date_of_birth") not in columns
        assert not any(
            table == "person" and column in {"name", "full_name", "date_of_birth", "dob"}
            for table, column in columns
        )
        stable = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_person_identifier_stable'")
        ).scalar()
        assert stable is not None
        assert "UNIQUE" in stable and "source_participant_id" in stable and "WHERE" in stable
        natural = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_justice_event_natural'")
        ).scalar()
        assert natural is not None and "NULLS NOT DISTINCT" in natural


def test_upgrade_downgrade_upgrade_round_trip_is_identical(migrated_database: Engine) -> None:
    url = _url(migrated_database)
    before = _snapshot(migrated_database)
    # Through 0003 first: its downgrade must leave exactly the 0002 shape.
    downgrade(url, "0002")
    assert current_revision(migrated_database) == "0002"
    intermediate = _snapshot(migrated_database)
    assert "uq_charge_case_source_row" not in intermediate.indexes["charge"]
    assert "uq_person_identifier_stable" not in intermediate.indexes["person_identifier"]
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


def test_ingest_role_has_dml_on_every_case_level_table(migrated_database: Engine) -> None:
    """The grants revision 0003 re-asserts, read from the catalog (any connection role)."""
    with migrated_database.connect() as connection:
        if not connection.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'judgemetrics_ingest'")
        ).scalar():
            pytest.skip("the judgemetrics_ingest role does not exist on this database")
        rows = connection.execute(
            text(
                "SELECT table_name, privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'judgemetrics_ingest' AND table_schema = 'public'"
            )
        ).all()
        granted: dict[str, set[str]] = {}
        for table, privilege in rows:
            granted.setdefault(table, set()).add(privilege)
        for table in (
            "person",
            "person_identifier",
            "court_case",
            "case_party",
            "judge_assignment",
            "charge",
            "court_event",
            "decision",
            "pretrial_release",
            "sentence",
            "justice_event",
        ):
            assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= granted.get(table, set()), table
        app_rows = connection.execute(
            text(
                "SELECT table_name FROM information_schema.role_table_grants "
                "WHERE grantee = 'judgemetrics_app' AND table_schema = 'public'"
            )
        ).all()
        app_tables = {row[0] for row in app_rows}
        if app_tables:
            assert "person_identifier" not in app_tables
            assert "correction_request" not in app_tables
