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
canonical rows. Revision 0013 (Phase 5 Step 6) replaces that table: the
members of one definition, subject, source, and snapshot are stored once, as a
member family (``metric_member_family`` and its rows, ``metric_member``), and
every observation of the family points at it (``member_family_id``) — each
observation's own members are a filter of the family's rows
(``judgemetrics.metrics.members``). Revision 0010 (Phase 4 Step 3) fills the reserved
``expected_count``, ``expected_rate``, and ``standardized_ratio`` for the
``observed_expected`` kind and adds ``outcome_model_id`` (the fitted model
an adjusted observation was computed with), ``pooling_weight``, and
``suppression_reason`` — set on every suppressed row of every kind and on
no other (two check constraints). Revision 0012 (Phase 5 Step 5) adds
``calendar_year`` (null for the whole coverage window; the year a calendar-year
observation covers, whose first and last days are then its period — checked)
to the observation and to its unique key, and ``coverage_statistic``: the
brief's six coverage statistics and the unknown-actor share per snapshot,
source, and scope (the source, a jurisdiction, a court) — aggregates only,
never a person or a case list.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
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
# Why a suppressed observation is withheld (metric_observation.suppression_reason, 0010).
SUPPRESSION_REASONS: tuple[str, ...] = (
    "below_threshold",
    "expected_below_minimum",
    "model_unavailable",
)
# coverage_statistic (0012): the scopes a statistic is computed over and its names.
COVERAGE_SCOPES: tuple[str, ...] = ("source", "jurisdiction", "court")
COVERAGE_STATISTICS: tuple[str, ...] = (
    "cases_with_identified_judge",
    "cases_with_final_disposition",
    "cases_with_person_resolution",
    "cases_with_adequate_follow_up",
    "cases_with_complete_charge_classification",
    "records_with_provenance",
    "unknown_actor_share",
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
        # dimension value, calendar year (0012), and snapshot (0005).
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
            "calendar_year",
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
        # 0010: a suppressed row names its reason, and only a suppressed row does.
        CheckConstraint(
            "suppression_reason IN ('below_threshold', 'expected_below_minimum', "
            "'model_unavailable')",
            name="suppression_reason",
        ),
        CheckConstraint(
            "(suppression_reason IS NOT NULL) = suppressed_flag",
            name="suppression_reason_flag",
        ),
        # 0012: a calendar-year observation's period is that year's first and last days.
        CheckConstraint(
            "calendar_year IS NULL OR (period_start = make_date(calendar_year, 1, 1) "
            "AND period_end = make_date(calendar_year, 12, 31))",
            name="calendar_year_period",
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
    # Revision 0010: an observed_expected observation's model (its artifact is the
    # coefficients the expected count and the interval were computed from), the
    # pooling weight E / (E + alpha), and why a suppressed row is withheld.
    outcome_model_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("outcome_model.id", ondelete="RESTRICT"), index=True
    )
    pooling_weight: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    suppression_reason: Mapped[str | None] = mapped_column(Text)
    # Revision 0012: the calendar year (UTC) a year observation covers; null for the
    # observation over the source's whole coverage window.
    calendar_year: Mapped[int | None] = mapped_column(SmallInteger)
    # Revision 0013: the member family the observation's members are a filter of; one family
    # serves every window, year, and dimension value of a definition, subject, and snapshot.
    member_family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_member_family.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    definition: Mapped[MetricDefinition] = relationship(back_populates="observations")
    snapshot: Mapped[MetricSnapshot] = relationship(back_populates="observations")
    family: Mapped[MetricMemberFamily] = relationship(back_populates="observations")


class MetricMemberFamily(UUIDPrimaryKey, Timestamps, Base):
    """The members behind every observation of one definition, subject, source, and snapshot.

    A family is content-addressed: ``members_hash`` is the sha256 over its member kind and
    canonical rows (``judgemetrics.metrics.members.MemberFamily.digest``), so the same
    members are stored once whoever computes them, an unchanged recompute finds its family
    instead of writing one, and a family is never rewritten — a changed one is a new row
    and the observations that cite the old one keep it (supersession is history). The rows
    are ``metric_member``. ``row_count`` is the rows stored and ``member_count`` the members
    they represent (the sum of the multiplicities). Public entity ids only.
    """

    __tablename__ = "metric_member_family"
    __table_args__ = (
        UniqueConstraint(
            "metric_definition_id",
            "subject_type",
            "subject_id",
            "source_id",
            "snapshot_id",
            "members_hash",
            name="uq_metric_member_family_key",
        ),
        CheckConstraint(
            "member_kind IN ('decision', 'charge', 'court_case', 'sentence', "
            "'court_event', 'justice_event')",
            name="member_kind",
        ),
        CheckConstraint("row_count >= 0 AND member_count >= row_count", name="counts"),
    )

    metric_definition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_definition.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subject_type: Mapped[SubjectType] = mapped_column(pg_enum(SubjectType), nullable=False)
    subject_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    member_kind: Mapped[str] = mapped_column(Text, nullable=False)
    members_hash: Mapped[str] = mapped_column(CHAR(64), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    member_count: Mapped[int] = mapped_column(Integer, nullable=False)

    observations: Mapped[list[MetricObservation]] = relationship(back_populates="family")
    members: Mapped[list[MetricMember]] = relationship(back_populates="family")


class MetricMember(Base):
    """A canonical row of a member family, with what is needed to cut it into observations.

    ``member_id`` is the id of a public case-level row (the family's ``member_kind`` names
    its table) — never a person id. ``anchor_year`` is the calendar year (UTC) of the row's
    anchor; ``dimension_value`` the dimension value the row belongs to or counts in;
    ``counted_mask`` and ``followed_mask`` carry the ``counted`` (numerator) and ``followed``
    (denominator after censoring) flags, bit ``i`` for the definition's ``i``-th window
    (bit 0 for a metric without windows); ``multiplicity`` how many identical rows this one
    stands for. ``ordinal`` is the row's place in the family's canonical order, which makes
    ``(family_id, ordinal)`` the key and a page of a family a range of it.
    """

    __tablename__ = "metric_member"
    __table_args__ = (
        CheckConstraint("multiplicity > 0", name="multiplicity"),
        CheckConstraint("counted_mask >= 0 AND followed_mask >= 0", name="masks"),
    )

    family_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_member_family.id", ondelete="CASCADE"),
        primary_key=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    member_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    anchor_year: Mapped[int | None] = mapped_column(SmallInteger)
    dimension_value: Mapped[str | None] = mapped_column(Text)
    counted_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    followed_mask: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    multiplicity: Mapped[int] = mapped_column(Integer, nullable=False)

    family: Mapped[MetricMemberFamily] = relationship(back_populates="members")


class CoverageStatistic(UUIDPrimaryKey, Timestamps, Base):
    """One coverage statistic of one snapshot, source, and scope (revision 0012).

    The brief's six coverage statistics and the unknown-actor share
    (``COVERAGE_STATISTICS``; defined in docs/METHODOLOGY.md "Coverage
    statistics" and computed by ``metrics.coverage`` on every compute), per
    source, per jurisdiction of the source's courts, and per court
    (``scope_type`` and ``scope_id``): a numerator, a denominator, and their
    share at six decimals (null without a denominator) under the methodology
    version that defined them. Aggregates only: no person id, no case list.
    The app role reads it; the ingest role writes it.
    """

    __tablename__ = "coverage_statistic"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_id",
            "source_id",
            "scope_type",
            "scope_id",
            "statistic",
            name="uq_coverage_statistic_key",
        ),
        CheckConstraint("scope_type IN ('source', 'jurisdiction', 'court')", name="scope_type"),
        CheckConstraint(
            "statistic IN ('cases_with_identified_judge', 'cases_with_final_disposition', "
            "'cases_with_person_resolution', 'cases_with_adequate_follow_up', "
            "'cases_with_complete_charge_classification', 'records_with_provenance', "
            "'unknown_actor_share')",
            name="statistic",
        ),
        CheckConstraint(
            "numerator >= 0 AND denominator >= numerator", name="numerator_denominator"
        ),
    )

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("metric_snapshot.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    scope_type: Mapped[str] = mapped_column(Text, nullable=False)
    scope_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    statistic: Mapped[str] = mapped_column(Text, nullable=False)
    numerator: Mapped[int] = mapped_column(Integer, nullable=False)
    denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    share: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    methodology_version: Mapped[str] = mapped_column(Text, nullable=False)
