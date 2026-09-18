# src/judgemetrics/db/models/audit.py
"""The append-only ``audit_log``: every administrative and entity-resolution decision.

Rows are written by ``judgemetrics.entity_resolution.audit.write_audit``
and never changed: revision 0004 attaches ``audit_log_append_only()``,
a trigger that raises on ``UPDATE`` and ``DELETE`` for every role. The
public API role has no privilege on the table; the ingest role may insert
and read; ``payload`` carries ids, counts, decisions, and reasons — never
a restricted value.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from judgemetrics.db.base import Base
from judgemetrics.db.models._types import JSONBDict


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_occurred_at", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    # An operator label passed on the command line, or ``system:<model version>``.
    actor: Mapped[str] = mapped_column(String(128), nullable=False)
    # ``er.merge``, ``er.decide``, … (dotted, lower case).
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
