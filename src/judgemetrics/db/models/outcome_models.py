# src/judgemetrics/db/models/outcome_models.py
"""Fitted expected-outcome models (revision 0009, Phase 4 Step 2).

One ``outcome_model`` row per snapshot, source, specification version,
target, window, and seed (``uq_outcome_model_key``, ``NULLS NOT DISTINCT``
because the release target has no window): the fit's status (``fitted``,
``insufficient_events``, ``not_converged``; revision 0012 adds ``unavailable``,
a target the source cannot support, with its reason), the temporal split's
counts (``n_train``/``events_train`` before the cutoff, ``n_test``/``events_test``
at or after it; the published fit is over both), the training range and
the cutoff, the test-set diagnostics and the ten calibration bins
(``diagnostics``), and per design column the level, the estimate, the
bootstrap standard deviation, and the sign agreement (``coefficients``) —
so a model card is served from the database without reading an artifact.
``content_hash`` is the sha256 of the canonical JSON artifact written once
under ``<snapshot_dir>/<snapshot hash>/models/`` (``storage_uri``, never
returned by a public surface). No column holds a person-level value: the
design rows exist only inside a fit. The app role reads the table; the
ingest role writes it.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CHAR, BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import JSONBDict

# Revision 0012 adds `unavailable`: a target the source cannot support (it does not
# record the population's gate, observe the outcome, or key persons across cases),
# recorded with its reason in `diagnostics` instead of a fit.
OUTCOME_MODEL_STATUSES: tuple[str, ...] = (
    "fitted",
    "insufficient_events",
    "not_converged",
    "unavailable",
)


class OutcomeModel(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "outcome_model"
    __table_args__ = (
        Index(
            "uq_outcome_model_key",
            "snapshot_id",
            "source_id",
            "spec_version",
            "target",
            "window_days",
            "seed",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "status IN ('fitted', 'insufficient_events', 'not_converged', 'unavailable')",
            name="status",
        ),
    )

    # sha256 of the canonical artifact: its id.
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    spec_version: Mapped[int] = mapped_column(Integer, nullable=False)
    model_version: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[str] = mapped_column(Text, nullable=False)
    # Null for the release target (no window).
    window_days: Mapped[int | None] = mapped_column(Integer)
    seed: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    n_train: Mapped[int] = mapped_column(Integer, nullable=False)
    events_train: Mapped[int] = mapped_column(Integer, nullable=False)
    n_test: Mapped[int] = mapped_column(Integer, nullable=False)
    events_test: Mapped[int] = mapped_column(Integer, nullable=False)
    # The published fit's index-time range and the temporal cutoff (null without rows).
    train_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    train_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    split_cutoff: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    diagnostics: Mapped[dict[str, Any] | None] = mapped_column(JSONBDict)
    coefficients: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONBDict)
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    code_version: Mapped[str] = mapped_column(Text, nullable=False)
    fitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
