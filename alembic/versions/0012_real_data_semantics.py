# alembic/versions/0012_real_data_semantics.py
"""Real-data semantics: source capabilities, coverage statistics, calendar years, unavailable.

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-09 18:00:00+00:00

Phase 5 Step 5 (docs/DATA_MODEL.md "Revision 0012", docs/ARCHITECTURE.md
"Metrics engine"):

- ``source.capabilities`` (JSONB, not null, default ``{}``): the judge gates
  the source records, its person-key scope, and the revocation scopes it
  documents (``judgemetrics.capabilities``), written by the ingest runner from
  the connector's ``SourceInfo``. An existing row keeps ``{}`` — every judge
  gate unrecorded — until its connector's next run writes them.
- ``coverage_statistic``: one row per snapshot, source, scope (``source``,
  ``jurisdiction``, ``court``) and statistic — the brief's six coverage
  statistics and the unknown-actor share — with numerator, denominator, the
  share at six decimals, and the methodology version; unique on (snapshot,
  source, scope type, scope id, statistic); checks on the scope type, the
  statistic name, and ``0 <= numerator <= denominator``. Aggregates only: no
  person id and no case list. Grants from constants: the app role ``SELECT``,
  the ingest role ``SELECT, INSERT, UPDATE, DELETE``.
- ``metric_observation.calendar_year`` (smallint, null for the whole coverage
  window) with a check that a year observation's period is that year's first
  and last days, and ``uq_metric_observation_key`` recreated with the column
  (``NULLS NOT DISTINCT``), so a source whose coverage window is one calendar
  year keeps its year observation beside the whole-window one.
- ``outcome_model.status`` gains ``unavailable`` (specification version 3): a
  target the source cannot support, recorded with its reason instead of a fit.

Every name is a module constant and every constraint is named through
``op.f()``; a grant is skipped where its role does not exist (a scratch
database without the init scripts), as in every earlier revision.
``downgrade()`` drops the table, deletes the calendar-year observations (their
members cascade) and drops the column, restores the key and the status check (a
stored ``unavailable`` model, and any suppressed observation that cites it, is
deleted first: the earlier check cannot hold it), and drops
``source.capabilities``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
APP_PRIVILEGES = "SELECT"
INGEST_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"

SOURCE_TABLE = "source"
CAPABILITIES_COLUMN = "capabilities"

COVERAGE_TABLE = "coverage_statistic"
COVERAGE_SCOPES: tuple[str, ...] = ("source", "jurisdiction", "court")
COVERAGE_STATISTICS: tuple[str, ...] = (
    "cases_with_identified_judge",
    "cases_with_final_disposition",
    "cases_with_person_resolution",
    "cases_with_adequate_follow_up",
    "cases_with_complete_charge_classification",
    "records_with_provenance",
    "unknown_actor_share",
)
COVERAGE_KEY = "uq_coverage_statistic_key"

OBSERVATION_TABLE = "metric_observation"
YEAR_COLUMN = "calendar_year"
YEAR_CHECK = "ck_metric_observation_calendar_year_period"
OBSERVATION_KEY = "uq_metric_observation_key"
KEY_BEFORE: tuple[str, ...] = (
    "metric_definition_id",
    "subject_type",
    "subject_id",
    "source_id",
    "period_start",
    "period_end",
    "window_days",
    "dimension_value",
    "snapshot_id",
)
KEY_AFTER: tuple[str, ...] = (*KEY_BEFORE[:-1], YEAR_COLUMN, KEY_BEFORE[-1])

MODEL_TABLE = "outcome_model"
MODEL_STATUS_CHECK = "ck_outcome_model_status"
STATUSES_BEFORE: tuple[str, ...] = ("fitted", "insufficient_events", "not_converged")
UNAVAILABLE = "unavailable"
STATUSES_AFTER: tuple[str, ...] = (*STATUSES_BEFORE, UNAVAILABLE)


def _quoted(values: Sequence[str]) -> str:
    return ", ".join(f"'{value}'" for value in values)


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
    """Role and table names and privileges are fixed module constants, never input."""
    if _role_exists(APP_ROLE):
        op.execute(f"GRANT {APP_PRIVILEGES} ON TABLE {COVERAGE_TABLE} TO {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        op.execute(f"GRANT {INGEST_PRIVILEGES} ON TABLE {COVERAGE_TABLE} TO {INGEST_ROLE}")


def upgrade() -> None:
    op.add_column(
        SOURCE_TABLE,
        sa.Column(
            CAPABILITIES_COLUMN,
            _jsonb(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )

    op.create_table(
        COVERAGE_TABLE,
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
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("scope_type", sa.Text(), nullable=False),
        sa.Column("scope_id", sa.UUID(), nullable=False),
        sa.Column("statistic", sa.Text(), nullable=False),
        sa.Column("numerator", sa.Integer(), nullable=False),
        sa.Column("denominator", sa.Integer(), nullable=False),
        sa.Column("share", sa.Numeric(precision=9, scale=6), nullable=True),
        sa.Column("methodology_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            f"scope_type IN ({_quoted(COVERAGE_SCOPES)})",
            name=op.f("ck_coverage_statistic_scope_type"),
        ),
        sa.CheckConstraint(
            f"statistic IN ({_quoted(COVERAGE_STATISTICS)})",
            name=op.f("ck_coverage_statistic_statistic"),
        ),
        sa.CheckConstraint(
            "numerator >= 0 AND denominator >= numerator",
            name=op.f("ck_coverage_statistic_numerator_denominator"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["metric_snapshot.id"],
            name=op.f("fk_coverage_statistic_snapshot_id_metric_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_coverage_statistic_source_id_source"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_coverage_statistic")),
        sa.UniqueConstraint(
            "snapshot_id",
            "source_id",
            "scope_type",
            "scope_id",
            "statistic",
            name=op.f(COVERAGE_KEY),
        ),
    )
    op.create_index(
        op.f("ix_coverage_statistic_snapshot_id"), COVERAGE_TABLE, ["snapshot_id"], unique=False
    )
    op.create_index(
        op.f("ix_coverage_statistic_source_id"), COVERAGE_TABLE, ["source_id"], unique=False
    )
    _apply_grants()

    op.add_column(OBSERVATION_TABLE, sa.Column(YEAR_COLUMN, sa.SmallInteger(), nullable=True))
    op.create_check_constraint(
        op.f(YEAR_CHECK),
        OBSERVATION_TABLE,
        f"{YEAR_COLUMN} IS NULL OR (period_start = make_date({YEAR_COLUMN}, 1, 1) "
        f"AND period_end = make_date({YEAR_COLUMN}, 12, 31))",
    )
    op.drop_index(OBSERVATION_KEY, table_name=OBSERVATION_TABLE)
    op.create_index(
        OBSERVATION_KEY,
        OBSERVATION_TABLE,
        list(KEY_AFTER),
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.drop_constraint(op.f(MODEL_STATUS_CHECK), MODEL_TABLE, type_="check")
    op.create_check_constraint(
        op.f(MODEL_STATUS_CHECK), MODEL_TABLE, f"status IN ({_quoted(STATUSES_AFTER)})"
    )


def downgrade() -> None:
    models = sa.table(MODEL_TABLE, sa.column("id"), sa.column("status"))
    observations = sa.table(
        OBSERVATION_TABLE, sa.column("outcome_model_id"), sa.column(YEAR_COLUMN)
    )
    # An unavailable model cannot satisfy the earlier check: it goes first, with the
    # suppressed observations that cite it (model_unavailable; members cascade).
    unavailable = sa.select(models.c.id).where(models.c.status == UNAVAILABLE)
    op.execute(observations.delete().where(observations.c.outcome_model_id.in_(unavailable)))
    op.execute(models.delete().where(models.c.status == UNAVAILABLE))
    op.drop_constraint(op.f(MODEL_STATUS_CHECK), MODEL_TABLE, type_="check")
    op.create_check_constraint(
        op.f(MODEL_STATUS_CHECK), MODEL_TABLE, f"status IN ({_quoted(STATUSES_BEFORE)})"
    )

    # A calendar-year observation has no representation without its column (and could
    # collide with the whole window's key): it goes, its members with it (CASCADE).
    op.execute(observations.delete().where(observations.c[YEAR_COLUMN].is_not(None)))
    op.drop_index(OBSERVATION_KEY, table_name=OBSERVATION_TABLE)
    op.create_index(
        OBSERVATION_KEY,
        OBSERVATION_TABLE,
        list(KEY_BEFORE),
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.drop_constraint(op.f(YEAR_CHECK), OBSERVATION_TABLE, type_="check")
    op.drop_column(OBSERVATION_TABLE, YEAR_COLUMN)

    op.drop_index(op.f("ix_coverage_statistic_source_id"), table_name=COVERAGE_TABLE)
    op.drop_index(op.f("ix_coverage_statistic_snapshot_id"), table_name=COVERAGE_TABLE)
    op.drop_table(COVERAGE_TABLE)

    op.drop_column(SOURCE_TABLE, CAPABILITIES_COLUMN)
