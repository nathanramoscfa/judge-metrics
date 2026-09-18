# tests/integration/test_health.py
"""`/api/v1/health` and `/api/v1/ready` through the FastAPI TestClient.

`/health` never touches the database, so those tests run everywhere; the
`/ready` 200 case needs the Compose / CI database at head and the 503 case
needs nothing but an unreachable URL.
"""

from __future__ import annotations

import logging as stdlib_logging
import re
from collections.abc import Iterator
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from judgemetrics import __version__
from judgemetrics.config import Settings
from judgemetrics.db.migrations import head_revision
from judgemetrics.main import REQUEST_ID_HEADER, create_app

pytestmark = pytest.mark.integration

UNREACHABLE_URL = (
    "postgresql+psycopg://nobody:placeholder@127.0.0.1:1/judgemetrics"  # pragma: allowlist secret
)
SHA = re.compile(r"^[0-9a-f]{40}$")


@pytest.fixture
def unreachable_client() -> Iterator[TestClient]:
    app = create_app(Settings(env="test", database_url=UNREACHABLE_URL, log_format="json"))
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


@pytest.fixture
def live_client(migrated_database: Engine, test_settings: Settings) -> Iterator[TestClient]:
    app = create_app(Settings(env=test_settings.env, database_url=test_settings.database_url))
    with TestClient(app) as client:
        yield client
    app.state.engine.dispose()


def test_health_reports_version_sha_and_head(unreachable_client: TestClient) -> None:
    response = unreachable_client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == __version__
    assert body["git_sha"] == "unknown" or SHA.match(body["git_sha"])
    assert body["alembic_head"] == head_revision() == "0004"
    assert set(body) == {"status", "version", "git_sha", "alembic_head"}


def test_health_exposes_no_configuration(unreachable_client: TestClient) -> None:
    """No configuration value, hostname, or credential leaks through /health."""
    text = unreachable_client.get("/api/v1/health").text
    parts = urlsplit(UNREACHABLE_URL.replace("postgresql+psycopg", "postgresql"))
    for forbidden in (parts.hostname, parts.username, parts.password, "postgresql", "psycopg"):
        assert forbidden and forbidden not in text
    assert "127.0.0.1" not in text
    assert "localhost" not in text


def test_health_echoes_or_generates_request_id(unreachable_client: TestClient) -> None:
    echoed = unreachable_client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "abc-123"})
    assert echoed.headers[REQUEST_ID_HEADER] == "abc-123"
    generated = unreachable_client.get("/api/v1/health")
    assert re.fullmatch(r"[0-9a-f-]{36}", generated.headers[REQUEST_ID_HEADER])
    unsafe = unreachable_client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "x\ty" * 100})
    assert unsafe.headers[REQUEST_ID_HEADER] != "x\ty" * 100


def test_access_log_carries_request_id(
    unreachable_client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(stdlib_logging.INFO)
    unreachable_client.get("/api/v1/health", headers={REQUEST_ID_HEADER: "trace-me"})
    # structlog hands the processed event dict to stdlib as the record message.
    records = [
        record.msg
        for record in caplog.records
        if record.name == "judgemetrics.access" and isinstance(record.msg, dict)
    ]
    assert records, "no access-log record"
    entry = records[-1]
    assert entry["event"] == "http.request"
    assert entry["request_id"] == "trace-me"
    assert entry["path"] == "/api/v1/health"
    assert entry["status"] == 200


def test_ready_returns_503_when_database_unreachable(unreachable_client: TestClient) -> None:
    response = unreachable_client.get("/api/v1/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["reason"] == "database unreachable"
    # Failure detail never carries the DSN.
    assert "nobody" not in response.text
    assert "placeholder" not in response.text


def test_ready_returns_200_at_head(live_client: TestClient) -> None:
    response = live_client.get("/api/v1/ready")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body == {"status": "ready", "database": "ok", "alembic_current": head_revision()}


def test_openapi_is_served_under_the_versioned_prefix(unreachable_client: TestClient) -> None:
    response = unreachable_client.get("/api/v1/openapi.json")
    assert response.status_code == 200
    document = response.json()
    assert document["info"]["title"] == "JudgeMetrics API"
    assert {"/api/v1/health", "/api/v1/ready"} <= document["paths"].keys()
