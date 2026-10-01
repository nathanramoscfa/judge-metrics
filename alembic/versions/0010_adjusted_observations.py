# alembic/versions/0010_adjusted_observations.py
"""Adjusted observations: the cited outcome model, the pooling weight, the suppression reason.

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-30 23:00:00+00:00

Phase 4 Step 3 (docs/ARCHITECTURE.md "Risk adjustment", docs/DATA_MODEL.md
"metric_observation by kind"): the ``observed_expected`` kind fills the
columns revision 0001 reserved (``expected_count``, ``expected_rate``,
``standardized_ratio``) and needs three more on ``metric_observation``:

- ``outcome_model_id``: the fitted ``outcome_model`` an adjusted observation
  was computed with (nullable — every other kind leaves it null; RESTRICT,
  so a model an observation cites is never deleted from under it; indexed);
- ``pooling_weight`` Numeric(9, 6): ``E / (E + alpha)``, the share of the
  pooled ratio that is the judge's own observed-to-expected ratio;
- ``suppression_reason`` text, checked against ``below_threshold``,
  ``expected_below_minimum``, and ``model_unavailable``, with a second check
  that a row carries a reason exactly when it is suppressed. The rows
  already stored are all of the Phase 3 kinds, whose only reason is the
  denominator threshold, so every suppressed row is backfilled with
  ``below_threshold`` before the checks are created.

The app role keeps ``SELECT`` on ``metric_observation`` (the baseline's
table-level grant covers the new columns: a model id, a weight, a reason —
no person-level value); the ingest role keeps its DML. Every name and value
is a module constant. ``downgrade()`` removes the checks, the index, the
foreign key, and the three columns (the backfilled reasons go with them).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "metric_observation"
MODEL_TABLE = "outcome_model"
MODEL_COLUMN = "outcome_model_id"
WEIGHT_COLUMN = "pooling_weight"
REASON_COLUMN = "suppression_reason"
DESCRIPTIVE_REASON = "below_threshold"
REASONS: tuple[str, ...] = (DESCRIPTIVE_REASON, "expected_below_minimum", "model_unavailable")
FOREIGN_KEY = "fk_metric_observation_outcome_model_id_outcome_model"
INDEX = "ix_metric_observation_outcome_model_id"
REASON_CHECK = "ck_metric_observation_suppression_reason"
FLAG_CHECK = "ck_metric_observation_suppression_reason_flag"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column(MODEL_COLUMN, sa.UUID(), nullable=True))
    op.add_column(TABLE, sa.Column(WEIGHT_COLUMN, sa.Numeric(9, 6), nullable=True))
    op.add_column(TABLE, sa.Column(REASON_COLUMN, sa.Text(), nullable=True))
    op.create_foreign_key(
        op.f(FOREIGN_KEY), TABLE, MODEL_TABLE, [MODEL_COLUMN], ["id"], ondelete="RESTRICT"
    )
    op.create_index(op.f(INDEX), TABLE, [MODEL_COLUMN], unique=False)
    # Every stored row is of a Phase 3 kind: its only suppression reason is the threshold.
    observations = sa.table(
        TABLE, sa.column("suppressed_flag", sa.Boolean()), sa.column(REASON_COLUMN, sa.Text())
    )
    op.execute(
        observations.update()
        .where(observations.c.suppressed_flag.is_(True))
        .values({REASON_COLUMN: DESCRIPTIVE_REASON})
    )
    reasons = ", ".join(f"'{reason}'" for reason in REASONS)
    op.create_check_constraint(op.f(REASON_CHECK), TABLE, f"{REASON_COLUMN} IN ({reasons})")
    op.create_check_constraint(
        op.f(FLAG_CHECK), TABLE, f"({REASON_COLUMN} IS NOT NULL) = suppressed_flag"
    )


def downgrade() -> None:
    op.drop_constraint(op.f(FLAG_CHECK), TABLE, type_="check")
    op.drop_constraint(op.f(REASON_CHECK), TABLE, type_="check")
    op.drop_index(op.f(INDEX), table_name=TABLE)
    op.drop_constraint(op.f(FOREIGN_KEY), TABLE, type_="foreignkey")
    op.drop_column(TABLE, REASON_COLUMN)
    op.drop_column(TABLE, WEIGHT_COLUMN)
    op.drop_column(TABLE, MODEL_COLUMN)
