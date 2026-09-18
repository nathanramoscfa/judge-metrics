# src/judgemetrics/ingest/publish.py
"""Step 12 for the case-level tables: batched ``INSERT … ON CONFLICT DO UPDATE`` upserts.

Every publisher follows the Phase 1 rule: rows are inserted in batches
under the PostgreSQL bind-parameter limit, conflicts arbitrate on the
table's natural-key index, and the update fires only when a substantive
column ``IS DISTINCT FROM`` the incoming value, so a rerun over unchanged
files writes nothing (no ``updated_at`` bump, no provenance change) and
``records_created = records_updated = 0``. ``source_record_id`` moves to
the newer artifact only when that artifact changed the row.

Order (dependencies first): persons and their identifier rows → cases →
parties → assignments → charges → court events → decisions and their
pretrial-release children → sentences → justice events. The runner
(``judgemetrics.ingest.runner``) resolves the drafts and calls these in
that order; each returns the ids of the rows it touched by natural key
so issues can be linked to entities.

Persons: a new person gets ``public_person_key = secrets.token_urlsafe(12)``
exactly once, at insert; the key is never in an update set, so nothing a
later run does can rewrite a public pseudonym. Identifier rows are
inserted with ``ON CONFLICT DO NOTHING`` (their natural key is
``(person_id, identifier_type, value_hash)``) and hold hashes only.
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base
from judgemetrics.ingest.base import (
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtEventDraft,
    DecisionDraft,
    IngestError,
    JudgeAssignmentDraft,
    JusticeEventDraft,
    NaturalKey,
    PersonDraft,
    SentenceDraft,
    TaggedRecord,
)

# Rows per INSERT statement: the widest table (decision, 14 columns) stays
# far below PostgreSQL's 65,535 bind parameters.
BATCH_SIZE = 500
PUBLIC_KEY_BYTES = 12
RESOLUTION_DETERMINISTIC = "deterministic"
LOG_LABELS = {"person_identifier": "identifier_hashes"}
DETERMINISTIC_CONFIDENCE = Decimal("1.0000")

PERSON = Base.metadata.tables["person"]
PERSON_IDENTIFIER = Base.metadata.tables["person_identifier"]
COURT_CASE = Base.metadata.tables["court_case"]
CASE_PARTY = Base.metadata.tables["case_party"]
JUDGE_ASSIGNMENT = Base.metadata.tables["judge_assignment"]
CHARGE = Base.metadata.tables["charge"]
COURT_EVENT = Base.metadata.tables["court_event"]
DECISION = Base.metadata.tables["decision"]
PRETRIAL_RELEASE = Base.metadata.tables["pretrial_release"]
SENTENCE = Base.metadata.tables["sentence"]
JUSTICE_EVENT = Base.metadata.tables["justice_event"]

_INSERTED = sa.literal_column("(xmax = 0)", type_=sa.Boolean).label("inserted")

IdMap = dict[NaturalKey, uuid.UUID]


class PublishError(IngestError):
    """A draft reached the publish step without the ids it depends on (a runner defect)."""


@dataclass(slots=True)
class TableCounts:
    created: int = 0
    updated: int = 0


@dataclass(slots=True)
class RunCounts:
    """The run's statistics: totals for ``ingest_run`` and a breakdown per table."""

    seen: int = 0
    created: int = 0
    updated: int = 0
    rejected: int = 0
    tables: dict[str, TableCounts] = field(default_factory=dict)

    def add(self, table: str, *, created: int, updated: int) -> None:
        entry = self.tables.setdefault(table, TableCounts())
        entry.created += created
        entry.updated += updated
        self.created += created
        self.updated += updated

    def by_table(self) -> dict[str, dict[str, int]]:
        """Counts per table for the run log.

        The restricted table is reported under ``identifier_hashes``: its
        real name contains ``person_id``, which the log scrubber redacts,
        and a row count is not sensitive.
        """
        return {
            LOG_LABELS.get(table, table): {"created": entry.created, "updated": entry.updated}
            for table, entry in sorted(self.tables.items())
        }


def provenance_id(item: TaggedRecord) -> uuid.UUID:
    if item.provenance is None:
        msg = f"{item.record.natural_key}: cannot publish a draft without provenance"
        raise PublishError(msg)
    return item.provenance.source_record_id


