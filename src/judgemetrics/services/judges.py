# src/judgemetrics/services/judges.py
"""Judge responses assembled from the repository rows."""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy.orm import Session

from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.repositories.judges import case_window, get_judge, list_judges, sorted_service
from judgemetrics.schemas.common import CoverageWindow, Page
from judgemetrics.schemas.judges import JudgeDetail, JudgeSummary, ServiceRecord
from judgemetrics.services.provenance import provenance_for
from judgemetrics.services.search import apply_similarity_threshold, similarity_mode


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
    word_threshold: float,
) -> Page[JudgeSummary]:
    normalized_q = normalize_person_name(q) if q else None
    if normalized_q == "":
        return Page[JudgeSummary].build([], total=0, limit=limit, offset=offset)
    word = False
    if normalized_q is not None:
        mode = similarity_mode(normalized_q)
        word = mode == "word"
        apply_similarity_threshold(
            session, mode, threshold=threshold, word_threshold=word_threshold
        )
    rows, total = list_judges(
        session,
        normalized_q=normalized_q,
        court_id=court_id,
        active_on=active_on,
        status=status,
        limit=limit,
        offset=offset,
        word=word,
    )
    items = [JudgeSummary.from_row(judge, synthetic=synthetic) for judge, synthetic in rows]
    return Page[JudgeSummary].build(items, total=total, limit=limit, offset=offset)


def judge_detail(session: Session, judge_id: uuid.UUID) -> JudgeDetail | None:
    """The judge, its service records (oldest first), its case window, and the artifacts behind it."""
    found = get_judge(session, judge_id)
    if found is None:
        return None
    judge, synthetic = found
    service = sorted_service(judge)
    window = case_window(session, judge_id)
    record_ids = {judge.source_record_id, *(row.source_record_id for row in service)}
    return JudgeDetail.from_row(
        judge,
        synthetic=synthetic,
        service=[ServiceRecord.model_validate(row) for row in service],
        case_count=window.case_count,
        coverage=(
            CoverageWindow(
                earliest_filed=window.earliest_filed,
                latest_filed=window.latest_filed,
                case_count=window.case_count,
            )
            if window.case_count
            else None
        ),
        provenance=provenance_for(session, record_ids),
    )


def judge_service(session: Session, judge_id: uuid.UUID) -> list[ServiceRecord] | None:
    """The judge's service records alone, or ``None`` when the judge does not exist."""
    found = get_judge(session, judge_id)
    if found is None:
        return None
    return [ServiceRecord.model_validate(row) for row in sorted_service(found[0])]
