# src/judgemetrics/db/models/persons.py
"""Person entities: person, person_identifier, justice_event.

``person`` is the internal resolved entity; public surfaces use only
``public_person_key``. ``person_identifier`` holds hashed (and optionally
encrypted) source identifiers and is never granted to the public API role.

Revision 0003: ``person.source_record_id`` (the artifact that created the
row; last-substantive-writer like the reference entities);
``uq_person_identifier_stable``, a partial unique index on
``(identifier_type, value_hash)`` for the stable source identifier kinds so
one participant id can belong to only one person (the deterministic
resolution key), while name and date-of-birth hashes may repeat across
persons; ``uq_person_identifier_person_type_hash`` so a rerun never
duplicates an identifier row of the same person; and the natural key of a
derived justice event, ``uq_justice_event_natural`` on
``(person_id, event_type, event_at, related_case_id)`` with
``NULLS NOT DISTINCT``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey


class Person(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "person"

    # Pseudonymous key shown publicly; unrelated to any source identifier.
    public_person_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # deterministic (stable source identifier), rule, probabilistic, review, merged
    resolution_status: Mapped[str] = mapped_column(String(32), nullable=False)
    resolution_confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    # The artifact whose participant row created the person.
    source_record_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("source_record.id", ondelete="RESTRICT"), index=True
    )

    identifiers: Mapped[list[PersonIdentifier]] = relationship(back_populates="person")
    justice_events: Mapped[list[JusticeEvent]] = relationship(back_populates="person")


class PersonIdentifier(UUIDPrimaryKey, Timestamps, Base):
    """Restricted: hashed source identifiers. Not readable by the app role."""

    __tablename__ = "person_identifier"
    __table_args__ = (
        # A stable source identifier belongs to exactly one person.
        Index(
            "uq_person_identifier_stable",
            "identifier_type",
            "value_hash",
            unique=True,
            postgresql_where=text("identifier_type IN ('source_participant_id')"),
        ),
        # One row per (person, kind, hash): the upsert key for identifier rows.
        Index(
            "uq_person_identifier_person_type_hash",
            "person_id",
            "identifier_type",
            "value_hash",
            unique=True,
        ),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id", ondelete="CASCADE"), nullable=False, index=True
    )
    identifier_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # sha256 of the normalized identifier plus a per-deployment pepper.
    value_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    encrypted_value: Mapped[bytes | None] = mapped_column(LargeBinary)
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    person: Mapped[Person] = relationship(back_populates="identifiers")


class JusticeEvent(UUIDPrimaryKey, Timestamps, Base):
    """Generalized subsequent event for longitudinal person timelines."""

    __tablename__ = "justice_event"
    __table_args__ = (
        Index(
            "uq_justice_event_natural",
            "person_id",
            "event_type",
            "event_at",
            "related_case_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    person_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("person.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # arrest / new_case / new_charge / conviction / fta / revocation / release / ...
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    related_case_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("court_case.id", ondelete="RESTRICT"), index=True
    )
    source_record_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_record.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    description: Mapped[str | None] = mapped_column(Text)

    person: Mapped[Person] = relationship(back_populates="justice_events")
