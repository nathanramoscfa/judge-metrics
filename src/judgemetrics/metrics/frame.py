# src/judgemetrics/metrics/frame.py
"""The analytic frame: the typed Polars tables every metric is computed over.

A ``Frame`` is a frozen bundle of Polars DataFrames with documented
schemas, plus the source's coverage window and the outcomes it can
document. A loader builds it — ``tests/property/support.frame_from_world``
from an in-memory synthetic world, Step 2's ``snapshot.py`` from a
Parquet snapshot of one source's rows — and the pure functions in
``attribution``, ``index_events``, ``exposure``, ``windows``, and
``censoring`` read it; nothing here touches a database.

Schemas (id columns are marked ``*``; ``?`` marks a nullable column):

- ``cases``: id*, court_id*, filed_at, closed_at?, status, case_type
- ``assignments``: case_id*, judge_id*, start_at, end_at?
- ``charges``: id*, case_id*, person_id*, filed_at, disposed_at?,
  disposition?, disposition_actor?, offense_category, severity,
  source_row_id? (the source's own charge identifier: the deterministic
  tie-break for a case's lead convicted charge, stable across re-ingests
  where the canonical id is not)
- ``decisions``: id*, case_id*, person_id*, judge_id*?, decision_type,
  decision_at, actor_type, discretion, release_at?, detained_flag?,
  release_type? (the release columns come from the decision's pretrial
  release row and are null for every other decision type)
- ``sentences``: id*, case_id*, person_id*, judge_id*?, sentence_at,
  incarceration_days?, probation_days?
- ``events``: id*, case_id*, person_id*?, judge_id*?, event_type, event_at
- ``justice_events``: id*, person_id*, event_type, event_at,
  related_case_id*? (the person's derived later events; ``event_type`` is
  a ``justice_event_type`` vocabulary value)
- ``persons``: id* (the resolved person, after merges: the frame's only
  person column)

Every timestamp column is a Polars ``Datetime`` with time zone ``UTC``
(any time unit). Day-level facts are placed on their day the way the case
timeline renders them: ``filed_at`` is 00:00:00 UTC of the filing date and
``closed_at`` the last microsecond of the closing date.

The frame is generic over the id dtype: Polars has no UUID type, so every
id column of one frame shares one dtype — ``String`` for the synthetic
world's own ids and for UUIDs rendered in their canonical text form, or
``Binary`` for a loader that keeps the sixteen bytes — and every function
in this package only compares, joins, groups, and sorts ids, never
interpreting them. ``Frame.id_dtype`` is the dtype of ``persons.id``;
validation requires every id column to match it.

``coverage_start`` and ``coverage_end`` are the source's window (inclusive
dates); ``coverage_end_exclusive_at`` is the day after ``coverage_end`` at
00:00 UTC, the instant follow-up is right-censored at. ``observable_outcomes``
lists the ``justice_event_type`` values the source can document; a metric
whose outcome is not among them is not observable for the source
(``windows.NotObservable``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import UTC, date, datetime, time, timedelta
from types import MappingProxyType

import polars as pl

from judgemetrics.normalization import vocabulary

ID = "id"
DATETIME = "datetime"
ColumnSpec = str | pl.DataType

UTC_DATETIME = pl.Datetime("us", "UTC")
# The id dtype of a frame built from string ids (the synthetic world, UUIDs as text).
STRING_ID: pl.DataType = pl.String()
SCHEMAS: Mapping[str, Mapping[str, ColumnSpec]] = MappingProxyType(
    {
        "cases": MappingProxyType(
            {
                "id": ID,
                "court_id": ID,
                "filed_at": DATETIME,
                "closed_at": DATETIME,
                "status": pl.String(),
                "case_type": pl.String(),
            }
        ),
        "assignments": MappingProxyType(
            {"case_id": ID, "judge_id": ID, "start_at": DATETIME, "end_at": DATETIME}
        ),
        "charges": MappingProxyType(
            {
                "id": ID,
                "case_id": ID,
                "person_id": ID,
                "filed_at": DATETIME,
                "disposed_at": DATETIME,
                "disposition": pl.String(),
                "disposition_actor": pl.String(),
                "offense_category": pl.String(),
                "severity": pl.String(),
                "source_row_id": pl.String(),
            }
        ),
        "decisions": MappingProxyType(
            {
                "id": ID,
                "case_id": ID,
                "person_id": ID,
                "judge_id": ID,
                "decision_type": pl.String(),
                "decision_at": DATETIME,
                "actor_type": pl.String(),
                "discretion": pl.String(),
                "release_at": DATETIME,
                "detained_flag": pl.Boolean(),
                "release_type": pl.String(),
            }
        ),
        "sentences": MappingProxyType(
            {
                "id": ID,
                "case_id": ID,
                "person_id": ID,
                "judge_id": ID,
                "sentence_at": DATETIME,
                "incarceration_days": pl.Int64(),
                "probation_days": pl.Int64(),
            }
        ),
        "events": MappingProxyType(
            {
                "id": ID,
                "case_id": ID,
                "person_id": ID,
                "judge_id": ID,
                "event_type": pl.String(),
                "event_at": DATETIME,
            }
        ),
        "justice_events": MappingProxyType(
            {
                "id": ID,
                "person_id": ID,
                "event_type": pl.String(),
                "event_at": DATETIME,
                "related_case_id": ID,
            }
        ),
        "persons": MappingProxyType({"id": ID}),
    }
)
TABLE_NAMES: tuple[str, ...] = tuple(SCHEMAS)


class FrameError(ValueError):
    """A table is missing a column, carries the wrong dtype, or the window is inverted."""


def _is_utc_datetime(dtype: pl.DataType) -> bool:
    return isinstance(dtype, pl.Datetime) and dtype.time_zone == "UTC"


def resolve_dtype(spec: ColumnSpec, id_dtype: pl.DataType) -> pl.DataType:
    """The concrete dtype of a schema column for a frame whose ids are ``id_dtype``."""
    if spec == ID:
        return id_dtype
    if spec == DATETIME:
        return UTC_DATETIME
    if isinstance(spec, pl.DataType):
        return spec
    msg = f"unknown column spec {spec!r}"
    raise FrameError(msg)


def empty_table(name: str, id_dtype: pl.DataType = STRING_ID) -> pl.DataFrame:
    """An empty, correctly typed table of the frame."""
    return pl.DataFrame(
        schema={column: resolve_dtype(spec, id_dtype) for column, spec in SCHEMAS[name].items()}
    )


def validate_table(name: str, table: pl.DataFrame, id_dtype: pl.DataType) -> None:
    """Raise ``FrameError`` unless ``table`` carries the schema's columns with the right dtypes."""
    schema = table.schema
    for column, spec in SCHEMAS[name].items():
        if column not in schema:
            msg = f"frame table {name!r} lacks column {column!r}"
            raise FrameError(msg)
        actual = schema[column]
        if spec == ID:
            if actual != id_dtype:
                msg = f"frame table {name!r} column {column!r}: id dtype {actual} != {id_dtype}"
                raise FrameError(msg)
        elif spec == DATETIME:
            if not _is_utc_datetime(actual):
                msg = f"frame table {name!r} column {column!r}: {actual} is not a UTC Datetime"
                raise FrameError(msg)
        elif actual != spec:
            msg = f"frame table {name!r} column {column!r}: dtype {actual} != {spec}"
            raise FrameError(msg)


