# src/judgemetrics/services/provenance.py
"""The ``provenance`` block: which raw artifacts a response is derived from."""

from __future__ import annotations

import uuid
from collections.abc import Iterable

from sqlalchemy.orm import Session

from judgemetrics.repositories.provenance import source_records
from judgemetrics.schemas.common import Provenance


def provenance_for(session: Session, record_ids: Iterable[uuid.UUID]) -> list[Provenance]:
    """One ``Provenance`` per distinct source record, newest retrieval first.

    The repository selects only the public columns, so the lake's internal
    storage key (``raw_object_path``) never reaches this layer.
    """
    return [Provenance(**row._asdict()) for row in source_records(session, record_ids)]
