# src/judgemetrics/services/search.py
"""Search over judges, courts, and case numbers (``/api/v1/search``).

The query is normalized twice: with ``normalize_person_name`` (the rule
that produced ``judge.normalized_name``) for the trigram arms, and with
``normalize_case_number`` (the rule that produced
``court_case.case_number_normalized``) for the exact case-number arm.
The ``pg_trgm`` similarity threshold is set for the request's transaction
from settings, and ``repositories.search`` runs the union ordered by
``similarity()`` (an exact case number scores 1). Every value is a bound
parameter; nothing is interpolated.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from judgemetrics.normalization.case_numbers import normalize_case_number
from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.repositories.search import search_matches
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
    """Judges and courts whose names are similar to ``q``, and the case numbered ``q``."""
    normalized_name = normalize_person_name(q)
    normalized_case_number = normalize_case_number(q)
    if not normalized_name and not normalized_case_number:
        return SearchResponse(query=normalized_name, limit=limit, items=[])
    if normalized_name:
        set_similarity_threshold(session, threshold)
    matches = search_matches(
        session,
        normalized_name=normalized_name,
        normalized_case_number=normalized_case_number,
        limit=limit,
    )
    items = [SearchResult(**match._asdict()) for match in matches]
    return SearchResponse(query=normalized_name, limit=limit, items=items)
