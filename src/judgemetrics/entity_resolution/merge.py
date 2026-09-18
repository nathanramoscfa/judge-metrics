# src/judgemetrics/entity_resolution/merge.py
"""Merging one person into another, and the filter public queries apply.

``merge_persons`` re-points every person-bearing row of ``drop`` to
``keep`` with bound-parameter Core updates — ``case_party``, ``charge``,
``court_event``, ``decision``, ``sentence``, ``justice_event``, and the
restricted ``person_identifier`` — respecting the natural-key unique
indexes: a justice event or identifier row that would collide with one
``keep`` already holds is deleted as a duplicate and counted. ``drop``
keeps its row with ``merged_into_person_id = keep`` and
``resolution_status = merged`` (its public key stops resolving); ``keep``
takes the deciding stage's status and confidence. One ``audit_log`` row
records the merge with the counts. A merge is applied only for a
``matched`` decision and is irreversible in this phase — Phase 6 adds
unmerge on top of the audit trail.

``unmerged()`` is the predicate every public query applies so a merged
person is never returned (Step 4's repositories use it).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy import CursorResult, select, update
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base
from judgemetrics.entity_resolution.audit import ACTION_MERGE, ENTITY_PERSON, write_audit
from judgemetrics.entity_resolution.config import STATUS_MERGED
from judgemetrics.ingest.base import IngestError

PERSON = Base.metadata.tables["person"]
PERSON_IDENTIFIER = Base.metadata.tables["person_identifier"]
JUSTICE_EVENT = Base.metadata.tables["justice_event"]
# Tables whose ``person_id`` column moves without any collision risk.
SIMPLE_TABLES: tuple[str, ...] = ("case_party", "charge", "court_event", "decision", "sentence")


class MergeError(IngestError):
    """The merge cannot be applied (same person, or a person already merged away)."""


@dataclass(slots=True)
class MergeResult:
    keep_id: uuid.UUID
    drop_id: uuid.UUID
    audit_id: uuid.UUID
    moved: dict[str, int] = field(default_factory=dict)
    dropped_duplicates: dict[str, int] = field(default_factory=dict)

    def as_payload(self) -> dict[str, Any]:
        return {
            "keep_person_id": str(self.keep_id),
            "drop_person_id": str(self.drop_id),
            "moved": dict(self.moved),
            "dropped_duplicates": dict(self.dropped_duplicates),
        }


def unmerged() -> sa.ColumnElement[bool]:
    """The predicate that hides merged persons from every public query."""
    return PERSON.c.merged_into_person_id.is_(None)


def canonical_person_id(session: Session, person_id: uuid.UUID) -> uuid.UUID:
    """Follow ``merged_into_person_id`` to the surviving person."""
    seen: set[uuid.UUID] = set()
    current = person_id
    while True:
        if current in seen:
            msg = f"merge cycle at person {current}"
            raise MergeError(msg)
        seen.add(current)
        target = session.execute(
            select(PERSON.c.merged_into_person_id).where(PERSON.c.id == current)
        ).scalar_one_or_none()
        if target is None:
            return current
        current = target


def merge_persons(
    session: Session,
    keep_id: uuid.UUID,
    drop_id: uuid.UUID,
    *,
    actor: str,
    reason: str,
    stage: str,
    confidence: float | Decimal | None,
    action: str = ACTION_MERGE,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> MergeResult:
    """Move every row of ``drop`` to ``keep``, mark ``drop`` merged, write one audit row."""
    if keep_id == drop_id:
        msg = "cannot merge a person into itself"
        raise MergeError(msg)
    rows = {
        row.id: row
        for row in session.execute(
            select(PERSON.c.id, PERSON.c.merged_into_person_id).where(
                PERSON.c.id.in_([keep_id, drop_id])
            )
        ).all()
    }
    if set(rows) != {keep_id, drop_id}:
        msg = "both persons must exist"
        raise MergeError(msg)
    for person_id, row in rows.items():
        if row.merged_into_person_id is not None:
            msg = f"person {person_id} is already merged"
            raise MergeError(msg)

    result = MergeResult(keep_id=keep_id, drop_id=drop_id, audit_id=uuid.uuid4())
    for name in SIMPLE_TABLES:
        table = Base.metadata.tables[name]
        outcome = cast(
            "CursorResult[Any]",
            session.execute(
                update(table).where(table.c.person_id == drop_id).values(person_id=keep_id)
            ),
        )
        result.moved[name] = int(outcome.rowcount)
    result.moved["justice_event"], result.dropped_duplicates["justice_event"] = _move_unique(
        session,
        JUSTICE_EVENT,
        keep_id,
        drop_id,
        key_columns=("event_type", "event_at", "related_case_id"),
    )
    result.moved["person_identifier"], result.dropped_duplicates["person_identifier"] = (
        _move_unique(
            session,
            PERSON_IDENTIFIER,
            keep_id,
            drop_id,
            key_columns=("identifier_type", "value_hash"),
        )
    )
    session.execute(
        update(PERSON)
        .where(PERSON.c.id == drop_id)
        .values(
            merged_into_person_id=keep_id,
            resolution_status=STATUS_MERGED,
            updated_at=sa.func.now(),
        )
    )
    session.execute(
        update(PERSON)
        .where(PERSON.c.id == keep_id)
        .values(
            resolution_status=stage,
            resolution_confidence=None if confidence is None else Decimal(str(confidence)),
            updated_at=sa.func.now(),
        )
    )
    audit_payload = {
        **result.as_payload(),
        "stage": stage,
        "confidence": None if confidence is None else float(confidence),
        "reason": reason,
        **(payload or {}),
    }
    result.audit_id = write_audit(
        session,
        actor=actor,
        action=action,
        entity_type=ENTITY_PERSON,
        entity_id=keep_id,
        payload=audit_payload,
        request_id=request_id,
    )
    return result


def _move_unique(
    session: Session,
    table: sa.Table,
    keep_id: uuid.UUID,
    drop_id: uuid.UUID,
    *,
    key_columns: tuple[str, ...],
) -> tuple[int, int]:
    """Move ``drop``'s rows whose natural key ``keep`` lacks; delete the ones it already has."""
    keep_keys = {
        tuple(row)
        for row in session.execute(
            select(*(table.c[column] for column in key_columns)).where(table.c.person_id == keep_id)
        ).all()
    }
    drop_rows = session.execute(
        select(table.c.id, *(table.c[column] for column in key_columns)).where(
            table.c.person_id == drop_id
        )
    ).all()
    duplicates = [row.id for row in drop_rows if tuple(row[1:]) in keep_keys]
    movable = [row.id for row in drop_rows if tuple(row[1:]) not in keep_keys]
    if duplicates:
        session.execute(sa.delete(table).where(table.c.id.in_(duplicates)))
    if movable:
        session.execute(update(table).where(table.c.id.in_(movable)).values(person_id=keep_id))
    return len(movable), len(duplicates)
