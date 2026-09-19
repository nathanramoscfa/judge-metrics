# alembic/versions/0007_corrections_intake.py
"""The corrections intake grant: INSERT, and nothing else, on correction_request for the app role.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-19 22:00:00+00:00

Phase 3 Step 3 (``POST /api/v1/corrections``; docs/API.md "Corrections",
docs/DATA_MODEL.md "Grants"). ``correction_request`` is a restricted
table: the baseline revoked every privilege of ``judgemetrics_app`` on it
because it holds requester contacts. The public API now writes one row
per accepted correction request — the contact encrypted with the Fernet
key from settings before it reaches the statement — so the app role is
granted ``INSERT`` on the table and nothing else: no ``SELECT`` (the API
never reads the table back; PostgreSQL therefore also rejects an insert
with a ``RETURNING`` clause, which is why the API's insert has none), no
``UPDATE``, no ``DELETE``. ``judgemetrics_ingest`` and the admin role are
unchanged. Role and table names are fixed identifiers, never user input;
the grant is skipped where the role does not exist (a scratch database
without the init scripts), as in every earlier revision. Downgrade
revokes the grant.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "judgemetrics_app"
TABLE = "correction_request"


def _role_exists(role: str) -> bool:
    bind = op.get_bind()
    return bool(
        bind.execute(
            sa.text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
        ).scalar()
    )


def upgrade() -> None:
    if _role_exists(APP_ROLE):
        op.execute(f"GRANT INSERT ON TABLE {TABLE} TO {APP_ROLE}")


def downgrade() -> None:
    if _role_exists(APP_ROLE):
        op.execute(f"REVOKE INSERT ON TABLE {TABLE} FROM {APP_ROLE}")
