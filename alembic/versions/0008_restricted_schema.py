# alembic/versions/0008_restricted_schema.py
"""The restricted schema: restricted.party_attribute, its grants, and the ordinal party key.

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-30 12:00:00+00:00

Phase 4 Step 1 (docs/DATA_MODEL.md "The restricted schema", docs/ARCHITECTURE.md
"Restricted schema"; ROADMAP.md "Data classification": restricted
attributes live in the ``restricted`` schema, reachable by the ingest and
admin roles only):

- ``CREATE SCHEMA restricted``; ``REVOKE ALL ON SCHEMA restricted FROM
  PUBLIC``; ``USAGE`` for ``judgemetrics_ingest`` and every privilege for
  ``judgemetrics_admin``; the app role ``judgemetrics_app`` receives no
  grant of any kind — without ``USAGE`` on the schema it cannot even name
  a table in it (the revokes below only make that explicit).
- ``restricted.party_attribute``: one row per case party per attribute
  (``id``, ``case_party_id`` → ``public.case_party`` ``ON DELETE CASCADE``,
  ``attribute``, ``value``, ``source_record_id`` → ``source_record``,
  ``created_at``, ``updated_at``), unique on ``(case_party_id, attribute)``
  as ``uq_party_attribute_case_party_attribute`` — the natural key the
  ingest runner upserts on.
- Table grants and ``ALTER DEFAULT PRIVILEGES IN SCHEMA restricted`` (for
  the role running the migration and, when it exists, for the admin role):
  the ingest role gets ``SELECT, INSERT, UPDATE, DELETE`` and the admin
  role ``ALL``, so a later table of the schema inherits the same split.
- ``case_party.source_row_id`` is rewritten to ``<party_type>:<ordinal>``,
  the party's 1-based position within its case and party type in the order
  of the old key (``COLLATE "C"``, the code-point order the connector sorts
  normalized participant ids in), so no plaintext participant id sits in an
  app-readable canonical column. The unique index is dropped for the
  rewrite and recreated, so no intermediate state can collide.

Every schema, role, and table name is a module constant, never input; a
statement for a role is skipped where the role does not exist (a scratch
database without the init scripts), as in every earlier revision. Creating
a schema needs ``CREATE`` on the database: the Compose init scripts grant
it to ``judgemetrics_admin`` (``infra/docker/postgres``), and CI migrates as
the database owner.

``downgrade()`` drops the table, the default privileges, and the schema.
It keeps the ordinal party keys: the participant ids are not recoverable
from the database (they were never stored elsewhere in plaintext), and a
re-ingest with the connector's parser version 2 writes the same ordinal
keys, so nothing else is restored.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "restricted"
TABLE = "party_attribute"
APP_ROLE = "judgemetrics_app"
INGEST_ROLE = "judgemetrics_ingest"
ADMIN_ROLE = "judgemetrics_admin"
INGEST_PRIVILEGES = "SELECT, INSERT, UPDATE, DELETE"
PARTY_INDEX = "uq_case_party_case_source_row"

# The rewrite reads only fixed identifiers: nothing is interpolated from input.
REWRITE_PARTY_KEYS = """
WITH ranked AS (
    SELECT
        id,
        party_type || ':' || row_number() OVER (
            PARTITION BY case_id, party_type
            ORDER BY source_row_id COLLATE "C", id
        ) AS ordinal_key
    FROM case_party
)
UPDATE case_party
SET source_row_id = ranked.ordinal_key
FROM ranked
WHERE case_party.id = ranked.id
  AND case_party.source_row_id IS DISTINCT FROM ranked.ordinal_key
"""


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def _default_privileges(action: str) -> None:
    """``GRANT`` (upgrade) or ``REVOKE`` (downgrade) the schema's default privileges."""
    owners = ["CURRENT_USER"]
    if _role_exists(ADMIN_ROLE):
        owners.append(ADMIN_ROLE)
    preposition = "TO" if action == "GRANT" else "FROM"
    for owner in owners:
        prefix = f"ALTER DEFAULT PRIVILEGES FOR ROLE {owner} IN SCHEMA {SCHEMA} {action}"
        if _role_exists(INGEST_ROLE):
            op.execute(f"{prefix} {INGEST_PRIVILEGES} ON TABLES {preposition} {INGEST_ROLE}")
        if _role_exists(ADMIN_ROLE):
            op.execute(f"{prefix} ALL ON TABLES {preposition} {ADMIN_ROLE}")


def _apply_grants() -> None:
    op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM PUBLIC")
    if _role_exists(APP_ROLE):
        op.execute(f"REVOKE ALL ON SCHEMA {SCHEMA} FROM {APP_ROLE}")
        op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA {SCHEMA} FROM {APP_ROLE}")
    if _role_exists(INGEST_ROLE):
        op.execute(f"GRANT USAGE ON SCHEMA {SCHEMA} TO {INGEST_ROLE}")
        op.execute(f"GRANT {INGEST_PRIVILEGES} ON ALL TABLES IN SCHEMA {SCHEMA} TO {INGEST_ROLE}")
    if _role_exists(ADMIN_ROLE):
        op.execute(f"GRANT ALL ON SCHEMA {SCHEMA} TO {ADMIN_ROLE}")
        op.execute(f"GRANT ALL ON ALL TABLES IN SCHEMA {SCHEMA} TO {ADMIN_ROLE}")
    _default_privileges("GRANT")


def upgrade() -> None:
    op.execute(f"CREATE SCHEMA {SCHEMA}")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("case_party_id", sa.UUID(), nullable=False),
        sa.Column("attribute", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("source_record_id", sa.UUID(), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["case_party_id"],
            ["public.case_party.id"],
            name=op.f("fk_party_attribute_case_party_id_case_party"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"],
            ["public.source_record.id"],
            name=op.f("fk_party_attribute_source_record_id_source_record"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_party_attribute")),
        sa.UniqueConstraint(
            "case_party_id", "attribute", name="uq_party_attribute_case_party_attribute"
        ),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_party_attribute_source_record_id",
        TABLE,
        ["source_record_id"],
        unique=False,
        schema=SCHEMA,
    )
    _apply_grants()

    op.drop_index(PARTY_INDEX, table_name="case_party")
    op.execute(REWRITE_PARTY_KEYS)
    op.create_index(PARTY_INDEX, "case_party", ["case_id", "source_row_id"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_party_attribute_source_record_id", table_name=TABLE, schema=SCHEMA)
    op.drop_table(TABLE, schema=SCHEMA)
    _default_privileges("REVOKE")
    op.execute(f"DROP SCHEMA {SCHEMA}")
