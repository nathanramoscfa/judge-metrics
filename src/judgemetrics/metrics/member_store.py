# src/judgemetrics/metrics/member_store.py
"""Member families in PostgreSQL: written with ``COPY``, read back, and cut into observations.

``metric_member_family`` holds one row per family and content (``members_hash``);
``metric_member`` holds the family's rows, keyed ``(family_id, ordinal)`` in the
canonical order (``judgemetrics.metrics.members``). This module is the only code that
touches those two tables' rows besides the migration and ``ingest retire``:

- ``write_rows`` streams a family's rows through psycopg's ``COPY ... FROM STDIN`` in
  chunks, as CSV Polars renders — the statement is a constant and the rows travel
  through the copy protocol, never through SQL text built from data; the family's
  ``ordinal`` is its place in the canonical order, so a family is one contiguous run
  of the primary key;
- ``read_rows`` and ``read_family`` bring a family back, canonical again, for
  ``metrics verify`` and the unchanged-recompute comparison;
- ``projection`` is the SQL twin of ``MemberFamily.project``: the member multiset of one
  observation (``year``, flag ``slot``, ``dimension``) as ``(member_id, counted,
  followed, multiplicity)`` rows, which the provenance trace joins to the canonical
  tables. ``tests/integration/test_member_storage.py`` holds the two equal;
- ``observation_members`` is that multiset for a stored observation, as ``Member`` objects
  (tests, tools, and small data: a trace pages instead).

Rows carry public entity ids only: nothing here reads or writes a person id.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Final

import polars as pl
import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base
from judgemetrics.metrics import members as m
from judgemetrics.metrics.members import Member, MemberFamily, mode_for, windows_for

FAMILY = Base.metadata.tables["metric_member_family"]
MEMBER = Base.metadata.tables["metric_member"]
OBSERVATION = Base.metadata.tables["metric_observation"]
DEFINITION = Base.metadata.tables["metric_definition"]

# Rows per ``COPY`` write: a chunk is rendered to CSV in memory, so this bounds the buffer.
COPY_CHUNK_ROWS: Final = 200_000
NULL_MARKER: Final = "\\N"
# The statement is constant: the column list is the table's, the rows go through the protocol.
COPY_STATEMENT: Final = (
    "COPY metric_member (family_id, ordinal, member_id, anchor_year, dimension_value, "
    f"counted_mask, followed_mask, multiplicity) FROM STDIN WITH (FORMAT csv, NULL '{NULL_MARKER}')"
)


class MemberStoreError(RuntimeError):
    """A family cannot be written or read (a defect, or a database that lost rows)."""


def _driver_connection(session: Session) -> Any:
    """The psycopg connection under the session's transaction (``COPY`` runs inside it)."""
    session.flush()
    return session.connection().connection.driver_connection


def write_rows(session: Session, family_id: uuid.UUID, rows: pl.DataFrame) -> int:
    """``COPY`` the family's canonical rows in order; the rows written."""
    if rows.height == 0:
        return 0
    connection = _driver_connection(session)
    written = 0
    with connection.cursor() as cursor, cursor.copy(COPY_STATEMENT) as copy:
        for start in range(0, rows.height, COPY_CHUNK_ROWS):
            chunk = rows.slice(start, COPY_CHUNK_ROWS).select(
                pl.lit(str(family_id)).alias("family_id"),
                (pl.int_range(pl.len(), dtype=pl.Int32) + start).alias("ordinal"),
                pl.col(m.ID),
                pl.col(m.YEAR),
                pl.col(m.DIMENSION),
                pl.col(m.COUNTED),
                pl.col(m.FOLLOWED),
                pl.col(m.COPIES),
            )
            copy.write(chunk.write_csv(include_header=False, null_value=NULL_MARKER))
            written += chunk.height
    return written


def create_family(
    session: Session,
    *,
    definition_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID,
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    family: MemberFamily,
) -> uuid.UUID:
    """Insert the family's row and its member rows; the new family's id."""
    family_id = uuid.uuid4()
    session.execute(
        sa.insert(FAMILY).values(
            id=family_id,
            metric_definition_id=definition_id,
            subject_type=subject_type,
            subject_id=subject_id,
            source_id=source_id,
            snapshot_id=snapshot_id,
            member_kind=family.kind,
            members_hash=family.digest,
            row_count=family.row_count,
            member_count=family.member_count,
        )
    )
    written = write_rows(session, family_id, family.rows)
    if written != family.row_count:  # pragma: no cover - COPY writes what it is given
        msg = f"family {family_id}: wrote {written} of {family.row_count} rows"
        raise MemberStoreError(msg)
    return family_id


