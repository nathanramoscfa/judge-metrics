# tests/integration/test_api_search.py
"""`/api/v1/search` over the committed FJC fixture ingest.

Search tolerance (a misspelt surname still finds the judge — alone, by
word similarity, and beside a first name, by whole-name similarity),
ordering by score, courts in the same result list, strict parameters, and
the in-process rate limiter: off by default under `env == test`, switched
on explicitly here with a held clock so the burst is exhausted
deterministically and the 429 carries `Retry-After` and an `ErrorBody`.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from judgemetrics.api.ratelimit import RETRY_AFTER_HEADER, TokenBucketLimiter
from judgemetrics.config import Settings
from judgemetrics.main import REQUEST_ID_HEADER
from tests.integration.conftest import FjcFixture, GoldenFixture, make_app

pytestmark = pytest.mark.integration

SOTOMAYOR = "1388091"
KAVANAUGH = "1392406"
GINSBURG = "1381271"


def test_misspelled_surname_finds_the_judge(api: TestClient, fjc_fixture: FjcFixture) -> None:
    response = api.get("/api/v1/search", params={"q": "Sotomayer"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"query", "limit", "items"}
    assert body["query"] == "sotomayer"
    assert body["limit"] == 25
    assert body["items"], "no results"
    top = body["items"][0]
    assert set(top) == {"entity_type", "id", "name", "score", "synthetic"}
    assert top == {
        "entity_type": "judge",
        "id": str(fjc_fixture.judge_ids[SOTOMAYOR]),
        "name": "Sonia Sotomayor",
        "score": top["score"],
        "synthetic": False,
    }
    assert 0.3 <= top["score"] <= 1.0

    kavanagh = api.get("/api/v1/search", params={"q": "kavanagh", "limit": 5}).json()
    assert str(fjc_fixture.judge_ids[KAVANAUGH]) in {item["id"] for item in kavanagh["items"]}


def test_misspelled_surname_alone_finds_a_long_full_name(
    api: TestClient, fjc_fixture: FjcFixture
) -> None:
    """Phase 1 finding 4.1: "Ginsberg" scored 0.26 against "ruth bader ginsburg" whole-name.

    A one-word query now matches by word similarity (`<%`), so the surname
    alone finds the judge; the same query with a first name keeps
    whole-name similarity and still finds her.
    """
    ginsburg = str(fjc_fixture.judge_ids[GINSBURG])
    alone = api.get("/api/v1/search", params={"q": "Ginsberg"}).json()
    assert alone["query"] == "ginsberg"
    judges = [item for item in alone["items"] if item["entity_type"] == "judge"]
    assert judges and judges[0]["id"] == ginsburg
    assert judges[0]["name"] == "Ruth Bader Ginsburg"
    assert 0.5 <= judges[0]["score"] <= 1.0
    # The judges list's `q` filter takes the same path.
    listed = api.get("/api/v1/judges", params={"q": "Ginsberg"}).json()
    assert listed["items"] and listed["items"][0]["id"] == ginsburg
    assert listed["total"] >= 1
    # Several words: whole-name similarity, as before.
    full = api.get("/api/v1/search", params={"q": "ruth ginsberg"}).json()
    assert full["items"] and full["items"][0]["id"] == ginsburg
    listed_full = api.get("/api/v1/judges", params={"q": "ruth ginsberg"}).json()
    assert listed_full["items"] and listed_full["items"][0]["id"] == ginsburg
    # A surname alone still ranks its judge first among the fixture's names.
    for query, nid in (("Kavanagh", KAVANAUGH), ("Sotomayer", SOTOMAYOR)):
        top = api.get("/api/v1/search", params={"q": query}).json()["items"][0]
        assert top["id"] == str(fjc_fixture.judge_ids[nid]), query
    # A word that matches nothing is an empty list, not an error.
    assert api.get("/api/v1/search", params={"q": "zzzzzzzz"}).json()["items"] == []


def test_results_are_ordered_by_score_and_include_courts(
    api: TestClient, fjc_fixture: FjcFixture
) -> None:
    body = api.get("/api/v1/search", params={"q": "Supreme Court", "limit": 10}).json()
    scores = [item["score"] for item in body["items"]]
    assert scores == sorted(scores, reverse=True)
    courts = [item for item in body["items"] if item["entity_type"] == "court"]
    assert courts and courts[0]["name"] == "Supreme Court of the United States"
    assert courts[0]["id"] == str(fjc_fixture.court_ids["Supreme Court of the United States"])
    assert {item["entity_type"] for item in body["items"]} <= {"judge", "court", "case"}


def test_query_is_normalized_and_limit_applies(api: TestClient) -> None:
    body = api.get("/api/v1/search", params={"q": "  ALARCÓN, Arthur ", "limit": 1}).json()
    assert body["query"] == "alarcon arthur"
    assert len(body["items"]) == 1
    assert body["items"][0]["name"] == "Arthur Lawrence Alarcón"
    nothing = api.get("/api/v1/search", params={"q": "!!!"}).json()
    assert nothing == {"query": "", "limit": 25, "items": []}
    assert "raw_object_path" not in api.get("/api/v1/search", params={"q": "Alito"}).text


@pytest.mark.parametrize(
    ("params", "fragment"),
    [
        ({}, "q"),
        ({"q": ""}, "q"),
        ({"q": "x" * 201}, "q"),
        ({"q": "alito", "limit": 101}, "limit"),
        ({"q": "alito", "limit": 0}, "limit"),
        ({"q": "alito", "offset": 5}, "offset"),
        ({"q": "alito", "type": "judge"}, "type"),
    ],
)
def test_invalid_parameters_are_422(
    api: TestClient, params: dict[str, object], fragment: str
) -> None:
    response = api.get("/api/v1/search", params=params)
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "validation_error"
    assert fragment in body["message"]


# --- case numbers (golden synthetic fixture) ------------------------------------------


def test_exact_case_number_matches_and_a_partial_one_does_not(
    api: TestClient, golden_fixture: GoldenFixture
) -> None:
    case_id = str(golden_fixture.case_ids["SYN-2020-000005"])
    for query in ("SYN-2020-000005", "syn 2020 000005", "  syn-2020-000005 ", "SYN/2020/000005"):
        body = api.get("/api/v1/search", params={"q": query}).json()
        cases = [item for item in body["items"] if item["entity_type"] == "case"]
        assert cases == [
            {
                "entity_type": "case",
                "id": case_id,
                "name": "SYN-2020-000005",
                "score": 1.0,
                "synthetic": True,
            }
        ], query
        # An exact number outranks any similar name.
        assert body["items"][0]["entity_type"] == "case"
    for partial in ("2020-000005", "SYN-2020", "SYN-2020-00000", "000005"):
        body = api.get("/api/v1/search", params={"q": partial}).json()
        assert not [item for item in body["items"] if item["entity_type"] == "case"], partial


def test_synthetic_judges_and_courts_are_flagged_in_search(
    api: TestClient, golden_fixture: GoldenFixture
) -> None:
    body = api.get("/api/v1/search", params={"q": "Puce Wingnut"}).json()
    top = body["items"][0]
    assert top["entity_type"] == "judge"
    assert top["id"] == str(golden_fixture.judge_ids["J-0003"])
    assert top["synthetic"] is True
    courts = api.get("/api/v1/search", params={"q": "Synthetic County Circuit Court"}).json()
    by_name = {item["name"]: item for item in courts["items"] if item["entity_type"] == "court"}
    assert by_name["Synthetic County Circuit Court, Division 3"]["synthetic"] is True
    # An FJC court similar enough to match is not flagged.
    assert all(not item["synthetic"] for name, item in by_name.items() if "U.S." in name)


# --- the rate limiter ---------------------------------------------------------------


def test_limiter_is_off_by_default_under_test(api: TestClient) -> None:
    assert api.app.state.search_limiter is None  # type: ignore[attr-defined]
    for _ in range(15):
        assert api.get("/api/v1/search", params={"q": "alito"}).status_code == 200


@pytest.fixture
def limited(fjc_fixture: FjcFixture, test_settings: Settings) -> Iterator[TestClient]:
    """An app with the limiter on (burst 3) and a clock that never advances."""
    app = make_app(
        test_settings,
        search_rate_limit_enabled=True,
        search_rate_limit_burst=3,
        search_rate_limit_per_minute=60,
        trust_proxy=True,
    )
    assert app.state.search_limiter is not None
    app.state.search_limiter = TokenBucketLimiter(per_minute=60, burst=3, clock=lambda: 0.0)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()


def test_limiter_returns_429_after_the_burst(limited: TestClient) -> None:
    for _ in range(3):
        assert limited.get("/api/v1/search", params={"q": "alito"}).status_code == 200
    response = limited.get("/api/v1/search", params={"q": "alito"})
    assert response.status_code == 429
    assert response.headers[RETRY_AFTER_HEADER] == "1"
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "rate_limited"
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    # The other endpoints are not limited.
    assert limited.get("/api/v1/judges", params={"limit": 1}).status_code == 200


def test_buckets_are_per_client_behind_a_trusted_proxy(limited: TestClient) -> None:
    first = {"X-Forwarded-For": "203.0.113.7"}
    second = {"X-Forwarded-For": "spoofed, 203.0.113.8"}
    for _ in range(3):
        assert (
            limited.get("/api/v1/search", params={"q": "alito"}, headers=first).status_code == 200
        )
    assert limited.get("/api/v1/search", params={"q": "alito"}, headers=first).status_code == 429
    # A different rightmost address is a different bucket.
    assert limited.get("/api/v1/search", params={"q": "alito"}, headers=second).status_code == 200


def test_forwarded_header_is_ignored_without_trust_proxy(
    fjc_fixture: FjcFixture, test_settings: Settings
) -> None:
    app = make_app(test_settings, search_rate_limit_enabled=True, search_rate_limit_burst=2)
    app.state.search_limiter = TokenBucketLimiter(per_minute=60, burst=2, clock=lambda: 0.0)
    with TestClient(app, raise_server_exceptions=False) as client:
        for address in ("203.0.113.1", "203.0.113.2"):
            headers = {"X-Forwarded-For": address}
            assert (
                client.get("/api/v1/search", params={"q": "a"}, headers=headers).status_code == 200
            )
        # Both requests drew from the same (peer-address) bucket.
        response = client.get("/api/v1/search", params={"q": "a"}, headers={"X-Forwarded-For": "x"})
        assert response.status_code == 429
    app.state.engine.dispose()
