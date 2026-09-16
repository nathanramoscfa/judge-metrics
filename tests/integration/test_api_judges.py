# tests/integration/test_api_judges.py
"""`/api/v1/judges` over the committed FJC fixture ingest.

Pagination bounds, strict filter validation, the `active_on` / `court_id`
/ `status` / `q` filters, the 404 envelope, provenance on the detail, the
cache header, and the guarantee that no internal storage key or error
detail leaves the API.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy.exc import OperationalError

from judgemetrics.api.deps import CACHE_CONTROL
from judgemetrics.api.routes import judges as judges_routes
from judgemetrics.main import REQUEST_ID_HEADER
from tests.integration.conftest import FjcFixture

pytestmark = pytest.mark.integration

ALITO = "1377101"
GINSBURG = "1381271"
SOTOMAYOR = "1388091"
THIRD_CIRCUIT = "U.S. Court of Appeals for the Third Circuit"
SUPREME_COURT = "Supreme Court of the United States"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
ERROR_KEYS = {"code", "message", "request_id"}


def _error(response: Response) -> dict[str, str]:
    """The `ErrorBody` of a non-2xx response, with exactly its three fields."""
    body: dict[str, str] = response.json()
    assert set(body) == ERROR_KEYS
    return body


# --- pagination -------------------------------------------------------------------


def test_list_pages_with_the_uniform_envelope(api: TestClient) -> None:
    response = api.get("/api/v1/judges", params={"limit": 10})
    assert response.status_code == 200, response.text
    page = response.json()
    assert set(page) == {"items", "total", "limit", "offset", "next_offset"}
    assert len(page["items"]) == 10
    assert page["total"] >= 25  # the fixture's judges, plus any live ingest
    assert (page["limit"], page["offset"], page["next_offset"]) == (10, 0, 10)
    assert set(page["items"][0]) == {"id", "canonical_name", "status"}
    names = [item["canonical_name"] for item in page["items"]]
    assert names == sorted(names)

    following = api.get("/api/v1/judges", params={"limit": 10, "offset": 10}).json()
    assert following["offset"] == 10
    assert following["items"][0]["id"] not in {item["id"] for item in page["items"]}

    last = api.get("/api/v1/judges", params={"limit": 10, "offset": page["total"]}).json()
    assert last == {
        "items": [],
        "total": page["total"],
        "limit": 10,
        "offset": page["total"],
        "next_offset": None,
    }


def test_default_and_maximum_page_sizes(api: TestClient) -> None:
    default = api.get("/api/v1/judges").json()
    assert default["limit"] == 25
    assert len(default["items"]) == min(25, default["total"])
    maximum = api.get("/api/v1/judges", params={"limit": 100})
    assert maximum.status_code == 200
    assert maximum.json()["limit"] == 100


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({"limit": 101}, "limit"),
        ({"limit": 0}, "limit"),
        ({"offset": -1}, "offset"),
        ({"limit": "ten"}, "limit"),
        ({"active_on": "yesterday"}, "active_on"),
        ({"status": "emeritus"}, "status"),
        ({"court_id": "not-a-uuid"}, "court_id"),
        ({"q": ""}, "q"),
        ({"q": "x" * 201}, "q"),
    ],
)
def test_invalid_parameters_are_422_with_the_error_envelope(
    api: TestClient, params: dict[str, object], fragment: str
) -> None:
    response = api.get("/api/v1/judges", params=params)
    assert response.status_code == 422, response.text
    body = _error(response)
    assert body["code"] == "validation_error"
    assert fragment in body["message"]
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]


def test_unknown_query_parameter_is_rejected(api: TestClient) -> None:
    response = api.get("/api/v1/judges", params={"name": "alito", "sort": "x"})
    assert response.status_code == 422
    body = _error(response)
    assert body["code"] == "validation_error"
    assert body["message"] == "unknown query parameter(s): name, sort"


# --- filters ----------------------------------------------------------------------


def test_active_on_and_court_id_select_the_service_interval(
    api: TestClient, fjc_fixture: FjcFixture
) -> None:
    alito = str(fjc_fixture.judge_ids[ALITO])
    third_circuit = str(fjc_fixture.court_ids[THIRD_CIRCUIT])
    supreme = str(fjc_fixture.court_ids[SUPREME_COURT])

    def ids(**params: str) -> set[str]:
        page = api.get("/api/v1/judges", params={"limit": 100, **params}).json()
        return {item["id"] for item in page["items"]}

    # Alito sat on the Third Circuit 1990-04-30 → 2006-01-31, then the Supreme Court.
    assert alito in ids(court_id=third_circuit, active_on="2000-01-01")
    assert alito not in ids(court_id=third_circuit, active_on="2010-01-01")
    assert alito in ids(court_id=supreme, active_on="2010-01-01")
    assert alito not in ids(court_id=supreme, active_on="2000-01-01")
    # Without a court, any service interval covering the date qualifies (the
    # `q` filter keeps the page small on a database with a live ingest).
    assert alito in ids(q="alito", active_on="1995-06-15")
    assert alito not in ids(q="alito", active_on="1980-01-01")
    # An open-ended appointment covers any later date.
    assert alito in ids(court_id=supreme, active_on="2099-01-01")


def test_status_filter(api: TestClient, fjc_fixture: FjcFixture) -> None:
    page = api.get("/api/v1/judges", params={"status": "deceased", "limit": 100}).json()
    ids = {item["id"] for item in page["items"]}
    assert all(item["status"] == "deceased" for item in page["items"])
    assert str(fjc_fixture.judge_ids[GINSBURG]) in ids or page["total"] > 100
    assert str(fjc_fixture.judge_ids[ALITO]) not in ids


def test_q_filter_ranks_the_closest_name_first(api: TestClient, fjc_fixture: FjcFixture) -> None:
    page = api.get("/api/v1/judges", params={"q": "Sotomayer"}).json()
    assert page["total"] >= 1
    assert page["items"][0]["id"] == str(fjc_fixture.judge_ids[SOTOMAYOR])
    # Normalization applies to the query: diacritics and case do not matter.
    accented = api.get("/api/v1/judges", params={"q": "ALARCÓN"}).json()
    assert accented["items"][0]["canonical_name"] == "Arthur Lawrence Alarcón"
    nothing = api.get("/api/v1/judges", params={"q": "!!!"}).json()
    assert nothing == {"items": [], "total": 0, "limit": 25, "offset": 0, "next_offset": None}


# --- detail ------------------------------------------------------------------------


def test_detail_carries_service_records_and_provenance(
    api: TestClient, fjc_fixture: FjcFixture
) -> None:
    alito = fjc_fixture.judge_ids[ALITO]
    response = api.get(f"/api/v1/judges/{alito}")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "id",
        "canonical_name",
        "status",
        "normalized_name",
        "external_ids",
        "metadata",
        "service",
        "provenance",
    }
    assert body["canonical_name"] == "Samuel A. Alito, Jr."
    assert body["normalized_name"] == "samuel a alito jr"
    assert body["status"] == "active"
    assert body["external_ids"]["fjc_nid"] == ALITO
    assert body["metadata"] == {"birth_year": 1950}

    assert [
        (s["court"]["canonical_name"], s["position_type"], s["start_date"], s["end_date"])
        for s in body["service"]
    ] == [
        (THIRD_CIRCUIT, "Judge", "1990-04-30", "2006-01-31"),
        (SUPREME_COURT, "Associate Justice", "2006-01-31", None),
    ]
    assert set(body["service"][0]) == {
        "id",
        "court",
        "position_type",
        "start_date",
        "end_date",
        "metadata",
    }
    assert body["service"][0]["court"]["id"] == str(fjc_fixture.court_ids[THIRD_CIRCUIT])

    assert body["provenance"], "detail has no provenance"
    for block in body["provenance"]:
        assert set(block) == {
            "source",
            "external_record_id",
            "retrieved_at",
            "raw_sha256",
            "parser_version",
            "ingest_run_id",
        }
        assert block["source"] == "fjc"
        assert SHA256.match(block["raw_sha256"])
        assert block["parser_version"] == "2026.09.1"
        uuid.UUID(block["ingest_run_id"])
    assert {block["external_record_id"] for block in body["provenance"]} <= {
        "judges.csv",
        "federal-judicial-service.csv",
    }
    assert "raw_object_path" not in response.text


def test_service_endpoint_lists_the_records_oldest_first(
    api: TestClient, fjc_fixture: FjcFixture
) -> None:
    response = api.get(f"/api/v1/judges/{fjc_fixture.judge_ids[ALITO]}/service")
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    starts = [record["start_date"] for record in response.json()]
    assert starts == ["1990-04-30", "2006-01-31"]
    assert "raw_object_path" not in response.text


def test_list_responses_are_publicly_cacheable(api: TestClient) -> None:
    assert api.get("/api/v1/judges").headers["Cache-Control"] == CACHE_CONTROL


@pytest.mark.parametrize("suffix", ["", "/service"])
def test_missing_judge_is_404_with_the_error_envelope(api: TestClient, suffix: str) -> None:
    missing = uuid.UUID(int=0)
    response = api.get(f"/api/v1/judges/{missing}{suffix}")
    assert response.status_code == 404
    body = _error(response)
    assert body["code"] == "not_found"
    assert str(missing) in body["message"]
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert "Cache-Control" not in response.headers


def test_malformed_id_is_422(api: TestClient) -> None:
    response = api.get("/api/v1/judges/not-a-uuid")
    assert response.status_code == 422
    assert _error(response)["code"] == "validation_error"


def test_detail_rejects_unknown_query_parameters(api: TestClient, fjc_fixture: FjcFixture) -> None:
    response = api.get(f"/api/v1/judges/{fjc_fixture.judge_ids[ALITO]}", params={"expand": "x"})
    assert response.status_code == 422
    assert _error(response)["message"] == "unknown query parameter(s): expand"


# --- error handlers -----------------------------------------------------------------


def test_unhandled_error_is_500_without_a_trace(
    api: TestClient, fjc_fixture: FjcFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def explode(*args: object, **kwargs: object) -> None:
        msg = "planted-failure-detail"
        raise RuntimeError(msg)

    monkeypatch.setattr(judges_routes, "judge_detail", explode)
    response = api.get(f"/api/v1/judges/{fjc_fixture.judge_ids[ALITO]}")
    assert response.status_code == 500
    body = _error(response)
    assert body == {
        "code": "internal_error",
        "message": "internal server error",
        "request_id": response.headers[REQUEST_ID_HEADER],
    }
    assert "planted-failure-detail" not in response.text
    assert "Traceback" not in response.text


def test_database_error_is_503_without_sql(
    api: TestClient, fjc_fixture: FjcFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        raise OperationalError("SELECT planted_secret_column FROM judge", {}, Exception("down"))

    monkeypatch.setattr(judges_routes, "judge_detail", unavailable)
    response = api.get(f"/api/v1/judges/{fjc_fixture.judge_ids[ALITO]}")
    assert response.status_code == 503
    body = _error(response)
    assert body["code"] == "database_unavailable"
    assert body["message"] == "database unavailable"
    assert "planted_secret_column" not in response.text
    assert "SELECT" not in response.text
