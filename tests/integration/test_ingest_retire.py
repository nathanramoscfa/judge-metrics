# tests/integration/test_ingest_retire.py
"""``judgemetrics ingest retire`` (Phase 5 Step 4, closing issue #36).

The Cook County fixture and the golden synthetic dataset are ingested into the scratch
database. Retiring ``cook_sao`` removes every row derived from it and leaves the synthetic
source, its persons, and its judges exactly as they were; it keeps the ``source`` row and the
run history and appends one ``ingest.retire`` audit row; a re-ingest then equals the first
ingest row for row (ids and timestamps aside); production and an unknown source are refused.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session
from typer.testing import CliRunner, Result

from judgemetrics.cli import app
from judgemetrics.config import Settings, get_settings
from judgemetrics.db.models import (
    AuditLog,
    Case,
    CaseParty,
    Charge,
    Court,
    CourtEvent,
    Decision,
    IngestRun,
    IngestRunStatus,
    Judge,
    JudgeService,
    Jurisdiction,
    JusticeEvent,
    PartyAttribute,
    Person,
    PersonIdentifier,
    Sentence,
    Source,
    SourceRecord,
)
from judgemetrics.ingest.cook_sao.connector import CookSaoConnector
from judgemetrics.ingest.registry import UnknownSourceError
from judgemetrics.ingest.retire import RetireError, retire_source
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import GOLDEN_FIXTURES, purge_source

pytestmark = pytest.mark.integration

COOK = "cook_sao"
SYNTHETIC = "synthetic"
COOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cook_sao"


def ingest_cook(engine: Engine, store: FilesystemRawObjectStore, settings: Settings) -> IngestRun:
    with Session(engine) as session:
        run = run_ingest(
            COOK,
            session=session,
            store=store,
            settings=settings,
            from_fixture=COOK_FIXTURES,
            connector=CookSaoConnector(pepper=SecretStr(TEST_IDENTIFIER_PEPPER)),
        )
        session.commit()
        assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
        return run


def rows_of(session: Session, source: str) -> dict[str, list[Any]]:
    """A fingerprint of a source's rows: content only, no ids, timestamps, or provenance."""
    source_id = session.scalar(select(Source.id).where(Source.name == source))
    records = select(SourceRecord.id).where(SourceRecord.source_id == source_id)
    case_number = Case.case_number_normalized
    return {
        "cases": sorted(
            session.execute(
                select(case_number, Case.filed_date, Case.closed_date, Case.status).where(
                    Case.source_record_id.in_(records)
                )
            )
        ),
        "charges": sorted(
            session.execute(
                select(
                    case_number,
                    Charge.source_row_id,
                    Charge.disposition,
                    Charge.disposed_at,
                    Charge.severity,
                    Charge.offense_category,
                    Charge.statute_code,
                )
                .join(Case, Case.id == Charge.case_id)
                .where(Charge.source_record_id.in_(records))
            ),
            key=repr,
        ),
        "sentences": sorted(
            session.execute(
                select(
                    case_number,
                    Sentence.source_row_id,
                    Sentence.sentence_at,
                    Sentence.incarceration_days,
                )
                .join(Case, Case.id == Sentence.case_id)
                .where(Sentence.source_record_id.in_(records))
            ),
            key=repr,
        ),
        "decisions": sorted(
            session.execute(
                select(
                    case_number,
                    Decision.source_row_id,
                    Decision.decision_type,
                    Decision.decision_at,
                )
                .join(Case, Case.id == Decision.case_id)
                .where(Decision.source_record_id.in_(records))
            ),
            key=repr,
        ),
        "events": sorted(
            session.execute(
                select(case_number, CourtEvent.source_row_id, CourtEvent.event_type)
                .join(Case, Case.id == CourtEvent.case_id)
                .where(CourtEvent.source_record_id.in_(records))
            ),
            key=repr,
        ),
        "justice_events": sorted(
            session.execute(
                select(JusticeEvent.event_type, JusticeEvent.event_at).where(
                    JusticeEvent.source_record_id.in_(records)
                )
            ),
            key=repr,
        ),
        "identifiers": sorted(
            session.scalars(
                select(PersonIdentifier.value_hash).where(
                    PersonIdentifier.source_record_id.in_(records)
                )
            )
        ),
        "attributes": sorted(
            session.execute(
                select(CaseParty.source_row_id, PartyAttribute.attribute, PartyAttribute.value)
                .join(CaseParty, CaseParty.id == PartyAttribute.case_party_id)
                .where(PartyAttribute.source_record_id.in_(records))
            ),
            key=repr,
        ),
        "judges": sorted(
            session.execute(select(Judge.canonical_name).where(Judge.source_record_id.in_(records)))
        ),
        "services": session.scalar(
            select(func.count())
            .select_from(JudgeService)
            .where(JudgeService.source_record_id.in_(records))
        ),
        "courts": sorted(
            session.execute(select(Court.canonical_name).where(Court.source_record_id.in_(records)))
        ),
        "jurisdictions": sorted(
            session.execute(
                select(Jurisdiction.name).where(Jurisdiction.source_record_id.in_(records))
            )
        ),
        "persons": session.scalar(
            select(func.count()).select_from(Person).where(Person.source_record_id.in_(records))
        ),
    }


