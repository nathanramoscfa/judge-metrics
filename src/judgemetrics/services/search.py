# src/judgemetrics/services/search.py
"""Search over judges, courts, and case numbers (``/api/v1/search``).

The query is normalized twice: with ``normalize_person_name`` (the rule
that produced ``judge.normalized_name``) for the trigram arms, and with
``normalize_case_number`` (the rule that produced
``court_case.case_number_normalized``) for the exact case-number arm.
A single-word query (one token after normalization: a surname alone)
matches by *word* similarity — ``<%`` under
``pg_trgm.word_similarity_threshold``, the best-matching extent of the
name — so a misspelt surname finds a long full name that whole-name
similarity would score below 0.3 ("Ginsberg" → Ruth Bader Ginsburg); a
query of several words keeps whole-name similarity (``%`` under
``pg_trgm.similarity_threshold``). The threshold of the mode in use is
set for the request's transaction from settings, and
``repositories.search`` runs the union ordered by the matching
similarity function (an exact case number scores 1). Every value is a
bound parameter; nothing is interpolated.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from judgemetrics.normalization.case_numbers import normalize_case_number
from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.repositories.search import search_matches
from judgemetrics.schemas.search import SearchResponse, SearchResult

SIMILARITY_SETTING = "pg_trgm.similarity_threshold"
WORD_SIMILARITY_SETTING = "pg_trgm.word_similarity_threshold"

SimilarityMode = Literal["whole", "word"]


def similarity_mode(normalized: str) -> SimilarityMode:
    """``word`` for a one-token query (a surname alone), ``whole`` for several tokens."""
    return "word" if " " not in normalized.strip() else "whole"


def _set(session: Session, setting: str, threshold: float) -> None:
    """``set_config(..., is_local => true)`` scopes the value to the transaction.

    The API opens one session (one transaction) per request, so a request
    never inherits another's threshold through the connection pool.
    """
    session.execute(select(func.set_config(setting, str(threshold), True)))


def set_similarity_threshold(session: Session, threshold: float) -> None:
    """Apply ``threshold`` to the ``%`` operator for the current transaction only."""
    _set(session, SIMILARITY_SETTING, threshold)


def set_word_similarity_threshold(session: Session, threshold: float) -> None:
    """Apply ``threshold`` to the ``<%`` operator for the current transaction only."""
    _set(session, WORD_SIMILARITY_SETTING, threshold)


def apply_similarity_threshold(
    session: Session, mode: SimilarityMode, *, threshold: float, word_threshold: float
) -> None:
    """Set the one threshold the mode's operator reads (one statement)."""
    if mode == "word":
        set_word_similarity_threshold(session, word_threshold)
    else:
        set_similarity_threshold(session, threshold)


def search(
    session: Session, q: str, limit: int, *, threshold: float, word_threshold: float
) -> SearchResponse:
    """Judges and courts whose names are similar to ``q``, and the case numbered ``q``."""
    normalized_name = normalize_person_name(q)
    normalized_case_number = normalize_case_number(q)
    if not normalized_name and not normalized_case_number:
        return SearchResponse(query=normalized_name, limit=limit, items=[])
    mode = similarity_mode(normalized_name)
    if normalized_name:
        apply_similarity_threshold(
            session, mode, threshold=threshold, word_threshold=word_threshold
        )
    matches = search_matches(
        session,
        normalized_name=normalized_name,
        normalized_case_number=normalized_case_number,
        limit=limit,
        word=mode == "word",
    )
    items = [SearchResult(**match._asdict()) for match in matches]
    return SearchResponse(query=normalized_name, limit=limit, items=items)
