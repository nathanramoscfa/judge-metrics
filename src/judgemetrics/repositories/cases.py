# src/judgemetrics/repositories/cases.py
"""Case queries: everything a case contains, and a judge's cases.

``load_case`` reads a case and every row that belongs to it in one
statement per table — the case with its court and synthetic flag, then
parties, assignments, charges, events, decisions (with their pretrial
release), sentences, and finally the distinct source records behind all
of them — eight statements whatever the case holds, so the detail and the
timeline are both assembled by the service from this one load. Each
person join applies ``entity_resolution.merge.unmerged()``: a merged
person's key is never read, and a row whose person was merged away
(which the merge re-points, so it should not exist) shows no key.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    Case,
    CaseParty,
    Charge,
    Court,
    CourtEvent,
    Decision,
    Judge,
    JudgeAssignment,
    Person,
    PretrialRelease,
    Sentence,
)
from judgemetrics.entity_resolution.merge import unmerged
from judgemetrics.repositories.common import MAX_LIMIT
from judgemetrics.repositories.provenance import (
    ProvenanceRow,
    source_records_by_id,
    synthetic_flag,
    with_source,
)


@dataclass(slots=True)
class CaseRows:
    """One case and every row that belongs to it, with the joins each row needs."""

    case: Case
    court: Court
    synthetic: bool
    # (party, the person's public key — None when no unmerged person is attached)
    parties: list[tuple[CaseParty, str | None]] = field(default_factory=list)
    assignments: list[tuple[JudgeAssignment, Judge]] = field(default_factory=list)
    charges: list[Charge] = field(default_factory=list)
    events: list[tuple[CourtEvent, Judge | None]] = field(default_factory=list)
    # (decision, its pretrial release if any, the deciding judge if any, the person's key)
    decisions: list[tuple[Decision, PretrialRelease | None, Judge | None, str | None]] = field(
        default_factory=list
    )
    sentences: list[tuple[Sentence, Judge | None]] = field(default_factory=list)
    # The artifacts behind the case and every row above, by source record id.
    provenance: dict[uuid.UUID, ProvenanceRow] = field(default_factory=dict)


def load_case(session: Session, case_id: uuid.UUID) -> CaseRows | None:
    """The case and all of its rows, or ``None`` when no case has that id."""
    head = (
        with_source(select(Case, Court, synthetic_flag()), Case.source_record_id)
        .join(Court, Court.id == Case.court_id)
        .where(Case.id == case_id)
    )
    found = session.execute(head).one_or_none()
    if found is None:
        return None
    rows = CaseRows(case=found[0], court=found[1], synthetic=bool(found[2]))

    unmerged_person = and_(Person.id == CaseParty.person_id, unmerged())
    rows.parties = [
        (party, key)
        for party, key in session.execute(
            select(CaseParty, Person.public_person_key)
            .outerjoin(Person, unmerged_person)
            .where(CaseParty.case_id == case_id)
            .order_by(CaseParty.party_type, CaseParty.source_row_id)
        ).tuples()
    ]
    rows.assignments = [
        (assignment, judge)
        for assignment, judge in session.execute(
            select(JudgeAssignment, Judge)
            .join(Judge, Judge.id == JudgeAssignment.judge_id)
            .where(JudgeAssignment.case_id == case_id)
            .order_by(JudgeAssignment.start_at, JudgeAssignment.source_row_id)
        ).tuples()
    ]
    rows.charges = list(
        session.scalars(
            select(Charge)
            .where(Charge.case_id == case_id)
            .order_by(Charge.filed_at, Charge.source_row_id)
        )
    )
    rows.events = [
        (event, judge)
        for event, judge in session.execute(
            select(CourtEvent, Judge)
            .outerjoin(Judge, Judge.id == CourtEvent.judge_id)
            .where(CourtEvent.case_id == case_id)
            .order_by(CourtEvent.event_at, CourtEvent.source_row_id)
        ).tuples()
    ]
    rows.decisions = [
        (decision, pretrial, judge, key)
        for decision, pretrial, judge, key in session.execute(
            select(Decision, PretrialRelease, Judge, Person.public_person_key)
            .outerjoin(PretrialRelease, PretrialRelease.decision_id == Decision.id)
            .outerjoin(Judge, Judge.id == Decision.judge_id)
            .outerjoin(Person, and_(Person.id == Decision.person_id, unmerged()))
            .where(Decision.case_id == case_id)
            .order_by(Decision.decision_at, Decision.source_row_id)
        ).tuples()
    ]
    rows.sentences = [
        (sentence, judge)
        for sentence, judge in session.execute(
            select(Sentence, Judge)
            .outerjoin(Judge, Judge.id == Sentence.judge_id)
            .where(Sentence.case_id == case_id)
            .order_by(Sentence.sentence_at, Sentence.source_row_id)
        ).tuples()
    ]
    record_ids = {
        rows.case.source_record_id,
        *(party.source_record_id for party, _ in rows.parties),
        *(assignment.source_record_id for assignment, _ in rows.assignments),
        *(charge.source_record_id for charge in rows.charges),
        *(event.source_record_id for event, _ in rows.events),
        *(decision.source_record_id for decision, *_ in rows.decisions),
        *(sentence.source_record_id for sentence, _ in rows.sentences),
    }
    rows.provenance = source_records_by_id(session, record_ids)
    return rows


def list_judge_cases(
    session: Session,
    judge_id: uuid.UUID,
    *,
    filed_from: date | None,
    filed_to: date | None,
    status: str | None,
    case_type: str | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Case, Court, bool]], int] | None:
    """One page of the cases assigned to a judge, newest filing first, with the total.

    One statement when the page has rows (the window count rides along);
    an empty page costs one more, which also settles whether the judge
    exists — ``None`` means it does not, so the route answers 404.
    """
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}"
        raise ValueError(msg)
    if offset < 0:
        msg = "offset must be non-negative"
        raise ValueError(msg)
    stmt = (
        with_source(select(Case, Court, synthetic_flag()), Case.source_record_id)
        .join(Court, Court.id == Case.court_id)
        .where(Case.assignments.any(JudgeAssignment.judge_id == judge_id))
        .order_by(Case.filed_date.desc().nulls_last(), Case.case_number_normalized, Case.id)
    )
    if filed_from is not None:
        stmt = stmt.where(Case.filed_date >= filed_from)
    if filed_to is not None:
        stmt = stmt.where(Case.filed_date <= filed_to)
    if status is not None:
        stmt = stmt.where(Case.status == status)
    if case_type is not None:
        stmt = stmt.where(Case.case_type == case_type)
    paged = stmt.add_columns(func.count().over().label("total")).limit(limit).offset(offset)
    results = session.execute(paged).all()
    if results:
        return [(row[0], row[1], bool(row[2])) for row in results], int(results[0].total)
    total = select(func.count()).select_from(stmt.order_by(None).subquery()).scalar_subquery()
    found = session.execute(select(Judge.id, total).where(Judge.id == judge_id)).one_or_none()
    if found is None:
        return None
    return [], int(found[1] or 0)
