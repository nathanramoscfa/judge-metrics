# src/judgemetrics/ingest/synthetic/parse.py
"""Polars string-only parsing of the synthetic files into ``SourceRecordDraft``s.

Every column is read as a string (no type inference; an empty cell stays
an empty string), values are whitespace-trimmed, and each row is
projected to the file's expected headers. ``record_type`` is the file
stem; ``external_record_id`` is the file's row id (``ROW_ID_COLUMNS``),
which is also the ``source_row_id`` of the canonical row it becomes.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence

import polars as pl

from judgemetrics.ingest.base import SourceRecordDraft
from judgemetrics.ingest.synthetic.schema import (
    EXPECTED_HEADERS,
    ROW_ID_COLUMNS,
    record_type_for,
)


def read_headers(data: bytes) -> list[str]:
    """The header row of a CSV payload (raises ``pl.exceptions.PolarsError`` if unreadable)."""
    frame = pl.read_csv(io.BytesIO(data), n_rows=1, infer_schema=False, encoding="utf8")
    return list(frame.columns)


def read_frame(data: bytes) -> pl.DataFrame:
    """The whole file with every column typed ``String``."""
    return pl.read_csv(
        io.BytesIO(data),
        infer_schema=False,
        encoding="utf8",
        empty_string_is_null=False,
    )


def iter_rows(frame: pl.DataFrame, columns: Sequence[str]) -> Iterator[dict[str, str]]:
    """Rows projected to ``columns`` (those present), values trimmed, never ``None``."""
    present = [column for column in columns if column in frame.columns]
    if not present:
        return
    for row in frame.select(present).iter_rows(named=True):
        yield {key: (value or "").strip() for key, value in row.items()}


def parse_file(file_name: str, data: bytes) -> Iterator[SourceRecordDraft]:
    """The rows of one source file as drafts (``file_name`` is the bare name, e.g. ``cases.csv``)."""
    expected = EXPECTED_HEADERS[file_name]
    row_id = ROW_ID_COLUMNS[file_name]
    record_type = record_type_for(file_name)
    for row in iter_rows(read_frame(data), expected):
        yield SourceRecordDraft(
            external_record_id=row.get(row_id, ""),
            effective_at=None,
            payload=row,
            record_type=record_type,
        )
