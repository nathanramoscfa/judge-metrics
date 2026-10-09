# src/judgemetrics/db/arrays.py
"""Lookups by a run-sized list of values, bound as one typed array parameter.

SQLAlchemy renders ``column.in_(values)`` as one bind parameter per value, and
PostgreSQL rejects a statement with more than 65,535 of them, so a run that
touches more cases or persons than that fails on its first lookup. ``in_array``
renders ``column = ANY(:values)`` instead — one parameter, typed from the column
(``uuid[]``, ``text[]``) — and ``fetch_by_values`` runs a statement over a long
list in batches of ``ID_BATCH`` so no single statement carries an unbounded
array either. Every lookup of a run-sized list in the ingest runner, the
publishers, and entity resolution goes through these two functions
(``tests/integration/test_bind_parameter_ceiling.py`` runs them over 70,000
ids on the scratch database).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from itertools import batched
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import QueryableAttribute, Session

# Values per statement: far below any driver limit, large enough that a lookup
# over the Cook County corpus (about 550,000 persons) is a dozen statements.
ID_BATCH = 50_000

# A Core column or expression, or an ORM attribute (``Case.id``).
Expression = sa.ColumnElement[Any] | QueryableAttribute[Any]


def _element(column: Expression) -> sa.ColumnElement[Any]:
    return column if isinstance(column, sa.ColumnElement) else column.__clause_element__()


def in_array(column: Expression, values: Iterable[Any]) -> sa.ColumnElement[bool]:
    """``column = ANY(:values)`` with ``values`` as one array parameter typed from ``column``."""
    element = _element(column)
    return element == sa.any_(sa.literal(list(values), type_=ARRAY(element.type)))


def fetch_by_values(
    session: Session,
    statement: Callable[[sa.ColumnElement[bool]], sa.Select[Any]],
    column: Expression,
    values: Iterable[Any],
    *,
    batch_size: int = ID_BATCH,
) -> Iterator[Any]:
    """Rows of ``statement(condition)`` for every ``column`` value, one batch per statement.

    ``statement`` receives the ``column = ANY(...)`` condition for one batch and
    returns the ``select`` to run; the values are de-duplicated (order kept) so a
    value repeated in ``values`` is looked up once.
    """
    unique = list(dict.fromkeys(values))
    for chunk in batched(unique, batch_size, strict=False):
        yield from session.execute(statement(in_array(column, chunk))).all()


__all__ = ["ID_BATCH", "fetch_by_values", "in_array"]
