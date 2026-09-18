# tests/integration/test_api_coverage.py
"""`/api/v1/coverage` over the committed fixtures.

The first test runs with the FJC fixture alone (the module purges any
synthetic rows first) and expects `synthetic_present` false; the second
requests the module-scoped golden ingest, after which the synthetic
source is reported with its counts, window, and last run and
`synthetic_present` is true. Test order in this file is therefore part
of the test: pytest instantiates the module-scoped `golden_fixture` on
its first use, which must come after the FJC-only assertions.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from judgemetrics.api.deps import CACHE_CONTROL
from tests.integration.conftest import FjcFixture, GoldenFixture, purge_synthetic

pytestmark = pytest.mark.integration

SOURCE_KEYS = {
    "source",
    "source_type",
    "synthetic",
    "jurisdictions",
    "courts",
    "judges",
    "cases",
    "persons",
    "earliest_filed",
    "latest_filed",
    "last_ingest",
}


def _by_source(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sources = body["sources"]
    assert isinstance(sources, list)
    return {entry["source"]: entry for entry in sources}


def test_only_the_fjc_fixture_present_means_no_synthetic_source(
    api: TestClient, fjc_fixture: FjcFixture, migrated_database: Engine
) -> None:
    purge_synthetic(migrated_database)
    response = api.get("/api/v1/coverage")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {"sources", "synthetic_present", "generated_at"}
    assert body["synthetic_present"] is False
    sources = _by_source(body)
    assert "synthetic" not in sources
    assert set(sources["fjc"]) == SOURCE_KEYS
    assert sources["fjc"]["synthetic"] is False
    assert sources["fjc"]["source_type"] == "government_directory"
    assert sources["fjc"]["cases"] == 0
    assert sources["fjc"]["earliest_filed"] is None
    # The fixture's own run is the latest FJC run on a clean database; on a
    # developer's database a live run may be newer, so only its shape is fixed.
    last = sources["fjc"]["last_ingest"]
    assert last is not None
    assert set(last) == {"run_id", "completed_at", "status"}
    uuid.UUID(last["run_id"])
    assert last["status"] == "succeeded"
    generated = datetime.fromisoformat(body["generated_at"])
    assert abs((datetime.now(UTC) - generated).total_seconds()) < 60


def test_golden_ingest_is_reported_with_counts_window_and_last_run(
    api: TestClient, fjc_fixture: FjcFixture, golden_fixture: GoldenFixture
) -> None:
    body = api.get("/api/v1/coverage").json()
    assert body["synthetic_present"] is True
    sources = _by_source(body)
    assert [entry["source"] for entry in body["sources"]] == sorted(sources)
    synthetic = sources["synthetic"]
    assert set(synthetic) == SOURCE_KEYS
    assert synthetic["source_type"] == "synthetic"
    assert synthetic["synthetic"] is True
    # The golden dataset: one jurisdiction, three courts, six judges, sixty
    # cases (three duplicate copies collapse), forty resolved persons after
    # the two planted split pairs merge.
    assert (
        synthetic["jurisdictions"],
        synthetic["courts"],
        synthetic["judges"],
        synthetic["cases"],
        synthetic["persons"],
    ) == (1, 3, 6, 60, 40)
    assert (synthetic["earliest_filed"], synthetic["latest_filed"]) == ("2019-01-21", "2021-11-25")
    assert synthetic["last_ingest"] == {
        "run_id": str(golden_fixture.run_id),
        "completed_at": synthetic["last_ingest"]["completed_at"],
        "status": "succeeded",
    }
    assert synthetic["last_ingest"]["completed_at"] is not None
    # The FJC source is unchanged by the synthetic ingest.
    assert sources["fjc"]["synthetic"] is False
    assert sources["fjc"]["cases"] == 0


def test_coverage_rejects_query_parameters(api: TestClient) -> None:
    response = api.get("/api/v1/coverage", params={"source": "fjc"})
    assert response.status_code == 422
    assert response.json()["message"] == "unknown query parameter(s): source"
