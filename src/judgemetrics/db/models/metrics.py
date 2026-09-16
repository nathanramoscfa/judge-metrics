# src/judgemetrics/db/models/metrics.py
"""Metrics: versioned definitions and precomputed, suppressible observations.

Every observation carries numerator (``observed_count``), denominator
(``cohort_size``), period, a suppression flag for small cohorts, and the
methodology version, so a published number is never separated from what
it counts.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import pg_enum
from judgemetrics.db.models.enums import SubjectType


class MetricDefinition(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "metric_definition"
    __table_args__ = (UniqueConstraint("slug", "version", name="metric_definition_slug_version"),)

    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    numerator_definition: Mapped[str] = mapped_column(Text, nullable=False)
    denominator_definition: Mapped[str] = mapped_column(Text, nullable=False)
    eligibility_definition: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    observations: Mapped[list[MetricObservation]] = relationship(back_populates="definition")


class MetricObservation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "metric_observation"
    __table_args__ = (
        Index(
            "ix_metric_observation_subject_period",
            "metric_definition_id",
            "subject_type",
            "subject_id",
            "period_start",
        ),
    )

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_definition.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_type: Mapped[SubjectType] = mapped_column(pg_enum(SubjectType), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    cohort_size: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_count: Mapped[int] = mapped_column(Integer, nullable=False)
    expected_count: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    observed_rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    expected_rate: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    standardized_ratio: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    lower_confidence_bound: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    upper_confidence_bound: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    suppressed_flag: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    methodology_version: Mapped[str] = mapped_column(String(32), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    definition: Mapped[MetricDefinition] = relationship(back_populates="observations")
