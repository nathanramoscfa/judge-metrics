# tests/golden/test_public_contract.py
"""The restricted tables are unreachable through the public contract.

Three doors, each checked: the OpenAPI document (the committed snapshot
and the one the running app generates) names no restricted property or
schema; the database grants — as the app role, ``SELECT`` from
``person_identifier``, ``entity_resolution_candidate``, ``audit_log`` (and
``correction_request``) raises ``InsufficientPrivilege``; and the case
routes — every ``/cases/{id}`` response for the golden cases carries
persons as public keys only, none of them a merged person's, and no
restricted field name anywhere in the body.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from judgemetrics.config import REPO_ROOT
from judgemetrics.db.models import RESTRICTED_TABLES, Person
from tests.golden.conftest import RESTRICTED_NAMES, GoldenFixture

pytestmark = [pytest.mark.golden, pytest.mark.integration]

OPENAPI_SNAPSHOT = REPO_ROOT / "docs" / "openapi.json"
PUBLIC_KEY = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
HEX64 = re.compile(r"[0-9a-f]{64}")


def _keys(value: Any, *, with_values: bool = False) -> set[str]:
    """Every dictionary key (and, with ``with_values``, every string value) in a JSON value."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(str(key))
            found |= _keys(inner, with_values=with_values)
    elif isinstance(value, list):
        for inner in value:
            found |= _keys(inner, with_values=with_values)
    elif with_values and isinstance(value, str):
        found.add(value)
    return found


def _restricted_hits(document: Any, *, with_values: bool = False) -> set[str]:
    """The restricted names that occur in (or as part of) a key, or a value when asked."""
    names = {name.lower() for name in _keys(document, with_values=with_values)}
    return {
        restricted for restricted in RESTRICTED_NAMES if any(restricted in name for name in names)
    }


def test_the_openapi_snapshot_names_no_restricted_property() -> None:
    document = json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))
    schemas = document["components"]["schemas"]
    assert schemas, "the snapshot has component schemas"
    assert _restricted_hits({"schemas": schemas, "paths": document["paths"]}) == set()


def test_the_running_app_generates_the_same_clean_document(golden_api: TestClient) -> None:
    live = golden_api.app.openapi()  # type: ignore[attr-defined]
    assert _restricted_hits(live) == set()
    snapshot = json.loads(OPENAPI_SNAPSHOT.read_text(encoding="utf-8"))
    assert set(live["paths"]) == set(snapshot["paths"])
    assert set(live["components"]["schemas"]) == set(snapshot["components"]["schemas"])


@pytest.mark.parametrize("table", sorted(RESTRICTED_TABLES))
def test_the_app_role_cannot_select_from_a_restricted_table(
    migrated_database: Engine, app_engine: Engine, table: str
) -> None:
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("the test database URL does not connect as judgemetrics_app")
        with pytest.raises(ProgrammingError) as caught:
            connection.execute(text(f"SELECT * FROM {table} LIMIT 1"))  # noqa: S608 - fixed name
        assert isinstance(caught.value.orig, InsufficientPrivilege), table
        assert "permission denied" in str(caught.value.orig)


def test_every_golden_case_carries_public_keys_only(
    golden_api: TestClient, golden_fixture: GoldenFixture, migrated_database: Engine
) -> None:
    with Session(migrated_database) as session:
        live_keys = set(
            session.scalars(
                select(Person.public_person_key).where(Person.merged_into_person_id.is_(None))
            )
        )
        merged_keys = set(
            session.scalars(
                select(Person.public_person_key).where(Person.merged_into_person_id.is_not(None))
            )
        )
    assert merged_keys, "the golden fixture plants split persons that merge"
    assert golden_fixture.case_ids, "the golden ingest published cases"

    seen: set[str] = set()
    for number, case_id in sorted(golden_fixture.case_ids.items()):
        response = golden_api.get(f"/api/v1/cases/{case_id}")
        assert response.status_code == 200, (number, response.text)
        body = response.json()
        assert body["synthetic"] is True, number
        assert _restricted_hits(body, with_values=True) == set(), number
        assert body["parties"], number
        for party in body["parties"]:
            assert set(party) == {"party_type", "public_person_key"}, number
            key = party["public_person_key"]
            assert PUBLIC_KEY.match(key), number
            assert key in live_keys and key not in merged_keys, number
            seen.add(key)
        for decision in body["decisions"]:
            assert decision["public_person_key"] in live_keys, number
        # The only 64-hex digests in the body are the artifacts' sha256 values:
        # no identifier hash leaves person_identifier.
        digests = {v for v in _keys(body, with_values=True) if HEX64.fullmatch(v)}
        assert digests <= {block["raw_sha256"] for block in body["provenance"]}, number
    assert len(seen) == len(live_keys & seen)
    assert len(seen) < len(golden_fixture.case_ids)  # persons with several cases
