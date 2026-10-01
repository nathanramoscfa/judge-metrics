# tests/integration/test_api_adjusted.py
"""The public hold-out: no metrics response serves an observed-to-expected figure before Step 5.

Over the module's golden ingest and its committed ``metrics compute`` —
which publishes adjusted observations for every golden judge — the API as
the read-only app role: ``GET /api/v1/metrics`` lists no ``observed_expected``
definition; a judge's and a court's ``/metrics`` carry no adjusted slug while
the descriptive observations are all served; ``/metrics/compare`` answers an
adjusted slug with the unknown-metric 422; the provenance route answers an
adjusted observation's id with 404 (and still serves a descriptive one);
``/api/v1/ready`` reports the latest snapshot's models as counts and versions
— never a model hash or an artifact path; and no response anywhere in the
walk names the kind or an adjusted slug. Phase 4 Step 5 turns this module
into the serving tests (``SERVED_KINDS`` gains the kind with its schema).
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import MetricDefinition, MetricObservation, OutcomeModel
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.registry import OBSERVED_EXPECTED, load_registry
from judgemetrics.services.metrics import SERVED_KINDS
from tests.integration.conftest import GoldenFixture, GoldenMetrics, make_app

pytestmark = pytest.mark.integration

REGISTRY = load_registry()
SPEC = load_spec()
ADJUSTED_SLUGS = {metric.slug for metric in REGISTRY.of_kind(OBSERVED_EXPECTED)}
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")


@pytest.fixture(scope="module")
def adjusted_api(golden_metrics: GoldenMetrics) -> Iterator[TestClient]:
    """The API, as the app role, over the module's golden ingest and its observations."""
    app = make_app(golden_metrics.settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()


def _no_adjusted(text: str) -> None:
    assert OBSERVED_EXPECTED not in text
    for slug in ADJUSTED_SLUGS:
        assert slug not in text, slug


def _adjusted_ids(engine: Engine) -> list[uuid.UUID]:
    with Session(engine) as session:
        return list(
            session.scalars(
                select(MetricObservation.id)
                .join(
                    MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id
                )
                .where(
                    MetricDefinition.kind == OBSERVED_EXPECTED,
                    MetricObservation.superseded_at.is_(None),
                )
                .order_by(MetricObservation.id)
            )
        )


def test_the_golden_compute_published_adjusted_observations(
    migrated_database: Engine, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    assert ADJUSTED_SLUGS == {
        "pretrial_release_observed_expected",
        "new_case_observed_expected",
        "failure_to_appear_observed_expected",
    }
    assert SERVED_KINDS == {"count", "share", "windowed_rate", "survival", "distribution", "median"}
    assert _adjusted_ids(migrated_database), "the hold-out tests need adjusted rows to hold out"


def test_the_registry_response_lists_no_adjusted_definition(adjusted_api: TestClient) -> None:
    response = adjusted_api.get("/api/v1/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["kind"] for item in body["definitions"]} <= SERVED_KINDS
    assert [item["slug"] for item in body["definitions"]] == [
        slug for slug, metric in REGISTRY.metrics.items() if metric.kind in SERVED_KINDS
    ]
    assert body["registry_version"] == 2 and body["methodology_version"] == "0.3"
    _no_adjusted(response.text)


def test_subject_routes_serve_every_descriptive_observation_and_no_adjusted_one(
    adjusted_api: TestClient, golden_fixture: GoldenFixture, migrated_database: Engine
) -> None:
    subjects = [("judges", "judge", judge_id) for judge_id in golden_fixture.judge_ids.values()]
    subjects += [("courts", "court", court_id) for court_id in golden_fixture.court_ids.values()]
    with Session(migrated_database) as session:
        for route, subject_type, subject_id in subjects:
            response = adjusted_api.get(f"/api/v1/{route}/{subject_id}/metrics")
            assert response.status_code == 200, response.text
            body = response.json()
            assert not set(body["observations"]) & ADJUSTED_SLUGS
            _no_adjusted(response.text)
            served = session.execute(
                select(MetricDefinition.kind)
                .join(
                    MetricObservation, MetricObservation.metric_definition_id == MetricDefinition.id
                )
                .where(
                    MetricObservation.subject_type == SubjectType(subject_type),
                    MetricObservation.subject_id == subject_id,
                    MetricObservation.superseded_at.is_(None),
                )
            ).all()
            descriptive = sum(1 for (kind,) in served if kind in SERVED_KINDS)
            assert body["total"] == descriptive
            if subject_type == "judge":
                assert len(served) > descriptive  # the judge does hold adjusted rows


def test_compare_answers_an_adjusted_slug_as_an_unknown_metric(
    adjusted_api: TestClient, golden_fixture: GoldenFixture
) -> None:
    court = next(iter(golden_fixture.court_ids.values()))
    for slug, window in (
        ("new_case_observed_expected", 365),
        ("failure_to_appear_observed_expected", 30),
        ("pretrial_release_observed_expected", None),
    ):
        query = f"metric={slug}&court_id={court}" + ("" if window is None else f"&window={window}")
        response = adjusted_api.get(f"/api/v1/metrics/compare?{query}")
        assert response.status_code == 422, response.text
        error = response.json()
        assert error["code"] == "validation_error"
        assert "is not a registry metric" in error["message"]
    # The descriptive metric it adjusts is still compared.
    ok = adjusted_api.get(
        f"/api/v1/metrics/compare?metric=new_case_rate&window=365&court_id={court}"
    )
    assert ok.status_code == 200, ok.text


def test_the_provenance_route_does_not_know_an_adjusted_observation(
    adjusted_api: TestClient, migrated_database: Engine
) -> None:
    for observation_id in _adjusted_ids(migrated_database)[:5]:
        response = adjusted_api.get(f"/api/v1/metrics/{observation_id}/provenance")
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"
    with Session(migrated_database) as session:
        served = session.scalar(
            select(MetricObservation.id)
            .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
            .where(
                MetricDefinition.slug == "new_case_rate", MetricObservation.superseded_at.is_(None)
            )
            .limit(1)
        )
    assert served is not None
    assert adjusted_api.get(f"/api/v1/metrics/{served}/provenance").status_code == 200


def test_ready_reports_the_latest_snapshots_models_without_a_hash_or_path(
    adjusted_api: TestClient, golden_metrics: GoldenMetrics, migrated_database: Engine
) -> None:
    response = adjusted_api.get("/api/v1/ready")
    assert response.status_code == 200, response.text
    metrics = response.json()["metrics"]
    assert metrics["snapshot_hash"] == golden_metrics.result.snapshot.content_hash
    with Session(migrated_database) as session:
        models = list(session.scalars(select(OutcomeModel)))
    assert metrics["models"] == {
        "fitted": sum(1 for model in models if model.status == "fitted"),
        "unavailable": sum(1 for model in models if model.status != "fitted"),
        "spec_version": SPEC.version,
        "model_version": SPEC.model_version,
    }
    assert metrics["models"]["unavailable"] == 13  # every golden model: insufficient_events
    # The snapshot hash is the only 64-hex string; no model hash, no artifact path.
    assert HEX64.findall(response.text) == [metrics["snapshot_hash"]]
    for model in models:
        assert model.content_hash not in response.text
    assert "file:" not in response.text and "models/" not in response.text