def record_as[R](kind: type[R], item: TaggedRecord) -> R:
    if not isinstance(item.record, kind):
        msg = f"expected a {kind.__name__}, got {type(item.record).__name__}"
        raise PublishError(msg)
    return item.record


def _batches[T](rows: Sequence[T]) -> Iterable[Sequence[T]]:
    for start in range(0, len(rows), BATCH_SIZE):
        yield rows[start : start + BATCH_SIZE]


def _count(result: sa.Result[Any], counts: RunCounts, table: str) -> None:
    rows = result.all()
    created = sum(1 for row in rows if row.inserted)
    counts.add(table, created=created, updated=len(rows) - created)


def _require(ids: IdMap, key: NaturalKey | None, what: str) -> uuid.UUID:
    if key is None or key not in ids:
        msg = f"{what} {key} was not resolved before publishing"
        raise PublishError(msg)
    return ids[key]


def _optional(ids: IdMap, key: NaturalKey | None, what: str) -> uuid.UUID | None:
    return None if key is None else _require(ids, key, what)


def utc_iso(value: datetime) -> str:
    """The instant in UTC ISO 8601 — the form natural keys use for timestamps."""
    return value.astimezone(UTC).isoformat()


def upsert_rows(
    session: Session,
    table: sa.Table,
    rows: Sequence[dict[str, Any]],
    *,
    conflict: Sequence[Any],
    compare: Sequence[str],
    counts: RunCounts,
    index_where: Any = None,
) -> None:
    """Batched upsert on ``conflict``, updating ``compare`` (and provenance) only when changed."""
    if not rows:
        return
    has_provenance = "source_record_id" in table.c
    for batch in _batches(rows):
        stmt = insert(table).values(list(batch))
        excluded = stmt.excluded
        set_: dict[str, Any] = {column: excluded[column] for column in compare}
        if has_provenance:
            set_["source_record_id"] = excluded.source_record_id
        set_["updated_at"] = sa.func.now()
        upsert = stmt.on_conflict_do_update(
            index_elements=list(conflict),
            index_where=index_where,
            set_=set_,
            where=sa.or_(
                *(table.c[column].is_distinct_from(excluded[column]) for column in compare)
            ),
        ).returning(table.c.id, _INSERTED)
        _count(session.execute(upsert), counts, table.name)


# --- persons ------------------------------------------------------------------------


