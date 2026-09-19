# src/judgemetrics/repositories/corrections.py
"""The corrections intake's two statements: the target lookup and the INSERT-only write.

``target_exists`` is one statement against the table the ``target_type``
names (``judge``, ``court``, ``court_case``, ``metric_observation``): the
API never reads ``correction_request``. ``insert_correction`` is an ORM
``INSERT`` with a client-generated id, ``status = received``, and no
``RETURNING`` — the app role holds ``INSERT`` on the table and nothing
else (revision 0007), and PostgreSQL requires ``SELECT`` on every column
a ``RETURNING`` clause names, so a returning insert would fail as the
API's role. The caller commits. Nothing in this module logs a submitted
field.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    Case,
    CorrectionRequest,
    CorrectionStatus,
    Court,
    Judge,
    MetricObservation,
)

TARGET_TABLES: dict[str, Any] = {
    "judge": Judge,
    "court": Court,
    "case": Case,
    "metric_observation": MetricObservation,
}


def target_exists(session: Session, target_type: str, target_id: uuid.UUID) -> bool:
    """Whether a row with ``target_id`` exists in the table ``target_type`` names: one statement."""
    model = TARGET_TABLES.get(target_type)
    if model is None:
        msg = f"unknown correction target type {target_type!r}"
        raise ValueError(msg)
    return session.execute(select(model.id).where(model.id == target_id)).first() is not None


def insert_correction(
    session: Session,
    *,
    correction_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    requester_contact: bytes,
    reason: str,
    supporting_material_path: str | None,
) -> None:
    """Insert the request with the given id; no ``RETURNING``; the caller commits."""
    session.execute(
        insert(CorrectionRequest).values(
            id=correction_id,
            target_type=target_type,
            target_id=target_id,
            requester_contact=requester_contact,
            reason=reason,
            supporting_material_path=supporting_material_path,
            status=CorrectionStatus.RECEIVED,
        )
    )