@dataclass(frozen=True, slots=True)
class Frame:
    """The typed tables of one source plus its coverage window and observable outcomes."""

    cases: pl.DataFrame
    assignments: pl.DataFrame
    charges: pl.DataFrame
    decisions: pl.DataFrame
    sentences: pl.DataFrame
    events: pl.DataFrame
    justice_events: pl.DataFrame
    persons: pl.DataFrame
    coverage_start: date
    coverage_end: date
    observable_outcomes: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.coverage_end < self.coverage_start:
            msg = f"coverage window {self.coverage_start}..{self.coverage_end} is inverted"
            raise FrameError(msg)
        id_dtype = self.persons.schema.get("id")
        if id_dtype is None:
            msg = "frame table 'persons' lacks column 'id'"
            raise FrameError(msg)
        for name in TABLE_NAMES:
            validate_table(name, self.table(name), id_dtype)
        unknown = sorted(
            outcome
            for outcome in self.observable_outcomes
            if not vocabulary.is_known("justice_event_type", outcome)
        )
        if unknown:
            msg = f"observable outcomes {unknown} are not justice_event_type values"
            raise FrameError(msg)

    @property
    def id_dtype(self) -> pl.DataType:
        """The dtype every id column of this frame carries (that of ``persons.id``)."""
        return self.persons.schema["id"]

    @property
    def coverage_end_exclusive_at(self) -> datetime:
        """The day after ``coverage_end`` at 00:00 UTC: follow-up is censored here."""
        return datetime.combine(self.coverage_end + timedelta(days=1), time.min, UTC)

    def table(self, name: str) -> pl.DataFrame:
        if name not in SCHEMAS:
            msg = f"unknown frame table {name!r}"
            raise FrameError(msg)
        table: pl.DataFrame = getattr(self, name)
        return table

    @classmethod
    def empty(
        cls,
        coverage_start: date,
        coverage_end: date,
        observable_outcomes: frozenset[str] = frozenset(),
        id_dtype: pl.DataType = STRING_ID,
    ) -> Frame:
        """A frame with every table empty (tests and loaders start from it)."""
        return cls(
            **{name: empty_table(name, id_dtype) for name in TABLE_NAMES},
            coverage_start=coverage_start,
            coverage_end=coverage_end,
            observable_outcomes=observable_outcomes,
        )

    def replace(self, **tables: pl.DataFrame) -> Frame:
        """A copy with the named tables replaced (validated again)."""
        unknown = set(tables) - set(TABLE_NAMES)
        if unknown:
            msg = f"unknown frame tables {sorted(unknown)}"
            raise FrameError(msg)
        values = {f.name: getattr(self, f.name) for f in fields(self)}
        values.update(tables)
        return Frame(**values)
