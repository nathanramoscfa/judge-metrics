# src/judgemetrics/db/models/resolution.py
"""Entity resolution: candidate pairs with their features and decision."""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Index, Numeric, String
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
