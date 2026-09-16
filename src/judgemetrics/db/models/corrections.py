# src/judgemetrics/db/models/corrections.py
"""Correction requests from the public.

``requester_contact`` is stored encrypted (Fernet, ``bytes``) under the
application-level key ``JUDGEMETRICS_CORRECTION_CONTACT_KEY`` — see
``judgemetrics.security.crypto``. The table is not readable by the public
API role; only admin tooling that answers corrections holds the key.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import pg_enum
from judgemetrics.db.models.enums import CorrectionStatus


class CorrectionRequest(UUIDPrimaryKey, Timestamps, Base):
    """Restricted: contains requester contact details. Not readable by the app role."""

    __tablename__ = "correction_request"

    # judge / court / case / metric_observation ...: what the request is about.
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False, index=True)
    requester_contact: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    supporting_material_path: Mapped[str | None] = mapped_column(Text)
    status: Mapped[CorrectionStatus] = mapped_column(
        pg_enum(CorrectionStatus), nullable=False, default=CorrectionStatus.RECEIVED
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
