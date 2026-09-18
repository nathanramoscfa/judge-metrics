# src/judgemetrics/db/models/resolution.py
"""Entity resolution: candidate pairs with their features, decision, stage, and reviewer.

One row per ordered pair (``left_record_id < right_record_id``, enforced
by a check) per ``model_version`` (``uq_er_candidate_pair_version``, the
upsert key): the brief's auditability clause — features, model version,
score, disposition, timestamp, and reviewer — in columns. ``decided_by``
is ``system:<model version>`` for an automatic decision, the reviewer's
label for a human one, and NULL while a review item waits; a human
decision is never overwritten by a rerun (docs/ENTITY_RESOLUTION.md).
Restricted: the public API role has no privilege on the table.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import JSONBDict, pg_enum
from judgemetrics.db.models.enums import ResolutionDecision


class EntityResolutionCandidate(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "entity_resolution_candidate"
    __table_args__ = (
        Index(
            "ix_entity_resolution_candidate_pair",
            "entity_type",
            "left_record_id",
            "right_record_id",
        ),
        # One stored decision per pair per model version (revision 0004).
        Index(
            "uq_er_candidate_pair_version",
            "entity_type",
            "left_record_id",
            "right_record_id",
            "model_version",
            unique=True,
        ),
        CheckConstraint("left_record_id < right_record_id", name="ordered_pair"),
    )

    # judge / court / case / person: which canonical table the ids refer to.
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    left_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    right_record_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    match_probability: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    decision: Mapped[ResolutionDecision] = mapped_column(
        pg_enum(ResolutionDecision), nullable=False, default=ResolutionDecision.REVIEW
    )
    features: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    model_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # deterministic | rule | probabilistic | review: the stage that decided.
    stage: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decided_by: Mapped[str | None] = mapped_column(String(128))
    reason: Mapped[str | None] = mapped_column(Text)
    ingest_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ingest_run.id", ondelete="SET NULL"), index=True
    )
