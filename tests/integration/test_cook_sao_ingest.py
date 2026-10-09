# tests/integration/test_cook_sao_ingest.py
"""The Cook County fixture through the fourteen-step runner (Phase 5 Step 4).

The 73-case real-row excerpt (``tests/fixtures/cook_sao``; race, gender, age, and the
quasi-identifying columns blank) is ingested into the scratch database and checked
for what the step promises: the expected rows, a second run that creates and updates
nothing, a ``--force`` run that changes nothing, provenance to the fixture's own
bytes, the expected issue codes and counts, no participant id in any column the app
role can read, and the app role's denial on ``data_quality_issue`` and the restricted
schema. The restricted values themselves are the next file's business
(``test_cook_sao_restricted.py``).
"""

from __future__ import annotations

import csv
import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import (
    Case,
    CaseParty,
    Charge,
    CourtEvent,
    DataQualityIssue,
    Decision,
    IngestRun,
    IngestRunStatus,
    Judge,
    JudgeService,
    JusticeEvent,
    Person,
    PersonIdentifier,
    PretrialRelease,
    Sentence,
    Source,
    SourceRecord,
)
from judgemetrics.ingest.cook_sao.connector import CookSaoConnector
from judgemetrics.ingest.cook_sao.rules import RULE_VERSION_TAG
from judgemetrics.ingest.cook_sao.sources import DATASETS, SOURCE_ID
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import purge_source

pytestmark = pytest.mark.integration

COOK_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "cook_sao"

# What the 905 fixture rows publish: one jurisdiction, the seven courts, the 47 judges the
# alias table resolves among the fixture's strings and their 52 services, then per case.
EXPECTED_CREATED = {
    "jurisdiction": 1,
    "court": 7,
    "judge": 47,
    "judge_service": 52,
    "court_case": 73,
    "person": 82,
    "person_identifier": 82,
    "case_party": 82,
    "party_attribute": 246,
    "charge": 631,
    "court_event": 83,
    "decision": 60,
    "pretrial_release": 8,
    "sentence": 61,
    "justice_event": 1,
}


def make_connector() -> CookSaoConnector:
    return CookSaoConnector(pepper=SecretStr(TEST_IDENTIFIER_PEPPER))


@dataclass(frozen=True)
class CookRun:
    first: IngestRun
    second: IngestRun
    forced: IngestRun
    store: FilesystemRawObjectStore


def _created(run: IngestRun) -> int:
    return run.records_created


@pytest.fixture(scope="module")
def cook_runs(
    migrated_database: Engine, test_settings: Settings, tmp_path_factory: pytest.TempPathFactory
) -> Iterator[CookRun]:
    """The fixture ingested, then again, then again with ``--force``, all committed."""
    with Session(migrated_database) as cleanup:
        purge_source(cleanup, SOURCE_ID)
        cleanup.commit()
    store = FilesystemRawObjectStore(tmp_path_factory.mktemp("cook-lake"))
    settings = test_settings.model_copy(update={"env": "test"})
    runs: list[IngestRun] = []
    for force in (False, False, True):
        with Session(migrated_database) as session:
            run = run_ingest(
                SOURCE_ID,
                session=session,
                store=store,
                settings=settings,
                from_fixture=COOK_FIXTURES,
                force=force,
                connector=make_connector(),
            )
            session.commit()
            session.refresh(run)
            session.expunge(run)
            runs.append(run)
    try:
        yield CookRun(first=runs[0], second=runs[1], forced=runs[2], store=store)
    finally:
        with Session(migrated_database) as session:
            purge_source(session, SOURCE_ID)
            session.commit()


def _fixture_participants() -> set[str]:
    ids: set[str] = set()
    for dataset in DATASETS:
        with (COOK_FIXTURES / dataset.external_id).open(encoding="utf-8", newline="") as handle:
            ids.update(row["CASE_PARTICIPANT_ID"].strip() for row in csv.DictReader(handle))
    return ids


def test_the_first_run_publishes_the_expected_rows(cook_runs: CookRun) -> None:
    run = cook_runs.first
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    assert run.parser_version == f"1+{RULE_VERSION_TAG}"
    assert run.records_seen == 905  # 15 + 156 + 616 + 116 + 2 rows
    assert run.records_rejected == 0