def existing_families(
    session: Session,
    *,
    subject_type: str,
    subject_id: uuid.UUID,
    source_id: uuid.UUID,
    snapshot_id: uuid.UUID,
) -> dict[tuple[uuid.UUID, str], uuid.UUID]:
    """The subject's families of one snapshot: ``(definition id, members hash)`` to family id."""
    rows = session.execute(
        select(FAMILY.c.id, FAMILY.c.metric_definition_id, FAMILY.c.members_hash).where(
            FAMILY.c.subject_type == subject_type,
            FAMILY.c.subject_id == subject_id,
            FAMILY.c.source_id == source_id,
            FAMILY.c.snapshot_id == snapshot_id,
        )
    ).all()
    return {
        (uuid.UUID(str(row.metric_definition_id)), str(row.members_hash)): uuid.UUID(str(row.id))
        for row in rows
    }


def read_rows(session: Session, family_id: uuid.UUID) -> pl.DataFrame:
    """The stored rows of one family, as the canonical schema (unsorted: ``from_stored`` sorts)."""
    result = session.execute(
        select(
            sa.cast(MEMBER.c.member_id, sa.Text),
            MEMBER.c.anchor_year,
            MEMBER.c.dimension_value,
            MEMBER.c.counted_mask,
            MEMBER.c.followed_mask,
            MEMBER.c.multiplicity,
        ).where(MEMBER.c.family_id == family_id),
        execution_options={"stream_results": True, "yield_per": COPY_CHUNK_ROWS},
    )
    batches = [
        pl.DataFrame([tuple(row) for row in chunk], schema=m.SCHEMA, orient="row")
        for chunk in result.partitions(COPY_CHUNK_ROWS)
    ]
    if not batches:
        return m.empty_rows()
    return pl.concat(batches, how="vertical", rechunk=True)


def read_family(
    session: Session,
    family_id: uuid.UUID,
    *,
    kind: str,
    mode: str,
    windows: Sequence[int | None],
) -> MemberFamily:
    """One stored family as a ``MemberFamily`` (the kind, mode, and windows come from its definition)."""
    return MemberFamily.from_stored(kind, mode, windows, read_rows(session, family_id))


def projection(
    family_id: uuid.UUID,
    *,
    mode: str,
    slot: int,
    year: int | None,
    dimension: str | None,
) -> sa.Select[Any]:
    """``(member_id, counted, followed, multiplicity)`` of one observation of a family.

    The SQL form of ``MemberFamily.project``: ``year`` keeps the rows whose anchor falls in
    it (``None``: all), a median by dimension keeps its dimension's rows, and a
    distribution counts a row in the value it belongs to.
    """
    bit = 1 << slot
    followed = (MEMBER.c.followed_mask.bitwise_and(bit)) != 0
    if mode == m.COUNTED_IN:
        counted: sa.ColumnElement[bool] = sa.func.coalesce(
            MEMBER.c.dimension_value == dimension, sa.false()
        )
    else:
        counted = (MEMBER.c.counted_mask.bitwise_and(bit)) != 0
    statement = select(
        MEMBER.c.member_id,
        counted.label("counted"),
        followed.label("followed"),
        MEMBER.c.multiplicity,
    ).where(MEMBER.c.family_id == family_id)
    if year is not None:
        statement = statement.where(MEMBER.c.anchor_year == year)
    if mode == m.BELONGS_TO and dimension is not None:
        statement = statement.where(MEMBER.c.dimension_value == dimension)
    return statement


def observation_members(session: Session, observation_id: uuid.UUID) -> tuple[Member, ...]:
    """The member multiset of one stored observation, one ``Member`` per copy.

    Read through the same SQL ``projection`` the provenance trace uses; for tests, tools,
    and small observations (a large one is paged by ``provenance.trace``).
    """
    row = session.execute(
        select(
            OBSERVATION.c.member_family_id,
            OBSERVATION.c.window_days,
            OBSERVATION.c.calendar_year,
            OBSERVATION.c.dimension_value,
            DEFINITION.c.kind,
            DEFINITION.c.windows_days,
            DEFINITION.c.dimension,
            FAMILY.c.member_kind,
        )
        .join(DEFINITION, DEFINITION.c.id == OBSERVATION.c.metric_definition_id)
        .join(FAMILY, FAMILY.c.id == OBSERVATION.c.member_family_id)
        .where(OBSERVATION.c.id == observation_id)
    ).first()
    if row is None:
        msg = f"no metric observation has id {observation_id}"
        raise MemberStoreError(msg)
    windows = windows_for(str(row.kind), row.windows_days)
    statement = projection(
        uuid.UUID(str(row.member_family_id)),
        mode=mode_for(str(row.kind), row.dimension),
        slot=windows.index(row.window_days),
        year=row.calendar_year,
        dimension=row.dimension_value,
    )
    members: list[Member] = []
    for member_id, counted, followed, copies in session.execute(statement):
        members.extend([Member(str(row.member_kind), str(member_id), counted, followed)] * copies)
    return tuple(members)
