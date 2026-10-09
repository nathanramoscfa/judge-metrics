# alembic/versions/0011_cook_county_connector.py
"""The Cook County connector: judge identity index, charge.judge_id, the issue table's grant.

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-08 12:00:00+00:00

Phase 5 Step 4 (docs/DATA_MODEL.md "Revision 0011", docs/ARCHITECTURE.md "Cook
County connector"):

- ``uq_judge_external_ids_cook_sao_judge``: the partial unique expression index
  that resolves a Cook County judge by the canonical key of
  ``data/reference/cook_sao/judges.csv`` the way ``fjc_nid`` resolves an FJC
  judge and ``synthetic_judge_code`` a synthetic one. The identity systems are
  an allow-list in the ingest runner (``JUDGE_IDENTITY_SYSTEMS``); the system
  named here is the module constant ``JUDGE_IDENTITY_SYSTEM`` and nothing from
  data ever reaches the expression.
- ``charge.judge_id``: nullable, indexed, a foreign key to ``judge`` with
  ``RESTRICT`` — the judge who entered the charge's disposition, as the source
  records it, else null. Every synthetic and FJC row leaves it null.
- ``REVOKE SELECT ON data_quality_issue FROM judgemetrics_app``: the app role
  no longer reads data-quality issues. No API route reads the table, and an
  issue describes source rows (case ids, charge ids, judge strings) that a
  real corpus makes sensitive; the ingest role keeps its DML and the admin role
  its ownership. ``infra/docker/postgres/03-test-database.sql`` re-applies the
  revoke after its blanket grants.

Every statement is built from the module constants below; a grant or revoke is
skipped where its role does not exist (a scratch database without the init
scripts), as in every earlier revision, and every constraint is named through
``op.f()``. ``downgrade()`` restores the app role's ``SELECT`` and removes the
column, its index and key, and the judge index.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
JUDGE_TABLE = "judge"
JUDGE_IDENTITY_SYSTEM = "cook_sao_judge"
JUDGE_INDEX = f"uq_judge_external_ids_{JUDGE_IDENTITY_SYSTEM}"
CHARGE_TABLE = "charge"
JUDGE_COLUMN = "judge_id"
CHARGE_FOREIGN_KEY = "fk_charge_judge_id_judge"
CHARGE_INDEX = "ix_charge_judge_id"
ISSUE_TABLE = "data_quality_issue"


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def upgrade() -> None:
    op.create_index(
        JUDGE_INDEX,
        JUDGE_TABLE,
        [sa.text(f"(external_ids ->> '{JUDGE_IDENTITY_SYSTEM}')")],
        unique=True,
        postgresql_where=sa.text(f"external_ids ? '{JUDGE_IDENTITY_SYSTEM}'"),
    )
    op.add_column(CHARGE_TABLE, sa.Column(JUDGE_COLUMN, sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f(CHARGE_FOREIGN_KEY),
        CHARGE_TABLE,
        JUDGE_TABLE,
        [JUDGE_COLUMN],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f(CHARGE_INDEX), CHARGE_TABLE, [JUDGE_COLUMN], unique=False)
    if _role_exists(APP_ROLE):
        op.execute(f"REVOKE ALL ON TABLE {ISSUE_TABLE} FROM {APP_ROLE}")


def downgrade() -> None:
    if _role_exists(APP_ROLE):
        op.execute(f"GRANT SELECT ON TABLE {ISSUE_TABLE} TO {APP_ROLE}")
    op.drop_index(op.f(CHARGE_INDEX), table_name=CHARGE_TABLE)
    op.drop_constraint(op.f(CHARGE_FOREIGN_KEY), CHARGE_TABLE, type_="foreignkey")
    op.drop_column(CHARGE_TABLE, JUDGE_COLUMN)
    op.drop_index(JUDGE_INDEX, table_name=JUDGE_TABLE)
