# tests/integration/test_api_corrections.py
"""`POST /api/v1/corrections`: the round trip, the grants, the limiter, and the missing key.

With a Fernet key generated in the test process the API (as the app
role) answers 202 with an id; the stored `requester_contact` is not the
plaintext bytes and decrypts to the submitted contact under the admin
role; as the app role an INSERT succeeds and a SELECT raises
`InsufficientPrivilege` (revision 0007 grants INSERT and nothing else);
422 on every invalid field and on an unknown target; 429 with
`Retry-After` once the corrections bucket is exhausted (the limiter is
enabled explicitly with a held clock); 503 with a fixed message when no
key is configured. Contacts use `example.invalid`; nothing submitted
appears in a log line.
"""

from __future__ import annotations

import logging as stdlib_logging
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg.errors import InsufficientPrivilege
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from judgemetrics.api.ratelimit import RETRY_AFTER_HEADER, TokenBucketLimiter
from judgemetrics.config import Settings
from judgemetrics.db.models import CorrectionRequest, CorrectionStatus
from judgemetrics.main import REQUEST_ID_HEADER
from judgemetrics.security.crypto import decrypt_contact
from tests.integration.conftest import FjcFixture, make_app

pytestmark = pytest.mark.integration

ALITO = "1377101"
CONTACT = "requester@example.invalid"
REASON = "The commission date on this profile is one year later than the source record shows."


@pytest.fixture(scope="module")
def contact_key() -> str:
    """A Fernet key generated in the test process; never committed."""
    return Fernet.generate_key().decode("ascii")


@pytest.fixture(scope="module")
def corrections_api(
    fjc_fixture: FjcFixture, test_settings: Settings, contact_key: str, migrated_database: Engine
) -> Iterator[TestClient]:
    app = make_app(test_settings, correction_contact_key=contact_key)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()
    with Session(migrated_database) as session:
        session.execute(delete(CorrectionRequest).where(CorrectionRequest.reason == REASON))
        session.commit()


def _body(fjc_fixture: FjcFixture, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "target_type": "judge",
        "target_id": str(fjc_fixture.judge_ids[ALITO]),
        "reason": REASON,
        "contact": CONTACT,
    }
    body.update(overrides)
    return body