def test_the_rows_in_every_table(migrated_database: Engine, cook_runs: CookRun) -> None:
    del cook_runs
    with Session(migrated_database) as session:
        source_id = session.scalar(select(Source.id).where(Source.name == SOURCE_ID))
        records = select(SourceRecord.id).where(SourceRecord.source_id == source_id)
        counts = {
            "court_case": session.scalar(
                select(func.count()).select_from(Case).where(Case.source_record_id.in_(records))
            ),
            "person": session.scalar(
                select(func.count()).select_from(Person).where(Person.source_record_id.in_(records))
            ),
            "case_party": session.scalar(
                select(func.count())
                .select_from(CaseParty)
                .where(CaseParty.source_record_id.in_(records))
            ),
            "charge": session.scalar(
                select(func.count()).select_from(Charge).where(Charge.source_record_id.in_(records))
            ),
            "court_event": session.scalar(
                select(func.count())
                .select_from(CourtEvent)
                .where(CourtEvent.source_record_id.in_(records))
            ),
            "decision": session.scalar(
                select(func.count())
                .select_from(Decision)
                .where(Decision.source_record_id.in_(records))
            ),
            "sentence": session.scalar(
                select(func.count())
                .select_from(Sentence)
                .where(Sentence.source_record_id.in_(records))
            ),
            "justice_event": session.scalar(
                select(func.count())
                .select_from(JusticeEvent)
                .where(JusticeEvent.source_record_id.in_(records))
            ),
            "judge": session.scalar(
                select(func.count()).select_from(Judge).where(Judge.source_record_id.in_(records))
            ),
            "judge_service": session.scalar(
                select(func.count())
                .select_from(JudgeService)
                .where(JudgeService.source_record_id.in_(records))
            ),
            "pretrial_release": session.scalar(
                select(func.count())
                .select_from(PretrialRelease)
                .join(Decision, Decision.id == PretrialRelease.decision_id)
                .where(Decision.source_record_id.in_(records))
            ),
            "person_identifier": session.scalar(
                select(func.count())
                .select_from(PersonIdentifier)
                .where(PersonIdentifier.source_record_id.in_(records))
            ),
        }
    for table, expected in EXPECTED_CREATED.items():
        if table in counts:
            assert counts[table] == expected, table


def test_a_second_run_creates_and_updates_nothing(cook_runs: CookRun) -> None:
    run = cook_runs.second
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    assert (run.records_seen, run.records_created, run.records_updated) == (0, 0, 0)


def test_a_force_run_changes_nothing(cook_runs: CookRun) -> None:
    run = cook_runs.forced
    assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
    assert run.records_seen == 905
    assert (run.records_created, run.records_updated) == (0, 0)
    assert run.records_rejected == 0


def test_the_first_run_created_every_expected_row(cook_runs: CookRun) -> None:
    created = cook_runs.first.records_created
    assert created == sum(EXPECTED_CREATED.values())


def test_every_published_row_traces_to_the_fixtures_own_bytes(
    migrated_database: Engine, cook_runs: CookRun
) -> None:
    del cook_runs
    digests = {
        dataset.external_id: hashlib.sha256(
            (COOK_FIXTURES / dataset.external_id).read_bytes()
        ).hexdigest()
        for dataset in DATASETS
    }
    with Session(migrated_database) as session:
        source_id = session.scalar(select(Source.id).where(Source.name == SOURCE_ID))
        records = session.execute(
            select(SourceRecord.external_record_id, SourceRecord.raw_sha256).where(
                SourceRecord.source_id == source_id
            )
        ).all()
        assert {name: digest for name, digest in records} == digests
        cited = {
            record_id
            for table in (Case, CaseParty, Charge, CourtEvent, Decision, Sentence, JusticeEvent)
            for record_id in session.scalars(select(table.source_record_id).distinct())
        }
        known = set(
            session.scalars(select(SourceRecord.id).where(SourceRecord.source_id == source_id))
        )
        assert cited & known
        assert cited & known == cited & set(
            session.scalars(select(SourceRecord.id).where(SourceRecord.source_id == source_id))
        )


