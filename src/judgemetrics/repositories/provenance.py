# src/judgemetrics/repositories/provenance.py
"""Source-record lookups behind the ``provenance`` blocks."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Source, SourceRecord


class ProvenanceRow(NamedTuple):
    """The public columns of a source record. ``raw_object_path`` is not selected at all."""

    source: str
    external_record_id: str | None
    retrieved_at: datetime
    raw_sha256: str
    parser_version: str
    ingest_run_id: uuid.UUID


def source_records(session: Session, record_ids: Iterable[uuid.UUID]) -> list[ProvenanceRow]:
    """One row per id, newest retrieval first, in one statement."""
    ids = sorted(set(record_ids), key=str)
    if not ids:
        return []
    stmt = (
        select(
            Source.name,
            SourceRecord.external_record_id,
            SourceRecord.retrieved_at,
            SourceRecord.raw_sha256,
            SourceRecord.parser_version,
            SourceRecord.ingest_run_id,
        )
        .join(Source, Source.id == SourceRecord.source_id)
        .where(SourceRecord.id.in_(ids))
        .order_by(
            SourceRecord.retrieved_at.desc(), SourceRecord.external_record_id, SourceRecord.id
        )
    )
    return [ProvenanceRow(*row) for row in session.execute(stmt).tuples()]
