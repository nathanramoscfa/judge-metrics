# tests/integration/test_api_metrics.py
"""The metrics API over the committed golden ingest with its computed observations.

`GET /metrics` serves the registry (the eight known limitations verbatim,
a `methodology_url` per definition) without a database; `/judges/{id}/metrics`
and `/courts/{id}/metrics` return every current observation with the
presentation fields, grouped by slug, with suppressed rows stripped of
their numbers and 404 for an unknown subject; `/metrics/compare` answers
one metric and window for one court or jurisdiction, sorted and
paginated, with 422 for an unknown metric, a window the metric lacks, a
missing or doubled cohort, an inverted period, and an unknown parameter,
404 for an unknown cohort, and suppressed rows sorted as if their figure
were null; `/metrics/{id}/provenance` answers the chain for a current
observation and 404 for an unknown or superseded one.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from judgemetrics.api.deps import CACHE_CONTROL
from judgemetrics.db.models import MetricObservation
from judgemetrics.metrics.methodology import (
    ATTRIBUTION_TEXT,
    CHANGELOG,
    GATE_TEXT,
    HOW_TO_READ,
    SEMANTICS,
)
from judgemetrics.metrics.registry import load_registry
from judgemetrics.schemas.metrics import SUPPRESSED_FIELDS
from tests.integration.conftest import GoldenFixture, GoldenMetrics, make_app

pytestmark = pytest.mark.integration

REGISTRY = load_registry()
BRIEF_WARNING_ONE = (
    "A judge who handles a disproportionately high-risk docket may exhibit higher raw "
    "subsequent-event rates even if decision-making has no causal effect. Raw rates must "
    "therefore be accompanied by case-mix context."
)
PRESENTATION_FIELDS = {
    "numerator",
    "denominator",
    "eligible_count",
    "period_start",
    "period_end",
    "coverage",
    "rate",
    "lower",
    "upper",
    "interval_method",
    "suppressed",
    "suppression_threshold",
    "methodology_version",
    "methodology_url",
    "snapshot_hash",
    "synthetic",
}
JUDGE = "J-0003"
COURT = "C-0003"


@pytest.fixture(scope="module")
def metrics_api(golden_metrics: GoldenMetrics) -> Iterator[TestClient]:
    """The API, as the app role, over the module's golden ingest and its observations."""
    app = make_app(golden_metrics.settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()


def _observations(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for group in body["observations"].values() for item in group]


def test_registry_lists_every_definition_with_the_known_limitations_verbatim(
    metrics_api: TestClient,
) -> None:
    response = metrics_api.get("/api/v1/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "registry_version",
        "methodology_version",
        "methodology_url",
        "windows_days",
        "known_limitations",
        "suppression",
        "how_to_read",
        "semantics",
        "attribution_notes",
        "gate_descriptions",
        "changelog",
        "definitions",
    }
    assert body["registry_version"] == REGISTRY.version
    # The prose the web methodology page renders is the renderer's own text.
    assert body["windows_days"] == [30, 90, 180, 365, 730, 1095]
    assert [item["term"] for item in body["how_to_read"]] == [term for term, _ in HOW_TO_READ]
    assert [item["term"] for item in body["semantics"]] == [term for term, _ in SEMANTICS]
    assert body["attribution_notes"] == list(ATTRIBUTION_TEXT)
    assert body["gate_descriptions"] == GATE_TEXT
    assert body["changelog"] == [{"version": v, "text": t} for v, t in CHANGELOG]
    assert body["changelog"][0]["version"] == REGISTRY.methodology_version
    assert body["methodology_version"] == REGISTRY.methodology_version
    assert body["known_limitations"] == list(REGISTRY.known_limitations)
    assert len(body["known_limitations"]) == 8
    assert body["known_limitations"][0] == BRIEF_WARNING_ONE
    assert body["suppression"]["default_threshold"] == 10
    assert [item["slug"] for item in body["definitions"]] == list(REGISTRY.metrics)
    for item in body["definitions"]:
        assert item["methodology_url"] == f"/methodology#{item['slug']}"
        assert set(item) >= {
            "slug",
            "name",
            "kind",
            "subject_types",
            "description",
            "numerator",
            "denominator",
            "eligibility",
            "attribution",
            "index_event",
            "outcome",
            "windows_days",
            "dimension",
            "suppression_threshold",
            "unit",
            "version",
        }
    assert metrics_api.get("/api/v1/metrics", params={"kind": "count"}).status_code == 422


def test_judge_metrics_carry_every_presentation_field_grouped_by_slug(
    metrics_api: TestClient, golden_fixture: GoldenFixture, golden_metrics: GoldenMetrics
) -> None:
    judge_id = golden_fixture.judge_ids[JUDGE]
    response = metrics_api.get(f"/api/v1/judges/{judge_id}/metrics")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "subject",
        "registry_version",
        "methodology_version",
        "methodology_url",
        "total",
        "observations",
    }
    assert body["subject"] == {
        "subject_type": "judge",
        "id": str(judge_id),
        "canonical_name": "Puce Wingnut",
        "synthetic": True,
    }
    observations = _observations(body)
    assert body["total"] == len(observations) > 0
    assert set(body["observations"]) <= set(REGISTRY.metrics)
    # Not-observable metrics have no entry; court-only metrics never appear for a judge.
    assert "release_violation_rate" not in body["observations"]
    assert "statutory_release_count" not in body["observations"]
    snapshot = golden_metrics.result.snapshot.content_hash
    for item in observations:
        assert PRESENTATION_FIELDS <= set(item), item["slug"]
        assert item["subject_type"] == "judge" and item["subject_id"] == str(judge_id)
        assert item["source"] == "synthetic" and item["synthetic"] is True
        assert (item["period_start"], item["period_end"]) == ("2019-01-01", "2021-12-31")
        assert item["coverage"] == {
            "coverage_start": "2019-01-01",
            "coverage_end": "2021-12-31",
            "observable": True,
        }
        assert item["methodology_version"] == REGISTRY.methodology_version
        assert item["methodology_url"] == f"/methodology#{item['slug']}"
        assert item["snapshot_hash"] == snapshot
        assert item["suppression_threshold"] == REGISTRY[item["slug"]].suppression_threshold
        definition = REGISTRY[item["slug"]]
        expected_method = {"share": "wilson", "windowed_rate": "wilson", "survival": "greenwood"}
        assert item["interval_method"] == expected_method.get(definition.kind)
        if item["suppressed"]:
            assert all(item[name] is None for name in SUPPRESSED_FIELDS), item["slug"]
            assert item["eligible_count"] >= 0
        else:
            assert item["numerator"] is not None and item["denominator"] is not None
            if definition.kind in {"share", "windowed_rate", "survival"} and item["denominator"]:
                assert item["rate"] is not None
                assert item["lower"] <= item["rate"] <= item["upper"]
    # Windowed metrics list every window in order.
    windowed = body["observations"]["new_case_rate"]
    assert [item["window_days"] for item in windowed] == [30, 90, 180, 365, 730, 1095]
    # Small cohorts exist in the golden fixture and are suppressed on the wire.
    assert any(item["suppressed"] for item in observations)


