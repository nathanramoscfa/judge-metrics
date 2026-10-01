# alembic/versions/0009_outcome_models.py
"""The expected-outcome model catalogue: outcome_model and its grants.

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-30 20:00:00+00:00

Phase 4 Step 2 (docs/ARCHITECTURE.md "Risk adjustment", docs/DATA_MODEL.md
"outcome_model"): ``judgemetrics models fit`` records one row per fitted
model — snapshot, source, specification version, target, window, seed —
with its status, the temporal split's counts, the training range and the
cutoff, the diagnostics and per-column coefficients as JSONB, and the
sha256 and location of its canonical JSON artifact:

- ``outcome_model``: ``id`` UUID; ``content_hash`` CHAR(64) unique;
  ``snapshot_id`` → ``metric_snapshot`` and ``source_id`` → ``source``
  (RESTRICT, indexed); ``spec_version``, ``model_version``, ``target``,
  ``window_days`` (null for the release target), ``seed``, ``status``
  (checked: ``fitted``, ``insufficient_events``, ``not_converged``);
  ``n_train``, ``events_train``, ``n_test``, ``events_test``;
  ``train_start``, ``train_end``, ``split_cutoff`` (timestamptz);
  ``diagnostics`` and ``coefficients`` (JSONB); ``storage_uri``;
  ``code_version``; ``fitted_at``; ``created_at``/``updated_at``; the
  unique index ``uq_outcome_model_key`` on ``(snapshot_id, source_id,
  spec_version, target, window_days, seed)`` with ``NULLS NOT DISTINCT``
  (PostgreSQL 15+, as revisions 0002 and 0005).
- Grants from constants: ``judgemetrics_app`` ``SELECT`` (the model card is
  public: coefficients, counts, and bins, no person-level value);
  ``judgemetrics_ingest`` ``SELECT, INSERT, UPDATE, DELETE``. A statement
  for a role is skipped where the role does not exist (a scratch database
  without the init scripts), as in every earlier revision.

``downgrade()`` drops the table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
TABLE = "outcome_model"
APP_PRIVILEGES = "SELECT"
INGEST_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"
STATUSES: tuple[str, ...] = ("fitted", "insufficient_events", "not_converged")
KEY_COLUMNS: tuple[str, ...] = (
    "snapshot_id",
    "source_id",
    "spec_version",
    "target",
    "window_days",
    "seed",
)


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
        op.execute(f"GRANT {APP_PRIVILEGES} ON TABLE {TABLE} TO {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        op.execute(f"GRANT {INGEST_PRIVILEGES} ON TABLE {TABLE} TO {INGEST_ROLE}")


def upgrade() -> None:
    statuses = ", ".join(f"'{status}'" for status in STATUSES)
    op.create_table(
        TABLE,
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
        sa.Column("snapshot_id", sa.UUID(), nullable=False),
        sa.Column("source_id", sa.UUID(), nullable=False),
        sa.Column("spec_version", sa.Integer(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("window_days", sa.Integer(), nullable=True),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("n_train", sa.Integer(), nullable=False),
        sa.Column("events_train", sa.Integer(), nullable=False),
        sa.Column("n_test", sa.Integer(), nullable=False),
        sa.Column("events_test", sa.Integer(), nullable=False),
        sa.Column("train_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("train_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("split_cutoff", sa.DateTime(timezone=True), nullable=True),
        sa.Column("diagnostics", _jsonb(), nullable=True),
        sa.Column("coefficients", _jsonb(), nullable=True),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("fitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"status IN ({statuses})", name=op.f("ck_outcome_model_status")),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["metric_snapshot.id"],
            name=op.f("fk_outcome_model_snapshot_id_metric_snapshot"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["source.id"],
            name=op.f("fk_outcome_model_source_id_source"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_outcome_model")),
        sa.UniqueConstraint("content_hash", name=op.f("uq_outcome_model_content_hash")),
    )
    op.create_index(op.f("ix_outcome_model_snapshot_id"), TABLE, ["snapshot_id"], unique=False)
    op.create_index(op.f("ix_outcome_model_source_id"), TABLE, ["source_id"], unique=False)
    op.create_index(
        "uq_outcome_model_key",
        TABLE,
        list(KEY_COLUMNS),
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    _apply_grants()


def downgrade() -> None:
    op.drop_index("uq_outcome_model_key", table_name=TABLE)
    op.drop_index(op.f("ix_outcome_model_source_id"), table_name=TABLE)
    op.drop_index(op.f("ix_outcome_model_snapshot_id"), table_name=TABLE)
    op.drop_table(TABLE)
