# tests/integration/test_api_courts.py
"""`/api/v1/courts` over the committed FJC fixture ingest."""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient

from judgemetrics.api.deps import CACHE_CONTROL
from judgemetrics.main import REQUEST_ID_HEADER
from tests.integration.conftest import FjcFixture

pytestmark = pytest.mark.integration

SUPREME_COURT = "Supreme Court of the United States"
MARYLAND = "U.S. District Court for the District of Maryland"
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_list_pages_with_the_uniform_envelope(api: TestClient) -> None:
    response = api.get("/api/v1/courts", params={"limit": 5})
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    page = response.json()
    assert set(page) == {"items", "total", "limit", "offset", "next_offset"}
    assert page["total"] >= 28
    assert len(page["items"]) == 5
    assert page["next_offset"] == 5
    assert set(page["items"][0]) == {
        "id",
        "canonical_name",
        "court_type",
        "state_code",
        "jurisdiction_id",
        "synthetic",
    }
    assert all(
        item["synthetic"] is False for item in page["items"] if item["court_type"] != "circuit"
    )
    names = [item["canonical_name"] for item in page["items"]]
    assert names == sorted(names)

    everything = api.get("/api/v1/courts", params={"limit": 100}).json()
    if everything["total"] <= 100:
        assert everything["next_offset"] is None
        assert {item["canonical_name"] for item in everything["items"]} >= {
            SUPREME_COURT,
            MARYLAND,
        }


@pytest.mark.parametrize(
    "params",
    [{"limit": 101}, {"offset": -1}, {"jurisdiction_id": "x"}, {"court_type": "Supreme!"}],
)
def test_invalid_parameters_are_422(api: TestClient, params: dict[str, object]) -> None:
    response = api.get("/api/v1/courts", params=params)
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "validation_error"


def test_unknown_query_parameter_is_rejected(api: TestClient) -> None:
    response = api.get("/api/v1/courts", params={"state": "MD"})
    assert response.status_code == 422
    assert response.json()["message"] == "unknown query parameter(s): state"


def test_filters(api: TestClient, fjc_fixture: FjcFixture) -> None:
    supreme = api.get("/api/v1/courts", params={"court_type": "supreme"}).json()
    assert [item["canonical_name"] for item in supreme["items"]] == [SUPREME_COURT]
    assert supreme["items"][0]["id"] == str(fjc_fixture.court_ids[SUPREME_COURT])

    district = api.get("/api/v1/courts", params={"court_type": "district", "limit": 100}).json()
    assert district["total"] >= 1
    assert all(item["court_type"] == "district" for item in district["items"])
    maryland = [item for item in district["items"] if item["canonical_name"] == MARYLAND]
    assert not maryland or maryland[0]["state_code"] == "MD"

    federal = api.get(
        "/api/v1/courts", params={"jurisdiction_id": str(fjc_fixture.jurisdiction_id)}
    ).json()
    assert federal["total"] >= 28
    other = api.get("/api/v1/courts", params={"jurisdiction_id": str(uuid.UUID(int=0))}).json()
    assert other == {"items": [], "total": 0, "limit": 25, "offset": 0, "next_offset": None}


def test_detail_carries_provenance(api: TestClient, fjc_fixture: FjcFixture) -> None:
    court_id = fjc_fixture.court_ids[MARYLAND]
    response = api.get(f"/api/v1/courts/{court_id}")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "id",
        "canonical_name",
        "court_type",
        "state_code",
        "jurisdiction_id",
        "external_ids",
        "active_from",
        "active_to",
        "synthetic",
        "provenance",
    }
    assert body["canonical_name"] == MARYLAND
    assert body["synthetic"] is False
    assert body["court_type"] == "district"
    assert body["state_code"] == "MD"
    assert body["jurisdiction_id"] == str(fjc_fixture.jurisdiction_id)
    assert body["external_ids"] == {"fjc_court_name": MARYLAND}
    (block,) = body["provenance"]
    assert block["source"] == "fjc"
    assert block["synthetic"] is False
    assert block["external_record_id"] == "federal-judicial-service.csv"
    assert SHA256.match(block["raw_sha256"])
    assert "raw_object_path" not in response.text


def test_missing_court_is_404(api: TestClient) -> None:
    response = api.get(f"/api/v1/courts/{uuid.UUID(int=0)}")
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert "Cache-Control" not in response.headers