# Issues by code for the fixture, as the runner persists them (each linked to a source record):
# the connector's findings, then the case-level checks over the drafts.
EXPECTED_ISSUES = {
    "bond_not_drafted": 1,
    "charge_version_replaced": 1,
    "event_order_impossible": 24,
    "judge_unresolved": 1,
    "received_before_coverage": 10,
    "sentence_term_flagged": 4,
}


def test_the_issue_codes_and_counts(migrated_database: Engine, cook_runs: CookRun) -> None:
    del cook_runs
    with Session(migrated_database) as session:
        source_id = session.scalar(select(Source.id).where(Source.name == SOURCE_ID))
        rows = session.execute(
            select(DataQualityIssue.issue_code, func.count())
            .join(SourceRecord, SourceRecord.id == DataQualityIssue.source_record_id)
            .where(SourceRecord.source_id == source_id)
            .group_by(DataQualityIssue.issue_code)
        ).all()
    assert {code: count for code, count in rows} == EXPECTED_ISSUES


def test_decisions_the_source_never_attributes_to_an_officer_are_counted_once(
    migrated_database: Engine, cook_runs: CookRun
) -> None:
    """Bond and diversion decisions name no judge in the source: one run-level count each."""
    del cook_runs
    with Session(migrated_database) as session:
        descriptions = list(
            session.scalars(
                select(DataQualityIssue.description).where(
                    DataQualityIssue.issue_code == "missing_judge_on_decision",
                    DataQualityIssue.source_record_id.is_(None),
                )
            )
        )
    assert any(d.startswith("8 pretrial_release decisions name no judge") for d in descriptions)
    assert any(d.startswith("2 diversion decisions name no judge") for d in descriptions)


def test_no_fixture_participant_id_is_readable_by_the_app_role(
    app_engine: Engine, cook_runs: CookRun
) -> None:
    del cook_runs
    ids = sorted(_fixture_participants())
    assert len(ids) == 82
    pattern = "(^|[^0-9])(" + "|".join(ids) + ")([^0-9]|$)"
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("the test database URL does not connect as judgemetrics_app")
        columns = connection.execute(
            text(
                "SELECT c.table_schema, c.table_name, c.column_name "
                "FROM information_schema.columns AS c "
                "JOIN information_schema.tables AS t "
                "  ON t.table_schema = c.table_schema AND t.table_name = c.table_name "
                "WHERE t.table_type = 'BASE TABLE' "
                "  AND c.table_schema NOT IN ('pg_catalog', 'information_schema') "
                "  AND c.data_type = ANY(:types) "
                "  AND has_schema_privilege(c.table_schema, 'USAGE') "
                "  AND has_column_privilege("
                "      quote_ident(c.table_schema) || '.' || quote_ident(c.table_name), "
                "      c.column_name, 'SELECT') "
                "ORDER BY 1, 2, 3"
            ),
            {"types": ["text", "character varying", "character", "json", "jsonb"]},
        ).all()
        scanned = {(schema, table) for schema, table, _ in columns}
        assert ("public", "charge") in scanned and ("public", "sentence") in scanned
        assert ("public", "data_quality_issue") not in scanned
        for schema, table, column in columns:
            found = connection.execute(
                text(
                    f'SELECT count(*) FROM "{schema}"."{table}" '  # noqa: S608 - catalog names
                    f'WHERE "{column}"::text ~ :pattern'
                ),
                {"pattern": pattern},
            ).scalar()
            assert found == 0, f"{schema}.{table}.{column} holds a fixture participant id"


def test_the_app_role_is_denied_the_issue_table_and_the_restricted_schema(
    app_engine: Engine, cook_runs: CookRun
) -> None:
    del cook_runs
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("the test database URL does not connect as judgemetrics_app")
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text("SELECT count(*) FROM data_quality_issue"))
        connection.rollback()
        with pytest.raises(ProgrammingError, match="permission denied"):
            connection.execute(text("SELECT count(*) FROM restricted.party_attribute"))
