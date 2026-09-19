# alembic/versions/0006_ingest_run_metrics_snapshot.py
"""The snapshot an ingest run's step 13 recompute published from.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-19 18:00:00+00:00

Phase 3 Step 2 (the computation engine; docs/ARCHITECTURE.md "Metrics
engine") records on ``ingest_run`` the ``metric_snapshot`` that pipeline
step 13 exported and published the impacted subjects' observations from:
``metrics_snapshot_id``, a nullable foreign key (RESTRICT, so a snapshot
that a run cites is never deleted from under it) with an index. A run
that touched no metric subject (a reference-only source, an unchanged
rerun) or that ran with ``JUDGEMETRICS_METRICS_RECOMPUTE_ON_INGEST``
off leaves it null.

The hash is a column rather than a key of ``ingest_run.checkpoint``
because the runner hands the whole checkpoint back to a checkpointing
connector at its next run (``SupportsCheckpoint.restore_checkpoint``),
so an engine-owned key there would leak into the connector's cursor
namespace. Reversible; no data is rewritten.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RUN = "ingest_run"
COLUMN = "metrics_snapshot_id"


def upgrade() -> None:
    op.add_column(RUN, sa.Column(COLUMN, sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ingest_run_metrics_snapshot_id_metric_snapshot"),
        RUN,
        "metric_snapshot",
        [COLUMN],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(op.f("ix_ingest_run_metrics_snapshot_id"), RUN, [COLUMN], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_ingest_run_metrics_snapshot_id"), table_name=RUN)
    op.drop_constraint(
        op.f("fk_ingest_run_metrics_snapshot_id_metric_snapshot"), RUN, type_="foreignkey"
    )
    op.drop_column(RUN, COLUMN)
