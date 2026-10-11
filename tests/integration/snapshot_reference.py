# tests/integration/snapshot_reference.py
"""The Phase 3 snapshot export, kept verbatim as the oracle for the streamed export.

``reference_frames(session)`` is ``snapshot._export_rows`` as it was before Phase 5 Step 6:
every table read with ``session.execute(...).all()``, turned into a Polars frame cell by cell in
Python. ``tests/integration/test_snapshot_export.py`` writes these frames to Parquet and requires
the streamed export (server-side cursor, batches, conversions in SQL) to produce the very same
bytes, hence the same content hash, on the golden data.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, time
from enum import Enum
from typing import Any

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.capabilities import CapabilityError, SourceCapabilities
from judgemetrics.metrics.snapshot import (
    CHARGE,
    COURT,
    COURT_CASE,
    COURT_EVENT,
    DECISION,
    JUDGE,
    JUDGE_ASSIGNMENT,
    JUSTICE_EVENT,
    PARQUET_SCHEMAS,
    PERSON,
    PRETRIAL_RELEASE,
    REPLACED_KEY,
    SENTENCE,
    SOURCE,
    SOURCE_RECORD,
    SnapshotError,
)


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Enum):
        return str(value.value)
    return str(value)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _start_of_day(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.min)


def _end_of_day(day: date | None) -> datetime | None:
    return None if day is None else datetime.combine(day, time.max)


def _frame(name: str, rows: Sequence[tuple[Any, ...]]) -> pl.DataFrame:
    schema = dict(PARQUET_SCHEMAS[name])
    return pl.DataFrame(list(rows), schema=schema, orient="row")


# --- export ------------------------------------------------------------------------------


def reference_frames(session: Session) -> dict[str, pl.DataFrame]:
    """Every snapshot table as a Polars frame, ordered by id, with the Parquet schema."""
    frames: dict[str, pl.DataFrame] = {}

    cases = session.execute(
        select(
            COURT_CASE.c.id,
            COURT_CASE.c.court_id,
            SOURCE_RECORD.c.source_id,
            COURT_CASE.c.filed_date,
            COURT_CASE.c.closed_date,
            COURT_CASE.c.status,
            COURT_CASE.c.case_type,
        )
        .join(SOURCE_RECORD, SOURCE_RECORD.c.id == COURT_CASE.c.source_record_id)
        .order_by(COURT_CASE.c.id)
    ).all()
    frames["cases"] = _frame(
        "cases",
        [
            (
                _text(row.id),
                _text(row.court_id),
                _text(row.source_id),
                _start_of_day(row.filed_date),
                _end_of_day(row.closed_date),
                _text(row.status),
                _text(row.case_type),
            )
            for row in cases
        ],
    )

    assignments = session.execute(
        select(
            JUDGE_ASSIGNMENT.c.id,
            JUDGE_ASSIGNMENT.c.case_id,
            JUDGE_ASSIGNMENT.c.judge_id,
            JUDGE_ASSIGNMENT.c.start_at,
            JUDGE_ASSIGNMENT.c.end_at,
        ).order_by(JUDGE_ASSIGNMENT.c.id)
    ).all()
    frames["assignments"] = _frame(
        "assignments",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.judge_id),
                _naive_utc(row.start_at),
                _naive_utc(row.end_at),
            )
            for row in assignments
        ],
    )

    charges = session.execute(
        select(
            CHARGE.c.id,
            CHARGE.c.case_id,
            CHARGE.c.person_id,
            CHARGE.c.filed_at,
            CHARGE.c.disposed_at,
            CHARGE.c.disposition,
            CHARGE.c.disposition_actor,
            CHARGE.c.offense_category,
            CHARGE.c.severity,
            CHARGE.c.source_row_id,
            CHARGE.c.judge_id,
        ).order_by(CHARGE.c.id)
    ).all()
    frames["charges"] = _frame(
        "charges",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _naive_utc(row.filed_at),
                _naive_utc(row.disposed_at),
                _text(row.disposition),
                _text(row.disposition_actor),
                _text(row.offense_category),
                _text(row.severity),
                _text(row.source_row_id),
                _text(row.judge_id),
            )
            for row in charges
        ],
    )

    decisions = session.execute(
        select(
            DECISION.c.id,
            DECISION.c.case_id,
            DECISION.c.person_id,
            DECISION.c.judge_id,
            DECISION.c.decision_type,
            DECISION.c.decision_at,
            DECISION.c.actor_type,
            DECISION.c.judicial_discretion_classification,
            PRETRIAL_RELEASE.c.release_at,
            PRETRIAL_RELEASE.c.detained_flag,
            PRETRIAL_RELEASE.c.release_type,
        )
        .join(PRETRIAL_RELEASE, PRETRIAL_RELEASE.c.decision_id == DECISION.c.id, isouter=True)
        .order_by(DECISION.c.id)
    ).all()
    frames["decisions"] = _frame(
        "decisions",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _text(row.judge_id),
                _text(row.decision_type),
                _naive_utc(row.decision_at),
                _text(row.actor_type),
                _text(row.judicial_discretion_classification),
                _naive_utc(row.release_at),
                row.detained_flag,
                _text(row.release_type),
            )
            for row in decisions
        ],
    )

    sentences = session.execute(
        select(
            SENTENCE.c.id,
            SENTENCE.c.case_id,
            SENTENCE.c.person_id,
            SENTENCE.c.judge_id,
            SENTENCE.c.sentence_at,
            SENTENCE.c.incarceration_days,
            SENTENCE.c.probation_days,
            SENTENCE.c.sentence_components[REPLACED_KEY].as_boolean().label(REPLACED_KEY),
        ).order_by(SENTENCE.c.id)
    ).all()
    frames["sentences"] = _frame(
        "sentences",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _text(row.judge_id),
                _naive_utc(row.sentence_at),
                row.incarceration_days,
                row.probation_days,
                bool(row.replaced),
            )
            for row in sentences
        ],
    )

    events = session.execute(
        select(
            COURT_EVENT.c.id,
            COURT_EVENT.c.case_id,
            COURT_EVENT.c.person_id,
            COURT_EVENT.c.judge_id,
            COURT_EVENT.c.event_type,
            COURT_EVENT.c.event_at,
        ).order_by(COURT_EVENT.c.id)
    ).all()
    frames["events"] = _frame(
        "events",
        [
            (
                _text(row.id),
                _text(row.case_id),
                _text(row.person_id),
                _text(row.judge_id),
                _text(row.event_type),
                _naive_utc(row.event_at),
            )
            for row in events
        ],
    )

    justice = session.execute(
        select(
            JUSTICE_EVENT.c.id,
            JUSTICE_EVENT.c.person_id,
            JUSTICE_EVENT.c.event_type,
            JUSTICE_EVENT.c.event_at,
            JUSTICE_EVENT.c.related_case_id,
        ).order_by(JUSTICE_EVENT.c.id)
    ).all()
    frames["justice_events"] = _frame(
        "justice_events",
        [
            (
                _text(row.id),
                _text(row.person_id),
                _text(row.event_type),
                _naive_utc(row.event_at),
                _text(row.related_case_id),
            )
            for row in justice
        ],
    )

    persons = session.execute(
        select(PERSON.c.id, PERSON.c.merged_into_person_id).order_by(PERSON.c.id)
    ).all()
    frames["persons"] = _frame(
        "persons", [(_text(row.id), _text(row.merged_into_person_id)) for row in persons]
    )

    judges = session.execute(select(JUDGE.c.id).order_by(JUDGE.c.id)).all()
    frames["judges"] = _frame("judges", [(_text(row.id),) for row in judges])

    courts = session.execute(select(COURT.c.id, COURT.c.jurisdiction_id).order_by(COURT.c.id)).all()
    frames["courts"] = _frame(
        "courts", [(_text(row.id), _text(row.jurisdiction_id)) for row in courts]
    )

    sources = session.execute(
        select(
            SOURCE.c.id,
            SOURCE.c.name,
            SOURCE.c.source_type,
            SOURCE.c.coverage_start,
            SOURCE.c.coverage_end,
            SOURCE.c.observable_outcomes,
            SOURCE.c.capabilities,
        ).order_by(SOURCE.c.id)
    ).all()
    source_rows: list[tuple[Any, ...]] = []
    for row in sources:
        try:
            capabilities = SourceCapabilities.from_json(row.capabilities)
        except CapabilityError as exc:
            msg = f"source {row.name} declares invalid capabilities: {exc}"
            raise SnapshotError(msg) from exc
        source_rows.append(
            (
                _text(row.id),
                _text(row.name),
                _text(row.source_type),
                row.coverage_start,
                row.coverage_end,
                sorted(str(item) for item in (row.observable_outcomes or [])),
                list(capabilities.judge_gates),
                capabilities.person_key_scope,
                list(capabilities.revocation_scopes),
            )
        )
    frames["sources"] = _frame("sources", source_rows)
    return frames
