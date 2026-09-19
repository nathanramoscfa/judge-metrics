# src/judgemetrics/db/models/metrics.py
"""Metrics: versioned definitions, snapshots, observations, and their members.

Every observation carries numerator (``observed_count``), denominator
(``cohort_size``), the cohort before the follow-up restriction
(``eligible_count``), period, window, dimension, a suppression flag for
small cohorts, and the methodology, registry, and code versions, so a
published number is never separated from what it counts. Revision 0005
(Phase 3 Step 1) adds the registry columns on ``metric_definition``
(``kind``, ``subject_types``, ``attribution``, ``index_event``,
``outcome``, ``windows_days``, ``dimension``, ``suppression_threshold``,
``unit``, ``registry_version``, ``methodology_version`` — mirrored from
``data/reference/metric_registry.yaml`` by ``metrics.registry.sync_definitions``),
``metric_snapshot`` (the hashed export every observation is computed from:
Step 2's ``metrics compute`` and ``metrics verify``), the snapshot, source,
window, dimension, eligible-count, value, distribution, version, and
``superseded_at`` columns on ``metric_observation`` with the unique key
``uq_metric_observation_key`` (``NULLS NOT DISTINCT``) and the partial
index over current observations, and ``metric_observation_member``: the
entity ids (never a person id) that formed an observation's denominator
and numerator — the provenance chain from a published number back to
canonical rows.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import JSONBDict, pg_enum
from judgemetrics.db.models.enums import SubjectType

# The canonical rows an observation member may point at (metric_observation_member.member_kind).
MEMBER_KINDS: tuple[str, ...] = (
    "decision",
    "charge",
    "court_case",
    "sentence",
    "court_event",
    "justice_event",
)


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
    # Registry columns (0005): count, share, windowed_rate, survival, distribution, median.
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    subject_types: Mapped[list[str]] = mapped_column(JSONBDict, nullable=False)
    # The structured inclusion rule: decision_type, actor_types, discretion, assignment_gate.
    attribution: Mapped[dict[str, Any]] = mapped_column(JSONBDict, nullable=False)
    index_event: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(Text)
    windows_days: Mapped[list[int] | None] = mapped_column(JSONBDict)
    dimension: Mapped[str | None] = mapped_column(Text)
    # The minimum denominator below which an observation is suppressed (0 for counts).
    suppression_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    unit: Mapped[str] = mapped_column(Text, nullable=False)
    registry_version: Mapped[int] = mapped_column(Integer, nullable=False)
    methodology_version: Mapped[str] = mapped_column(Text, nullable=False)

    observations: Mapped[list[MetricObservation]] = relationship(back_populates="definition")


class MetricSnapshot(UUIDPrimaryKey, Timestamps, Base):
    """One hashed export of the canonical tables that observations are computed from."""

    __tablename__ = "metric_snapshot"

    # sha256 over the sorted `table:sha256` lines of the export's manifest.
    content_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False, unique=True)
    label: Mapped[str | None] = mapped_column(Text)
    exported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    code_version: Mapped[str] = mapped_column(Text, nullable=False)
    registry_version: Mapped[int] = mapped_column(Integer, nullable=False)
    methodology_version: Mapped[str] = mapped_column(Text, nullable=False)
    # {"<table>": <rows>} and {"<source id>": {"coverage_start": …, "coverage_end": …}}.
    row_counts: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    coverage: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)

    observations: Mapped[list[MetricObservation]] = relationship(back_populates="snapshot")


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
        # One observation per definition, subject, source, period, window,
        # dimension value, and snapshot (0005).
        Index(
            "uq_metric_observation_key",
            "metric_definition_id",
            "subject_type",
            "subject_id",
            "source_id",
            "period_start",
            "period_end",
            "window_days",
            "dimension_value",
            "snapshot_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        # The current observations of a subject (the ones the API serves).
        Index(
            "ix_metric_observation_current",
            "subject_type",
            "subject_id",
            postgresql_where=text("superseded_at IS NULL"),
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
    # Revision 0005: the snapshot and source the observation was computed
    # from, its window and dimension, the cohort before the follow-up
    # restriction, a value (medians, in days), a distribution, the versions,
    # and when a recompute superseded it. Shares, fixed-window rates, and
    # Kaplan-Meier cumulative incidences live in `observed_rate` (six
    # decimals) with their interval in the two bounds (docs/DATA_MODEL.md).
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    window_days: Mapped[int | None] = mapped_column(Integer)
    dimension_value: Mapped[str | None] = mapped_column(Text)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    value: Mapped[Decimal | None] = mapped_column(Numeric(14, 4))
    distribution: Mapped[dict[str, Any] | None] = mapped_column(JSONBDict)
    code_version: Mapped[str] = mapped_column(Text, nullable=False)
    registry_version: Mapped[int] = mapped_column(Integer, nullable=False)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    definition: Mapped[MetricDefinition] = relationship(back_populates="observations")
    snapshot: Mapped[MetricSnapshot] = relationship(back_populates="observations")
    members: Mapped[list[MetricObservationMember]] = relationship(back_populates="observation")


class MetricObservationMember(Base):
    """A canonical row behind an observation: in its denominator or numerator.

    ``followed`` marks the denominator after censoring and ``counted`` the
    numerator. ``member_id`` is the id of a public case-level row (``member_kind`` names
    its table) — never a person id — so a published number traces to the
    decisions, charges, cases, sentences, court events, and justice events
    that formed it (the provenance chain of ROADMAP.md §5).
    """

    __tablename__ = "metric_observation_member"
    __table_args__ = (
        Index("ix_metric_observation_member_observation_id", "observation_id"),
        Index("ix_metric_observation_member_member", "member_kind", "member_id"),
        CheckConstraint(
            "member_kind IN ('decision', 'charge', 'court_case', 'sentence', "
            "'court_event', 'justice_event')",
            name="member_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(always=False), primary_key=True)
    observation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_observation.id", ondelete="CASCADE"),
        nullable=False,
    )
    member_kind: Mapped[str] = mapped_column(Text, nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # In the numerator; in the denominator after censoring.
    counted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    followed: Mapped[bool] = mapped_column(Boolean, nullable=False)

    observation: Mapped[MetricObservation] = relationship(back_populates="members")
