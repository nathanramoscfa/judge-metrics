# src/judgemetrics/repositories/judges.py
"""Judge queries: the filtered list and the detail with its service records."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import ColumnElement, and_, func, or_, select
from sqlalchemy.orm import Session, selectinload

from judgemetrics.db.models import Judge, JudgeService
from judgemetrics.repositories.common import paginate


def _service_matches(court_id: uuid.UUID | None, active_on: date | None) -> ColumnElement[bool]:
    """A service record at ``court_id`` (if given) whose interval covers ``active_on`` (if given).

    Both conditions apply to the same record, so ``court_id`` with
    ``active_on`` means "sat at that court on that date".
    """
    clauses: list[ColumnElement[bool]] = []
    if court_id is not None:
        clauses.append(JudgeService.court_id == court_id)
    if active_on is not None:
        clauses.append(JudgeService.start_date <= active_on)
        clauses.append(or_(JudgeService.end_date.is_(None), JudgeService.end_date >= active_on))
    return and_(*clauses)


def list_judges(
    session: Session,
    *,
    normalized_q: str | None,
    court_id: uuid.UUID | None,
    active_on: date | None,
    status: str | None,
    limit: int,
    offset: int,
) -> tuple[list[Judge], int]:
    """One page of judges.

    ``normalized_q`` is matched with the trigram ``%`` operator against
    ``normalized_name`` (GIN index ``ix_judge_normalized_name_trgm``) at the
    threshold the caller set for the session (``services.search``); matches
    are ordered by similarity, otherwise by name.
    """
    stmt = select(Judge)
    if normalized_q is not None:
        similarity = func.similarity(Judge.normalized_name, normalized_q)
        stmt = stmt.where(Judge.normalized_name.op("%")(normalized_q)).order_by(
            similarity.desc(), Judge.canonical_name, Judge.id
        )
    else:
        stmt = stmt.order_by(Judge.canonical_name, Judge.id)
    if court_id is not None or active_on is not None:
        stmt = stmt.where(Judge.service_records.any(_service_matches(court_id, active_on)))
    if status is not None:
        stmt = stmt.where(Judge.status == status)
    return paginate(session, stmt, limit=limit, offset=offset)


def get_judge(session: Session, judge_id: uuid.UUID) -> Judge | None:
    """The judge with its service records and their courts: two statements."""
    stmt = (
        select(Judge)
        .where(Judge.id == judge_id)
        .options(selectinload(Judge.service_records).joinedload(JudgeService.court))
    )
    return session.scalars(stmt).one_or_none()


def sorted_service(judge: Judge) -> list[JudgeService]:
    """Service records oldest first; undated records last."""
    return sorted(
        judge.service_records,
        key=lambda s: (s.start_date is None, s.start_date or date.min, s.position_type, str(s.id)),
    )
