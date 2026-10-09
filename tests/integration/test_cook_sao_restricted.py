# tests/integration/test_cook_sao_restricted.py
"""Race, gender, and the age band reach ``restricted.party_attribute`` only (Phase 5 Step 4).

The committed fixture has those columns blank, so a temporary copy of it is written with
vocabulary labels in them ("White/Black [Hispanic or Latino]", "Male Name, No Gender Given",
an age of 40) and ingested. The three values must land in the restricted table, one per
party and attribute, and nowhere else: not in any column of the public schema, not in a
data-quality issue, not in a log line.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, func, select, text
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import (
    DataQualityIssue,
    IngestRunStatus,
    PartyAttribute,
    Source,
    SourceRecord,
)
from judgemetrics.ingest.cook_sao.connector import CookSaoConnector
from judgemetrics.ingest.cook_sao.sources import DATASETS, SOURCE_ID
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.logging import configure_logging
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import purge_source
from tests.unit.test_cook_sao_normalize import fixture_bytes

pytestmark = pytest.mark.integration

RACE_LABEL = "White/Black [Hispanic or Latino]"
GENDER_LABEL = "Male Name, No Gender Given"
AGE = "40"
RACE_VALUE = "white_black_hispanic_or_latino"
GENDER_VALUE = "male_name_no_gender_given"
AGE_BAND = "35-44"
# Every spelling of the injected values that must not appear outside the restricted table.
FORBIDDEN = (RACE_VALUE, GENDER_VALUE, AGE_BAND, RACE_LABEL, GENDER_LABEL, "Hispanic or Latino")


def write_labelled_fixture(directory: Path) -> None:
    import csv
    import io

    for name, data in fixture_bytes().items():
        rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
        headers = list(rows[0])
        for row in rows:
            if "RACE" in row:
                row["RACE"] = RACE_LABEL
            if "GENDER" in row:
                row["GENDER"] = GENDER_LABEL
            if "AGE_AT_INCIDENT" in row:
                row["AGE_AT_INCIDENT"] = AGE
        with (directory / name).open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=headers, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)


@pytest.fixture(scope="module")
def labelled_ingest(
    migrated_database: Engine,
    test_settings: Settings,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[list[logging.LogRecord]]:
    with Session(migrated_database) as session:
        purge_source(session, SOURCE_ID)
        session.commit()
    directory = tmp_path_factory.mktemp("labelled-cook")
    write_labelled_fixture(directory)
    settings = test_settings.model_copy(update={"env": "test", "log_format": "json"})
    configure_logging(settings)
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    capture = Capture(level=logging.DEBUG)
    root = logging.getLogger()
    root.addHandler(capture)
    try:
        with Session(migrated_database) as session:
            run = run_ingest(
                SOURCE_ID,
                session=session,
                store=FilesystemRawObjectStore(tmp_path_factory.mktemp("labelled-lake")),
                settings=settings,
                from_fixture=directory,
                connector=CookSaoConnector(pepper=SecretStr(TEST_IDENTIFIER_PEPPER)),
            )
            session.commit()
            assert run.status is IngestRunStatus.SUCCEEDED, run.failure_reason
        yield records
    finally:
        root.removeHandler(capture)
        with Session(migrated_database) as session:
            purge_source(session, SOURCE_ID)
            session.commit()


def test_the_three_values_land_in_the_restricted_table_one_per_party_and_attribute(
    labelled_ingest: list[logging.LogRecord], migrated_database: Engine
) -> None:
    del labelled_ingest
    with Session(migrated_database) as session:
        source_id = session.scalar(select(Source.id).where(Source.name == SOURCE_ID))
        rows = session.execute(
            select(PartyAttribute.attribute, PartyAttribute.value, func.count())
            .where(
                PartyAttribute.source_record_id.in_(
                    select(SourceRecord.id).where(SourceRecord.source_id == source_id)
                )
            )
            .group_by(PartyAttribute.attribute, PartyAttribute.value)
        ).all()
    assert {(attribute, value): count for attribute, value, count in rows} == {
        ("race", RACE_VALUE): 82,
        ("gender", GENDER_VALUE): 82,
        ("age_band", AGE_BAND): 82,
    }


def test_no_public_column_holds_a_restricted_value(
    labelled_ingest: list[logging.LogRecord], migrated_database: Engine
) -> None:
    del labelled_ingest
    with migrated_database.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT table_name, column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' "
                "AND data_type IN ('text', 'character varying', 'character', 'json', 'jsonb') "
                "ORDER BY 1, 2"
            )
        ).all()
        assert ("charge", "description") in columns and (
            "data_quality_issue",
            "description",
        ) in columns
        for table, column in columns:
            for forbidden in FORBIDDEN:
                found = connection.execute(
                    text(
                        f'SELECT count(*) FROM public."{table}" '  # noqa: S608 - catalog names
                        f'WHERE "{column}"::text ILIKE :pattern'
                    ),
                    {"pattern": f"%{forbidden}%"},
                ).scalar()
                assert found == 0, f"public.{table}.{column} holds {forbidden!r}"


def test_no_issue_describes_a_restricted_value(
    labelled_ingest: list[logging.LogRecord], migrated_database: Engine
) -> None:
    del labelled_ingest
    with Session(migrated_database) as session:
        descriptions = list(session.scalars(select(DataQualityIssue.description)))
    assert descriptions
    for description in descriptions:
        assert not any(value.lower() in description.lower() for value in FORBIDDEN), description


def test_no_log_line_carries_a_restricted_value(labelled_ingest: list[logging.LogRecord]) -> None:
    assert labelled_ingest, "the run logged"
    rendered = " ".join(f"{record.getMessage()} {record.__dict__}" for record in labelled_ingest)
    assert not any(value.lower() in rendered.lower() for value in FORBIDDEN)


def test_every_export_of_the_run_was_read(labelled_ingest: list[logging.LogRecord]) -> None:
    messages = [str(record.msg) for record in labelled_ingest]
    for dataset in DATASETS:
        assert any(dataset.external_id in message for message in messages), dataset.external_id
