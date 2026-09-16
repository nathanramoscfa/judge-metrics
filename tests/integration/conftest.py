# tests/integration/conftest.py
"""Fixtures for the API tests: a committed FJC fixture ingest and a client.

The API opens its own sessions, so the data it reads must be committed —
the transactional ``db_session`` of the root conftest cannot feed it. The
``fjc_fixture`` fixture runs the fourteen-step runner once per test module
against the fixture excerpt (``tests/fixtures/fjc``) and, at module
teardown, removes exactly what that run created. On a database that
already holds a live FJC ingest the fixture rows resolve to the existing
judges and courts (same natural keys), so the tests assert against the
fixture's judges by their public FJC ids and never against absolute totals.
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
from sqlalchemy import Engine, delete, select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Court,
    DataQualityIssue,
    IngestRun,
    IngestRunStatus,
    Judge,
    JudgeService,
    Jurisdiction,
    SourceRecord,
)
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.main import create_app

FJC_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fjc"


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