def test_court_metrics_and_the_unknown_subject(
    metrics_api: TestClient, golden_fixture: GoldenFixture
) -> None:
    court_id = golden_fixture.court_ids[COURT]
    body = metrics_api.get(f"/api/v1/courts/{court_id}/metrics").json()
    assert body["subject"]["subject_type"] == "court"
    assert body["subject"]["id"] == str(court_id)
    assert "statutory_release_count" in body["observations"]
    assert all(item["subject_type"] == "court" for item in _observations(body))
    for path in (
        f"/api/v1/judges/{uuid.uuid4()}/metrics",
        f"/api/v1/courts/{uuid.uuid4()}/metrics",
        f"/api/v1/courts/{court_id}/metrics?limit=5",
        f"/api/v1/judges/{golden_fixture.judge_ids[JUDGE]}/metrics?q=x",
    ):
        response = metrics_api.get(path)
        assert response.status_code in {404, 422}, path
        assert set(response.json()) == {"code", "message", "request_id"}
    assert metrics_api.get(f"/api/v1/judges/{uuid.uuid4()}/metrics").status_code == 404
    assert metrics_api.get(f"/api/v1/courts/{court_id}/metrics?limit=5").status_code == 422
    # A reference judge without cases (none in the golden module) would be an empty
    # grouping, not an error: the FJC judges have no observation.
    fjc_less = metrics_api.get(f"/api/v1/judges/{uuid.uuid4()}/metrics")
    assert fjc_less.json()["code"] == "not_found"


