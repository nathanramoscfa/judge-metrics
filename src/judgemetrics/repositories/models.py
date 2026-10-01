# src/judgemetrics/repositories/models.py
"""Outcome model queries: the model card's one statement.

``model_card_row`` reads one ``outcome_model`` row joined to its snapshot
(content hash) and its source (key, and the synthetic flag by the same rule
as ``repositories.provenance.synthetic_flag``), and only while the model's
snapshot still carries a current observation (``EXISTS`` over
``metric_observation``): a model of a snapshot every observation has moved
on from is history, served by the CLI (``judgemetrics models show``) but a
404 on the public surface, the way a superseded observation is. The
``storage_uri`` column is never selected.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import Row, exists, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    SYNTHETIC_SOURCE_TYPE,
    MetricObservation,
    MetricSnapshot,
    OutcomeModel,
    Source,
)

# Every column a model card reads; `storage_uri` is deliberately absent.
CARD_COLUMNS = (
    OutcomeModel.id,
    OutcomeModel.content_hash,
    OutcomeModel.spec_version,
    OutcomeModel.model_version,
    OutcomeModel.target,
    OutcomeModel.window_days,
    OutcomeModel.seed,
    OutcomeModel.status,
    OutcomeModel.n_train,
    OutcomeModel.events_train,
    OutcomeModel.n_test,
    OutcomeModel.events_test,
    OutcomeModel.train_start,
    OutcomeModel.train_end,
    OutcomeModel.split_cutoff,
    OutcomeModel.diagnostics,
    OutcomeModel.coefficients,
    OutcomeModel.code_version,
    OutcomeModel.fitted_at,
)


def model_card_row(session: Session, model_id: uuid.UUID) -> Row[Any] | None:
    """The model with its snapshot hash and source, or ``None`` (unknown or superseded)."""
    current = exists().where(
        MetricObservation.snapshot_id == OutcomeModel.snapshot_id,
        MetricObservation.superseded_at.is_(None),
    )
    stmt = (
        select(
            *CARD_COLUMNS,
            MetricSnapshot.content_hash.label("snapshot_hash"),
            Source.name.label("source_name"),
            (Source.source_type == SYNTHETIC_SOURCE_TYPE).label("synthetic"),
        )
        .join(MetricSnapshot, MetricSnapshot.id == OutcomeModel.snapshot_id)
        .join(Source, Source.id == OutcomeModel.source_id)
        .where(OutcomeModel.id == model_id, current)
    )
    return session.execute(stmt).one_or_none()
