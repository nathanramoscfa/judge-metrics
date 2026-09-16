# tests/integration/test_api_jurisdictions.py
"""`/api/v1/jurisdictions` over the committed FJC fixture ingest."""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from judgemetrics.api.deps import CACHE_CONTROL
from judgemetrics.main import REQUEST_ID_HEADER
from tests.integration.conftest import FjcFixture

pytestmark = pytest.mark.integration

SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_list_contains_the_federal_jurisdiction(api: TestClient, fjc_fixture: FjcFixture) -> None:
    response = api.get("/api/v1/jurisdictions")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    page = response.json()
    assert set(page) == {"items", "total", "limit", "offset", "next_offset"}
    assert page["total"] >= 1
    federal = [item for item in page["items"] if item["id"] == str(fjc_fixture.jurisdiction_id)]
    assert federal == [
        {
            "id": str(fjc_fixture.jurisdiction_id),
            "name": "United States federal courts",
            "type": "federal",
            "state_code": None,
            "fips_code": None,
            "parent_jurisdiction_id": None,
        }
    ]


@pytest.mark.parametrize("params", [{"limit": 101}, {"limit": 0}, {"offset": -1}])
def test_pagination_bounds(api: TestClient, params: dict[str, int]) -> None:
    response = api.get("/api/v1/jurisdictions", params=params)
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
    accepted = api.get("/api/v1/jurisdictions", params={"limit": 100, "offset": 0})
    assert accepted.status_code == 200


def test_unknown_query_parameter_is_rejected(api: TestClient) -> None:
    response = api.get("/api/v1/jurisdictions", params={"type": "federal"})
    assert response.status_code == 422
    assert response.json()["message"] == "unknown query parameter(s): type"


def test_detail_carries_provenance(api: TestClient, fjc_fixture: FjcFixture) -> None:
    response = api.get(f"/api/v1/jurisdictions/{fjc_fixture.jurisdiction_id}")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert body["name"] == "United States federal courts"
    assert body["type"] == "federal"
    (block,) = body["provenance"]
    assert block["source"] == "fjc"
    assert SHA256.match(block["raw_sha256"])
    uuid.UUID(block["ingest_run_id"])
    assert "raw_object_path" not in response.text


def test_missing_jurisdiction_is_404(api: TestClient) -> None:
    response = api.get(f"/api/v1/jurisdictions/{uuid.UUID(int=0)}")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