# --- compare -----------------------------------------------------------------------------


def test_compare_answers_one_metric_and_window_for_a_court_sorted_and_paginated(
    metrics_api: TestClient, golden_fixture: GoldenFixture
) -> None:
    court_id = golden_fixture.court_ids[COURT]
    params = {"metric": "eligible_cases", "court_id": str(court_id), "sort": "numerator"}
    response = metrics_api.get("/api/v1/metrics/compare", params=params)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "items",
        "total",
        "limit",
        "offset",
        "next_offset",
        "cohort",
        "methodology_version",
        "methodology_url",
    }
    assert body["cohort"] == {
        "metric": "eligible_cases",
        "version": REGISTRY["eligible_cases"].version,
        "window_days": None,
        "court_id": str(court_id),
        "jurisdiction_id": str(golden_fixture.jurisdiction_id),
        "name": "Synthetic County Circuit Court, Division 3",
        "period_start": "2019-01-01",
        "period_end": "2021-12-31",
        "sort": "numerator",
        "order": "desc",
    }
    assert body["methodology_url"] == "/methodology#eligible_cases"
    assert body["total"] == len(body["items"]) >= 1
    numerators = [item["numerator"] for item in body["items"]]
    assert numerators == sorted(numerators, reverse=True)
    for item in body["items"]:
        assert item["court"]["id"] == str(court_id)
        assert item["synthetic"] is True
        assert item["coverage_warning"] is None
        assert item["window_days"] is None and item["dimension_value"] is None
        assert item["numerator"] == item["eligible_count"] == item["denominator"]
    # The judge's own subject metrics agree with the compare row.
    top = body["items"][0]
    own = metrics_api.get(f"/api/v1/judges/{top['subject_id']}/metrics").json()
    assert own["observations"]["eligible_cases"][0]["id"] == top["observation_id"]
    assert own["observations"]["eligible_cases"][0]["numerator"] == top["numerator"]

    # A windowed metric needs its window; rows sort by rate with suppressed rows last.
    windowed = metrics_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "new_case_rate",
            "window": 365,
            "jurisdiction_id": str(golden_fixture.jurisdiction_id),
            "limit": 100,
        },
    ).json()
    assert windowed["cohort"]["court_id"] is None
    assert windowed["cohort"]["name"] == "Synthetic State"
    assert windowed["total"] == len(golden_fixture.judge_ids)
    assert {item["subject_id"] for item in windowed["items"]} == {
        str(judge_id) for judge_id in golden_fixture.judge_ids.values()
    }
    visible = [item for item in windowed["items"] if not item["suppressed"]]
    hidden = [item for item in windowed["items"] if item["suppressed"]]
    rates = [item["rate"] for item in visible]
    assert rates == sorted(rates, reverse=True)
    assert windowed["items"][: len(visible)] == visible, "suppressed rows sort last"
    for item in hidden:
        assert all(item[name] is None for name in SUPPRESSED_FIELDS)
        assert item["suppression_threshold"] == 10
    asc = metrics_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "new_case_rate",
            "window": 365,
            "jurisdiction_id": str(golden_fixture.jurisdiction_id),
            "order": "asc",
            "limit": 100,
        },
    ).json()
    assert [i["rate"] for i in asc["items"] if not i["suppressed"]] == sorted(rates)
    assert asc["items"][-len(hidden) :] == hidden if hidden else True
    # Pagination follows next_offset until it is null.
    first = metrics_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "eligible_cases",
            "jurisdiction_id": str(golden_fixture.jurisdiction_id),
            "sort": "name",
            "order": "asc",
            "limit": 2,
        },
    ).json()
    assert first["limit"] == 2 and first["offset"] == 0
    assert first["next_offset"] == 2
    names = [item["name"] for item in first["items"]]
    assert names == sorted(names)
    # A period filter restricts to the exact source period; another period is empty, not 404.
    same = metrics_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "eligible_cases",
            "court_id": str(court_id),
            "period_start": "2019-01-01",
            "period_end": "2021-12-31",
        },
    ).json()
    assert same["total"] == body["total"]
    other = metrics_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "eligible_cases",
            "court_id": str(court_id),
            "period_start": "2018-01-01",
            "period_end": "2018-12-31",
        },
    )
    assert other.status_code == 200
    assert other.json()["total"] == 0 and other.json()["items"] == []
    assert other.json()["cohort"]["name"] == "Synthetic County Circuit Court, Division 3"


