# alembic/versions/0003_case_level_natural_keys.py
"""Case-level natural keys, person provenance, and identifier indexes.

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-17 09:00:00+00:00

Phase 2 Step 2 (the synthetic connector and case-level publishing,
docs/phase02-roadmap.md) makes the case-level tables upsertable the way
revision 0002 made the reference tables:

- ``source_row_id`` (Text, NOT NULL — the tables are empty, so no backfill)
  on ``case_party``, ``judge_assignment``, ``charge``, ``court_event``,
  ``decision``, and ``sentence``, and the unique index
  ``uq_<table>_case_source_row`` on ``(case_id, source_row_id)`` for each:
  the source's own row identifier within a case is the natural key;
- ``uq_justice_event_natural`` on ``(person_id, event_type, event_at,
  related_case_id)`` with ``NULLS NOT DISTINCT``: a derived event has no
  source row, so its identity is what it says;
- ``person.source_record_id`` (nullable, last-substantive-writer like the
  reference entities);
- ``uq_person_identifier_stable``, partial on ``(identifier_type,
  value_hash) WHERE identifier_type IN ('source_participant_id')``: a stable
  source identifier belongs to one person (name and date-of-birth hashes
  may legitimately repeat), and ``uq_person_identifier_person_type_hash``
  on ``(person_id, identifier_type, value_hash)`` so a rerun never adds a
  duplicate identifier row;
- ``court_case.related_case_number_normalized`` (Text, nullable, indexed),
  the source's link to a related case kept for Step 3's linkage feature;
- ``charge.disposition_actor`` (``actor_type``, nullable): who disposed of
  the charge, the charge-level attribution the judicial-dismissal rule
  reads (a departure from the brief's field list, recorded in
  docs/DATA_MODEL.md);
- ``uq_judge_external_ids_synthetic_judge_code``, the partial unique
  expression index that resolves synthetic judges the way ``fjc_nid``
  resolves FJC judges.

No table is created, so the baseline's grants cover every new column; the
grants are nevertheless re-asserted here (app role: SELECT on the public
tables only, nothing on ``person_identifier``; ingest role: DML on every
case-level table) so the revision documents the privilege split it relies
on. ``downgrade()`` removes everything this revision added.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
RESTRICTED_TABLES = ("person_identifier",)
# Tables that gain the (case_id, source_row_id) natural key.
SOURCE_ROW_TABLES = (
    "case_party",
    "judge_assignment",
    "charge",
    "court_event",
    "decision",
    "sentence",
)
# Every table the case-level publish writes (grants re-asserted below).
CASE_LEVEL_TABLES = (
    "person",
    "person_identifier",
    "court_case",
    *SOURCE_ROW_TABLES,
    "pretrial_release",
    "justice_event",
)
STABLE_IDENTIFIER_TYPES = ("source_participant_id",)


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def _reassert_grants() -> None:
    """The privilege split of revision 0001 over the case-level tables.

    Role and table names are fixed identifiers, never user input; grants
    are skipped where a role does not exist (a scratch database).
    """
    if _role_exists(APP_ROLE):
        for table in CASE_LEVEL_TABLES:
            if table in RESTRICTED_TABLES:
                op.execute(f"REVOKE ALL ON TABLE {table} FROM {APP_ROLE}")
            else:
                op.execute(f"GRANT SELECT ON TABLE {table} TO {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        for table in CASE_LEVEL_TABLES:
            op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE {table} TO {INGEST_ROLE}")


def upgrade() -> None:
    for table in SOURCE_ROW_TABLES:
        op.add_column(table, sa.Column("source_row_id", sa.Text(), nullable=False))
        op.create_index(
            f"uq_{table}_case_source_row", table, ["case_id", "source_row_id"], unique=True
        )

    op.create_index(
        "uq_justice_event_natural",
        "justice_event",
        ["person_id", "event_type", "event_at", "related_case_id"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )

    op.add_column("person", sa.Column("source_record_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_person_source_record_id_source_record"),
        "person",
        "source_record",
        ["source_record_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        op.f("ix_person_source_record_id"), "person", ["source_record_id"], unique=False
    )

    stable = ", ".join(f"'{kind}'" for kind in STABLE_IDENTIFIER_TYPES)
    op.create_index(
        "uq_person_identifier_stable",
        "person_identifier",
        ["identifier_type", "value_hash"],
        unique=True,
        postgresql_where=sa.text(f"identifier_type IN ({stable})"),
    )
    op.create_index(
        "uq_person_identifier_person_type_hash",
        "person_identifier",
        ["person_id", "identifier_type", "value_hash"],
        unique=True,
    )

    op.add_column(
        "court_case", sa.Column("related_case_number_normalized", sa.Text(), nullable=True)
    )
    op.create_index(
        op.f("ix_court_case_related_case_number_normalized"),
        "court_case",
        ["related_case_number_normalized"],
        unique=False,
    )

    op.add_column(
        "charge",
        sa.Column(
            "disposition_actor",
            postgresql.ENUM(name="actor_type", create_type=False),
            nullable=True,
        ),
    )

    op.create_index(
        "uq_judge_external_ids_synthetic_judge_code",
        "judge",
        [sa.text("(external_ids ->> 'synthetic_judge_code')")],
        unique=True,
        postgresql_where=sa.text("external_ids ? 'synthetic_judge_code'"),
    )

    _reassert_grants()


def downgrade() -> None:
    op.drop_index("uq_judge_external_ids_synthetic_judge_code", table_name="judge")
    op.drop_column("charge", "disposition_actor")
    op.drop_index(op.f("ix_court_case_related_case_number_normalized"), table_name="court_case")
    op.drop_column("court_case", "related_case_number_normalized")
    op.drop_index("uq_person_identifier_person_type_hash", table_name="person_identifier")
    op.drop_index("uq_person_identifier_stable", table_name="person_identifier")
    op.drop_index(op.f("ix_person_source_record_id"), table_name="person")
    op.drop_constraint(
        op.f("fk_person_source_record_id_source_record"), "person", type_="foreignkey"
    )
    op.drop_column("person", "source_record_id")
    op.drop_index("uq_justice_event_natural", table_name="justice_event")
    for table in reversed(SOURCE_ROW_TABLES):
        op.drop_index(f"uq_{table}_case_source_row", table_name=table)
        op.drop_column(table, "source_row_id")
