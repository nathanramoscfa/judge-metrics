# src/judgemetrics/ingest/fjc/parse.py
"""Polars CSV parsing of the FJC files into row-level ``SourceRecordDraft``s.

Every column is read as a string (no type inference, empty cells stay
empty strings), values are whitespace-trimmed, and each row is projected
to the file's expected headers, so demographic columns never enter a
payload.
"""

from __future__ import annotations

import io
from collections.abc import Iterator, Sequence

import polars as pl

from judgemetrics.ingest.base import SourceRecordDraft
from judgemetrics.ingest.fjc.schema import (
    JUDGES_EXPECTED_HEADERS,
    NID,
    RECORD_TYPE_JUDGE,
    RECORD_TYPE_SERVICE,
    SEQUENCE,
    SERVICE_EXPECTED_HEADERS,
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


def parse_judges(data: bytes) -> Iterator[SourceRecordDraft]:
    for row in iter_rows(read_frame(data), JUDGES_EXPECTED_HEADERS):
        yield SourceRecordDraft(
            external_record_id=row.get(NID, ""),
            effective_at=None,
            payload=row,
            record_type=RECORD_TYPE_JUDGE,
        )


def parse_service(data: bytes) -> Iterator[SourceRecordDraft]:
    for row in iter_rows(read_frame(data), SERVICE_EXPECTED_HEADERS):
        yield SourceRecordDraft(
            external_record_id=f"{row.get(NID, '')}:{row.get(SEQUENCE, '')}",
            effective_at=None,
            payload=row,
            record_type=RECORD_TYPE_SERVICE,
        )