@pytest.mark.parametrize(
    ("params", "status", "fragment"),
    [
        ({"metric": "eligible_cases"}, 422, "court_id"),
        (
            {"metric": "eligible_cases", "court_id": "{court}", "jurisdiction_id": "{jur}"},
            422,
            "court_id",
        ),
        ({"metric": "not_a_metric", "court_id": "{court}"}, 422, "metric"),
        ({"metric": "eligible_cases", "window": 30, "court_id": "{court}"}, 422, "window"),
        ({"metric": "new_case_rate", "court_id": "{court}"}, 422, "window"),
        (
            {"metric": "new_case_rate", "window": 31, "court_id": "{court}"},
            422,
            "window",
        ),
        ({"metric": "statutory_release_count", "court_id": "{court}"}, 422, "metric"),
        ({"metric": "eligible_cases", "court_id": "{court}", "sort": "rank"}, 422, "sort"),
        ({"metric": "eligible_cases", "court_id": "{court}", "order": "up"}, 422, "order"),
        ({"metric": "eligible_cases", "court_id": "{court}", "limit": 101}, 422, "limit"),
        ({"metric": "eligible_cases", "court_id": "{court}", "cohort": "court"}, 422, "cohort"),
        (
            {
                "metric": "eligible_cases",
                "court_id": "{court}",
                "period_start": "2021-01-01",
                "period_end": "2020-01-01",
            },
            422,
            "period_end",
        ),
        ({"metric": "eligible_cases", "court_id": "not-a-uuid"}, 422, "court_id"),
        (
            {"metric": "eligible_cases", "court_id": "00000000-0000-0000-0000-000000000000"},
            404,
            "court",
        ),
        (
            {"metric": "eligible_cases", "jurisdiction_id": "00000000-0000-0000-0000-000000000000"},
            404,
            "jurisdiction",
        ),
    ],
)
def test_compare_rejects_bad_requests_with_the_error_envelope(
    metrics_api: TestClient,
    golden_fixture: GoldenFixture,
    params: dict[str, Any],
    status: int,
    fragment: str,
) -> None:
    filled = {
        key: str(value)
        .replace("{court}", str(golden_fixture.court_ids[COURT]))
        .replace("{jur}", str(golden_fixture.jurisdiction_id))
        for key, value in params.items()
    }
    response = metrics_api.get("/api/v1/metrics/compare", params=filled)
    assert response.status_code == status, (filled, response.text)
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == ("not_found" if status == 404 else "validation_error")
    assert fragment in body["message"]


