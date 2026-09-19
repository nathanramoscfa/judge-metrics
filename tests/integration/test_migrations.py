# tests/integration/test_migrations.py
"""The migrations (0001–0006): round trip, model constraints, role grants, the audit trigger.

Runs against the Compose / CI PostgreSQL through the admin URL; skipped
with a clear reason when no database URL is configured (tests/conftest.py).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import NamedTuple

import pytest
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError
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
    # The brief's twenty-three, audit_log (0004), metric_snapshot and
    # metric_observation_member (0005).
    assert len(CANONICAL_TABLES) == 26
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
    # Revision 0004: candidate bookkeeping, merged persons, the audit log.
    assert "uq_er_candidate_pair_version" in indexes["entity_resolution_candidate"]
    assert "ix_entity_resolution_candidate_ingest_run_id" in indexes["entity_resolution_candidate"]
    assert "ix_person_merged_into_person_id" in indexes["person"]
    assert "ix_audit_log_entity" in indexes["audit_log"]
    assert "ix_audit_log_occurred_at" in indexes["audit_log"]
    # Revision 0005: the observation key, the current-observation index, members.
    assert "uq_metric_observation_key" in indexes["metric_observation"]
    assert "ix_metric_observation_current" in indexes["metric_observation"]
    assert "ix_metric_observation_snapshot_id" in indexes["metric_observation"]
    assert "ix_metric_observation_source_id" in indexes["metric_observation"]
    assert "ix_metric_observation_member_observation_id" in indexes["metric_observation_member"]
    assert "ix_metric_observation_member_member" in indexes["metric_observation_member"]
    uniques = snapshot.uniques
    assert "court_case_number" in uniques["court_case"]
    assert "uq_person_public_person_key" in uniques["person"]
    assert "uq_metric_snapshot_content_hash" in uniques["metric_snapshot"]
    assert "ix_ingest_run_metrics_snapshot_id" in indexes["ingest_run"]
    assert current_revision(migrated_database) == head_revision() == "0006"


def test_revision_0005_columns_key_and_member_check(migrated_database: Engine) -> None:
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
        definition = "metric_definition"
        assert columns[(definition, "kind")] == ("text", False)
        assert columns[(definition, "subject_types")] == ("jsonb", False)
        assert columns[(definition, "attribution")] == ("jsonb", False)
        assert columns[(definition, "index_event")] == ("text", True)
        assert columns[(definition, "windows_days")] == ("jsonb", True)
        assert columns[(definition, "suppression_threshold")] == ("integer", False)
        assert columns[(definition, "registry_version")] == ("integer", False)
        assert columns[(definition, "methodology_version")] == ("text", False)
        snapshot = "metric_snapshot"
        assert columns[(snapshot, "content_hash")] == ("character", False)
        assert columns[(snapshot, "exported_at")] == ("timestamp with time zone", False)
        assert columns[(snapshot, "coverage")] == ("jsonb", False)
        assert columns[(snapshot, "storage_uri")] == ("text", False)
        observation = "metric_observation"
        assert columns[(observation, "snapshot_id")] == ("uuid", False)
        assert columns[(observation, "source_id")] == ("uuid", False)
        assert columns[(observation, "window_days")] == ("integer", True)
        assert columns[(observation, "dimension_value")] == ("text", True)
        assert columns[(observation, "eligible_count")] == ("integer", False)
        assert columns[(observation, "value")] == ("numeric", True)
        assert columns[(observation, "distribution")] == ("jsonb", True)
        assert columns[(observation, "superseded_at")] == ("timestamp with time zone", True)
        member = "metric_observation_member"
        assert columns[(member, "id")] == ("bigint", False)
        assert columns[(member, "member_kind")] == ("text", False)
        assert columns[(member, "member_id")] == ("uuid", False)
        assert columns[(member, "counted")] == ("boolean", False)
        assert columns[(member, "followed")] == ("boolean", False)
        # The member table carries entity ids only: no person column at all.
        assert not any(table == member and "person" in column for table, column in columns)
        assert columns[("source", "coverage_start")] == ("date", True)
        assert columns[("source", "coverage_end")] == ("date", True)
        assert columns[("source", "observable_outcomes")] == ("jsonb", False)
        # Revision 0006: the snapshot a run's step 13 published from (nullable, RESTRICT).
        assert columns[("ingest_run", "metrics_snapshot_id")] == ("uuid", True)
        rule = connection.execute(
            text(
                "SELECT rc.delete_rule FROM information_schema.referential_constraints rc "
                "WHERE rc.constraint_name = 'fk_ingest_run_metrics_snapshot_id_metric_snapshot'"
            )
        ).scalar()
        assert rule == "RESTRICT"
        key = connection.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_metric_observation_key'")
        ).scalar()
        assert key is not None and "UNIQUE" in key and "NULLS NOT DISTINCT" in key
        current = connection.execute(
            text(
                "SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_metric_observation_current'"
            )
        ).scalar()
        assert current is not None and "WHERE (superseded_at IS NULL)" in current
        checks = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE contype = 'c' AND conrelid = 'metric_observation_member'::regclass"
                )
            )
        }
        assert "member_kind" in checks["ck_metric_observation_member_member_kind"]
        default = connection.execute(
            text(
                "SELECT column_default FROM information_schema.columns "
                "WHERE table_name = 'source' AND column_name = 'observable_outcomes'"
            )
        ).scalar()
        assert default is not None and "[]" in default


def test_revision_0004_columns_check_and_trigger(migrated_database: Engine) -> None:
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
        candidate = "entity_resolution_candidate"
        assert columns[(candidate, "stage")] == ("character varying", False)
        assert columns[(candidate, "decided_at")] == ("timestamp with time zone", True)
        assert columns[(candidate, "decided_by")] == ("character varying", True)
        assert columns[(candidate, "reason")] == ("text", True)
        assert columns[(candidate, "ingest_run_id")] == ("uuid", True)
        assert columns[("person", "merged_into_person_id")] == ("uuid", True)
        assert columns[("audit_log", "actor")] == ("character varying", False)
        assert columns[("audit_log", "payload")] == ("jsonb", False)
        assert columns[("audit_log", "occurred_at")] == ("timestamp with time zone", False)
        checks = {
            row[0]: row[1]
            for row in connection.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE contype = 'c' AND conrelid = 'entity_resolution_candidate'::regclass"
                )
            )
        }
        assert (
            "left_record_id < right_record_id"
            in checks["ck_entity_resolution_candidate_ordered_pair"]
        )
        triggers = {
            row[0]
            for row in connection.execute(
                text("SELECT tgname FROM pg_trigger WHERE tgrelid = 'audit_log'::regclass")
            )
        }
        assert "trg_audit_log_append_only" in triggers


def test_audit_log_rejects_update_and_delete_even_for_the_admin_role(
    migrated_database: Engine,
) -> None:
    with migrated_database.connect() as connection:
        transaction = connection.begin()
        try:
            row_id = connection.execute(
                text(
                    "INSERT INTO audit_log (actor, action, entity_type, payload) "
                    "VALUES ('tests', 'test.append', 'person', '{}'::jsonb) RETURNING id"
                )
            ).scalar_one()
            with pytest.raises(DBAPIError, match="append-only"):
                with connection.begin_nested():
                    connection.execute(
                        text("UPDATE audit_log SET actor = 'x' WHERE id = :id"), {"id": row_id}
                    )
            with pytest.raises(DBAPIError, match="append-only"):
                with connection.begin_nested():
                    connection.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row_id})
            assert (
                connection.execute(
                    text("SELECT actor FROM audit_log WHERE id = :id"), {"id": row_id}
                ).scalar_one()
                == "tests"
            )
        finally:
            transaction.rollback()


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
    # Through 0004 and 0003 first: each downgrade must leave exactly the prior shape.
    downgrade(url, "0003")
    assert current_revision(migrated_database) == "0003"
    without_audit = _snapshot(migrated_database)
    assert "audit_log" not in without_audit.tables
    assert (
        "uq_er_candidate_pair_version" not in without_audit.indexes["entity_resolution_candidate"]
    )
    assert "ix_person_merged_into_person_id" not in without_audit.indexes["person"]
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
            "entity_resolution_candidate",
        ):
            assert {"SELECT", "INSERT", "UPDATE", "DELETE"} <= granted.get(table, set()), table
        # The audit log: the ingest role appends and reads, never changes or removes.
        assert granted.get("audit_log", set()) == {"SELECT", "INSERT"}
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
            assert "entity_resolution_candidate" not in app_tables
            assert "audit_log" not in app_tables
        admin_rows = connection.execute(
            text(
                "SELECT privilege_type FROM information_schema.role_table_grants "
                "WHERE grantee = 'judgemetrics_admin' AND table_name = 'audit_log'"
            )
        ).all()
        if admin_rows:
            assert {"SELECT", "INSERT"} <= {row[0] for row in admin_rows}
