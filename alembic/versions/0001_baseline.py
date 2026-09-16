# alembic/versions/0001_baseline.py
"""Baseline: the twenty-three canonical tables, enums, indexes, and grants.

Revision ID: 0001
Revises:
Create Date: 2026-09-16 17:02:44+00:00

Creates every entity of the brief's canonical data model (ROADMAP.md §4
Phase 1.2) with the performance-strategy indexes: every ``court_id``,
``judge_id``, ``person_id``, ``case_id``, and ``source_record_id`` foreign
key; ``court_case (court_id, case_number_normalized)`` unique; the event
timestamps; the metric-observation lookup; trigram (``pg_trgm``) indexes on
``judge.normalized_name`` and ``court.canonical_name``; GIN indexes on the
``external_ids`` JSONB columns; and a unique index on the FJC node id
(``judge.external_ids->>'fjc_nid'``). The public API role receives SELECT
on every table except the restricted ``person_identifier`` and
``correction_request``. ``downgrade()`` removes everything it created.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
RESTRICTED_TABLES = ("person_identifier", "correction_request")
# Every table this revision creates (self-contained: migrations never import models).
TABLES = (
    "jurisdiction",
    "court",
    "judge",
    "judge_service",
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
    "source",
    "source_record",
    "ingest_run",
    "entity_resolution_candidate",
    "metric_definition",
    "metric_observation",
    "data_quality_issue",
    "correction_request",
)

# PostgreSQL ENUM types, created once before the tables and dropped after them.
ENUMS: dict[str, tuple[str, ...]] = {
    "jurisdiction_type": ("federal", "state", "county", "city", "district", "circuit"),
    "actor_type": (
        "judge",
        "prosecutor",
        "defense",
        "jury",
        "clerk",
        "law_enforcement",
        "legislature_or_mandatory_rule",
        "appellate_court",
        "unknown",
    ),
    "resolution_decision": ("matched", "rejected", "review"),
    "subject_type": ("judge", "court", "jurisdiction"),
    "ingest_run_status": ("running", "succeeded", "failed", "refused"),
    "issue_severity": ("info", "warning", "error", "critical"),
    "issue_status": ("open", "acknowledged", "resolved", "wont_fix"),
    "correction_status": ("received", "under_review", "accepted", "rejected", "closed"),
}


def _enum(name: str, *values: str) -> postgresql.ENUM:
    """Reference an ENUM type created explicitly in ``upgrade()``."""
    return postgresql.ENUM(*values, name=name, create_type=False)


def _create_enums() -> None:
    bind = op.get_bind()
    for name, values in ENUMS.items():
        postgresql.ENUM(*values, name=name).create(bind, checkfirst=True)


def _drop_enums() -> None:
    bind = op.get_bind()
    for name in reversed(ENUMS):
        postgresql.ENUM(name=name).drop(bind, checkfirst=True)


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def _apply_grants() -> None:
    """Public API role: SELECT on public tables only; ingest role: DML everywhere.

    Role names are fixed identifiers from infra/docker/postgres/02-roles.sql,
    never user input. Grants are skipped where a role does not exist (a
    scratch database without the init scripts) so the schema itself is
    still reproducible.
    """
    if _role_exists(APP_ROLE):
        for table in TABLES:
            if table in RESTRICTED_TABLES:
                op.execute(f"REVOKE ALL ON TABLE {table} FROM {APP_ROLE}")
            else:
                op.execute(f"GRANT SELECT ON TABLE {table} TO {APP_ROLE}")
        op.execute(f"GRANT SELECT ON TABLE alembic_version TO {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        for table in TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {INGEST_ROLE}")


def upgrade() -> None:
    # Trusted extension: a no-op where the init script already created it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    _create_enums()
    op.create_table(
        "correction_request",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=64), nullable=False),
        sa.Column("target_id", sa.UUID(), nullable=False),
        sa.Column("requester_contact", sa.LargeBinary(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("supporting_material_path", sa.Text(), nullable=True),
        sa.Column(
            "status",
            _enum(
                "correction_status", "received", "under_review", "accepted", "rejected", "closed"
            ),
            nullable=False,
        ),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_correction_request")),
    )
    op.create_index(
        op.f("ix_correction_request_target_id"), "correction_request", ["target_id"], unique=False
    )
    op.create_table(
        "entity_resolution_candidate",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("left_record_id", sa.UUID(), nullable=False),
        sa.Column("right_record_id", sa.UUID(), nullable=False),
        sa.Column("match_probability", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column(
            "decision",
            _enum("resolution_decision", "matched", "rejected", "review"),
            nullable=False,
        ),
        sa.Column(
            "features",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("model_version", sa.String(length=64), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_entity_resolution_candidate")),
    )
    op.create_index(
        "ix_entity_resolution_candidate_pair",
        "entity_resolution_candidate",
        ["entity_type", "left_record_id", "right_record_id"],
        unique=False,
    )
    op.create_table(
        "judge",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column(
            "external_ids",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judge")),
    )
    op.create_table(
        "jurisdiction",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column(
            "type",
            _enum("jurisdiction_type", "federal", "state", "county", "city", "district", "circuit"),
            nullable=False,
        ),
        sa.Column("state_code", sa.String(length=2), nullable=True),
        sa.Column("fips_code", sa.String(length=10), nullable=True),
        sa.Column("parent_jurisdiction_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["parent_jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_jurisdiction_parent_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jurisdiction")),
    )
    op.create_index(
        op.f("ix_jurisdiction_parent_jurisdiction_id"),
        "jurisdiction",
        ["parent_jurisdiction_id"],
        unique=False,
    )
    op.create_table(
        "metric_definition",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("numerator_definition", sa.Text(), nullable=False),
        sa.Column("denominator_definition", sa.Text(), nullable=False),
        sa.Column("eligibility_definition", sa.Text(), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_definition")),
        sa.UniqueConstraint("slug", "version", name="metric_definition_slug_version"),
    )
    op.create_table(
        "person",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("public_person_key", sa.String(length=64), nullable=False),
        sa.Column("resolution_status", sa.String(length=32), nullable=False),
        sa.Column("resolution_confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person")),
        sa.UniqueConstraint("public_person_key", name=op.f("uq_person_public_person_key")),
    )
    op.create_table(
        "court",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=False),
        sa.Column("canonical_name", sa.Text(), nullable=False),
        sa.Column("court_type", sa.String(length=64), nullable=False),
        sa.Column(
            "external_ids",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("active_from", sa.Date(), nullable=True),
        sa.Column("active_to", sa.Date(), nullable=True),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_court_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_court")),
    )
    op.create_index(op.f("ix_court_jurisdiction_id"), "court", ["jurisdiction_id"], unique=False)
    op.create_table(
        "metric_observation",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("metric_definition_id", sa.UUID(), nullable=False),
        sa.Column(
            "subject_type", _enum("subject_type", "judge", "court", "jurisdiction"), nullable=False
        ),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("cohort_size", sa.Integer(), nullable=False),
        sa.Column("observed_count", sa.Integer(), nullable=False),
        sa.Column("expected_count", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("observed_rate", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("expected_rate", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("standardized_ratio", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("lower_confidence_bound", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("upper_confidence_bound", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("suppressed_flag", sa.Boolean(), nullable=False),
        sa.Column("methodology_version", sa.String(length=32), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["metric_definition_id"],
            ["metric_definition.id"],
            name=op.f("fk_metric_observation_metric_definition_id_metric_definition"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_observation")),
    )
    op.create_index(
        "ix_metric_observation_subject_period",
        "metric_observation",
        ["metric_definition_id", "subject_type", "subject_id", "period_start"],
        unique=False,
    )
    op.create_table(
        "source",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("jurisdiction_id", sa.UUID(), nullable=True),
        sa.Column("access_method", sa.String(length=64), nullable=False),
        sa.Column(
            "terms_metadata",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["jurisdiction_id"],
            ["jurisdiction.id"],
            name=op.f("fk_source_jurisdiction_id_jurisdiction"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source")),
        sa.UniqueConstraint("name", name=op.f("uq_source_name")),
    )
    op.create_index(op.f("ix_source_jurisdiction_id"), "source", ["jurisdiction_id"], unique=False)
    op.create_table(
        "ingest_run",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            _enum("ingest_run_status", "running", "succeeded", "failed", "refused"),
            nullable=False,
        ),
        sa.Column("records_seen", sa.Integer(), nullable=False),
        sa.Column("records_created", sa.Integer(), nullable=False),
        sa.Column("records_updated", sa.Integer(), nullable=False),
        sa.Column("records_rejected", sa.Integer(), nullable=False),
        sa.Column("code_version", sa.String(length=64), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_ingest_run_source_id_source"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ingest_run")),
    )
    op.create_index(op.f("ix_ingest_run_source_id"), "ingest_run", ["source_id"], unique=False)
    op.create_table(
        "source_record",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("external_record_id", sa.Text(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_object_path", sa.Text(), nullable=False),
        sa.Column("raw_sha256", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=64), nullable=False),
        sa.Column("ingest_run_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["ingest_run_id"],
            ["ingest_run.id"],
            name=op.f("fk_source_record_ingest_run_id_ingest_run"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_source_record_source_id_source"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_source_record")),
    )
    op.create_index(
        op.f("ix_source_record_external_record_id"),
        "source_record",
        ["external_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_source_record_ingest_run_id"), "source_record", ["ingest_run_id"], unique=False
    )
    op.create_index(
        op.f("ix_source_record_raw_sha256"), "source_record", ["raw_sha256"], unique=False
    )
    op.create_index(
        op.f("ix_source_record_source_id"), "source_record", ["source_id"], unique=False
    )
    op.create_table(
        "court_case",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("case_number", sa.Text(), nullable=False),
        sa.Column("case_number_normalized", sa.Text(), nullable=False),
        sa.Column("case_type", sa.String(length=64), nullable=False),
        sa.Column("filed_date", sa.Date(), nullable=True),
        sa.Column("closed_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["court_id"],
            ["court.id"],
            name=op.f("fk_court_case_court_id_court"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_court_case_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_court_case")),
        sa.UniqueConstraint("court_id", "case_number_normalized", name="court_case_number"),
    )
    op.create_index(op.f("ix_court_case_court_id"), "court_case", ["court_id"], unique=False)
    op.create_index(
        op.f("ix_court_case_source_record_id"), "court_case", ["source_record_id"], unique=False
    )
    op.create_table(
        "data_quality_issue",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("source_record_id", sa.UUID(), nullable=True),
        sa.Column("entity_type", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column(
            "severity",
            _enum("issue_severity", "info", "warning", "error", "critical"),
            nullable=False,
        ),
        sa.Column("issue_code", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column(
            "status",
            _enum("issue_status", "open", "acknowledged", "resolved", "wont_fix"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_data_quality_issue_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_data_quality_issue")),
    )
    op.create_index(
        op.f("ix_data_quality_issue_issue_code"), "data_quality_issue", ["issue_code"], unique=False
    )
    op.create_index(
        op.f("ix_data_quality_issue_source_record_id"),
        "data_quality_issue",
        ["source_record_id"],
        unique=False,
    )
    op.create_table(
        "judge_service",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("judge_id", sa.UUID(), nullable=False),
        sa.Column("court_id", sa.UUID(), nullable=False),
        sa.Column("position_type", sa.String(length=64), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["court_id"],
            ["court.id"],
            name=op.f("fk_judge_service_court_id_court"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["judge_id"],
            ["judge.id"],
            name=op.f("fk_judge_service_judge_id_judge"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_judge_service_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judge_service")),
    )
    op.create_index(op.f("ix_judge_service_court_id"), "judge_service", ["court_id"], unique=False)
    op.create_index(op.f("ix_judge_service_judge_id"), "judge_service", ["judge_id"], unique=False)
    op.create_index(
        op.f("ix_judge_service_source_record_id"),
        "judge_service",
        ["source_record_id"],
        unique=False,
    )
    op.create_table(
        "person_identifier",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("identifier_type", sa.String(length=64), nullable=False),
        sa.Column("value_hash", sa.String(length=64), nullable=False),
        sa.Column("encrypted_value", sa.LargeBinary(), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_person_identifier_person_id_person"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_person_identifier_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_person_identifier")),
    )
    op.create_index(
        op.f("ix_person_identifier_person_id"), "person_identifier", ["person_id"], unique=False
    )
    op.create_index(
        op.f("ix_person_identifier_source_record_id"),
        "person_identifier",
        ["source_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_person_identifier_value_hash"), "person_identifier", ["value_hash"], unique=False
    )
    op.create_table(
        "case_party",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=True),
        sa.Column("party_type", sa.String(length=32), nullable=False),
        sa.Column("source_party_label", sa.Text(), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["court_case.id"],
            name=op.f("fk_case_party_case_id_court_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_case_party_person_id_person"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_case_party_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_case_party")),
    )
    op.create_index(op.f("ix_case_party_case_id"), "case_party", ["case_id"], unique=False)
    op.create_index(op.f("ix_case_party_person_id"), "case_party", ["person_id"], unique=False)
    op.create_index(
        op.f("ix_case_party_source_record_id"), "case_party", ["source_record_id"], unique=False
    )
    op.create_table(
        "charge",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("statute_code", sa.String(length=128), nullable=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("offense_category", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=64), nullable=False),
        sa.Column("violent_flag", sa.Boolean(), nullable=True),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disposed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disposition", sa.String(length=64), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["court_case.id"],
            name=op.f("fk_charge_case_id_court_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_charge_person_id_person"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_charge_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_charge")),
    )
    op.create_index(op.f("ix_charge_case_id"), "charge", ["case_id"], unique=False)
    op.create_index(op.f("ix_charge_person_id"), "charge", ["person_id"], unique=False)
    op.create_index(
        op.f("ix_charge_source_record_id"), "charge", ["source_record_id"], unique=False
    )
    op.create_table(
        "court_event",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=True),
        sa.Column("judge_id", sa.UUID(), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "actor_type",
            _enum(
                "actor_type",
                "judge",
                "prosecutor",
                "defense",
                "jury",
                "clerk",
                "law_enforcement",
                "legislature_or_mandatory_rule",
                "appellate_court",
                "unknown",
            ),
            nullable=True,
        ),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["court_case.id"],
            name=op.f("fk_court_event_case_id_court_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judge_id"],
            ["judge.id"],
            name=op.f("fk_court_event_judge_id_judge"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_court_event_person_id_person"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_court_event_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_court_event")),
    )
    op.create_index(op.f("ix_court_event_case_id"), "court_event", ["case_id"], unique=False)
    op.create_index(op.f("ix_court_event_event_at"), "court_event", ["event_at"], unique=False)
    op.create_index(op.f("ix_court_event_judge_id"), "court_event", ["judge_id"], unique=False)
    op.create_index(op.f("ix_court_event_person_id"), "court_event", ["person_id"], unique=False)
    op.create_index(
        op.f("ix_court_event_source_record_id"), "court_event", ["source_record_id"], unique=False
    )
    op.create_table(
        "decision",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("judge_id", sa.UUID(), nullable=True),
        sa.Column("decision_type", sa.String(length=64), nullable=False),
        sa.Column("decision_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "decision_value",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "actor_type",
            _enum(
                "actor_type",
                "judge",
                "prosecutor",
                "defense",
                "jury",
                "clerk",
                "law_enforcement",
                "legislature_or_mandatory_rule",
                "appellate_court",
                "unknown",
            ),
            nullable=False,
        ),
        sa.Column("judicial_discretion_classification", sa.String(length=64), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["court_case.id"],
            name=op.f("fk_decision_case_id_court_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judge_id"], ["judge.id"], name=op.f("fk_decision_judge_id_judge"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_decision_person_id_person"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_decision_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_decision")),
    )
    op.create_index(op.f("ix_decision_case_id"), "decision", ["case_id"], unique=False)
    op.create_index(op.f("ix_decision_decision_at"), "decision", ["decision_at"], unique=False)
    op.create_index(op.f("ix_decision_judge_id"), "decision", ["judge_id"], unique=False)
    op.create_index(op.f("ix_decision_person_id"), "decision", ["person_id"], unique=False)
    op.create_index(
        op.f("ix_decision_source_record_id"), "decision", ["source_record_id"], unique=False
    )
    op.create_table(
        "judge_assignment",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("judge_id", sa.UUID(), nullable=False),
        sa.Column("assignment_type", sa.String(length=64), nullable=False),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["court_case.id"],
            name=op.f("fk_judge_assignment_case_id_court_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judge_id"],
            ["judge.id"],
            name=op.f("fk_judge_assignment_judge_id_judge"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_judge_assignment_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_judge_assignment")),
    )
    op.create_index(
        op.f("ix_judge_assignment_case_id"), "judge_assignment", ["case_id"], unique=False
    )
    op.create_index(
        op.f("ix_judge_assignment_judge_id"), "judge_assignment", ["judge_id"], unique=False
    )
    op.create_index(
        op.f("ix_judge_assignment_source_record_id"),
        "judge_assignment",
        ["source_record_id"],
        unique=False,
    )
    op.create_table(
        "justice_event",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("related_case_id", sa.UUID(), nullable=True),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_justice_event_person_id_person"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["related_case_id"],
            ["court_case.id"],
            name=op.f("fk_justice_event_related_case_id_court_case"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_justice_event_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_justice_event")),
    )
    op.create_index(op.f("ix_justice_event_event_at"), "justice_event", ["event_at"], unique=False)
    op.create_index(
        op.f("ix_justice_event_person_id"), "justice_event", ["person_id"], unique=False
    )
    op.create_index(
        op.f("ix_justice_event_related_case_id"), "justice_event", ["related_case_id"], unique=False
    )
    op.create_index(
        op.f("ix_justice_event_source_record_id"),
        "justice_event",
        ["source_record_id"],
        unique=False,
    )
    op.create_table(
        "sentence",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("case_id", sa.UUID(), nullable=False),
        sa.Column("person_id", sa.UUID(), nullable=False),
        sa.Column("judge_id", sa.UUID(), nullable=True),
        sa.Column("sentence_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("incarceration_days", sa.Integer(), nullable=True),
        sa.Column("probation_days", sa.Integer(), nullable=True),
        sa.Column("fine_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "sentence_components",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["court_case.id"],
            name=op.f("fk_sentence_case_id_court_case"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["judge_id"], ["judge.id"], name=op.f("fk_sentence_judge_id_judge"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["person_id"],
            ["person.id"],
            name=op.f("fk_sentence_person_id_person"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["source_record.id"],
            name=op.f("fk_sentence_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sentence")),
    )
    op.create_index(op.f("ix_sentence_case_id"), "sentence", ["case_id"], unique=False)
    op.create_index(op.f("ix_sentence_judge_id"), "sentence", ["judge_id"], unique=False)
    op.create_index(op.f("ix_sentence_person_id"), "sentence", ["person_id"], unique=False)
    op.create_index(
        op.f("ix_sentence_source_record_id"), "sentence", ["source_record_id"], unique=False
    )
    op.create_table(
        "pretrial_release",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("decision_id", sa.UUID(), nullable=False),
        sa.Column("release_type", sa.String(length=64), nullable=False),
        sa.Column("bond_amount", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column(
            "conditions",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            server_default="{}",
            nullable=False,
        ),
        sa.Column("release_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detained_flag", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["decision_id"],
            ["decision.id"],
            name=op.f("fk_pretrial_release_decision_id_decision"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pretrial_release")),
        sa.UniqueConstraint("decision_id", name=op.f("uq_pretrial_release_decision_id")),
    )
    # Search and lookup indexes beyond the plain foreign-key indexes above.
    op.create_index(
        "ix_judge_normalized_name_trgm",
        "judge",
        ["normalized_name"],
        postgresql_using="gin",
        postgresql_ops={"normalized_name": "gin_trgm_ops"},
    )
    op.create_index(
        "ix_court_canonical_name_trgm",
        "court",
        ["canonical_name"],
        postgresql_using="gin",
        postgresql_ops={"canonical_name": "gin_trgm_ops"},
    )
    op.create_index("ix_judge_external_ids", "judge", ["external_ids"], postgresql_using="gin")
    op.create_index("ix_court_external_ids", "court", ["external_ids"], postgresql_using="gin")
    op.create_index(
        "uq_judge_external_ids_fjc_nid",
        "judge",
        [sa.text("(external_ids ->> 'fjc_nid')")],
        unique=True,
        postgresql_where=sa.text("external_ids ? 'fjc_nid'"),
    )
    _apply_grants()


def downgrade() -> None:
    op.drop_index("uq_judge_external_ids_fjc_nid", table_name="judge")
    op.drop_index("ix_court_external_ids", table_name="court")
    op.drop_index("ix_judge_external_ids", table_name="judge")
    op.drop_index("ix_court_canonical_name_trgm", table_name="court")
    op.drop_index("ix_judge_normalized_name_trgm", table_name="judge")
    op.drop_table("pretrial_release")
    op.drop_index(op.f("ix_sentence_source_record_id"), table_name="sentence")
    op.drop_index(op.f("ix_sentence_person_id"), table_name="sentence")
    op.drop_index(op.f("ix_sentence_judge_id"), table_name="sentence")
    op.drop_index(op.f("ix_sentence_case_id"), table_name="sentence")
    op.drop_table("sentence")
    op.drop_index(op.f("ix_justice_event_source_record_id"), table_name="justice_event")
    op.drop_index(op.f("ix_justice_event_related_case_id"), table_name="justice_event")
    op.drop_index(op.f("ix_justice_event_person_id"), table_name="justice_event")
    op.drop_index(op.f("ix_justice_event_event_at"), table_name="justice_event")
    op.drop_table("justice_event")
    op.drop_index(op.f("ix_judge_assignment_source_record_id"), table_name="judge_assignment")
    op.drop_index(op.f("ix_judge_assignment_judge_id"), table_name="judge_assignment")
    op.drop_index(op.f("ix_judge_assignment_case_id"), table_name="judge_assignment")
    op.drop_table("judge_assignment")
    op.drop_index(op.f("ix_decision_source_record_id"), table_name="decision")
    op.drop_index(op.f("ix_decision_person_id"), table_name="decision")
    op.drop_index(op.f("ix_decision_judge_id"), table_name="decision")
    op.drop_index(op.f("ix_decision_decision_at"), table_name="decision")
    op.drop_index(op.f("ix_decision_case_id"), table_name="decision")
    op.drop_table("decision")
    op.drop_index(op.f("ix_court_event_source_record_id"), table_name="court_event")
    op.drop_index(op.f("ix_court_event_person_id"), table_name="court_event")
    op.drop_index(op.f("ix_court_event_judge_id"), table_name="court_event")
    op.drop_index(op.f("ix_court_event_event_at"), table_name="court_event")
    op.drop_index(op.f("ix_court_event_case_id"), table_name="court_event")
    op.drop_table("court_event")
    op.drop_index(op.f("ix_charge_source_record_id"), table_name="charge")
    op.drop_index(op.f("ix_charge_person_id"), table_name="charge")
    op.drop_index(op.f("ix_charge_case_id"), table_name="charge")
    op.drop_table("charge")
    op.drop_index(op.f("ix_case_party_source_record_id"), table_name="case_party")
    op.drop_index(op.f("ix_case_party_person_id"), table_name="case_party")
    op.drop_index(op.f("ix_case_party_case_id"), table_name="case_party")
    op.drop_table("case_party")
    op.drop_index(op.f("ix_person_identifier_value_hash"), table_name="person_identifier")
    op.drop_index(op.f("ix_person_identifier_source_record_id"), table_name="person_identifier")
    op.drop_index(op.f("ix_person_identifier_person_id"), table_name="person_identifier")
    op.drop_table("person_identifier")
    op.drop_index(op.f("ix_judge_service_source_record_id"), table_name="judge_service")
    op.drop_index(op.f("ix_judge_service_judge_id"), table_name="judge_service")
    op.drop_index(op.f("ix_judge_service_court_id"), table_name="judge_service")
    op.drop_table("judge_service")
    op.drop_index(op.f("ix_data_quality_issue_source_record_id"), table_name="data_quality_issue")
    op.drop_index(op.f("ix_data_quality_issue_issue_code"), table_name="data_quality_issue")
    op.drop_table("data_quality_issue")
    op.drop_index(op.f("ix_court_case_source_record_id"), table_name="court_case")
    op.drop_index(op.f("ix_court_case_court_id"), table_name="court_case")
    op.drop_table("court_case")
    op.drop_index(op.f("ix_source_record_source_id"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_raw_sha256"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_ingest_run_id"), table_name="source_record")
    op.drop_index(op.f("ix_source_record_external_record_id"), table_name="source_record")
    op.drop_table("source_record")
    op.drop_index(op.f("ix_ingest_run_source_id"), table_name="ingest_run")
    op.drop_table("ingest_run")
    op.drop_index(op.f("ix_source_jurisdiction_id"), table_name="source")
    op.drop_table("source")
    op.drop_index("ix_metric_observation_subject_period", table_name="metric_observation")
    op.drop_table("metric_observation")
    op.drop_index(op.f("ix_court_jurisdiction_id"), table_name="court")
    op.drop_table("court")
    op.drop_table("person")
    op.drop_table("metric_definition")
    op.drop_index(op.f("ix_jurisdiction_parent_jurisdiction_id"), table_name="jurisdiction")
    op.drop_table("jurisdiction")
    op.drop_table("judge")
    op.drop_index("ix_entity_resolution_candidate_pair", table_name="entity_resolution_candidate")
    op.drop_table("entity_resolution_candidate")
    op.drop_index(op.f("ix_correction_request_target_id"), table_name="correction_request")
    op.drop_table("correction_request")
    _drop_enums()