# --- provenance ----------------------------------------------------------------------------


def test_provenance_endpoint_answers_the_chain_and_404_for_unknown_or_superseded(
    metrics_api: TestClient,
    golden_fixture: GoldenFixture,
    golden_metrics: GoldenMetrics,
    migrated_database: Engine,
) -> None:
    judge_id = golden_fixture.judge_ids[JUDGE]
    own = metrics_api.get(f"/api/v1/judges/{judge_id}/metrics").json()
    observation = own["observations"]["pretrial_decisions"][0]
    response = metrics_api.get(f"/api/v1/metrics/{observation['id']}/provenance")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "observation",
        "snapshot",
        "members",
        "source_records",
        "sources",
        "complete",
    }
    assert body["complete"] is True
    assert body["observation"]["id"] == observation["id"]
    assert body["observation"]["numerator"] == observation["numerator"]
    assert body["observation"]["superseded_at"] is None
    assert body["observation"]["registry_version"] == REGISTRY.version
    assert body["snapshot"]["content_hash"] == golden_metrics.result.snapshot.content_hash
    assert "storage_uri" not in body["snapshot"]
    assert body["snapshot"]["row_counts"]["cases"] == 60
    assert [group["member_kind"] for group in body["members"]] == ["decision"]
    group = body["members"][0]
    assert group["members"] == group["resolved"] == observation["eligible_count"]
    assert group["counted"] == observation["numerator"]
    assert group["case_ids"] and all(
        uuid.UUID(case_id) in golden_fixture.case_ids.values() for case_id in group["case_ids"]
    )
    assert [record["external_record_id"] for record in body["source_records"]] == [
        "source/decisions.csv"
    ]
    record = body["source_records"][0]
    assert set(record) == {
        "id",
        "source",
        "external_record_id",
        "raw_sha256",
        "retrieved_at",
        "parser_version",
        "ingest_run_id",
        "artifact_uri",
    }
    assert record["artifact_uri"] is None  # a fixture file, not a public URL
    assert record["ingest_run_id"] == str(golden_fixture.run_id)
    assert body["sources"] == [
        {
            "source": "synthetic",
            "owner": body["sources"][0]["owner"],
            "source_type": "synthetic",
            "synthetic": True,
            "coverage_start": "2019-01-01",
            "coverage_end": "2021-12-31",
            "observable_outcomes": [
                "failure_to_appear",
                "new_case",
                "new_charge",
                "reconviction",
                "revocation",
            ],
        }
    ]
    assert "raw_object_path" not in response.text
    assert metrics_api.get(f"/api/v1/metrics/{uuid.uuid4()}/provenance").status_code == 404
    assert metrics_api.get("/api/v1/metrics/not-a-uuid/provenance").status_code == 422
    # A superseded observation is history: 404 on the public surface.
    with Session(migrated_database) as session:
        session.execute(
            update(MetricObservation)
            .where(MetricObservation.id == uuid.UUID(observation["id"]))
            .values(superseded_at=MetricObservation.computed_at)
        )
        session.commit()
        try:
            gone = metrics_api.get(f"/api/v1/metrics/{observation['id']}/provenance")
            assert gone.status_code == 404
            assert gone.json()["code"] == "not_found"
            still = metrics_api.get(f"/api/v1/judges/{judge_id}/metrics").json()
            assert observation["id"] not in {item["id"] for item in _observations(still)}
        finally:
            session.execute(
                update(MetricObservation)
                .where(MetricObservation.id == uuid.UUID(observation["id"]))
                .values(superseded_at=None)
            )
            session.commit()
        assert (
            session.scalar(
                select(MetricObservation.superseded_at).where(
                    MetricObservation.id == uuid.UUID(observation["id"])
                )
            )
            is None
        )