@dataclass
class Retired:
    engine: Engine
    store: FilesystemRawObjectStore
    settings: Settings
    cook_before: dict[str, list[Any]]
    synthetic_before: dict[str, list[Any]]
    result_deleted: dict[str, int]
    after_retire_cook: dict[str, list[Any]]
    after_retire_synthetic: dict[str, list[Any]]
    runs_after_retire: int
    source_kept: bool
    after_reingest: dict[str, list[Any]]


@pytest.fixture(scope="module")
def retired(
    migrated_database: Engine, test_settings: Settings, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[Retired]:
    settings = test_settings.model_copy(update={"env": "test"})
    with Session(migrated_database) as session:
        purge_source(session, COOK)
        purge_source(session, SYNTHETIC)
        session.commit()
    store = FilesystemRawObjectStore(tmp_path_factory.mktemp("retire-lake"))
    with Session(migrated_database) as session:
        run = run_ingest(
            SYNTHETIC,
            session=session,
            store=store,
            settings=settings,
            from_fixture=GOLDEN_FIXTURES,
        )
        session.commit()
        assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    ingest_cook(migrated_database, store, settings)
    try:
        with Session(migrated_database) as session:
            cook_before = rows_of(session, COOK)
            synthetic_before = rows_of(session, SYNTHETIC)
        with Session(migrated_database) as session:
            result = retire_source(session, COOK, settings=settings, actor="tests:retire")
            session.commit()
        with Session(migrated_database) as session:
            after_cook = rows_of(session, COOK)
            after_synthetic = rows_of(session, SYNTHETIC)
            runs = session.scalar(
                select(func.count())
                .select_from(IngestRun)
                .join(Source, Source.id == IngestRun.source_id)
                .where(Source.name == COOK)
            )
            kept = session.scalar(select(Source.id).where(Source.name == COOK)) is not None
        ingest_cook(migrated_database, store, settings)
        with Session(migrated_database) as session:
            again = rows_of(session, COOK)
        yield Retired(
            engine=migrated_database,
            store=store,
            settings=settings,
            cook_before=cook_before,
            synthetic_before=synthetic_before,
            result_deleted=result.deleted,
            after_retire_cook=after_cook,
            after_retire_synthetic=after_synthetic,
            runs_after_retire=runs or 0,
            source_kept=kept,
            after_reingest=again,
        )
    finally:
        with Session(migrated_database) as session:
            purge_source(session, COOK)
            purge_source(session, SYNTHETIC)
            session.commit()


def test_retire_deletes_what_the_source_published(retired: Retired) -> None:
    assert retired.cook_before["cases"], "the fixture ingest published cases"
    for name, value in retired.after_retire_cook.items():
        assert not value, name
    deleted = retired.result_deleted
    assert deleted["court_case"] == 73
    assert deleted["person"] == 82
    assert deleted["charge"] == 631
    assert deleted["sentence"] == 61
    assert deleted["judge"] == 47 and deleted["court"] == 7 and deleted["jurisdiction"] == 1
    assert deleted["source_record"] == 5
    assert "source" not in deleted


def test_retire_leaves_every_other_source_untouched(retired: Retired) -> None:
    assert retired.synthetic_before["cases"], "the golden dataset was ingested"
    assert retired.after_retire_synthetic == retired.synthetic_before


def test_retire_keeps_the_source_row_the_run_history_and_writes_one_audit_row(
    retired: Retired,
) -> None:
    assert retired.source_kept
    assert retired.runs_after_retire >= 1
    with Session(retired.engine) as session:
        rows = session.scalars(
            select(AuditLog).where(
                AuditLog.action == "ingest.retire", AuditLog.actor == "tests:retire"
            )
        ).all()
    assert rows, "an ingest.retire audit row was written"
    payload = rows[-1].payload
    assert payload["source"] == COOK and payload["deleted"]["court_case"] == 73
    assert all(isinstance(count, int) for count in payload["deleted"].values())


def test_a_reingest_after_a_retire_equals_the_first_ingest(retired: Retired) -> None:
    assert retired.after_reingest == retired.cook_before


def test_a_retire_is_refused_in_production_and_deletes_nothing(
    retired: Retired, db_session: Session
) -> None:
    before = rows_of(db_session, COOK)
    with pytest.raises(RetireError, match="production"):
        retire_source(db_session, COOK, settings=Settings(env="production"))
    assert rows_of(db_session, COOK) == before


def test_only_a_registered_source_can_be_retired(db_session: Session) -> None:
    with pytest.raises(UnknownSourceError):
        retire_source(db_session, "not-a-source", settings=Settings(env="test"))


def test_a_source_nothing_was_ingested_for_retires_to_nothing(db_session: Session) -> None:
    purge_source(db_session, "fjc")
    result = retire_source(db_session, "fjc", settings=Settings(env="test"))
    assert result.deleted == {} and result.total == 0


def cli_env(settings: Settings, **extra: str) -> dict[str, str]:
    return {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url,
        "JUDGEMETRICS_LOG_FORMAT": "json",
        "JUDGEMETRICS_IDENTIFIER_PEPPER": TEST_IDENTIFIER_PEPPER,
        **extra,
    }


def invoke(args: list[str], env: dict[str, str], input_text: str | None = None) -> Result:
    """One CLI call with its own environment: the settings cache is cleared around it."""
    get_settings.cache_clear()
    try:
        return CliRunner().invoke(app, args, env=env, input=input_text)
    finally:
        get_settings.cache_clear()


def test_the_cli_asks_first_and_refuses_production_and_unknown_sources(
    retired: Retired,
) -> None:
    env = cli_env(retired.settings)
    declined = invoke(["ingest", "retire", COOK], env, "n\n")
    assert declined.exit_code == 1 and "nothing deleted" in declined.output
    assert rows_of_cook(retired)["cases"], "declining deleted nothing"
    production = invoke(
        ["ingest", "retire", COOK, "--yes"],
        cli_env(retired.settings, JUDGEMETRICS_ENV="production"),
    )
    assert production.exit_code == 1 and "production" in production.output
    assert rows_of_cook(retired)["cases"], "production deleted nothing"
    unknown = invoke(["ingest", "retire", "nope", "--yes"], env)
    assert unknown.exit_code == 2 and "unknown source" in unknown.output
    assert rows_of_cook(retired)["cases"]


def rows_of_cook(retired: Retired) -> dict[str, list[Any]]:
    with Session(retired.engine) as session:
        return rows_of(session, COOK)


def test_the_cli_retires_with_yes_and_prints_the_counts(retired: Retired) -> None:
    result = invoke(["ingest", "retire", COOK, "--yes"], cli_env(retired.settings))
    assert result.exit_code == 0, result.output
    assert f"retired {COOK}:" in result.output and "court_case" in result.output
    assert not rows_of_cook(retired)["cases"]
