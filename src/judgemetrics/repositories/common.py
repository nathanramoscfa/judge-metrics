# src/judgemetrics/repositories/common.py
"""Pagination shared by the list queries."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Row, Select, func, select
from sqlalchemy.orm import Session

from judgemetrics.db.base import Base

DEFAULT_LIMIT = 25
MAX_LIMIT = 100


def paginate_rows(
    session: Session, stmt: Select[Any], *, limit: int, offset: int
) -> tuple[list[Row[Any]], int]:
    """Return one page of ``stmt``'s rows and the total row count in a single statement.

    The count rides along as a window function (``count(*) OVER ()``) so a
    list page costs one round trip. When the page is empty (an offset past
    the end, or no match) the window yields no row, and the total is
    fetched with a plain count instead. Each returned ``Row`` has the
    statement's own columns followed by ``total``.
    """
    if not 1 <= limit <= MAX_LIMIT:
        msg = f"limit must be between 1 and {MAX_LIMIT}"
        raise ValueError(msg)
    if offset < 0:
        msg = "offset must be non-negative"
        raise ValueError(msg)
    paged = stmt.add_columns(func.count().over().label("total")).limit(limit).offset(offset)
    results = session.execute(paged).all()
    if results:
        return list(results), int(results[0].total)
    total = session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    return [], int(total or 0)


def paginate[Entity: Base](
    session: Session, stmt: Select[tuple[Entity]], *, limit: int, offset: int
) -> tuple[list[Entity], int]:
    """``paginate_rows`` for a statement that selects one entity."""
    rows, total = paginate_rows(session, stmt, limit=limit, offset=offset)
    return [row[0] for row in rows], total
