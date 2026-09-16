# src/judgemetrics/services/judges.py
"""Judge responses assembled from the repository rows."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.repositories.judges import get_judge, list_judges, sorted_service
from judgemetrics.schemas.common import Page
from judgemetrics.schemas.judges import JudgeDetail, JudgeSummary, ServiceRecord
from judgemetrics.services.provenance import provenance_for
from judgemetrics.services.search import set_similarity_threshold


def judges_page(
    session: Session,
    *,
    q: str | None,
    court_id: uuid.UUID | None,
    active_on: date | None,
    status: str | None,
    limit: int,
    offset: int,
    threshold: float,
) -> Page[JudgeSummary]:
    normalized_q = normalize_person_name(q) if q else None
    if normalized_q == "":
        return Page[JudgeSummary].build([], total=0, limit=limit, offset=offset)
    if normalized_q is not None:
        set_similarity_threshold(session, threshold)
    rows, total = list_judges(
        session,
        normalized_q=normalized_q,
        court_id=court_id,
        active_on=active_on,
        status=status,
        limit=limit,
        offset=offset,
    )
    items = [JudgeSummary.model_validate(row) for row in rows]
    return Page[JudgeSummary].build(items, total=total, limit=limit, offset=offset)


def judge_detail(session: Session, judge_id: uuid.UUID) -> JudgeDetail | None:
    """The judge, its service records (oldest first), and the artifacts behind them."""
    judge = get_judge(session, judge_id)
    if judge is None:
        return None
    service = sorted_service(judge)
    record_ids = {judge.source_record_id, *(row.source_record_id for row in service)}
    return JudgeDetail.from_row(
        judge,
        service=[ServiceRecord.model_validate(row) for row in service],
        provenance=provenance_for(session, record_ids),
    )


def judge_service(session: Session, judge_id: uuid.UUID) -> list[ServiceRecord] | None:
    """The judge's service records alone, or ``None`` when the judge does not exist."""
    judge = get_judge(session, judge_id)
    if judge is None:
        return None
    return [ServiceRecord.model_validate(row) for row in sorted_service(judge)]
