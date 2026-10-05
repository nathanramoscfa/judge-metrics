# tests/integration/test_cook_sao_fetch.py
"""The Cook County connector at parser version 0 through the runner.

``ingest run cook_sao --from-fixture tests/fixtures/cook_sao`` stores the
five excerpted exports as five ``source_record`` rows (the objects in the
lake under hash-derived keys, path-backed and stored with ``put_file``)
and publishes no canonical row; a rerun records nothing new. The
rows-updated short-circuit is exercised end to end: the runner forwards
the previous record's rows-updated time and a fetch that sees it unchanged
downloads nothing. The run's temporary directory is gone after the run,
succeeded or failed. The CLI test commits for real and purges its runs.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Case,
    Charge,
    Court,
    IngestRun,
    IngestRunStatus,
    Judge,
    Jurisdiction,
    Person,
    Source,
    SourceRecord,
)
from judgemetrics.ingest.base import (
    PREVIOUS_ROWS_UPDATED_AT,
    PREVIOUS_SHA256,
    RawArtifact,
    SourceArtifact,
    sha256_file,
    utc_now,
)
from judgemetrics.ingest.cook_sao.connector import CookSaoConnector
from judgemetrics.ingest.cook_sao.sources import EXTERNAL_IDS
from judgemetrics.ingest.runner import WORK_DIR_PREFIX, run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import purge_run, purge_source

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cook_sao"
KEY_SHAPE = re.compile(r"^cook_sao/\d{4}/\d{2}/[0-9a-f]{64}\.csv$")
ROWS_UPDATED = "2026-04-02T14:23:42+00:00"


@pytest.fixture
def clean_session(db_session: Session) -> Session:
    """The transactional session without any committed cook_sao rows (rolled back after)."""
    purge_source(db_session, "cook_sao")
    return db_session


@pytest.fixture
def store(tmp_path: Path) -> FilesystemRawObjectStore:
    return FilesystemRawObjectStore(tmp_path / "lake")


def _run(session: Session, store: FilesystemRawObjectStore, **kwargs: object) -> IngestRun:
    return run_ingest(
        "cook_sao",
        session=session,
        store=store,
        settings=Settings(env="test"),
        **kwargs,  # type: ignore[arg-type]
    )


def _records(session: Session) -> list[SourceRecord]:
    return list(
        session.scalars(
            select(SourceRecord)
            .join(Source, Source.id == SourceRecord.source_id)
            .where(Source.name == "cook_sao")
            .order_by(SourceRecord.external_record_id)
        )
    )


def _canonical_rows(session: Session, records: list[SourceRecord]) -> int:
    ids = [record.id for record in records]
    total = 0
    for model in (Jurisdiction, Court, Judge, Person, Case, Charge):
        total += (
            session.scalar(
                select(func.count()).select_from(model).where(model.source_record_id.in_(ids))
            )
            or 0
        )
    return total


def test_the_fixture_stores_five_records_and_publishes_nothing(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    run = _run(session, store, from_fixture=FIXTURES)
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    assert run.parser_version == "0"
    assert (run.records_seen, run.records_created, run.records_updated, run.records_rejected) == (
        0,
        0,
        0,
        0,
    )
    records = _records(session)
    assert sorted(str(record.external_record_id) for record in records) == sorted(EXTERNAL_IDS)
    for record in records:
        assert KEY_SHAPE.match(record.raw_object_path), record.raw_object_path
        assert record.external_record_id is not None
        digest, _ = sha256_file(FIXTURES / record.external_record_id)
        assert record.raw_sha256 == digest
        assert record.parser_version == "0"
        assert record.ingest_run_id == run.id
        assert store.exists(record.raw_object_path)
        assert record.metadata_["uri"].startswith("https://datacatalog.cookcountyil.gov/api/views/")
    assert _canonical_rows(session, records) == 0
    source = session.scalar(select(Source).where(Source.name == "cook_sao"))
    assert source is not None
    assert source.owner == "Cook County State's Attorney's Office"
    assert source.observable_outcomes == []
    assert source.coverage_start is None and source.coverage_end is None


def test_a_rerun_records_nothing_new(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    first = _run(session, store, from_fixture=FIXTURES)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason
    second = _run(session, store, from_fixture=FIXTURES)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    records = _records(session)
    assert len(records) == len(EXTERNAL_IDS)
    assert all(record.ingest_run_id == first.id for record in records)
    assert len([p for p in (store.root / "cook_sao").rglob("*") if p.is_file()]) == 5


def test_the_rows_updated_time_short_circuits_the_download(
    clean_session: Session, store: FilesystemRawObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    session = clean_session
    work_dirs: list[Path] = []
    original = CookSaoConnector.use_work_dir

    def remember(self: CookSaoConnector, directory: Path) -> None:
        work_dirs.append(directory)
        original(self, directory)

    async def from_fixture(self: CookSaoConnector, artifact: SourceArtifact) -> RawArtifact:
        assert self._work_dir is not None
        copy = self._work_dir / f"download-{artifact.external_id}"
        copy.write_bytes((FIXTURES / artifact.external_id).read_bytes())
        return RawArtifact.from_path(
            artifact,
            copy,
            retrieved_at=utc_now(),
            response_headers={"rows_updated_at": ROWS_UPDATED, "license": "Public Domain"},
        )

    monkeypatch.setattr(CookSaoConnector, "use_work_dir", remember)
    monkeypatch.setattr(CookSaoConnector, "fetch", from_fixture)
    first = _run(session, store)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason
    assert all(r.metadata_["rows_updated_at"] == ROWS_UPDATED for r in _records(session))

    seen: list[str] = []

    async def unchanged(self: CookSaoConnector, artifact: SourceArtifact) -> RawArtifact:
        # The runner forwarded the previous record's rows-updated time and digest.
        assert artifact.metadata[PREVIOUS_ROWS_UPDATED_AT] == ROWS_UPDATED
        seen.append(artifact.external_id)
        return RawArtifact.unchanged(
            artifact,
            sha256=artifact.metadata[PREVIOUS_SHA256],
            retrieved_at=utc_now(),
            response_headers={"rows_updated_at": ROWS_UPDATED},
        )

    monkeypatch.setattr(CookSaoConnector, "fetch", unchanged)
    second = _run(session, store)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert seen == list(EXTERNAL_IDS)
    assert len(_records(session)) == len(EXTERNAL_IDS)
    assert len(work_dirs) == 2
    for directory in work_dirs:
        assert directory.name.startswith(WORK_DIR_PREFIX)
        assert not directory.exists()


def test_the_work_directory_is_removed_when_the_run_fails(
    clean_session: Session, store: FilesystemRawObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dirs: list[Path] = []
    original = CookSaoConnector.use_work_dir

    def remember(self: CookSaoConnector, directory: Path) -> None:
        work_dirs.append(directory)
        original(self, directory)

    async def half_written(self: CookSaoConnector, artifact: SourceArtifact) -> RawArtifact:
        assert self._work_dir is not None
        (self._work_dir / "download-partial.part").write_bytes(b"CASE_ID\n")
        msg = "the portal went away"
        raise RuntimeError(msg)

    monkeypatch.setattr(CookSaoConnector, "use_work_dir", remember)
    monkeypatch.setattr(CookSaoConnector, "fetch", half_written)
    run = _run(clean_session, store)
    assert run.status is IngestRunStatus.FAILED
    assert "the portal went away" in (run.failure_reason or "")
    assert work_dirs and not work_dirs[0].exists()
    assert _records(clean_session) == []


def test_cli_run_from_the_fixture(
    test_settings: Settings, migrated_database: Engine, tmp_path: Path
) -> None:
    settings = test_settings
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url
        if settings.ingest_database_url
        else settings.effective_admin_database_url,
        "JUDGEMETRICS_RAW_STORE_URL": f"file://{(tmp_path / 'lake').as_posix()}",
        "JUDGEMETRICS_LOG_FORMAT": "json",
        "JUDGEMETRICS_IDENTIFIER_PEPPER": TEST_IDENTIFIER_PEPPER,
    }
    digests = {sha256_file(FIXTURES / name)[0] for name in EXTERNAL_IDS}
    runner = CliRunner()
    run_ids: list[uuid.UUID] = []
    try:
        for _ in range(2):
            result = runner.invoke(
                app, ["ingest", "run", "cook_sao", "--from-fixture", str(FIXTURES)], env=env
            )
            found = re.search(r"^run ([0-9a-f-]{36}) ", result.output, re.MULTILINE)
            if found is not None:
                run_ids.append(uuid.UUID(found.group(1)))
            assert result.exit_code == 0, result.output
            assert "source=cook_sao status=succeeded seen=0 created=0" in result.output
        assert len(run_ids) == 2
        with Session(migrated_database) as session:
            fixture_records = [r for r in _records(session) if r.raw_sha256 in digests]
            assert len(fixture_records) == len(EXTERNAL_IDS)
            # The rerun recorded nothing new.
            assert not [r for r in fixture_records if r.ingest_run_id == run_ids[1]]
    finally:
        # The CLI committed for real; remove exactly what its runs created.
        with Session(migrated_database) as session:
            for run_id in run_ids:
                purge_run(session, run_id)
            session.commit()
