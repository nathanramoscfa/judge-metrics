# src/judgemetrics/ingest/cook_sao/frames.py
"""One Cook County export read into a canonical, sorted Polars frame.

``read_export`` reads only the columns the connector uses (``schema.READ_COLUMNS``;
the incident's city and dates, the arresting agency and unit, and every other
column never leave the file), every column a string and every empty field null,
the way the profile reads them. The date columns are parsed in either export
format; a value that is not a date, one after the corpus end (the exports carry
typos to the year 2924), and one before 1900 become null and are counted as
findings. Identifier columns are stripped. The frame is then sorted by every
column read, identifiers first, so the same rows in any order give the same
frame: the connector's output cannot depend on the order the portal wrote its
rows in (``tests/property/test_cook_sao_order.py``). A ``_row`` column keeps the
row's 1-based position in the file for the findings' sake and is not a sort key.
"""

from __future__ import annotations

import io
from pathlib import Path

import polars as pl

from judgemetrics.ingest.cook_sao.findings import (
    DATE_AFTER_CORPUS_END,
    ROW_WITHOUT_KEY,
    UNPARSEABLE_DATE,
    Findings,
)
from judgemetrics.ingest.cook_sao.schema import (
    CASE_ID,
    CHARGE_ID,
    CHARGE_VERSION_ID,
    COVERAGE_END,
    DATASET_ORDER,
    DATE_FORMATS,
    EARLIEST_DATE,
    PARTICIPANT_ID,
    READ_COLUMNS,
    READ_DATE_COLUMNS,
)

ROW = "_row"
# Columns that identify a case, a participant, or a charge: stripped of outer whitespace.
IDENTIFIER_COLUMNS = (CASE_ID, PARTICIPANT_ID, CHARGE_ID, CHARGE_VERSION_ID)
CHARGE_DATASETS = ("initiation.csv", "dispositions.csv", "sentencing.csv")


def _parsed(column: str) -> pl.Expr:
    formats = list(DATE_FORMATS)
    return pl.coalesce(
        *(pl.col(column).str.to_datetime(fmt, strict=False) for fmt in formats)
    ).alias(column)


def read_export(source: Path | bytes, name: str, findings: Findings) -> pl.DataFrame:
    """The sorted frame of export ``name`` read from a file or bytes (see the module docstring)."""
    if name not in READ_COLUMNS:
        msg = f"{name} is not a Cook County export"
        raise KeyError(msg)
    columns = list(READ_COLUMNS[name])
    frame = pl.read_csv(
        io.BytesIO(source) if isinstance(source, bytes) else source,
        columns=columns,
        infer_schema=False,
        null_values=[""],
        encoding="utf8",
    ).with_row_index(ROW, offset=1)
    identifiers = [column for column in IDENTIFIER_COLUMNS if column in columns]
    frame = frame.with_columns(
        [pl.col(column).str.strip_chars().replace("", None) for column in identifiers]
    )
    # A row without the identifiers that place it cannot be attributed to a case.
    required = [CASE_ID, PARTICIPANT_ID]
    if name in CHARGE_DATASETS:
        required += [CHARGE_ID, CHARGE_VERSION_ID]
    for column in required:
        missing = int(frame[column].null_count())
        if missing:
            findings.add(ROW_WITHOUT_KEY, name, column, missing)
    frame = frame.drop_nulls(subset=required)
    for column in READ_DATE_COLUMNS[name]:
        frame = _clean_dates(frame, name, column, findings)
    return frame.sort(columns, nulls_last=False)


def _clean_dates(frame: pl.DataFrame, name: str, column: str, findings: Findings) -> pl.DataFrame:
    """``column`` parsed; values that are not dates, or out of range, null and counted."""
    parsed = _parsed(column)
    unparseable, late, early = frame.select(
        (pl.col(column).is_not_null() & parsed.is_null()).sum().alias("unparseable"),
        (parsed.dt.date() > COVERAGE_END).sum().alias("late"),
        (parsed.dt.date() < EARLIEST_DATE).sum().alias("early"),
    ).row(0)
    if unparseable or early:
        findings.add(UNPARSEABLE_DATE, name, column, int(unparseable) + int(early))
    if late:
        findings.add(DATE_AFTER_CORPUS_END, name, column, int(late))
    return frame.with_columns(
        pl.when(parsed.dt.date().is_between(EARLIEST_DATE, COVERAGE_END))
        .then(parsed)
        .otherwise(None)
        .alias(column)
    )


__all__ = ["DATASET_ORDER", "IDENTIFIER_COLUMNS", "ROW", "read_export"]
