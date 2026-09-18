# tests/integration/conftest.py
"""Fixtures for the API tests: committed FJC and golden fixture ingests and a client.

The API opens its own sessions, so the data it reads must be committed —
the transactional ``db_session`` of the root conftest cannot feed it. The
``fjc_fixture`` fixture runs the fourteen-step runner once per test module
against the fixture excerpt (``tests/fixtures/fjc``) and, at module
teardown, removes exactly what that run created. On a database that
already holds a live FJC ingest the fixture rows resolve to the existing
judges and courts (same natural keys), so the tests assert against the
fixture's judges by their public FJC ids and never against absolute totals.

``golden_fixture`` ingests the golden synthetic dataset
(``tests/fixtures/golden``) the same way. The golden and demo datasets
share natural keys (judge codes, participant ids, case numbers), so the
fixture first purges every row of the ``synthetic`` source — on a
developer's database that is the demo seed, which ``uv run poe seed``
restores in seconds — and purges the source again at teardown. The
merges the ingest performs write ``audit_log`` rows that are append-only
by trigger and therefore stay; they carry ids and counts only.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Case,
    CaseParty,
    Charge,
    Court,
    CourtEvent,
    DataQualityIssue,
    Decision,
    EntityResolutionCandidate,
    IngestRun,
    IngestRunStatus,
    Judge,
    JudgeAssignment,
    JudgeService,
    Jurisdiction,
    JusticeEvent,
    Person,
    PersonIdentifier,
    PretrialRelease,
    Sentence,
    Source,
    SourceRecord,
)
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.main import create_app

FJC_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fjc"
GOLDEN_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "golden"
SYNTHETIC_SOURCE = "synthetic"


@dataclass(frozen=True)
class FjcFixture:
    """Handles into the committed fixture data, looked up by public FJC ids."""

    run_id: uuid.UUID
    judge_ids: dict[str, uuid.UUID]  # fjc_nid → judge.id
    court_ids: dict[str, uuid.UUID]  # canonical name → court.id
    jurisdiction_id: uuid.UUID


def purge_run(session: Session, run_id: uuid.UUID) -> None:
    """Delete what one committed run created: its issues, the rows its records own, its records.

    Rows an earlier run already published (a live ingest on the developer's
    database) reference that run's records and are left alone.
    """
    records = select(SourceRecord.id).where(SourceRecord.ingest_run_id == run_id)
    session.execute(delete(DataQualityIssue).where(DataQualityIssue.source_record_id.in_(records)))
    session.execute(delete(JudgeService).where(JudgeService.source_record_id.in_(records)))
    session.execute(delete(Judge).where(Judge.source_record_id.in_(records)))
    session.execute(delete(Court).where(Court.source_record_id.in_(records)))
    session.execute(delete(Jurisdiction).where(Jurisdiction.source_record_id.in_(records)))
    session.execute(delete(SourceRecord).where(SourceRecord.ingest_run_id == run_id))
    session.execute(delete(IngestRun).where(IngestRun.id == run_id))
    session.flush()


@pytest.fixture(scope="module")
def fjc_fixture(
    migrated_database: Engine, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[FjcFixture]:
    """The FJC fixture excerpt ingested and committed for the module."""
    store = FilesystemRawObjectStore(tmp_path_factory.mktemp("lake"))
    with Session(migrated_database) as session:
        run = run_ingest(
            "fjc",
            session=session,
            store=store,
            settings=Settings(env="test"),
            from_fixture=FJC_FIXTURES,
        )
        assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
        session.commit()
        run_id = run.id
        judge_ids = {
            nid: judge_id
            for judge_id, nid in session.execute(
                select(Judge.id, Judge.external_ids["fjc_nid"].astext).where(
                    Judge.external_ids.has_key("fjc_nid")
                )
            ).all()
        }
        court_ids = {
            name: court_id
            for court_id, name in session.execute(select(Court.id, Court.canonical_name)).all()
        }
        jurisdiction_id = session.scalar(
            select(Jurisdiction.id).where(Jurisdiction.name == "United States federal courts")
        )
        assert jurisdiction_id is not None
    try:
        yield FjcFixture(
            run_id=run_id,
            judge_ids=judge_ids,
            court_ids=court_ids,
            jurisdiction_id=jurisdiction_id,
        )
    finally:
        with Session(migrated_database) as session:
            purge_run(session, run_id)
            session.commit()


@dataclass(frozen=True)
class GoldenFixture:
    """Handles into the committed golden synthetic ingest, by the dataset's own codes."""

    run_id: uuid.UUID
    judge_ids: dict[str, uuid.UUID]  # synthetic judge code (J-0001) → judge.id
    court_ids: dict[str, uuid.UUID]  # court code (C-0001) → court.id
    case_ids: dict[str, uuid.UUID]  # normalized case number → court_case.id
    jurisdiction_id: uuid.UUID


