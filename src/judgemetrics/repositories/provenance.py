# src/judgemetrics/repositories/provenance.py
"""Source-record lookups behind the ``provenance`` blocks, and the synthetic flag.

Every canonical row points at a ``source_record``, which points at its
``source``; ``source.source_type = 'synthetic'`` is what labels a row as
demo data. ``with_source`` joins the two tables into a statement so a list
page or a detail carries the flag in the same round trip, and
``synthetic_flag`` is the labelled boolean column to select.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import Any, NamedTuple

from sqlalchemy import Label, Select, select
from sqlalchemy.orm import Mapped, Session

from judgemetrics.db.models import SYNTHETIC_SOURCE_TYPE, Source, SourceRecord


class ProvenanceRow(NamedTuple):
    """The public columns of a source record. ``raw_object_path`` is not selected at all."""

    source: str
    external_record_id: str | None
    retrieved_at: datetime
    raw_sha256: str
    parser_version: str
    ingest_run_id: uuid.UUID
    synthetic: bool


def synthetic_flag() -> Label[bool]:
    """``source.source_type = 'synthetic'``, for a statement that ``with_source`` joined."""
    return (Source.source_type == SYNTHETIC_SOURCE_TYPE).label("synthetic")


def with_source(stmt: Select[Any], source_record_id: Mapped[uuid.UUID]) -> Select[Any]:
    """Join the ``source_record`` and ``source`` behind ``source_record_id`` (both to-one)."""
    return stmt.join(SourceRecord, SourceRecord.id == source_record_id).join(
        Source, Source.id == SourceRecord.source_id
    )


def source_records(session: Session, record_ids: Iterable[uuid.UUID]) -> list[ProvenanceRow]:
    """One row per id, newest retrieval first, in one statement."""
    return list(source_records_by_id(session, record_ids).values())


def source_records_by_id(
    session: Session, record_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, ProvenanceRow]:
    """One row per id keyed by record id, newest retrieval first, in one statement."""
    ids = sorted(set(record_ids), key=str)
    if not ids:
        return {}
    stmt = (
        select(
            SourceRecord.id,
            Source.name,
            SourceRecord.external_record_id,
            SourceRecord.retrieved_at,
            SourceRecord.raw_sha256,
            SourceRecord.parser_version,
            SourceRecord.ingest_run_id,
            Source.source_type == SYNTHETIC_SOURCE_TYPE,
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .where(SourceRecord.id.in_(ids))
        .order_by(
            SourceRecord.retrieved_at.desc(), SourceRecord.external_record_id, SourceRecord.id
        )
    )
    rows: dict[uuid.UUID, ProvenanceRow] = {}
    for record_id, name, external, retrieved, sha, parser, run_id, synthetic in session.execute(
        stmt
    ).tuples():
        rows[record_id] = ProvenanceRow(
            name, external, retrieved, sha, parser, run_id, bool(synthetic)
        )
    return rows
