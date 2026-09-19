# tests/golden/conftest.py
"""Fixtures for the golden suite: the committed golden ingest and an API client over it.

The golden suite is the parametrized, permanent form of the Step 2 and
Step 3 integration assertions over ``tests/fixtures/golden``. It reuses
the module-scoped ``golden_fixture`` of ``tests/integration/conftest.py``
(imported here so pytest registers it for this package): one committed
ingest of the fixture per module on the scratch test database
(``test_settings``), purged at module teardown. ``golden_api`` is the
public API over that ingest as the read-only app role. Shared readers of
the fixture's files live here so every test reads ``truth/`` the same way.
"""

from __future__ import annotations

import csv
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import EntityResolutionCandidate, Person, PersonIdentifier
from judgemetrics.entity_resolution.config import MODEL_VERSION
from judgemetrics.security.identifiers import KIND_SOURCE_PARTICIPANT_ID, hash_identifier
from tests.conftest import TEST_IDENTIFIER_PEPPER
from tests.integration.conftest import (
    GOLDEN_FIXTURES,
    GoldenFixture,
    GoldenMetrics,
    golden_fixture,
    golden_metrics,
    make_app,
)

# ``golden_fixture`` and ``golden_metrics`` are re-exported so pytest registers
# them for this package.
__all__ = [
    "GOLDEN",
    "GoldenFixture",
    "GoldenMetrics",
    "candidate_for",
    "canonical",
    "family",
    "golden_fixture",
    "golden_metrics",
    "person_of",
    "planted_ids",
    "read_rows",
]
PEPPER = SecretStr(TEST_IDENTIFIER_PEPPER)

GOLDEN = GOLDEN_FIXTURES
SOURCE_ID = "synthetic"
RESTRICTED_NAMES: tuple[str, ...] = (
    "value_hash",
    "encrypted_value",
    "date_of_birth",
    "full_name",
    "person_identifier",
    "entity_resolution_candidate",
    "audit_log",
    "raw_object_path",
    "identifier_pepper",
    "merged_into_person_id",
)


def read_rows(relative: str) -> list[dict[str, str]]:
    """The rows of one fixture CSV (``source/<file>`` or ``truth/<file>``)."""
    with (GOLDEN / Path(*relative.split("/"))).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def planted_ids(row: dict[str, str]) -> dict[str, str]:
    """``planted.csv``'s ``ids`` column (``key=value;key=value``) as a mapping."""
    return dict(pair.split("=", 1) for pair in row["ids"].split(";"))


def person_of(session: Session, participant_id: str) -> Person:
    """The person row that carries a participant id's stable hash (merged or not)."""
    value_hash = hash_identifier(PEPPER, KIND_SOURCE_PARTICIPANT_ID, participant_id)
    person = session.scalar(
        select(Person)
        .join(PersonIdentifier, PersonIdentifier.person_id == Person.id)
        .where(
            PersonIdentifier.identifier_type == KIND_SOURCE_PARTICIPANT_ID,
            PersonIdentifier.value_hash == value_hash,
        )
    )
    assert person is not None, participant_id
    return person


def canonical(session: Session, person: Person) -> Person:
    """The survivor at the end of ``person``'s merge chain."""
    current = person
    while current.merged_into_person_id is not None:
        nxt = session.get(Person, current.merged_into_person_id)
        assert nxt is not None
        current = nxt
    return current


def family(session: Session, person: Person) -> set[uuid.UUID]:
    """The survivor of ``person`` and every person merged into it."""
    keep = canonical(session, person)
    merged = set(session.scalars(select(Person.id).where(Person.merged_into_person_id == keep.id)))
    return {keep.id, *merged}


def candidate_for(session: Session, left: Person, right: Person) -> EntityResolutionCandidate:
    """The one stored candidate between two persons, found through their merge families."""
    members = family(session, left) | family(session, right)
    candidates = list(
        session.scalars(
            select(EntityResolutionCandidate).where(
                EntityResolutionCandidate.left_record_id.in_(members),
                EntityResolutionCandidate.right_record_id.in_(members),
                EntityResolutionCandidate.model_version == MODEL_VERSION,
            )
        )
    )
    assert len(candidates) == 1, [candidate.id for candidate in candidates]
    return candidates[0]


@pytest.fixture
def session(migrated_database: Engine, golden_fixture: GoldenFixture) -> Iterator[Session]:
    """A read-only session over the module's committed golden ingest."""
    with Session(migrated_database) as session:
        yield session
        session.rollback()


@pytest.fixture(scope="module")
def golden_api(golden_fixture: GoldenFixture, test_settings: Settings) -> Iterator[TestClient]:
    """The API, as the app role, over the module's golden ingest."""
    app = make_app(test_settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()
