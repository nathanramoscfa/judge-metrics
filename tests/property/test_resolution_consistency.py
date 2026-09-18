# tests/property/test_resolution_consistency.py
"""Identical deterministic identifiers resolve consistently (the brief's fourth
property), for any seed and any ordering of the incoming drafts.

For a random seed at the ``tiny`` scale, the participant rows are
normalized through the synthetic connector into ``PersonDraft``s and
resolved twice with ``pipeline.resolve_persons`` — the ingest runner's
step 10 — in two different orders drawn by Hypothesis (a ``permutations``
strategy over the draft list). The second pass, which also carries the
planted duplicate source row, must find exactly the persons the first
pass created: the same person per participant hash, nothing new. The
deterministic stage then maps equal ``source_participant_id`` hashes to
equal persons and distinct hashes to distinct persons, and
``lookup_by_identity`` over the stored rows returns the same map.

Every example runs inside one transaction on the scratch test database
and is rolled back; Hypothesis's failure output carries the seed and the
draft order, never a hash.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from judgemetrics.db.models import IngestRun, IngestRunStatus, Source, SourceRecord
from judgemetrics.entity_resolution.deterministic import lookup_by_identity
from judgemetrics.entity_resolution.pipeline import resolve_persons
from judgemetrics.ingest.base import NaturalKey, PersonDraft, Provenance, TaggedRecord
from judgemetrics.synthetic.config import TINY
from tests.property.support import DatasetCache, seeds

pytestmark = [pytest.mark.property, pytest.mark.integration]


@pytest.fixture(scope="module")
def datasets(tmp_path_factory: pytest.TempPathFactory) -> DatasetCache:
    return DatasetCache(tmp_path_factory.mktemp)


def _deduplicated(drafts: list[PersonDraft]) -> list[PersonDraft]:
    """One draft per natural key, the first wins (the runner's step 9)."""
    kept: dict[NaturalKey, PersonDraft] = {}
    for draft in drafts:
        kept.setdefault(draft.natural_key, draft)
    return list(kept.values())


def _provenance(session: Session) -> tuple[IngestRun, Provenance]:
    """A source, a run, and one source record for the drafts to cite (inside the transaction)."""
    source = Source(
        name=f"property-{uuid.uuid4().hex[:8]}",
        owner="tests",
        source_type="fixture",
        access_method="in-memory",
    )
    session.add(source)
    session.flush()
    run = IngestRun(
        source_id=source.id,
        started_at=datetime.now(tz=UTC),
        status=IngestRunStatus.RUNNING,
        code_version="0" * 40,
        parser_version="1",
    )
    session.add(run)
    session.flush()
    record = SourceRecord(
        source_id=source.id,
        external_record_id="source/participants.csv",
        retrieved_at=datetime.now(tz=UTC),
        raw_object_path=f"property/{source.name}/participants.csv",
        raw_sha256="0" * 64,
        parser_version="1",
        ingest_run_id=run.id,
    )
    session.add(record)
    session.flush()
    return run, Provenance(source_record_id=record.id, raw_sha256=record.raw_sha256)


def _tagged(drafts: list[PersonDraft], provenance: Provenance) -> list[TaggedRecord]:
    return [TaggedRecord(record=draft, provenance=provenance) for draft in drafts]


@given(seed=seeds, data=st.data())
def test_resolution_does_not_depend_on_draft_order(
    migrated_database: Engine, datasets: DatasetCache, seed: int, data: st.DataObject
) -> None:
    dataset = datasets.get(seed, TINY)
    all_drafts = dataset.persons
    unique = _deduplicated(all_drafts)
    assert len(all_drafts) > len(unique), dataset  # the planted duplicate source record
    first = data.draw(st.permutations(unique), label="first order")
    second = data.draw(st.permutations(all_drafts), label="second order (with duplicates)")

    connection = migrated_database.connect()
    transaction = connection.begin()
    session = Session(bind=connection, join_transaction_mode="create_savepoint")
    try:
        run, provenance = _provenance(session)
        created = resolve_persons(session, _tagged(first, provenance), run)
        assert created.created_persons == len(unique), dataset
        assert not created.existing, dataset
        assert set(created.ids) == {draft.natural_key for draft in unique}

        found = resolve_persons(session, _tagged(second, provenance), run)
        assert found.created_persons == 0 and found.created_identifiers == 0, dataset
        assert found.existing == frozenset(created.ids), dataset
        assert found.ids == created.ids, dataset

        # The deterministic stage on the stored rows: the same map, and equal
        # stable hashes are exactly the pairs that share a person.
        stored = lookup_by_identity(session, [draft.natural_key for draft in all_drafts])
        assert stored == created.ids, dataset
        for left in unique:
            for right in unique:
                same_hash = left.identity == right.identity
                same_person = created.ids[left.natural_key] == created.ids[right.natural_key]
                assert same_hash == same_person, dataset
    finally:
        session.close()
        transaction.rollback()
        connection.close()
