# tests/integration/test_fjc_ingest.py
"""End-to-end FJC ingest from the fixture excerpt.

Runs the fourteen-step runner twice (and once forced) inside the
transactional test session: counts, provenance down to the stored raw
bytes, idempotency, the two data-quality issues the fixture plants by row
selection, validation failure, and the production refusals. The CLI test
commits for real and cleans up after itself.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import shutil
import uuid
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import Engine, delete, func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app
from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Court,
    DataQualityIssue,
    IngestRun,
    IngestRunStatus,
    IssueSeverity,
    Judge,
    JudgeService,
    Jurisdiction,
    Source,
    SourceRecord,
)
from judgemetrics.ingest import registry
from judgemetrics.ingest.base import (
    PREVIOUS_SHA256,
    CanonicalRecord,
    RawArtifact,
    SourceArtifact,
    SourceInfo,
    SourceRecordDraft,
    ValidationResult,
    utc_now,
)
from judgemetrics.ingest.fjc.connector import FjcConnector
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.test_synthetic_ingest import purge_source as purge_synthetic_source

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "fjc"
JUDGES_FILE = FIXTURES / "judges.csv"
SERVICE_FILE = FIXTURES / "federal-judicial-service.csv"
EXPECTED_JUDGES = 25
EXPECTED_SERVICE = 42
EXPECTED_COURTS = 28
EXPECTED_JURISDICTIONS = 1
KEY_SHAPE = re.compile(r"^fjc/\d{4}/\d{2}/[0-9a-f]{64}\.csv$")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def purge_source(session: Session, name: str) -> None:
    """Delete every row derived from source ``name`` (FK order), and the source itself."""
    source_id = session.scalar(select(Source.id).where(Source.name == name))
    if source_id is None:
        return
    records = select(SourceRecord.id).where(SourceRecord.source_id == source_id)
    session.execute(delete(DataQualityIssue).where(DataQualityIssue.source_record_id.in_(records)))
    session.execute(delete(JudgeService).where(JudgeService.source_record_id.in_(records)))
    session.execute(delete(Judge).where(Judge.source_record_id.in_(records)))
    session.execute(delete(Court).where(Court.source_record_id.in_(records)))
    session.execute(delete(Jurisdiction).where(Jurisdiction.source_record_id.in_(records)))
    session.execute(delete(SourceRecord).where(SourceRecord.source_id == source_id))
    session.execute(delete(IngestRun).where(IngestRun.source_id == source_id))
    session.execute(delete(Source).where(Source.id == source_id))
    session.flush()


@pytest.fixture
def clean_session(db_session: Session) -> Session:
    """The transactional session with every FJC- and synthetic-derived row removed.

    The synthetic rows go too (rolled back afterwards) because these tests
    count judges, courts, and jurisdictions absolutely and a developer's
    database may hold a `uv run poe seed`.
    """
    purge_synthetic_source(db_session, "synthetic")
    purge_source(db_session, "fjc")
    return db_session


@pytest.fixture
def store(tmp_path: Path) -> FilesystemRawObjectStore:
    return FilesystemRawObjectStore(tmp_path / "lake")


def _run(
    session: Session,
    store: FilesystemRawObjectStore,
    *,
    fixture: Path = FIXTURES,
    force: bool = False,
    env: str = "test",
) -> IngestRun:
    return run_ingest(
        "fjc",
        session=session,
        store=store,
        settings=Settings(env=env),
        from_fixture=fixture,
        force=force,
    )


def _count(session: Session, model: type[Judge | Court | Jurisdiction | JudgeService]) -> int:
    return session.scalar(select(func.count()).select_from(model)) or 0


def _judge(session: Session, nid: str) -> Judge:
    judge = session.scalar(select(Judge).where(Judge.external_ids["fjc_nid"].astext == nid))
    assert judge is not None, nid
    return judge


def _services(session: Session, judge: Judge) -> list[JudgeService]:
    stmt = (
        select(JudgeService)
        .where(JudgeService.judge_id == judge.id)
        .order_by(JudgeService.start_date.nulls_last(), JudgeService.position_type)
    )
    return list(session.scalars(stmt))


def _court(session: Session, name: str) -> Court:
    court = session.scalar(select(Court).where(Court.canonical_name == name))
    assert court is not None, name
    return court


def _issues(session: Session) -> list[DataQualityIssue]:
    records = select(SourceRecord.id).join(Source).where(Source.name == "fjc")
    stmt = (
        select(DataQualityIssue)
        .where(DataQualityIssue.source_record_id.in_(records))
        .order_by(DataQualityIssue.issue_code)
    )
    return list(session.scalars(stmt))


# --- the first run -----------------------------------------------------------------


def test_first_run_publishes_every_row_with_provenance(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    run = _run(session, store)
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    assert run.completed_at is not None
    assert run.failure_reason is None
    assert run.parser_version == "2026.09.1"
    assert run.code_version == "unknown" or re.fullmatch(r"[0-9a-f]{40}", run.code_version)
    assert run.records_seen == EXPECTED_JUDGES + EXPECTED_SERVICE
    assert run.records_created == (
        EXPECTED_JURISDICTIONS + EXPECTED_COURTS + EXPECTED_JUDGES + EXPECTED_SERVICE
    )
    assert run.records_updated == 0
    assert run.records_rejected == 0

    assert _count(session, Judge) == EXPECTED_JUDGES
    assert _count(session, JudgeService) == EXPECTED_SERVICE
    assert _count(session, Court) == EXPECTED_COURTS
    jurisdictions = list(session.scalars(select(Jurisdiction)))
    assert [(j.name, j.type.value, j.state_code) for j in jurisdictions] == [
        ("United States federal courts", "federal", None)
    ]

    source = session.scalar(select(Source).where(Source.name == "fjc"))
    assert source is not None
    assert "Federal Judicial Center" in source.owner
    assert source.terms_metadata["redistribution"]["commercial"] == "yes"

    records = {
        record.external_record_id: record
        for record in session.scalars(
            select(SourceRecord).where(SourceRecord.source_id == source.id)
        )
    }
    assert set(records) == {"judges.csv", "federal-judicial-service.csv"}
    expected_sha = {
        "judges.csv": _sha(JUDGES_FILE),
        "federal-judicial-service.csv": _sha(SERVICE_FILE),
    }
    for name, record in records.items():
        assert name is not None
        assert record.raw_sha256 == expected_sha[name]
        assert record.ingest_run_id == run.id
        assert record.parser_version == "2026.09.1"
        assert KEY_SHAPE.match(record.raw_object_path), record.raw_object_path
        assert record.raw_object_path.endswith(f"{record.raw_sha256}.csv")
        # The stored raw object is byte-identical to what the record claims.
        assert store.exists(record.raw_object_path)
        assert hashlib.sha256(store.get(record.raw_object_path)).hexdigest() == record.raw_sha256
        assert record.metadata_["uri"].startswith("https://www.fjc.gov/")
        assert record.metadata_["export_page"].startswith("https://www.fjc.gov/")
        assert record.metadata_["final_url"].startswith("file:")
        assert record.retrieved_at.tzinfo is not None

    # Every canonical row references the record of the file it came from.
    by_id = {record.id: record for record in records.values()}
    for judge in session.scalars(select(Judge)):
        assert by_id[judge.source_record_id].external_record_id == "judges.csv"
    for row in [
        *session.scalars(select(Court)),
        *session.scalars(select(JudgeService)),
        *jurisdictions,
    ]:
        assert by_id[row.source_record_id].external_record_id == "federal-judicial-service.csv"


# --- idempotency -------------------------------------------------------------------


def test_second_and_forced_runs_create_and_update_nothing(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    first = _run(session, store)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason
    snapshot = (
        _count(session, Judge),
        _count(session, JudgeService),
        _count(session, Court),
        _count(session, Jurisdiction),
        len(_issues(session)),
    )
    updated_at = {judge.id: judge.updated_at for judge in session.scalars(select(Judge))}

    second = _run(session, store)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert second.id != first.id
    assert (second.records_seen, second.records_created, second.records_updated) == (0, 0, 0)
    assert second.records_rejected == 0
    # Unchanged hashes reuse the existing source records: none were added.
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2
    assert all(record.ingest_run_id == first.id for record in session.scalars(select(SourceRecord)))

    forced = _run(session, store, force=True)
    assert forced.status is IngestRunStatus.SUCCEEDED, forced.failure_reason
    assert forced.records_seen == EXPECTED_JUDGES + EXPECTED_SERVICE
    assert (forced.records_created, forced.records_updated, forced.records_rejected) == (0, 0, 0)

    assert (
        _count(session, Judge),
        _count(session, JudgeService),
        _count(session, Court),
        _count(session, Jurisdiction),
        len(_issues(session)),
    ) == snapshot
    session.expire_all()
    assert {judge.id: judge.updated_at for judge in session.scalars(select(Judge))} == updated_at
    runs = list(session.scalars(select(IngestRun).order_by(IngestRun.started_at)))
    assert [run.status for run in runs] == [IngestRunStatus.SUCCEEDED] * 3


def test_a_changed_artifact_updates_only_changed_rows(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    session = clean_session
    first = _run(session, store)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason

    # Alito's Supreme Court service ends: one changed service row, one changed judge status.
    edited = tmp_path / "edited"
    edited.mkdir()
    shutil.copy(JUDGES_FILE, edited / "judges.csv")
    with SERVICE_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    header = rows[0]
    for row in rows[1:]:
        if row[header.index("nid")] == "1377101" and row[header.index("Sequence")] == "2":
            row[header.index("Termination")] = "Retirement"
            row[header.index("Termination Date")] = "2030-06-30"
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerows(rows)
    (edited / "federal-judicial-service.csv").write_text(out.getvalue(), encoding="utf-8")

    second = _run(session, store, fixture=edited)
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert second.records_seen == EXPECTED_SERVICE  # judges.csv was unchanged and skipped
    assert second.records_created == 0
    assert second.records_updated == 1
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 3
    service = [
        s
        for s in _services(session, _judge(session, "1377101"))
        if s.position_type == "Associate Justice"
    ]
    assert len(service) == 1
    assert service[0].end_date == date(2030, 6, 30)
    assert service[0].metadata_["termination"] == "Retirement"
    new_record = session.get(SourceRecord, service[0].source_record_id)
    assert new_record is not None and new_record.ingest_run_id == second.id
    # Untouched rows keep their original provenance.
    other = _court(session, "U.S. District Court for the District of Maryland")
    assert session.get(SourceRecord, other.source_record_id).ingest_run_id == first.id  # type: ignore[union-attr]


# --- normalized values --------------------------------------------------------------


def test_normalized_judges_courts_and_service(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED

    alito = _judge(session, "1377101")
    assert alito.canonical_name == "Samuel A. Alito, Jr."
    assert alito.normalized_name == "samuel a alito jr"
    assert alito.status == "active"
    assert alito.metadata_ == {"birth_year": 1950}
    assert alito.external_ids == {"fjc_nid": "1377101", "fjc_jid": alito.external_ids["fjc_jid"]}
    services = _services(session, alito)
    assert [
        (s.court.canonical_name, s.court.court_type, s.position_type, s.start_date, s.end_date)
        for s in services
    ] == [
        (
            "U.S. Court of Appeals for the Third Circuit",
            "appeals",
            "Judge",
            date(1990, 4, 30),
            date(2006, 1, 31),
        ),
        (
            "Supreme Court of the United States",
            "supreme",
            "Associate Justice",
            date(2006, 1, 31),
            None,
        ),
    ]

    assert _judge(session, "1377031").status == "senior"  # Henry Lee Adams, Jr.
    assert _judge(session, "1377251").status == "removed"  # Archbald, impeached and convicted
    assert _judge(session, "1381271").status == "deceased"  # Ruth Bader Ginsburg
    assert _judge(session, "1377011").status == "retired"  # Arlin Adams
    assert _judge(session, "1377021").status == "resigned"  # George Adams
    andrews = _judge(session, "1390306")  # recess appointment only, never confirmed
    assert andrews.status == "inactive"
    (recess,) = _services(session, andrews)
    assert recess.start_date == date(1949, 10, 21)
    assert recess.metadata_["start_date_basis"] == "recess_appointment_date"
    assert _judge(session, "1383686").metadata_ == {
        "birth_year": 1793,
        "birth_year_approximate": True,
    }
    assert _judge(session, "13762064").metadata_ == {}
    assert _judge(session, "1377066").canonical_name == "Arthur Lawrence Alarcón"
    assert _judge(session, "1377066").normalized_name == "arthur lawrence alarcon"

    groner = _judge(session, "1381546")
    chief = [s for s in _services(session, groner) if s.position_type == "Chief Justice"]
    assert chief[0].metadata_ == {
        "fjc_sequence": "3",
        "start_date_basis": "commission_date",
        "senior_status_date": "1948-03-08",
        "termination": "Death",
    }

    federal = session.scalar(select(Jurisdiction))
    assert federal is not None
    for name, court_type, state in (
        ("U.S. District Court for the District of Maryland", "district", "MD"),
        ("U.S. District Court for the District of Puerto Rico", "district", "PR"),
        ("U.S. District Court for the District of Columbia", "district", "DC"),
        ("U.S. District Court for the Southern District of New York", "district", "NY"),
        ("U.S. Court of International Trade", "other", None),
        ("U.S. Circuit Courts for the Third Circuit", "other", None),
        ("U.S. Circuit Court for the Districts of California", "other", None),
        ("U.S. Court of Appeals for the Ninth Circuit", "appeals", None),
        ("Supreme Court of the United States", "supreme", None),
    ):
        court = _court(session, name)
        assert (court.court_type, court.state_code) == (court_type, state), name
        assert court.jurisdiction_id == federal.id
        assert court.external_ids == {"fjc_court_name": name}


# --- data-quality issues -------------------------------------------------------------


def test_the_two_planted_quality_issues_are_persisted(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    session = clean_session
    assert _run(session, store).status is IngestRunStatus.SUCCEEDED
    issues = _issues(session)
    assert [(issue.issue_code, issue.severity) for issue in issues] == [
        ("missing_start_date", IssueSeverity.INFO),
        ("service_overlap", IssueSeverity.WARNING),
    ]
    missing, overlap = issues
    service_record = session.scalar(
        select(SourceRecord).where(
            SourceRecord.external_record_id == "federal-judicial-service.csv"
        )
    )
    assert service_record is not None
    assert missing.source_record_id == overlap.source_record_id == service_record.id

    assert "13762157" in missing.description  # Byrne: nominated, no commission date yet
    byrne_service = _services(session, _judge(session, "13762157"))
    assert [s.id for s in byrne_service] == [missing.entity_id]
    assert missing.entity_type == "judge_service"

    assert "1381546" in overlap.description  # Groner: two overlapping D.C. Circuit appointments
    assert "District of Columbia Circuit" in overlap.description
    groner_chief = [
        s
        for s in _services(session, _judge(session, "1381546"))
        if s.position_type == "Chief Justice"
    ]
    assert overlap.entity_id == groner_chief[0].id
    assert all(issue.status.value == "open" for issue in issues)


# --- failure paths -------------------------------------------------------------------


def test_missing_header_fails_the_run_and_publishes_nothing(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    session = clean_session
    broken = tmp_path / "broken"
    broken.mkdir()
    shutil.copy(JUDGES_FILE, broken / "judges.csv")
    with SERVICE_FILE.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    column = rows[0].index("Commission Date")
    out = io.StringIO()
    writer = csv.writer(out, quoting=csv.QUOTE_ALL, lineterminator="\n")
    writer.writerows(row[:column] + row[column + 1 :] for row in rows)
    (broken / "federal-judicial-service.csv").write_text(out.getvalue(), encoding="utf-8")

    run = _run(session, store, fixture=broken)
    assert run.status is IngestRunStatus.FAILED
    assert run.failure_reason is not None
    assert "missing expected header 'Commission Date'" in run.failure_reason
    assert run.completed_at is not None
    # The publish transaction rolled back: no records, no rows; only the run remains.
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 0
    assert _count(session, Judge) == 0
    persisted = session.get(IngestRun, run.id)
    assert persisted is not None and persisted.status is IngestRunStatus.FAILED


def test_missing_fixture_file_fails_the_run(
    clean_session: Session, store: FilesystemRawObjectStore, tmp_path: Path
) -> None:
    run = _run(clean_session, store, fixture=tmp_path)
    assert run.status is IngestRunStatus.FAILED
    assert run.failure_reason is not None and "fixture file missing" in run.failure_reason


def test_fixture_ingest_is_refused_in_production(
    clean_session: Session, store: FilesystemRawObjectStore
) -> None:
    run = _run(clean_session, store, env="production")
    assert run.status is IngestRunStatus.REFUSED
    assert run.failure_reason == "fixture ingests are refused in production"
    assert _count(clean_session, Judge) == 0


class _SyntheticStub:
    source_id = "synthetic-stub"
    parser_version = "0"
    source_info = SourceInfo(owner="tests", source_type="synthetic", access_method="generated")

    async def discover(self) -> list[SourceArtifact]:
        return [SourceArtifact(self.source_id, "seed.csv", "memory://seed", "text/csv")]

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:  # pragma: no cover
        raise NotImplementedError

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:  # pragma: no cover
        return ValidationResult.passed()

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:  # pragma: no cover
        return []

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:  # pragma: no cover
        return []


def test_synthetic_source_is_refused_in_production(
    db_session: Session, store: FilesystemRawObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        registry, "_REGISTRY", {**registry._REGISTRY, "synthetic-stub": _SyntheticStub}
    )  # noqa: SLF001
    run = run_ingest(
        "synthetic-stub",
        session=db_session,
        store=store,
        settings=Settings(env="production"),
    )
    assert run.status is IngestRunStatus.REFUSED
    assert run.failure_reason == "synthetic sources are refused in production"
    # The same source runs outside production (and then fails on its stub fetch).
    run = run_ingest(
        "synthetic-stub", session=db_session, store=store, settings=Settings(env="test")
    )
    assert run.status is IngestRunStatus.FAILED
    assert run.failure_reason is not None and "NotImplementedError" in run.failure_reason
    purge_source(db_session, "synthetic-stub")


# --- the CLI ---------------------------------------------------------------------------


def purge_run(session: Session, run_id: uuid.UUID) -> None:
    """Delete what one committed run created: its issues, the rows its records own, its records.

    Rows that an earlier run already published (a live ingest on the
    developer's database) reference that run's records and are left alone.
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


def test_cli_run_and_runs(settings: Settings, migrated_database: Engine, tmp_path: Path) -> None:
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
    runner = CliRunner()
    result = runner.invoke(app, ["ingest", "run", "fjc", "--from-fixture", str(FIXTURES)], env=env)
    run_id = re.search(r"^run ([0-9a-f-]{36}) ", result.output, re.MULTILINE)
    try:
        assert result.exit_code == 0, result.output
        assert run_id is not None, result.output
        assert "source=fjc status=succeeded" in result.output
        assert "rejected=0" in result.output

        listing = runner.invoke(app, ["ingest", "runs", "--source", "fjc", "--limit", "5"], env=env)
        assert listing.exit_code == 0, listing.output
        lines = listing.output.strip().splitlines()
        assert lines[0].split()[:4] == ["run_id", "source", "status", "started_at"]
        assert any(
            run_id.group(1) in line and "succeeded" in line and "2026.09.1" in line
            for line in lines[1:]
        )

        unknown = runner.invoke(app, ["ingest", "run", "nope"], env=env)
        assert unknown.exit_code == 2
        assert "unknown source" in unknown.output
    finally:
        # The CLI committed for real; remove exactly what its run created.
        if run_id is not None:
            with Session(migrated_database) as session:
                purge_run(session, uuid.UUID(run_id.group(1)))
                session.commit()


def test_not_modified_reuses_records_and_force_reparses_from_the_lake(
    clean_session: Session, store: FilesystemRawObjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 304 answer maps to the existing record; --force then re-parses the stored bytes."""
    session = clean_session
    first = _run(session, store)
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason

    async def not_modified(self: FjcConnector, artifact: SourceArtifact) -> RawArtifact:
        assert PREVIOUS_SHA256 in artifact.metadata  # the runner passed the validators
        return RawArtifact.unchanged(
            artifact,
            sha256=artifact.metadata[PREVIOUS_SHA256],
            retrieved_at=utc_now(),
            response_headers={"etag": '"unchanged"'},
        )

    monkeypatch.setattr(FjcConnector, "fetch", not_modified)
    settings = Settings(env="test")
    unchanged = run_ingest("fjc", session=session, store=store, settings=settings)
    assert unchanged.status is IngestRunStatus.SUCCEEDED, unchanged.failure_reason
    assert (unchanged.records_seen, unchanged.records_created, unchanged.records_updated) == (
        0,
        0,
        0,
    )
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2

    forced = run_ingest("fjc", session=session, store=store, settings=settings, force=True)
    assert forced.status is IngestRunStatus.SUCCEEDED, forced.failure_reason
    assert forced.records_seen == EXPECTED_JUDGES + EXPECTED_SERVICE
    assert (forced.records_created, forced.records_updated, forced.records_rejected) == (0, 0, 0)
    assert session.scalar(select(func.count()).select_from(SourceRecord)) == 2
    assert _count(session, Judge) == EXPECTED_JUDGES


def test_run_ids_are_uuids(clean_session: Session, store: FilesystemRawObjectStore) -> None:
    run = _run(clean_session, store)
    assert isinstance(run.id, uuid.UUID)
