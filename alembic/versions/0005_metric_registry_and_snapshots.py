# alembic/versions/0005_metric_registry_and_snapshots.py
"""Metric registry columns, snapshots, observation keys, members, and source coverage.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-18 18:00:00+00:00

Phase 3 Step 1 (the metric registry and the analytic frame;
docs/METHODOLOGY.md, docs/ARCHITECTURE.md "Metrics engine") needs:

- on ``metric_definition``: the registry columns ``kind``,
  ``subject_types`` (JSONB array), ``attribution`` (JSONB), ``index_event``,
  ``outcome``, ``windows_days`` (JSONB), ``dimension``,
  ``suppression_threshold``, ``unit``, ``registry_version``, and
  ``methodology_version``; the table has never held a row, so the NOT NULL
  columns are added without defaults (as 0004 did for ``stage``);
- ``metric_snapshot``: one hashed export of the canonical tables
  (``content_hash`` unique, ``label``, ``exported_at``, ``code_version``,
  ``registry_version``, ``methodology_version``, ``row_counts``,
  ``coverage``, ``storage_uri``) that Step 2's ``metrics compute`` writes
  and ``metrics verify`` recomputes from;
- on ``metric_observation``: ``snapshot_id`` and ``source_id`` (RESTRICT,
  NOT NULL; the table is empty), ``window_days``, ``dimension_value``,
  ``eligible_count`` (the cohort before the follow-up restriction),
  ``value`` (medians in days, survival estimates), ``distribution``,
  ``code_version``, ``registry_version``, ``superseded_at``, the unique
  index ``uq_metric_observation_key`` on ``(metric_definition_id,
  subject_type, subject_id, source_id, period_start, period_end,
  window_days, dimension_value, snapshot_id)`` with ``NULLS NOT DISTINCT``
  (PostgreSQL 15+, as revision 0002's keys), and the partial index
  ``ix_metric_observation_current`` over ``(subject_type, subject_id)``
  where ``superseded_at IS NULL``;
- ``metric_observation_member``: the entity ids behind an observation
  (``member_kind`` one of decision, charge, court_case, sentence,
  court_event, justice_event — a check constraint; ``member_id``;
  ``counted`` in the numerator; ``followed`` in the denominator after
  censoring), indexed on ``observation_id`` and on ``(member_kind,
  member_id)``; never a person id;
- on ``source``: ``coverage_start``, ``coverage_end`` (the window the
  engine right-censors at) and ``observable_outcomes`` (JSONB array,
  default ``[]``);
- grants from constants: ``judgemetrics_app`` SELECT on ``metric_snapshot``
  and ``metric_observation_member`` (both public: hashes, counts, and
  entity ids of public rows), ``judgemetrics_ingest`` SELECT, INSERT,
  UPDATE, DELETE on both. The baseline's grants on ``metric_definition``
  and ``metric_observation`` cover the new columns.

``downgrade()`` removes everything this revision added.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
DEFINITION = "metric_definition"
OBSERVATION = "metric_observation"
SNAPSHOT = "metric_snapshot"
MEMBER = "metric_observation_member"
SOURCE = "source"
NEW_TABLES: tuple[str, ...] = (SNAPSHOT, MEMBER)
MEMBER_KINDS: tuple[str, ...] = (
    "decision",
    "charge",
    "court_case",
    "sentence",
    "court_event",
    "justice_event",
)
DEFINITION_COLUMNS: tuple[str, ...] = (
    "kind",
    "subject_types",
    "attribution",
    "index_event",
    "outcome",
    "windows_days",
    "dimension",
    "suppression_threshold",
    "unit",
    "registry_version",
    "methodology_version",
)
OBSERVATION_COLUMNS: tuple[str, ...] = (
    "snapshot_id",
    "source_id",
    "window_days",
    "dimension_value",
    "eligible_count",
    "value",
    "distribution",
    "code_version",
    "registry_version",
    "superseded_at",
)
SOURCE_COLUMNS: tuple[str, ...] = ("coverage_start", "coverage_end", "observable_outcomes")


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(none_as_null=True, astext_type=sa.Text())


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def _apply_grants() -> None:
    """Role and table names are fixed module constants, never user input."""
    if _role_exists(APP_ROLE):
        for table in NEW_TABLES:
            op.execute(f"GRANT SELECT ON TABLE {table} TO {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        for table in NEW_TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {INGEST_ROLE}")


def upgrade() -> None:
    # --- metric_definition: the registry columns --------------------------------------
    op.add_column(DEFINITION, sa.Column("kind", sa.Text(), nullable=False))
    op.add_column(DEFINITION, sa.Column("subject_types", _jsonb(), nullable=False))
    op.add_column(DEFINITION, sa.Column("attribution", _jsonb(), nullable=False))
    op.add_column(DEFINITION, sa.Column("index_event", sa.Text(), nullable=True))
    op.add_column(DEFINITION, sa.Column("outcome", sa.Text(), nullable=True))
    op.add_column(DEFINITION, sa.Column("windows_days", _jsonb(), nullable=True))
    op.add_column(DEFINITION, sa.Column("dimension", sa.Text(), nullable=True))
    op.add_column(DEFINITION, sa.Column("suppression_threshold", sa.Integer(), nullable=False))
    op.add_column(DEFINITION, sa.Column("unit", sa.Text(), nullable=False))
    op.add_column(DEFINITION, sa.Column("registry_version", sa.Integer(), nullable=False))
    op.add_column(DEFINITION, sa.Column("methodology_version", sa.Text(), nullable=False))

    # --- metric_snapshot ----------------------------------------------------------------
    op.create_table(
        SNAPSHOT,
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
        sa.Column("content_hash", sa.CHAR(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("registry_version", sa.Integer(), nullable=False),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.Column("row_counts", _jsonb(), server_default="{}", nullable=False),
        sa.Column("coverage", _jsonb(), server_default="{}", nullable=False),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_snapshot")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_metric_snapshot_content_hash")),
    )

    # --- metric_observation: snapshot, source, window, dimension, versions --------------
    op.add_column(OBSERVATION, sa.Column("snapshot_id", sa.UUID(), nullable=False))
    op.add_column(OBSERVATION, sa.Column("source_id", sa.UUID(), nullable=False))
    op.add_column(OBSERVATION, sa.Column("window_days", sa.Integer(), nullable=True))
    op.add_column(OBSERVATION, sa.Column("dimension_value", sa.Text(), nullable=True))
    op.add_column(OBSERVATION, sa.Column("eligible_count", sa.Integer(), nullable=False))
    op.add_column(OBSERVATION, sa.Column("value", sa.Numeric(precision=14, scale=4), nullable=True))
    op.add_column(OBSERVATION, sa.Column("distribution", _jsonb(), nullable=True))
    op.add_column(OBSERVATION, sa.Column("code_version", sa.Text(), nullable=False))
    op.add_column(OBSERVATION, sa.Column("registry_version", sa.Integer(), nullable=False))
    op.add_column(
        OBSERVATION, sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_metric_observation_snapshot_id_metric_snapshot"),
        OBSERVATION,
        SNAPSHOT,
        ["snapshot_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        op.f("fk_metric_observation_source_id_source"),
        OBSERVATION,
        SOURCE,
        ["source_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_metric_observation_snapshot_id"), OBSERVATION, ["snapshot_id"], unique=False
    )
    op.create_index(
        op.f("ix_metric_observation_source_id"), OBSERVATION, ["source_id"], unique=False
    )
    op.create_index(
        "uq_metric_observation_key",
        OBSERVATION,
        [
            "metric_definition_id",
            "subject_type",
            "subject_id",
            "source_id",
            "period_start",
            "period_end",
            "window_days",
            "dimension_value",
            "snapshot_id",
        ],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_metric_observation_current",
        OBSERVATION,
        ["subject_type", "subject_id"],
        unique=False,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )

    # --- metric_observation_member --------------------------------------------------------
    kinds = ", ".join(f"'{kind}'" for kind in MEMBER_KINDS)
    op.create_table(
        MEMBER,
        sa.Column("id", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("observation_id", sa.UUID(), nullable=False),
        sa.Column("member_kind", sa.Text(), nullable=False),
        sa.Column("member_id", sa.UUID(), nullable=False),
        sa.Column("counted", sa.Boolean(), nullable=False),
        sa.Column("followed", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            f"member_kind IN ({kinds})", name=op.f("ck_metric_observation_member_member_kind")
        ),
        sa.ForeignKeyConstraint(
            ["observation_id"],
            ["metric_observation.id"],
            name=op.f("fk_metric_observation_member_observation_id_metric_observation"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_metric_observation_member")),
    )
    op.create_index(
        "ix_metric_observation_member_observation_id", MEMBER, ["observation_id"], unique=False
    )
    op.create_index(
        "ix_metric_observation_member_member", MEMBER, ["member_kind", "member_id"], unique=False
    )

    # --- source: coverage window and observable outcomes ----------------------------------
    op.add_column(SOURCE, sa.Column("coverage_start", sa.Date(), nullable=True))
    op.add_column(SOURCE, sa.Column("coverage_end", sa.Date(), nullable=True))
    op.add_column(
        SOURCE, sa.Column("observable_outcomes", _jsonb(), server_default="[]", nullable=False)
    )
    _apply_grants()


def downgrade() -> None:
    for column in SOURCE_COLUMNS:
        op.drop_column(SOURCE, column)

    op.drop_index("ix_metric_observation_member_member", table_name=MEMBER)
    op.drop_index("ix_metric_observation_member_observation_id", table_name=MEMBER)
    op.drop_table(MEMBER)

    op.drop_index("ix_metric_observation_current", table_name=OBSERVATION)
    op.drop_index("uq_metric_observation_key", table_name=OBSERVATION)
    op.drop_index(op.f("ix_metric_observation_source_id"), table_name=OBSERVATION)
    op.drop_index(op.f("ix_metric_observation_snapshot_id"), table_name=OBSERVATION)
    op.drop_constraint(
        op.f("fk_metric_observation_source_id_source"), OBSERVATION, type_="foreignkey"
    )
    op.drop_constraint(
        op.f("fk_metric_observation_snapshot_id_metric_snapshot"), OBSERVATION, type_="foreignkey"
    )
    for column in reversed(OBSERVATION_COLUMNS):
        op.drop_column(OBSERVATION, column)

    op.drop_table(SNAPSHOT)

    for column in reversed(DEFINITION_COLUMNS):
        op.drop_column(DEFINITION, column)
