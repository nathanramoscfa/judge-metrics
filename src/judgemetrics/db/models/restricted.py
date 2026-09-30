# src/judgemetrics/db/models/restricted.py
"""The ``restricted`` PostgreSQL schema (revision 0008, Phase 4 Step 1).

Restricted attributes of a case party — ``age_band`` and the synthetic
source's ``synthetic_group`` today, a real source's demographic fields from
Phase 5 — live here and nowhere else (ROADMAP.md "Data classification").
The schema grants ``USAGE`` to the ingest and admin roles only; the public
API's role ``judgemetrics_app`` holds no privilege on the schema or its
tables, so no public route, the snapshot, or a log line can reach them.
Values come from the vocabulary's restricted kinds
(``restricted_attribute`` names the attributes; ``age_band`` and
``synthetic_group`` list their values), are never a model feature, and are
read only by the aggregate fairness analysis (Phase 4 Step 4).

``party_attribute`` is one row per case party per attribute, upserted by
the ingest runner on ``(case_party_id, attribute)`` after the parties it
belongs to; a party's rows cascade with it.
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey

RESTRICTED_SCHEMA = "restricted"


class PartyAttribute(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "party_attribute"
    __table_args__ = (
        UniqueConstraint(
            "case_party_id", "attribute", name="uq_party_attribute_case_party_attribute"
        ),
        Index("ix_party_attribute_source_record_id", "source_record_id"),
        {"schema": RESTRICTED_SCHEMA},
    )

    case_party_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("case_party.id", ondelete="CASCADE"),
        nullable=False,
    )
    # A `restricted_attribute` vocabulary value, and a value of that kind.
    attribute: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_record.id", ondelete="RESTRICT"),
        nullable=False,
    )
