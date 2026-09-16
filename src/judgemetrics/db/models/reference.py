# src/judgemetrics/db/models/reference.py
"""Reference entities: jurisdiction, court, judge, judge_service."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, Index, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import JSONBDict, pg_enum
from judgemetrics.db.models.enums import JurisdictionType


class Jurisdiction(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "jurisdiction"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[JurisdictionType] = mapped_column(pg_enum(JurisdictionType), nullable=False)
    state_code: Mapped[str | None] = mapped_column(String(2))
    fips_code: Mapped[str | None] = mapped_column(String(10))
    parent_jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jurisdiction.id", ondelete="RESTRICT"), index=True
    )

    parent: Mapped[Jurisdiction | None] = relationship(remote_side="Jurisdiction.id")
    courts: Mapped[list[Court]] = relationship(back_populates="jurisdiction")


class Court(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "court"
    __table_args__ = (
        # Trigram search on the display name (/api/v1/search) and JSONB
        # containment lookups on source identifiers.
        Index(
            "ix_court_canonical_name_trgm",
            "canonical_name",
            postgresql_using="gin",
            postgresql_ops={"canonical_name": "gin_trgm_ops"},
        ),
        Index("ix_court_external_ids", "external_ids", postgresql_using="gin"),
    )

    jurisdiction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("jurisdiction.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    court_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Source identifiers, e.g. {"fjc_court_name": "...", "courtlistener": "..."}.
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    active_from: Mapped[date | None] = mapped_column(Date)
    active_to: Mapped[date | None] = mapped_column(Date)

    jurisdiction: Mapped[Jurisdiction] = relationship(back_populates="courts")
    service_records: Mapped[list[JudgeService]] = relationship(back_populates="court")


class Judge(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "judge"
    __table_args__ = (
        Index(
            "ix_judge_normalized_name_trgm",
            "normalized_name",
            postgresql_using="gin",
            postgresql_ops={"normalized_name": "gin_trgm_ops"},
        ),
        Index("ix_judge_external_ids", "external_ids", postgresql_using="gin"),
        # One judge per FJC node id (docs/DATA_SOURCES.md `fjc`, key `nid`).
        Index(
            "uq_judge_external_ids_fjc_nid",
            text("(external_ids ->> 'fjc_nid')"),
            unique=True,
            postgresql_where=text("external_ids ? 'fjc_nid'"),
        ),
    )

    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_name: Mapped[str] = mapped_column(Text, nullable=False)
    # {"fjc_nid": "1234"}: the FJC node id is unique per judge (expression index).
    external_ids: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # Public biographical facts only (birth year, appointing president, ...).
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONBDict, nullable=False, default=dict, server_default="{}"
    )

    service_records: Mapped[list[JudgeService]] = relationship(back_populates="judge")


class JudgeService(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "judge_service"

    judge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("judge.id", ondelete="CASCADE"), nullable=False, index=True
    )
    court_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("court.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position_type: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    judge: Mapped[Judge] = relationship(back_populates="service_records")
    court: Mapped[Court] = relationship(back_populates="service_records")
