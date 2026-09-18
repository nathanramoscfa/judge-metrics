# alembic/versions/0004_entity_resolution_review.py
"""Entity-resolution review: candidate bookkeeping, merged persons, the append-only audit log.

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-18 12:00:00+00:00

Phase 2 Step 3 (the staged person-resolution framework, review queue, and
audit log; docs/ENTITY_RESOLUTION.md) needs:

- on ``entity_resolution_candidate``: ``stage`` (which stage decided),
  ``decided_at`` / ``decided_by`` / ``reason`` (the brief's timestamp and
  reviewer; ``system:<model version>`` for automatic decisions, NULL while
  a review item waits), ``ingest_run_id`` (the run that produced the
  candidate, NULL for ``er run``), the unique index
  ``uq_er_candidate_pair_version`` on ``(entity_type, left_record_id,
  right_record_id, model_version)`` the upsert arbitrates on, and the
  check ``left_record_id < right_record_id`` so a pair is stored once;
  the table is empty before this revision, so ``stage`` is added NOT NULL
  without a default;
- ``person.merged_into_person_id`` (self reference, indexed): a merged
  person keeps its row and points at the survivor, and every public
  query filters ``IS NULL``;
- ``audit_log``: ``occurred_at``, ``actor``, ``action``, the entity, a
  JSONB ``payload``, and ``request_id``, indexed on ``(entity_type,
  entity_id)`` and ``occurred_at``, with the trigger function
  ``audit_log_append_only()`` — a fixed string, no interpolation — that
  raises on UPDATE or DELETE, attached BEFORE UPDATE OR DELETE, so a
  written row is history for every role;
- grants: ``judgemetrics_ingest`` INSERT and SELECT on ``audit_log``,
  ``judgemetrics_admin`` SELECT and INSERT (the admin role owns the
  tables; the trigger, not the grant, is what stops it changing rows),
  ``judgemetrics_app`` nothing on ``audit_log`` and — re-asserted, the
  baseline granted SELECT — nothing on ``entity_resolution_candidate``.

``downgrade()`` removes everything this revision added.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
ADMIN_ROLE = "judgemetrics_admin"
CANDIDATE = "entity_resolution_candidate"
AUDIT_LOG = "audit_log"
TRIGGER_FUNCTION = "audit_log_append_only"
TRIGGER = "trg_audit_log_append_only"

# The trigger body is a fixed string: nothing is interpolated into it.
CREATE_TRIGGER_FUNCTION = """
CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only: % on row % is not allowed', TG_OP, OLD.id
        USING ERRCODE = 'insufficient_privilege';
END;
$$ LANGUAGE plpgsql;
"""
CREATE_TRIGGER = """
CREATE TRIGGER trg_audit_log_append_only
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_append_only();
"""


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
    """Role and table names are fixed identifiers, never user input."""
    if _role_exists(APP_ROLE):
        op.execute(f"REVOKE ALL ON TABLE {AUDIT_LOG} FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON TABLE {CANDIDATE} FROM {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        op.execute(f"REVOKE ALL ON TABLE {AUDIT_LOG} FROM {INGEST_ROLE}")
        op.execute(f"GRANT SELECT, INSERT ON TABLE {AUDIT_LOG} TO {INGEST_ROLE}")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {CANDIDATE} TO {INGEST_ROLE}")
    if _role_exists(ADMIN_ROLE):
        op.execute(f"GRANT SELECT, INSERT ON TABLE {AUDIT_LOG} TO {ADMIN_ROLE}")


def upgrade() -> None:
    op.add_column(CANDIDATE, sa.Column("stage", sa.String(length=32), nullable=False))
    op.add_column(CANDIDATE, sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(CANDIDATE, sa.Column("decided_by", sa.String(length=128), nullable=True))
    op.add_column(CANDIDATE, sa.Column("reason", sa.Text(), nullable=True))
    op.add_column(CANDIDATE, sa.Column("ingest_run_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_entity_resolution_candidate_ingest_run_id_ingest_run"),
        CANDIDATE,
        "ingest_run",
        ["ingest_run_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_entity_resolution_candidate_ingest_run_id"),
        CANDIDATE,
        ["ingest_run_id"],
        unique=False,
    )
    op.create_index(
        "uq_er_candidate_pair_version",
        CANDIDATE,
        ["entity_type", "left_record_id", "right_record_id", "model_version"],
        unique=True,
    )
    op.create_check_constraint(
        op.f("ck_entity_resolution_candidate_ordered_pair"),
        CANDIDATE,
        "left_record_id < right_record_id",
    )

    op.add_column("person", sa.Column("merged_into_person_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_person_merged_into_person_id_person"),
        "person",
        "person",
        ["merged_into_person_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_person_merged_into_person_id"), "person", ["merged_into_person_id"], unique=False
    )

    op.create_table(
        AUDIT_LOG,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("actor", sa.String(length=128), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=True),
        sa.Column("entity_id", sa.UUID(), nullable=True),
        sa.Column("payload", _jsonb(), server_default="{}", nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
    )
    op.create_index("ix_audit_log_entity", AUDIT_LOG, ["entity_type", "entity_id"], unique=False)
    op.create_index("ix_audit_log_occurred_at", AUDIT_LOG, ["occurred_at"], unique=False)
    op.execute(CREATE_TRIGGER_FUNCTION)
    op.execute(CREATE_TRIGGER)
    _apply_grants()


def downgrade() -> None:
    op.execute(f"DROP TRIGGER IF EXISTS {TRIGGER} ON {AUDIT_LOG}")
    op.execute(f"DROP FUNCTION IF EXISTS {TRIGGER_FUNCTION}()")
    op.drop_index("ix_audit_log_occurred_at", table_name=AUDIT_LOG)
    op.drop_index("ix_audit_log_entity", table_name=AUDIT_LOG)
    op.drop_table(AUDIT_LOG)

    op.drop_index(op.f("ix_person_merged_into_person_id"), table_name="person")
    op.drop_constraint(op.f("fk_person_merged_into_person_id_person"), "person", type_="foreignkey")
    op.drop_column("person", "merged_into_person_id")

    op.drop_constraint(
        op.f("ck_entity_resolution_candidate_ordered_pair"), CANDIDATE, type_="check"
    )
    op.drop_index("uq_er_candidate_pair_version", table_name=CANDIDATE)
    op.drop_index(op.f("ix_entity_resolution_candidate_ingest_run_id"), table_name=CANDIDATE)
    op.drop_constraint(
        op.f("fk_entity_resolution_candidate_ingest_run_id_ingest_run"),
        CANDIDATE,
        type_="foreignkey",
    )
    for column in ("ingest_run_id", "reason", "decided_by", "decided_at", "stage"):
        op.drop_column(CANDIDATE, column)
    if _role_exists(APP_ROLE):
        # The baseline's posture: the app role could read candidates before this revision.
        op.execute(f"GRANT SELECT ON TABLE {CANDIDATE} TO {APP_ROLE}")