def upsert_persons(
    session: Session,
    new_items: Sequence[TaggedRecord],
    existing_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    """Insert the persons the resolution step found no row for; add identifier rows for all.

    Returns the ids of every person the run touched (existing and new) by
    natural key.
    """
    ids: IdMap = dict(existing_ids)
    person_rows: list[dict[str, Any]] = []
    for item in new_items:
        draft = record_as(PersonDraft, item)
        person_id = uuid.uuid4()
        ids[draft.natural_key] = person_id
        person_rows.append(
            {
                "id": person_id,
                "public_person_key": secrets.token_urlsafe(PUBLIC_KEY_BYTES),
                "resolution_status": RESOLUTION_DETERMINISTIC,
                "resolution_confidence": DETERMINISTIC_CONFIDENCE,
                "source_record_id": provenance_id(item),
            }
        )
    for batch in _batches(person_rows):
        result = session.execute(insert(PERSON).values(list(batch)).returning(PERSON.c.id))
        counts.add(PERSON.name, created=len(result.all()), updated=0)
    return ids


def upsert_person_identifiers(
    session: Session, items: Sequence[TaggedRecord], person_ids: IdMap, counts: RunCounts
) -> None:
    """One identifier row per (person, kind, hash); existing rows are left untouched."""
    rows: list[dict[str, Any]] = []
    seen: set[tuple[uuid.UUID, str, str]] = set()
    for item in items:
        draft = record_as(PersonDraft, item)
        person_id = _require(person_ids, draft.natural_key, "person")
        for kind, value_hash in sorted(draft.identifier_hashes.items()):
            signature = (person_id, kind, value_hash)
            if signature in seen:
                continue
            seen.add(signature)
            rows.append(
                {
                    "id": uuid.uuid4(),
                    "person_id": person_id,
                    "identifier_type": kind,
                    "value_hash": value_hash,
                    "encrypted_value": None,
                    "source_record_id": provenance_id(item),
                }
            )
    for batch in _batches(rows):
        stmt = insert(PERSON_IDENTIFIER).values(list(batch))
        result = session.execute(stmt.on_conflict_do_nothing().returning(PERSON_IDENTIFIER.c.id))
        counts.add(PERSON_IDENTIFIER.name, created=len(result.all()), updated=0)


# --- cases --------------------------------------------------------------------------


def upsert_cases(
    session: Session, items: Sequence[TaggedRecord], court_ids: IdMap, counts: RunCounts
) -> IdMap:
    rows: list[dict[str, Any]] = []
    for item in items:
        draft = record_as(CaseDraft, item)
        rows.append(
            {
                "id": uuid.uuid4(),
                "court_id": _require(court_ids, draft.court_key, "court"),
                "case_number": draft.case_number,
                "case_number_normalized": draft.case_number_normalized,
                "case_type": draft.case_type,
                "filed_date": draft.filed_date,
                "closed_date": draft.closed_date,
                "status": draft.status,
                "related_case_number_normalized": draft.related_case_number_normalized,
                "source_record_id": provenance_id(item),
            }
        )
    upsert_rows(
        session,
        COURT_CASE,
        rows,
        conflict=[COURT_CASE.c.court_id, COURT_CASE.c.case_number_normalized],
        compare=[
            "case_number",
            "case_type",
            "filed_date",
            "closed_date",
            "status",
            "related_case_number_normalized",
        ],
        counts=counts,
    )
    return lookup_cases(
        session, [record_as(CaseDraft, item).natural_key for item in items], court_ids
    )


def lookup_cases(session: Session, keys: Iterable[NaturalKey], court_ids: IdMap) -> IdMap:
    """Ids of the cases with these keys (``("case", court name, court type, normalized)``)."""
    wanted = set(keys)
    if not wanted:
        return {}
    court_keys_by_id = {value: key for key, value in court_ids.items()}
    by_court: dict[uuid.UUID, set[str]] = {}
    for key in wanted:
        if len(key) != 4:
            continue
        court_id = court_ids.get(("court", key[1], key[2]))
        if court_id is not None:
            by_court.setdefault(court_id, set()).add(key[3])
    if not by_court:
        return {}
    rows = session.execute(
        select(COURT_CASE.c.id, COURT_CASE.c.court_id, COURT_CASE.c.case_number_normalized).where(
            COURT_CASE.c.court_id.in_(by_court)
        )
    ).all()
    found: IdMap = {}
    for row_id, court_id, normalized in rows:
        court_key = court_keys_by_id.get(court_id)
        if court_key is None:
            continue
        key = ("case", *court_key[1:], normalized)
        if key in wanted:
            found[key] = row_id
    return found


# --- rows that belong to a case -------------------------------------------------------


def _source_row_ids(
    session: Session, table: sa.Table, keys: Iterable[NaturalKey], case_ids: IdMap
) -> IdMap:
    """Ids by ``("<table>", *case_key[1:], source_row_id)`` for the cases involved."""
    wanted = set(keys)
    if not wanted:
        return {}
    case_keys_by_id = {value: key for key, value in case_ids.items()}
    involved = {
        case_ids[("case", *key[1:-1])] for key in wanted if ("case", *key[1:-1]) in case_ids
    }
    if not involved:
        return {}
    rows = session.execute(
        select(table.c.id, table.c.case_id, table.c.source_row_id).where(
            table.c.case_id.in_(involved)
        )
    ).all()
    found: IdMap = {}
    for row_id, case_id, source_row_id in rows:
        case_key = case_keys_by_id.get(case_id)
        if case_key is None:
            continue
        key = (table.name, *case_key[1:], source_row_id)
        if key in wanted:
            found[key] = row_id
    return found


def _case_rows(
    table: sa.Table,
    items: Sequence[TaggedRecord],
    build: Any,
    counts: RunCounts,
    session: Session,
    compare: Sequence[str],
    case_ids: IdMap,
) -> IdMap:
    rows = [build(item) for item in items]
    upsert_rows(
        session,
        table,
        rows,
        conflict=[table.c.case_id, table.c.source_row_id],
        compare=compare,
        counts=counts,
    )
    return _source_row_ids(session, table, [item.record.natural_key for item in items], case_ids)


def upsert_parties(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    person_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    def build(item: TaggedRecord) -> dict[str, Any]:
        draft = record_as(CasePartyDraft, item)
        return {
            "id": uuid.uuid4(),
            "case_id": _require(case_ids, draft.case_key, "case"),
            "person_id": _optional(person_ids, draft.person_key, "person"),
            "party_type": draft.party_type,
            "source_party_label": draft.source_party_label,
            "source_row_id": draft.source_row_id,
            "source_record_id": provenance_id(item),
        }

    return _case_rows(
        CASE_PARTY,
        items,
        build,
        counts,
        session,
        ["person_id", "party_type", "source_party_label"],
        case_ids,
    )


def upsert_assignments(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    judge_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    def build(item: TaggedRecord) -> dict[str, Any]:
        draft = record_as(JudgeAssignmentDraft, item)
        return {
            "id": uuid.uuid4(),
            "case_id": _require(case_ids, draft.case_key, "case"),
            "judge_id": _require(judge_ids, draft.judge_key, "judge"),
            "assignment_type": draft.assignment_type,
            "start_at": draft.start_at,
            "end_at": draft.end_at,
            "confidence": draft.confidence,
            "source_row_id": draft.source_row_id,
            "source_record_id": provenance_id(item),
        }

    return _case_rows(
        JUDGE_ASSIGNMENT,
        items,
        build,
        counts,
        session,
        ["judge_id", "assignment_type", "start_at", "end_at", "confidence"],
        case_ids,
    )


def upsert_charges(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    person_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    def build(item: TaggedRecord) -> dict[str, Any]:
        draft = record_as(ChargeDraft, item)
        return {
            "id": uuid.uuid4(),
            "case_id": _require(case_ids, draft.case_key, "case"),
            "person_id": _require(person_ids, draft.person_key, "person"),
            "statute_code": draft.statute_code,
            "description": draft.description,
            "offense_category": draft.offense_category,
            "severity": draft.severity,
            "violent_flag": draft.violent_flag,
            "filed_at": draft.filed_at,
            "disposed_at": draft.disposed_at,
            "disposition": draft.disposition,
            "disposition_actor": draft.disposition_actor,
            "source_row_id": draft.source_row_id,
            "source_record_id": provenance_id(item),
        }

    return _case_rows(
        CHARGE,
        items,
        build,
        counts,
        session,
        [
            "person_id",
            "statute_code",
            "description",
            "offense_category",
            "severity",
            "violent_flag",
            "filed_at",
            "disposed_at",
            "disposition",
            "disposition_actor",
        ],
        case_ids,
    )


def upsert_events(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    person_ids: IdMap,
    judge_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    def build(item: TaggedRecord) -> dict[str, Any]:
        draft = record_as(CourtEventDraft, item)
        return {
            "id": uuid.uuid4(),
            "case_id": _require(case_ids, draft.case_key, "case"),
            "person_id": _optional(person_ids, draft.person_key, "person"),
            "judge_id": _optional(judge_ids, draft.judge_key, "judge"),
            "event_type": draft.event_type,
            "event_at": draft.event_at,
            "description": draft.description,
            "actor_type": draft.actor_type,
            "source_row_id": draft.source_row_id,
            "source_record_id": provenance_id(item),
        }

    return _case_rows(
        COURT_EVENT,
        items,
        build,
        counts,
        session,
        ["person_id", "judge_id", "event_type", "event_at", "description", "actor_type"],
        case_ids,
    )


def upsert_decisions(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    person_ids: IdMap,
    judge_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    """Decisions, then the pretrial-release child of every decision that carries one."""

    def build(item: TaggedRecord) -> dict[str, Any]:
        draft = record_as(DecisionDraft, item)
        return {
            "id": uuid.uuid4(),
            "case_id": _require(case_ids, draft.case_key, "case"),
            "person_id": _require(person_ids, draft.person_key, "person"),
            "judge_id": _optional(judge_ids, draft.judge_key, "judge"),
            "decision_type": draft.decision_type,
            "decision_at": draft.decision_at,
            "decision_value": dict(draft.decision_value),
            "actor_type": draft.actor_type,
            "judicial_discretion_classification": draft.judicial_discretion_classification,
            "source_row_id": draft.source_row_id,
            "source_record_id": provenance_id(item),
        }

    decision_ids = _case_rows(
        DECISION,
        items,
        build,
        counts,
        session,
        [
            "person_id",
            "judge_id",
            "decision_type",
            "decision_at",
            "decision_value",
            "actor_type",
            "judicial_discretion_classification",
        ],
        case_ids,
    )
    pretrial_rows: list[dict[str, Any]] = []
    for item in items:
        draft = record_as(DecisionDraft, item)
        if draft.pretrial is None:
            continue
        pretrial_rows.append(
            {
                "id": uuid.uuid4(),
                "decision_id": _require(decision_ids, draft.natural_key, "decision"),
                "release_type": draft.pretrial.release_type,
                "bond_amount": draft.pretrial.bond_amount,
                "conditions": dict(draft.pretrial.conditions),
                "release_at": draft.pretrial.release_at,
                "detained_flag": draft.pretrial.detained_flag,
            }
        )
    upsert_rows(
        session,
        PRETRIAL_RELEASE,
        pretrial_rows,
        conflict=[PRETRIAL_RELEASE.c.decision_id],
        compare=["release_type", "bond_amount", "conditions", "release_at", "detained_flag"],
        counts=counts,
    )
    return decision_ids


def upsert_sentences(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    person_ids: IdMap,
    judge_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    def build(item: TaggedRecord) -> dict[str, Any]:
        draft = record_as(SentenceDraft, item)
        return {
            "id": uuid.uuid4(),
            "case_id": _require(case_ids, draft.case_key, "case"),
            "person_id": _require(person_ids, draft.person_key, "person"),
            "judge_id": _optional(judge_ids, draft.judge_key, "judge"),
            "sentence_at": draft.sentence_at,
            "incarceration_days": draft.incarceration_days,
            "probation_days": draft.probation_days,
            "fine_amount": draft.fine_amount,
            "sentence_components": dict(draft.components),
            "source_row_id": draft.source_row_id,
            "source_record_id": provenance_id(item),
        }

    return _case_rows(
        SENTENCE,
        items,
        build,
        counts,
        session,
        [
            "person_id",
            "judge_id",
            "sentence_at",
            "incarceration_days",
            "probation_days",
            "fine_amount",
            "sentence_components",
        ],
        case_ids,
    )


# --- justice events --------------------------------------------------------------------


def upsert_justice_events(
    session: Session,
    items: Sequence[TaggedRecord],
    case_ids: IdMap,
    person_ids: IdMap,
    counts: RunCounts,
) -> IdMap:
    rows: list[dict[str, Any]] = []
    for item in items:
        draft = record_as(JusticeEventDraft, item)
        rows.append(
            {
                "id": uuid.uuid4(),
                "person_id": _require(person_ids, draft.person_key, "person"),
                "event_type": draft.event_type,
                "event_at": draft.event_at,
                "related_case_id": _optional(case_ids, draft.related_case_key, "case"),
                "description": draft.description,
                "confidence": draft.confidence,
                "source_record_id": provenance_id(item),
            }
        )
    upsert_rows(
        session,
        JUSTICE_EVENT,
        rows,
        conflict=[
            JUSTICE_EVENT.c.person_id,
            JUSTICE_EVENT.c.event_type,
            JUSTICE_EVENT.c.event_at,
            JUSTICE_EVENT.c.related_case_id,
        ],
        compare=["description", "confidence"],
        counts=counts,
    )
    wanted = {item.record.natural_key for item in items}
    involved = {row["person_id"] for row in rows}
    if not involved:
        return {}
    person_keys_by_id = {value: key for key, value in person_ids.items()}
    case_keys_by_id = {value: key for key, value in case_ids.items()}
    lookup = session.execute(
        select(
            JUSTICE_EVENT.c.id,
            JUSTICE_EVENT.c.person_id,
            JUSTICE_EVENT.c.event_type,
            JUSTICE_EVENT.c.event_at,
            JUSTICE_EVENT.c.related_case_id,
        ).where(JUSTICE_EVENT.c.person_id.in_(involved))
    ).all()
    found: IdMap = {}
    for row_id, person_id, event_type, event_at, related_case_id in lookup:
        person_key = person_keys_by_id.get(person_id)
        if person_key is None:
            continue
        related = case_keys_by_id.get(related_case_id) if related_case_id else None
        key = (
            "justice_event",
            *person_key[1:],
            event_type,
            utc_iso(event_at),
            *(related[1:] if related else ()),
        )
        if key in wanted:
            found[key] = row_id
    return found
