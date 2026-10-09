# tests/integration/test_bind_parameter_ceiling.py
"""A lookup of tens of thousands of ids works through the shared array helper (Phase 5 Step 4).

PostgreSQL rejects a statement with more than 65,535 bind parameters, and SQLAlchemy's
``column.in_(values)`` renders one per value, so a run past that many cases or persons
failed on its first lookup (no test covered it). ``judgemetrics.db.arrays`` renders
``column = ANY(:values)`` — one typed array parameter — and every lookup of a run-sized id
list in the runner, the publishers, and entity resolution goes through it. This test runs
the helper and the real lookups over 70,000 ids on the scratch database, and shows the old
form failing on the same ids.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from judgemetrics.db.arrays import ID_BATCH, fetch_by_values, in_array
from judgemetrics.db.models import Base, Case, Person
from judgemetrics.entity_resolution.candidates import load_candidates
from judgemetrics.entity_resolution.config import ENTITY_PERSON, MODEL_VERSION
from judgemetrics.entity_resolution.deterministic import lookup_by_identity
from judgemetrics.entity_resolution.features import blocks_for, load_profiles
from judgemetrics.entity_resolution.merge import canonical_person_ids
from judgemetrics.ingest.publish import lookup_cases

pytestmark = pytest.mark.integration

IDS = 70_000
assert IDS > 65_535


def many_uuids() -> list[uuid.UUID]:
    return [uuid.UUID(int=index + 1) for index in range(IDS)]


def test_the_old_form_fails_past_the_driver_ceiling(db_session: Session) -> None:
    with pytest.raises(DBAPIError):
        db_session.execute(select(Case.id).where(Case.id.in_(many_uuids()))).all()


def test_the_array_form_answers_for_70000_uuids(db_session: Session) -> None:
    assert db_session.execute(select(Case.id).where(in_array(Case.id, many_uuids()))).all() == []
    assert (
        list(
            fetch_by_values(
                db_session,
                lambda condition: select(Case.id).where(condition),
                Case.id,
                many_uuids(),
            )
        )
        == []
    )


def test_the_array_form_answers_for_70000_strings(db_session: Session) -> None:
    table = Base.metadata.tables["person_identifier"]
    hashes = [f"{index:064x}" for index in range(IDS)]
    rows = db_session.execute(select(table.c.id).where(in_array(table.c.value_hash, hashes))).all()
    assert rows == []


def test_batches_are_smaller_than_the_ceiling() -> None:
    assert 0 < ID_BATCH < 65_535


def test_a_lookup_finds_the_real_row_among_70000_candidates(db_session: Session) -> None:
    first = Person(public_person_key="ceiling-test-1", resolution_status="deterministic")
    second = Person(public_person_key="ceiling-test-2", resolution_status="deterministic")
    third = Person(public_person_key="ceiling-test-3", resolution_status="deterministic")
    db_session.add_all([first, second, third])
    db_session.flush()
    first.merged_into_person_id = second.id
    second.merged_into_person_id = third.id
    db_session.flush()
    wanted = [first.id, second.id, third.id, *many_uuids()]
    canonical = canonical_person_ids(db_session, wanted)
    assert canonical[first.id] == canonical[second.id] == canonical[third.id] == third.id
    assert canonical[uuid.UUID(int=5)] == uuid.UUID(int=5)
    assert len(canonical) == len(wanted)
    found = db_session.scalars(select(Person.id).where(in_array(Person.id, wanted))).all()
    assert sorted(found) == sorted([first.id, second.id, third.id])


def test_the_real_lookups_accept_70000_keys(db_session: Session) -> None:
    person_keys = {("person", "source_participant_id", f"{index:064x}") for index in range(IDS)}
    assert lookup_by_identity(db_session, person_keys) == {}
    case_keys = {("case", "No Such Court", "circuit", f"CASE-{index}") for index in range(IDS)}
    assert (
        lookup_cases(db_session, case_keys, {("court", "No Such Court", "circuit"): uuid.uuid4()})
        == {}
    )
    assert blocks_for(db_session, {("full_name", f"{index:064x}") for index in range(IDS)}) == {}
    assert load_profiles(db_session, many_uuids())[uuid.UUID(int=1)].cases == ()
    pairs = [(uuid.UUID(int=index + 1), uuid.UUID(int=index + 2)) for index in range(IDS)]
    assert (
        load_candidates(db_session, pairs, entity_type=ENTITY_PERSON, model_version=MODEL_VERSION)
        == {}
    )


def test_the_session_fixture_is_the_migrated_scratch_database(migrated_database: Engine) -> None:
    assert migrated_database.dialect.name == "postgresql"