def purge_source(session: Session, name: str) -> None:
    """Delete every row derived from source ``name`` (FK order), and the source itself.

    Resolution bookkeeping goes first: candidates, then the merge pointers
    (a self reference with RESTRICT) before the person rows. ``audit_log``
    rows cannot be deleted (append-only trigger) and are left as history.
    """
    source_id = session.scalar(select(Source.id).where(Source.name == name))
    if source_id is None:
        return
    records = select(SourceRecord.id).where(SourceRecord.source_id == source_id)
    session.execute(delete(DataQualityIssue).where(DataQualityIssue.source_record_id.in_(records)))
    session.execute(delete(JusticeEvent).where(JusticeEvent.source_record_id.in_(records)))
    decisions = select(Decision.id).where(Decision.source_record_id.in_(records))
    session.execute(delete(PretrialRelease).where(PretrialRelease.decision_id.in_(decisions)))
    for model in (Sentence, Decision, CourtEvent, Charge, JudgeAssignment, CaseParty):
        session.execute(delete(model).where(model.source_record_id.in_(records)))
    session.execute(delete(Case).where(Case.source_record_id.in_(records)))
    persons = select(Person.id).where(Person.source_record_id.in_(records))
    session.execute(delete(PersonIdentifier).where(PersonIdentifier.person_id.in_(persons)))
    session.execute(
        delete(EntityResolutionCandidate).where(
            EntityResolutionCandidate.left_record_id.in_(persons)
            | EntityResolutionCandidate.right_record_id.in_(persons)
        )
    )
    session.execute(
        update(Person)
        .where(Person.source_record_id.in_(records))
        .values(merged_into_person_id=None)
    )
    session.execute(delete(Person).where(Person.source_record_id.in_(records)))
    session.execute(delete(JudgeService).where(JudgeService.source_record_id.in_(records)))
    session.execute(delete(Judge).where(Judge.source_record_id.in_(records)))
    session.execute(delete(Court).where(Court.source_record_id.in_(records)))
    session.execute(delete(Jurisdiction).where(Jurisdiction.source_record_id.in_(records)))
    session.execute(delete(SourceRecord).where(SourceRecord.source_id == source_id))
    session.execute(delete(IngestRun).where(IngestRun.source_id == source_id))
    session.execute(delete(Source).where(Source.id == source_id))
    session.flush()


def purge_synthetic(engine: Engine) -> None:
    """Remove the ``synthetic`` source and everything derived from it, committed."""
    with Session(engine) as session:
        purge_source(session, SYNTHETIC_SOURCE)
        session.commit()


@pytest.fixture(scope="module")
def golden_fixture(
    migrated_database: Engine, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[GoldenFixture]:
    """The golden synthetic dataset ingested and committed for the module (see the module doc)."""
    purge_synthetic(migrated_database)
    store = FilesystemRawObjectStore(tmp_path_factory.mktemp("golden-lake"))
    with Session(migrated_database) as session:
        run = run_ingest(
            SYNTHETIC_SOURCE,
            session=session,
            store=store,
            settings=Settings(env="test"),
            from_fixture=GOLDEN_FIXTURES,
        )
        assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
        session.commit()
        run_id = run.id
        judge_ids = {
            code: judge_id
            for judge_id, code in session.execute(
                select(Judge.id, Judge.external_ids["synthetic_judge_code"].astext).where(
                    Judge.external_ids.has_key("synthetic_judge_code")
                )
            ).all()
        }
        court_ids = {
            code: court_id
            for court_id, code in session.execute(
                select(Court.id, Court.external_ids["synthetic_court_code"].astext).where(
                    Court.external_ids.has_key("synthetic_court_code")
                )
            ).all()
        }
        case_ids = {
            number: case_id
            for case_id, number in session.execute(
                select(Case.id, Case.case_number_normalized)
                .join(SourceRecord, SourceRecord.id == Case.source_record_id)
                .where(SourceRecord.ingest_run_id == run_id)
            ).all()
        }
        jurisdiction_id = session.scalar(
            select(Jurisdiction.id).where(Jurisdiction.name == "Synthetic State")
        )
        assert jurisdiction_id is not None
    try:
        yield GoldenFixture(
            run_id=run_id,
            judge_ids=judge_ids,
            court_ids=court_ids,
            case_ids=case_ids,
            jurisdiction_id=jurisdiction_id,
        )
    finally:
        purge_synthetic(migrated_database)


def make_app(settings: Settings, **overrides: Any) -> FastAPI:
    """A fresh app for the read-only role under the test environment."""
    values: dict[str, Any] = {
        "env": "test",
        "database_url": settings.database_url,
        "log_format": "json",
        **overrides,
    }
    return create_app(Settings(**values))


@pytest.fixture(scope="module")
def api(fjc_fixture: FjcFixture) -> Iterator[TestClient]:
    """The API over the module's fixture data (the limiter is off under `env == test`).

    Server errors are rendered through the handlers, not re-raised, so the
    500 envelope can be asserted.
    """
    app = make_app(Settings())
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()