def test_round_trip_stores_an_encrypted_contact_the_admin_role_decrypts(
    corrections_api: TestClient,
    fjc_fixture: FjcFixture,
    test_settings: Settings,
    contact_key: str,
    migrated_database: Engine,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(stdlib_logging.INFO)
    response = corrections_api.post(
        "/api/v1/corrections",
        json=_body(fjc_fixture, supporting_material="https://example.invalid/evidence.pdf"),
    )
    assert response.status_code == 202, response.text
    assert response.headers["Cache-Control"] == "no-store"
    body = response.json()
    assert set(body) == {"id", "status", "received_at"}
    assert body["status"] == "received"
    correction_id = uuid.UUID(body["id"])
    # The response carries nothing the requester submitted.
    assert CONTACT not in response.text and REASON not in response.text
    # Nothing submitted reached a log line either.
    for record in caplog.records:
        rendered = str(record.msg)
        assert CONTACT not in rendered and REASON not in rendered
    with Session(migrated_database) as session:
        stored = session.get(CorrectionRequest, correction_id)
        assert stored is not None
        assert stored.status is CorrectionStatus.RECEIVED
        assert stored.target_type == "judge"
        assert stored.target_id == fjc_fixture.judge_ids[ALITO]
        assert stored.reason == REASON
        assert stored.supporting_material_path == "https://example.invalid/evidence.pdf"
        assert stored.resolved_at is None
        assert stored.requester_contact != CONTACT.encode("utf-8")
        assert CONTACT.encode("utf-8") not in stored.requester_contact
        admin = test_settings.model_copy(update={"correction_contact_key": SecretStr(contact_key)})
        assert decrypt_contact(admin, stored.requester_contact) == CONTACT


def test_app_role_may_insert_but_never_read_the_table(
    migrated_database: Engine, app_engine: Engine, fjc_fixture: FjcFixture, contact_key: str
) -> None:
    key_settings = Settings(env="test", correction_contact_key=contact_key)
    from judgemetrics.security.crypto import encrypt_contact

    ciphertext = encrypt_contact(key_settings, CONTACT)
    correction_id = uuid.uuid4()
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("the test database URL does not connect as judgemetrics_app")
        connection.execute(
            text(
                "INSERT INTO correction_request "
                "(id, target_type, target_id, requester_contact, reason, status) "
                "VALUES (:id, 'judge', :target, :contact, :reason, 'received')"
            ),
            {
                "id": correction_id,
                "target": fjc_fixture.judge_ids[ALITO],
                "contact": ciphertext,
                "reason": REASON,
            },
        )
        connection.commit()
        for statement in (
            "SELECT count(*) FROM correction_request",
            "SELECT requester_contact FROM correction_request LIMIT 1",
            "UPDATE correction_request SET status = 'closed' WHERE id = :id",
            "DELETE FROM correction_request WHERE id = :id",
        ):
            connection.rollback()
            with pytest.raises(ProgrammingError) as caught:
                connection.execute(text(statement), {"id": correction_id})
            assert isinstance(caught.value.orig, InsufficientPrivilege), statement
        connection.rollback()
        # A RETURNING clause needs SELECT on the returned columns: refused too.
        with pytest.raises(ProgrammingError) as returning:
            connection.execute(
                text(
                    "INSERT INTO correction_request "
                    "(id, target_type, target_id, requester_contact, reason, status) "
                    "VALUES (:id, 'judge', :target, :contact, :reason, 'received') RETURNING id"
                ),
                {
                    "id": uuid.uuid4(),
                    "target": fjc_fixture.judge_ids[ALITO],
                    "contact": ciphertext,
                    "reason": REASON,
                },
            )
        assert isinstance(returning.value.orig, InsufficientPrivilege)
        connection.rollback()
    with Session(migrated_database) as session:
        stored = session.get(CorrectionRequest, correction_id)
        assert stored is not None and stored.status is CorrectionStatus.RECEIVED
        session.delete(stored)
        session.commit()


@pytest.mark.parametrize(
    ("overrides", "fragment"),
    [
        ({"target_type": "person"}, "target_type"),
        ({"target_id": "not-a-uuid"}, "target_id"),
        ({"target_id": str(uuid.UUID(int=0))}, "target_id"),
        ({"reason": "too short"}, "reason"),
        ({"reason": "x" * 4001}, "reason"),
        ({"contact": "ab"}, "contact"),
        ({"contact": "x" * 321}, "contact"),
        ({"supporting_material": "ftp://example.invalid/x"}, "supporting_material"),
        ({"supporting_material": "https://example.invalid/" + "p" * 2000}, "supporting_material"),
        ({"public_person_key": "abc"}, "public_person_key"),
    ],
)
def test_every_invalid_field_is_422(
    corrections_api: TestClient, fjc_fixture: FjcFixture, overrides: dict[str, Any], fragment: str
) -> None:
    response = corrections_api.post("/api/v1/corrections", json=_body(fjc_fixture, **overrides))
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "validation_error"
    assert fragment in body["message"]


def test_unknown_target_missing_body_and_query_parameters_are_422(
    corrections_api: TestClient, fjc_fixture: FjcFixture
) -> None:
    for target_type in ("judge", "court", "case", "metric_observation"):
        response = corrections_api.post(
            "/api/v1/corrections",
            json=_body(fjc_fixture, target_type=target_type, target_id=str(uuid.uuid4())),
        )
        assert response.status_code == 422, target_type
        assert f"no {target_type} with id" in response.json()["message"]
    assert corrections_api.post("/api/v1/corrections").status_code == 422
    assert corrections_api.post("/api/v1/corrections", json=[]).status_code == 422
    unknown = corrections_api.post(
        "/api/v1/corrections", params={"notify": "1"}, json=_body(fjc_fixture)
    )
    assert unknown.status_code == 422
    assert unknown.json()["message"] == "unknown query parameter(s): notify"
    assert corrections_api.get("/api/v1/corrections").status_code == 405


def test_without_a_key_the_intake_is_503_with_a_fixed_message(
    fjc_fixture: FjcFixture, test_settings: Settings
) -> None:
    app = make_app(test_settings, correction_contact_key=None)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/api/v1/corrections", json=_body(fjc_fixture))
    app.state.engine.dispose()
    assert response.status_code == 503, response.text
    body = response.json()
    assert body["code"] == "corrections_unavailable"
    assert body["message"] == (
        "corrections are not being accepted: the contact encryption key is not configured"
    )
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


@pytest.fixture
def limited(
    fjc_fixture: FjcFixture, test_settings: Settings, contact_key: str
) -> Iterator[TestClient]:
    """An app with the corrections limiter on (burst 2) and a clock that never advances."""
    app = make_app(
        test_settings,
        correction_contact_key=contact_key,
        corrections_rate_limit_enabled=True,
        corrections_rate_limit_burst=2,
        corrections_rate_limit_per_hour=5,
    )
    assert app.state.corrections_limiter is not None
    app.state.corrections_limiter = TokenBucketLimiter(per_hour=5, burst=2, clock=lambda: 0.0)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()


def test_limiter_returns_429_after_the_burst_before_validation(
    limited: TestClient, fjc_fixture: FjcFixture, migrated_database: Engine
) -> None:
    ids: list[uuid.UUID] = []
    try:
        for _ in range(2):
            response = limited.post("/api/v1/corrections", json=_body(fjc_fixture))
            assert response.status_code == 202, response.text
            ids.append(uuid.UUID(response.json()["id"]))
        refused = limited.post("/api/v1/corrections", json=_body(fjc_fixture))
        assert refused.status_code == 429
        assert refused.headers[RETRY_AFTER_HEADER] == "720"
        body = refused.json()
        assert body["code"] == "rate_limited"
        assert set(body) == {"code", "message", "request_id"}
        # Over the limit, an invalid body is still 429: the bucket is checked first.
        assert limited.post("/api/v1/corrections", json={"nonsense": 1}).status_code == 429
        # The search bucket is separate.
        assert limited.get("/api/v1/search", params={"q": "alito"}).status_code == 200
    finally:
        with Session(migrated_database) as session:
            session.execute(delete(CorrectionRequest).where(CorrectionRequest.id.in_(ids)))
            session.commit()
    with Session(migrated_database) as session:
        assert (
            session.scalar(select(CorrectionRequest).where(CorrectionRequest.id.in_(ids))) is None
        )
