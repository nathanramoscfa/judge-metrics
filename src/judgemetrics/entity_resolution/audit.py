# src/judgemetrics/entity_resolution/audit.py
"""Writing to the append-only ``audit_log``.

Every administrative and entity-resolution decision leaves one row:
who (an operator label or ``system:<model version>``), what (``action``),
on which entity, with a JSON payload of ids, counts, decisions, and
reasons — never a name, a date of birth, a hash, or a participant id.
The table's trigger (``audit_log_append_only``, revision 0004) rejects
``UPDATE`` and ``DELETE`` for every role, so a written row is history.
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base

AUDIT_LOG = Base.metadata.tables["audit_log"]

ACTION_MERGE = "er.merge"
ACTION_DECIDE = "er.decide"
ACTION_REJECT = "er.reject"
ENTITY_PERSON = "person"
ENTITY_CANDIDATE = "entity_resolution_candidate"


def write_audit(
    session: Session,
    *,
    actor: str,
    action: str,
    entity_type: str | None,
    entity_id: uuid.UUID | None,
    payload: dict[str, Any],
    request_id: str | None = None,
) -> uuid.UUID:
    """Append one row and return its id."""
    if not actor.strip():
        msg = "an audit row needs an actor"
        raise ValueError(msg)
    row_id = uuid.uuid4()
    session.execute(
        insert(AUDIT_LOG).values(
            id=row_id,
            actor=actor.strip(),
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
            request_id=request_id,
        )
    )
    return row_id
