# tests/unit/test_snapshot_export.py
"""The streamed snapshot export: batches in, the same Parquet bytes out (no database).

``snapshot.read_table`` turns a server-side cursor's batches into one rechunked frame, and
Polars writes the same bytes whatever the batch size, so the content hash does not depend on
how the export was streamed. A fake session that hands rows over in batches of every size from
one to the whole table stands in for the cursor; ``tests/integration/test_snapshot_export.py``
holds the real export equal to the Phase 3 reference on the golden data.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

import polars as pl
import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from judgemetrics.metrics.snapshot import (
    EXPORT_BATCH_ROWS,
    PARQUET_SCHEMAS,
    RESTRICTED_TABLES,
    SNAPSHOT_TABLES,
    export_statements,
    read_table,
)

pytestmark = pytest.mark.unit


class _Result:
    def __init__(self, rows: Sequence[tuple[Any, ...]]) -> None:
        self._rows = rows

    def partitions(self, size: int) -> Iterator[Sequence[tuple[Any, ...]]]:
        for start in range(0, len(self._rows), size):
            yield self._rows[start : start + size]


class _Session:
    """A session whose ``execute`` returns the rows it was built with, streamed in batches."""

    def __init__(self, rows: Sequence[tuple[Any, ...]], batch: int) -> None:
        self._rows = rows
        self.batch = batch
        self.options: list[dict[str, Any]] = []

    def execute(self, statement: Any, execution_options: dict[str, Any] | None = None) -> _Result:
        self.options.append(dict(execution_options or {}))
        return _Result(self._rows)


def _charges(count: int) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    for i in range(count):
        rows.append(
            (
                f"{i:08d}-0000-0000-0000-000000000001",
                f"{i % 7:08d}-0000-0000-0000-00000000000c",
                f"{i % 5:08d}-0000-0000-0000-00000000000a",
                datetime(2020, 1, 1 + i % 28, 9, i % 60),
                None if i % 3 == 0 else datetime(2021, 2, 1 + i % 28, 17, 30, i % 60, i),
                None if i % 4 == 0 else "convicted_plea",
                None if i % 5 == 0 else "judge",
                "drug" if i % 2 else "property",
                "felony_3",
                f"CH-{i}",
                None if i % 6 == 0 else f"{i % 3:08d}-0000-0000-0000-00000000000b",
            )
        )
    return rows


def _digest(frame: pl.DataFrame) -> str:
    buffer = io.BytesIO()
    frame.write_parquet(buffer)
    return hashlib.sha256(buffer.getvalue()).hexdigest()


@pytest.mark.parametrize("batch", [1, 2, 3, 7, 64, 1000])
def test_the_bytes_do_not_depend_on_the_size_of_the_batches(
    monkeypatch: pytest.MonkeyPatch, batch: int
) -> None:
    rows = _charges(137)
    reference = _digest(pl.DataFrame(rows, schema=dict(PARQUET_SCHEMAS["charges"]), orient="row"))
    monkeypatch.setattr("judgemetrics.metrics.snapshot.EXPORT_BATCH_ROWS", batch)
    fake = _Session(rows, batch)
    frame = read_table(fake, "charges", sa.select(sa.literal(1)))  # type: ignore[arg-type]
    assert frame.height == len(rows)
    assert frame.schema == pl.Schema(PARQUET_SCHEMAS["charges"])
    assert _digest(frame) == reference
    # The statement is streamed from a server-side cursor in batches of the module's size.
    assert fake.options == [{"stream_results": True, "yield_per": batch}]


def test_an_empty_table_is_an_empty_frame_with_the_schema() -> None:
    frame = read_table(_Session([], 10), "charges", sa.select(sa.literal(1)))  # type: ignore[arg-type]
    assert frame.height == 0 and frame.schema == pl.Schema(PARQUET_SCHEMAS["charges"])
    reference = pl.DataFrame([], schema=dict(PARQUET_SCHEMAS["charges"]), orient="row")
    assert _digest(frame) == _digest(reference)


def _sql(statement: sa.Select[Any]) -> str:
    return str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]


def test_the_export_reads_every_table_but_the_sources_by_a_statement_ordered_by_id() -> None:
    statements = export_statements()
    assert set(statements) == set(SNAPSHOT_TABLES) - {"sources"}
    for name, statement in statements.items():
        compiled = _sql(statement)
        assert " ORDER BY " in compiled, name
        assert ".id" in compiled.split(" ORDER BY ")[1], name
        for table in RESTRICTED_TABLES:
            assert table not in compiled, (name, table)


def test_the_database_does_the_conversions_the_python_export_used_to_do() -> None:
    cases = _sql(export_statements()["cases"])
    # Ids and enums as text, a date at its day's start and its day's last microsecond.
    assert "CAST(court_case.id AS TEXT)" in cases
    assert "CAST(court_case.filed_date AS TIMESTAMP WITHOUT TIME ZONE)" in cases
    assert "INTERVAL '23:59:59.999999'" in cases
    # A timestamptz as a naive UTC timestamp.
    assert "timezone(" in _sql(export_statements()["charges"])


def test_the_default_batch_is_bounded() -> None:
    assert 1 <= EXPORT_BATCH_ROWS <= 1_000_000
