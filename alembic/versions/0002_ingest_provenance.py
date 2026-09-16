# alembic/versions/0002_ingest_provenance.py
"""Ingest provenance: source-record references, natural keys, run bookkeeping.

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-16 19:30:00+00:00

Phase 1 Step 3 (the ingest framework, ROADMAP.md §4 Phase 1.3) needs what
the baseline lacked:

- ``jurisdiction``, ``court``, and ``judge`` reference the ``source_record``
  whose artifact produced their current values (last-substantive-writer
  provenance), so every row the runner publishes traces to raw bytes and
  the ``provenance_complete`` data-quality check can be enforced;
- ``court.state_code``, parsed from federal district-court names;
- ``judge_service.metadata`` (senior-status date, termination reason, the
  source's sequence number) and ``source_record.metadata`` (the HTTP
  validators ``ETag`` and ``Last-Modified``, the artifact URI, and the
  export page, which is how the runner issues conditional requests);
- ``ingest_run.parser_version``, ``ingest_run.checkpoint`` (incremental
  connector state), and ``ingest_run.failure_reason``;
- the unique indexes that make ``INSERT … ON CONFLICT`` upserts possible:
  jurisdiction ``(name, type)``, court ``(canonical_name, court_type)``,
  judge_service ``(judge_id, court_id, position_type, start_date)`` and
  source_record ``(source_id, external_record_id, raw_sha256)``, the last
  two with ``NULLS NOT DISTINCT`` so a null start date or external id still
  collides.

The affected tables are empty before this revision (no connector existed),
so the NOT NULL columns are added without defaults. No table is created,
so the baseline's grants cover every new column. ``downgrade()`` removes
everything this revision added.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Reference entities that gain a source_record reference.
PROVENANCE_TABLES = ("jurisdiction", "court", "judge")


def _jsonb() -> postgresql.JSONB:
    return postgresql.JSONB(none_as_null=True, astext_type=sa.Text())


def upgrade() -> None:
    for table in PROVENANCE_TABLES:
        op.add_column(table, sa.Column("source_record_id", sa.UUID(), nullable=False))
        op.create_foreign_key(
            op.f(f"fk_{table}_source_record_id_source_record"),
            table,
            "source_record",
            ["source_record_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(
            op.f(f"ix_{table}_source_record_id"), table, ["source_record_id"], unique=False
        )

    op.add_column("court", sa.Column("state_code", sa.String(length=2), nullable=True))
    op.create_index(op.f("ix_court_state_code"), "court", ["state_code"], unique=False)

    op.add_column(
        "judge_service",
        sa.Column("metadata", _jsonb(), server_default="{}", nullable=False),
    )
    op.add_column(
        "source_record",
        sa.Column("metadata", _jsonb(), server_default="{}", nullable=False),
    )
    op.add_column("ingest_run", sa.Column("parser_version", sa.String(length=64), nullable=False))
    op.add_column("ingest_run", sa.Column("checkpoint", _jsonb(), nullable=True))
    op.add_column("ingest_run", sa.Column("failure_reason", sa.Text(), nullable=True))

    op.create_index("uq_jurisdiction_name_type", "jurisdiction", ["name", "type"], unique=True)
    op.create_index(
        "uq_court_canonical_name_court_type",
        "court",
        ["canonical_name", "court_type"],
        unique=True,
    )
    op.create_index(
        "uq_judge_service_natural_key",
        "judge_service",
        ["judge_id", "court_id", "position_type", "start_date"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "uq_source_record_source_external_sha256",
        "source_record",
        ["source_id", "external_record_id", "raw_sha256"],
        unique=True,
        postgresql_nulls_not_distinct=True,
    )


def downgrade() -> None:
    op.drop_index("uq_source_record_source_external_sha256", table_name="source_record")
    op.drop_index("uq_judge_service_natural_key", table_name="judge_service")
    op.drop_index("uq_court_canonical_name_court_type", table_name="court")
    op.drop_index("uq_jurisdiction_name_type", table_name="jurisdiction")

    op.drop_column("ingest_run", "failure_reason")
    op.drop_column("ingest_run", "checkpoint")
    op.drop_column("ingest_run", "parser_version")
    op.drop_column("source_record", "metadata")
    op.drop_column("judge_service", "metadata")

    op.drop_index(op.f("ix_court_state_code"), table_name="court")
    op.drop_column("court", "state_code")

    for table in reversed(PROVENANCE_TABLES):
        op.drop_index(op.f(f"ix_{table}_source_record_id"), table_name=table)
        op.drop_constraint(
            op.f(f"fk_{table}_source_record_id_source_record"), table, type_="foreignkey"
        )
        op.drop_column(table, "source_record_id")
