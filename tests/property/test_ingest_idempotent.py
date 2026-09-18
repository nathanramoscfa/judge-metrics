# tests/property/test_ingest_idempotent.py
"""Rerunning an ingestion produces no duplicates (the brief's third property).

For ``tiny`` datasets from five sampled seeds, the dataset is ingested
twice through the fourteen-step runner (``run_ingest(...,
from_fixture=<dataset root>)``, the path the golden fixture takes). After
the first run every row of the dataset's own
``truth/resolution_expectations.csv`` holds (the planted pairs resolve as
the truth predicts for any seed, including the same-court fallback of the
ambiguous plant). The second run must parse nothing, create and update
zero rows in every canonical table — asserted on the run's counters and,
per table, on the row count and the latest ``updated_at`` — and write
zero entity-resolution candidates; the ``ingest_run`` and
``source_record`` tables gain only the second run's own row and no
record. Examples are derandomized (``derandomize=True``) so CI replays
the same five seeds every time, and each example runs inside one
transaction on the scratch test database that is rolled back afterwards,
which is how the runs are purged.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from hypothesis import given, settings
from sqlalchemy import Engine, func, null, select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import (
    CANONICAL_TABLES,
    Base,
    EntityResolutionCandidate,
    IngestRunStatus,
    SourceRecord,
)
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.synthetic.config import TINY
from tests.golden.conftest import candidate_for, person_of
from tests.integration.conftest import purge_source
from tests.property.support import PEPPER, SOURCE_ID, Dataset, DatasetCache, seeds

pytestmark = [pytest.mark.property, pytest.mark.integration]

# Every canonical table except the append-only audit log (a merge writes one
# row on the first run and none on the second, which the candidate count
# already proves) and the run bookkeeping asserted separately.
WATCHED_TABLES = tuple(
    table for table in CANONICAL_TABLES if table not in {"audit_log", "ingest_run"}
)


@pytest.fixture(scope="module")
def datasets(tmp_path_factory: pytest.TempPathFactory) -> DatasetCache:
    return DatasetCache(tmp_path_factory.mktemp)


def _assert_truth_expectations(session: Session, dataset: Dataset) -> None:
    """Every planted pair of ``dataset`` resolved as its truth file predicts."""
    rows = dataset.truth["resolution_expectations.csv"]
    assert rows, dataset
    for row in rows:
        left = person_of(session, row["left_participant_id"])
        right = person_of(session, row["right_participant_id"])
        candidate = candidate_for(session, left, right)
        expected = ResolutionDecision(row["expected_decision"])
        assert candidate.decision is expected, (dataset, row["reason"])
        assert (left.id == right.id) == (expected is ResolutionDecision.MATCHED), dataset


def _snapshot(session: Session) -> dict[str, tuple[int, datetime | None]]:
    """Row count and latest ``updated_at`` per watched table."""
    snapshot: dict[str, tuple[int, datetime | None]] = {}
    for name in WATCHED_TABLES:
        table = Base.metadata.tables[name]
        latest: Any = func.max(table.c.updated_at) if "updated_at" in table.c else null()
        count, updated = session.execute(select(func.count(), latest).select_from(table)).one()
        snapshot[name] = (int(count), updated)
    return snapshot


@settings(max_examples=5, derandomize=True)
@given(seed=seeds)
def test_a_second_ingest_creates_updates_and_resolves_nothing(
    migrated_database: Engine,
    datasets: DatasetCache,
    tmp_path_factory: pytest.TempPathFactory,
    seed: int,
) -> None:
    dataset = datasets.get(seed, TINY)
    store = FilesystemRawObjectStore(tmp_path_factory.mktemp("lake"))
    run_settings = Settings(env="test", identifier_pepper=PEPPER)

    connection = migrated_database.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        purge_source(session, SOURCE_ID)
        first = run_ingest(
            SOURCE_ID,
            session=session,
            store=store,
            settings=run_settings,
            from_fixture=dataset.root,
        )
        assert first.status is IngestRunStatus.SUCCEEDED, (dataset, first.failure_reason)
        assert first.records_created > 0, dataset
        _assert_truth_expectations(session, dataset)
        before = _snapshot(session)
        candidates_before = session.scalar(
            select(func.count()).select_from(EntityResolutionCandidate)
        )

        second = run_ingest(
            SOURCE_ID,
            session=session,
            store=store,
            settings=run_settings,
            from_fixture=dataset.root,
        )
        assert second.status is IngestRunStatus.SUCCEEDED, (dataset, second.failure_reason)
        assert (second.records_seen, second.records_created, second.records_updated) == (0, 0, 0)
        assert second.records_rejected == 0, dataset

        session.expire_all()
        after = _snapshot(session)
        assert after == before, dataset
        assert (
            session.scalar(select(func.count()).select_from(EntityResolutionCandidate))
            == candidates_before
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(EntityResolutionCandidate)
                .where(EntityResolutionCandidate.ingest_run_id == second.id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(SourceRecord)
                .where(SourceRecord.ingest_run_id == second.id)
            )
            == 0
        )
    finally:
        session.close()
        transaction.rollback()
        connection.close()
