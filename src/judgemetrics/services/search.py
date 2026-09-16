# src/judgemetrics/services/search.py
"""Trigram search over judges and courts (``/api/v1/search``).

The query is normalized with ``normalize_person_name`` (the same rule that
produced ``judge.normalized_name``), the ``pg_trgm`` similarity threshold
is set for the request's transaction from settings, and one ``UNION ALL``
returns judge and court matches ordered by ``similarity()``. Matching
uses the ``%`` operator so the GIN trigram indexes of the baseline
(``ix_judge_normalized_name_trgm``, ``ix_court_canonical_name_trgm``)
apply. Every value is a bound parameter; nothing is interpolated.
"""

from __future__ import annotations

from sqlalchemy import func, literal, select, union_all
from sqlalchemy.orm import Session

from judgemetrics.db.models import Court, Judge
from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.schemas.search import SearchResponse, SearchResult

SIMILARITY_SETTING = "pg_trgm.similarity_threshold"


def set_similarity_threshold(session: Session, threshold: float) -> None:
    """Apply ``threshold`` to the ``%`` operator for the current transaction only.

    ``set_config(..., is_local => true)`` scopes the value to the
    transaction, and the API opens one session (one transaction) per
    request, so a request never inherits another's threshold through the
    connection pool.
    """
    session.execute(select(func.set_config(SIMILARITY_SETTING, str(threshold), True)))


def search(session: Session, q: str, limit: int, *, threshold: float) -> SearchResponse:
    """Judges and courts whose names are similar to ``q``, best first."""
    normalized = normalize_person_name(q)
    if not normalized:
        return SearchResponse(query=normalized, limit=limit, items=[])
    set_similarity_threshold(session, threshold)
    judges = select(
        literal("judge").label("entity_type"),
        Judge.id.label("id"),
        Judge.canonical_name.label("name"),
        func.similarity(Judge.normalized_name, normalized).label("score"),
    ).where(Judge.normalized_name.op("%")(normalized))
    courts = select(
        literal("court").label("entity_type"),
        Court.id.label("id"),
        Court.canonical_name.label("name"),
        func.similarity(Court.canonical_name, normalized).label("score"),
    ).where(Court.canonical_name.op("%")(normalized))
    matches = union_all(judges, courts).subquery("matches")
    stmt = (
        select(matches.c.entity_type, matches.c.id, matches.c.name, matches.c.score)
        .order_by(matches.c.score.desc(), matches.c.name, matches.c.id)
        .limit(limit)
    )
    items = [
        SearchResult(entity_type=entity_type, id=entity_id, name=name, score=float(score))
        for entity_type, entity_id, name, score in session.execute(stmt).all()
    ]
    return SearchResponse(query=normalized, limit=limit, items=items)
