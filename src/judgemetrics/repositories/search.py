# src/judgemetrics/repositories/search.py
"""The search union: judges and courts by trigram similarity, cases by exact number.

Judge and court arms use the ``%`` operator (whole-name similarity) for a
query of several words and the ``<%`` operator (word similarity: the
query against the best-matching extent of the name, the query on the
left as the pg_trgm documentation shows) for a single word, so the GIN
trigram indexes of the baseline (``ix_judge_normalized_name_trgm``,
``ix_court_canonical_name_trgm``) apply under the threshold the service
set for the transaction (``pg_trgm.similarity_threshold`` or
``pg_trgm.word_similarity_threshold``); ``score`` is the matching
function, ``similarity()`` or ``word_similarity()``. The case arm is an
equality on ``case_number_normalized`` (the unique ``court_case_number``
constraint's index) scored 1. Every arm joins ``source_record`` and
``source`` for the synthetic flag, and every value is a bound parameter.
"""

from __future__ import annotations

import uuid
from typing import Any, NamedTuple

from sqlalchemy import ColumnElement, Select, func, literal, select, union_all
from sqlalchemy.orm import Session

from judgemetrics.db.models import Case, Court, Judge
from judgemetrics.repositories.provenance import synthetic_flag, with_source

WHOLE_NAME_OPERATOR = "%"
WORD_OPERATOR = "<%"


class SearchMatch(NamedTuple):
    entity_type: str
    id: uuid.UUID
    name: str
    score: float
    synthetic: bool


def name_match(column: Any, normalized_query: str, *, word: bool) -> ColumnElement[bool]:
    """``query <% column`` (word similarity) or ``column % query`` (whole name)."""
    if word:
        matched: ColumnElement[bool] = literal(normalized_query).op(WORD_OPERATOR)(column)
        return matched
    whole: ColumnElement[bool] = column.op(WHOLE_NAME_OPERATOR)(normalized_query)
    return whole


def name_score(column: Any, normalized_query: str, *, word: bool) -> ColumnElement[float]:
    """The similarity the match was made under, for ordering and the ``score`` field."""
    if word:
        return func.word_similarity(normalized_query, column)
    return func.similarity(column, normalized_query)


def _judges(normalized_name: str, *, word: bool) -> Select[tuple[str, uuid.UUID, str, float, bool]]:
    stmt = select(
        literal("judge").label("entity_type"),
        Judge.id.label("id"),
        Judge.canonical_name.label("name"),
        name_score(Judge.normalized_name, normalized_name, word=word).label("score"),
        synthetic_flag(),
    ).where(name_match(Judge.normalized_name, normalized_name, word=word))
    return with_source(stmt, Judge.source_record_id)


def _courts(normalized_name: str, *, word: bool) -> Select[tuple[str, uuid.UUID, str, float, bool]]:
    stmt = select(
        literal("court").label("entity_type"),
        Court.id.label("id"),
        Court.canonical_name.label("name"),
        name_score(Court.canonical_name, normalized_name, word=word).label("score"),
        synthetic_flag(),
    ).where(name_match(Court.canonical_name, normalized_name, word=word))
    return with_source(stmt, Court.source_record_id)


def _cases(normalized_case_number: str) -> Select[tuple[str, uuid.UUID, str, float, bool]]:
    stmt = select(
        literal("case").label("entity_type"),
        Case.id.label("id"),
        Case.case_number.label("name"),
        literal(1.0).label("score"),
        synthetic_flag(),
    ).where(Case.case_number_normalized == normalized_case_number)
    return with_source(stmt, Case.source_record_id)


def search_matches(
    session: Session,
    *,
    normalized_name: str,
    normalized_case_number: str,
    limit: int,
    word: bool = False,
) -> list[SearchMatch]:
    """Judges, courts, and cases matching the normalized inputs, best first: one statement.

    An empty ``normalized_name`` skips the name arms and an empty
    ``normalized_case_number`` the case arm; the caller returns nothing
    without calling when both are empty. ``word`` selects word similarity
    for the name arms (a one-token query).
    """
    arms: list[Select[tuple[str, uuid.UUID, str, float, bool]]] = []
    if normalized_name:
        arms.extend((_judges(normalized_name, word=word), _courts(normalized_name, word=word)))
    if normalized_case_number:
        arms.append(_cases(normalized_case_number))
    if not arms:
        return []
    matches = union_all(*arms).subquery("matches")
    stmt = (
        select(
            matches.c.entity_type,
            matches.c.id,
            matches.c.name,
            matches.c.score,
            matches.c.synthetic,
        )
        .order_by(matches.c.score.desc(), matches.c.name, matches.c.id)
        .limit(limit)
    )
    return [
        SearchMatch(entity_type, entity_id, name, float(score), bool(synthetic))
        for entity_type, entity_id, name, score, synthetic in session.execute(stmt).tuples()
    ]
