# src/judgemetrics/db/models/cases.py
"""Case entities: court_case, case_party, judge_assignment, charge, court_event,
decision, pretrial_release, sentence.

The brief's ``case`` entity is stored in table ``court_case`` (``case`` is a
reserved word). Arrest, charge, decision, disposition, and sentence are
separate rows by design: an arrest never proves a crime, and a
prosecutor's dismissal is not a judicial dismissal (``actor_type``).

Revision 0003 gives every row that belongs to a case a ``source_row_id``
(the source's own identifier for that row) and the unique index
``uq_<table>_case_source_row`` on ``(case_id, source_row_id)``: the natural
key the ingest runner upserts on, so a re-export of the same row updates
in place and a rerun writes nothing. ``court_case`` keeps its baseline
natural key ``(court_id, case_number_normalized)`` and gains the normalized
number of a related case for Step 3's linkage feature.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from judgemetrics.db.base import Base, Timestamps, UUIDPrimaryKey
from judgemetrics.db.models._types import JSONBDict, pg_enum
from judgemetrics.db.models.enums import ActorType


def _fk(target: str, *, nullable: bool = False, ondelete: str = "RESTRICT") -> Any:
    return mapped_column(
        UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable, index=True
    )


def _source_row_index(table: str) -> Index:
    """The natural key of a row that belongs to a case: ``(case_id, source_row_id)``."""
    return Index(f"uq_{table}_case_source_row", "case_id", "source_row_id", unique=True)


def _source_row_id() -> Any:
    # The source's own identifier for the row (a charge id, an event id, …).
    return mapped_column(Text, nullable=False)


class Case(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "court_case"
    __table_args__ = (
        UniqueConstraint("court_id", "case_number_normalized", name="court_case_number"),
    )

    court_id: Mapped[uuid.UUID] = _fk("court.id")
    case_number: Mapped[str] = mapped_column(Text, nullable=False)
    case_number_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    case_type: Mapped[str] = mapped_column(String(64), nullable=False)
    filed_date: Mapped[date | None] = mapped_column(Date)
    closed_date: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    # A case the source links this one to (normalized number, same court
    # namespace): the linkage signal of the entity-resolution rule stage.
    related_case_number_normalized: Mapped[str | None] = mapped_column(Text, index=True)
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    parties: Mapped[list[CaseParty]] = relationship(back_populates="case")
    assignments: Mapped[list[JudgeAssignment]] = relationship(back_populates="case")
    charges: Mapped[list[Charge]] = relationship(back_populates="case")
    events: Mapped[list[CourtEvent]] = relationship(back_populates="case")
    decisions: Mapped[list[Decision]] = relationship(back_populates="case")
    sentences: Mapped[list[Sentence]] = relationship(back_populates="case")


class CaseParty(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "case_party"
    __table_args__ = (_source_row_index("case_party"),)

    case_id: Mapped[uuid.UUID] = _fk("court_case.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID | None] = _fk("person.id", nullable=True)
    party_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_party_label: Mapped[str | None] = mapped_column(Text)
    source_row_id: Mapped[str] = _source_row_id()
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    case: Mapped[Case] = relationship(back_populates="parties")


class JudgeAssignment(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "judge_assignment"
    __table_args__ = (_source_row_index("judge_assignment"),)

    case_id: Mapped[uuid.UUID] = _fk("court_case.id", ondelete="CASCADE")
    judge_id: Mapped[uuid.UUID] = _fk("judge.id")
    assignment_type: Mapped[str] = mapped_column(String(64), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))
    source_row_id: Mapped[str] = _source_row_id()
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    case: Mapped[Case] = relationship(back_populates="assignments")


class Charge(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "charge"
    __table_args__ = (_source_row_index("charge"),)

    case_id: Mapped[uuid.UUID] = _fk("court_case.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = _fk("person.id")
    statute_code: Mapped[str | None] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    offense_category: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(64), nullable=False)
    violent_flag: Mapped[bool | None] = mapped_column(Boolean)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    disposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disposition: Mapped[str | None] = mapped_column(String(64))
    # Who disposed of the charge (judge, prosecutor, jury, …): the
    # attribution the judicial-dismissal rule reads at charge level.
    disposition_actor: Mapped[ActorType | None] = mapped_column(pg_enum(ActorType))
    source_row_id: Mapped[str] = _source_row_id()
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    case: Mapped[Case] = relationship(back_populates="charges")


class CourtEvent(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "court_event"
    __table_args__ = (_source_row_index("court_event"),)

    case_id: Mapped[uuid.UUID] = _fk("court_case.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID | None] = _fk("person.id", nullable=True)
    judge_id: Mapped[uuid.UUID | None] = _fk("judge.id", nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    actor_type: Mapped[ActorType | None] = mapped_column(pg_enum(ActorType))
    source_row_id: Mapped[str] = _source_row_id()
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    case: Mapped[Case] = relationship(back_populates="events")


class Decision(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "decision"
    __table_args__ = (_source_row_index("decision"),)

    case_id: Mapped[uuid.UUID] = _fk("court_case.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = _fk("person.id")
    judge_id: Mapped[uuid.UUID | None] = _fk("judge.id", nullable=True)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    decision_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    decision_value: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    actor_type: Mapped[ActorType] = mapped_column(pg_enum(ActorType), nullable=False)
    # Outcome of the versioned attribution rule (discretionary / mandatory / ...).
    judicial_discretion_classification: Mapped[str] = mapped_column(String(64), nullable=False)
    source_row_id: Mapped[str] = _source_row_id()
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    case: Mapped[Case] = relationship(back_populates="decisions")
    pretrial_release: Mapped[PretrialRelease | None] = relationship(back_populates="decision")


class PretrialRelease(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "pretrial_release"

    decision_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("decision.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    release_type: Mapped[str] = mapped_column(String(64), nullable=False)
    bond_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    conditions: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    release_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detained_flag: Mapped[bool] = mapped_column(Boolean, nullable=False)

    decision: Mapped[Decision] = relationship(back_populates="pretrial_release")


class Sentence(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "sentence"
    __table_args__ = (_source_row_index("sentence"),)

    case_id: Mapped[uuid.UUID] = _fk("court_case.id", ondelete="CASCADE")
    person_id: Mapped[uuid.UUID] = _fk("person.id")
    judge_id: Mapped[uuid.UUID | None] = _fk("judge.id", nullable=True)
    sentence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    incarceration_days: Mapped[int | None] = mapped_column(Integer)
    probation_days: Mapped[int | None] = mapped_column(Integer)
    fine_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sentence_components: Mapped[dict[str, Any]] = mapped_column(
        JSONBDict, nullable=False, default=dict, server_default="{}"
    )
    source_row_id: Mapped[str] = _source_row_id()
    source_record_id: Mapped[uuid.UUID] = _fk("source_record.id")

    case: Mapped[Case] = relationship(back_populates="sentences")
