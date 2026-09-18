# src/judgemetrics/db/models/provenance.py
"""Provenance entities: source, source_record, ingest_run, data_quality_issue.

Every canonical fact row points at a ``source_record`` (the raw artifact
it was parsed from: immutable object path plus sha256), and every source
record points at the ``ingest_run`` that fetched it, so
``judgemetrics provenance trace`` can walk from a published number back to
raw bytes.

A ``source_record`` is one retrieved artifact (one file, one hash): it is
unique on ``(source_id, external_record_id, raw_sha256)``, which is what
makes reruns idempotent — an unchanged artifact maps to the existing
record and is not parsed again.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import JSONBDict, pg_enum
from judgemetrics.db.models.enums import IngestRunStatus, IssueSeverity, IssueStatus

# The ``source.source_type`` of the in-repo generator (docs/DATA_SOURCES.md
# ``synthetic``): the ingest runner refuses it in production and the API
# labels every row derived from it.
SYNTHETIC_SOURCE_TYPE = "synthetic"


class Source(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "source"

    # The register key from docs/DATA_SOURCES.md (fjc, synthetic, ...).
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    owner: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(64), nullable=False)
    jurisdiction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("jurisdiction.id", ondelete="RESTRICT"), index=True
    )
    access_method: Mapped[str] = mapped_column(String(64), nullable=False)
    terms_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )

    records: Mapped[list[SourceRecord]] = relationship(back_populates="source")
    runs: Mapped[list[IngestRun]] = relationship(back_populates="source")


class IngestRun(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "ingest_run"

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[IngestRunStatus] = mapped_column(pg_enum(IngestRunStatus), nullable=False)
    # Source rows parsed; canonical rows inserted; canonical rows whose
    # substantive columns changed; source rows that could not be normalized
    # or resolved (each rejection also leaves a data_quality_issue).
    records_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    records_rejected: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Git SHA of the connector code that produced the run, and the
    # connector's own parser version.
    code_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Incremental state returned by a checkpointing connector after a
    # successful run; handed back to the connector at the next run.
    checkpoint: Mapped[dict[str, Any] | None] = mapped_column(JSONBDict)
    # Why a run ended `failed` or `refused` (never a raw row or a secret).
    failure_reason: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="runs")
    records: Mapped[list[SourceRecord]] = relationship(back_populates="ingest_run")


class SourceRecord(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "source_record"
    __table_args__ = (
        # One record per retrieved artifact per content hash.
        Index(
            "uq_source_record_source_external_sha256",
            "source_id",
            "external_record_id",
            "raw_sha256",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    external_record_id: Mapped[str | None] = mapped_column(Text, index=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Immutable object in the raw lake (never overwritten) and its digest.
    raw_object_path: Mapped[str] = mapped_column(Text, nullable=False)
    raw_sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    ingest_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ingest_run.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    # Retrieval facts with no column of their own: the artifact URI, the
    # export page, and the HTTP validators (etag, last_modified) that the
    # next run sends as If-None-Match / If-Modified-Since.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONBDict, nullable=False, default=dict, server_default="{}"
    )

    source: Mapped[Source] = relationship(back_populates="records")
    ingest_run: Mapped[IngestRun] = relationship(back_populates="records")


class DataQualityIssue(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "data_quality_issue"

    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_record.id", ondelete="RESTRICT"), index=True
    )
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    severity: Mapped[IssueSeverity] = mapped_column(pg_enum(IssueSeverity), nullable=False)
    issue_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[IssueStatus] = mapped_column(
        pg_enum(IssueStatus), nullable=False, default=IssueStatus.OPEN
    )
