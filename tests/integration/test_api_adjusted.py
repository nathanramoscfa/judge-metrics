# tests/integration/test_api_adjusted.py
"""Serving the observed-to-expected kind (Phase 4 Step 5; the Step 3 hold-out's tests, turned).

Over the module's golden ingest and its committed ``metrics compute`` —
which publishes adjusted observations for every golden judge, all of them
suppressed (``below_threshold``; the golden models are
``insufficient_events``) — the API as the read-only app role: ``GET
/api/v1/metrics`` lists the three adjusted definitions with their adjustment
target; a judge's ``/metrics`` serves every adjusted observation with every
new field, a suppressed one withholding every figure while keeping its reason
and its model; the court's carries none (the adjusted metrics are
judge-only); ``/metrics/compare`` serves an adjusted metric sorted by
``ratio`` by default with suppressed rows last; the model card of a cited
model answers every documented field and never ``storage_uri``, 404 for an
unknown or superseded snapshot's model and 422 for a malformed id; and the
provenance body of an adjusted observation names its model with a verified
artifact. The ordering of published ratios (none in the golden world) is
asserted over a published copy planted inside a rolled-back transaction.
``/api/v1/ready`` still reports the latest snapshot's models as counts and
versions — never a model hash or an artifact path.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, update
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    MetricDefinition,
    MetricObservation,
    MetricSnapshot,
    OutcomeModel,
)
from judgemetrics.db.models.enums import SubjectType
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.registry import OBSERVED_EXPECTED, load_registry
from judgemetrics.schemas.metrics import SUPPRESSED_FIELDS
from judgemetrics.services.metrics import SERVED_KINDS
from tests.integration.conftest import GoldenFixture, GoldenMetrics, make_app

pytestmark = pytest.mark.integration

REGISTRY = load_registry()
SPEC = load_spec()
ADJUSTED_SLUGS = {metric.slug for metric in REGISTRY.of_kind(OBSERVED_EXPECTED)}
ADJUSTED_FIELDS = (
    "expected",
    "expected_rate",
    "ratio",
    "ratio_lower",
    "ratio_upper",
    "pooling_weight",
    "model",
    "suppression_reason",
)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
JUDGE = "J-0003"


@pytest.fixture(scope="module")
def adjusted_api(golden_metrics: GoldenMetrics) -> Iterator[TestClient]:
    """The API, as the app role, over the golden observations and their model artifacts."""
    app = make_app(golden_metrics.settings)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client
    app.state.engine.dispose()


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


def _observations(body: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for group in body["observations"].values() for item in group]


def test_the_golden_compute_published_adjusted_observations(
    migrated_database: Engine, golden_metrics: GoldenMetrics
) -> None:
    del golden_metrics
    assert ADJUSTED_SLUGS == {
        "pretrial_release_observed_expected",
        "new_case_observed_expected",
        "failure_to_appear_observed_expected",
    }
    assert OBSERVED_EXPECTED in SERVED_KINDS
    assert {metric.kind for metric in REGISTRY.metrics.values()} == SERVED_KINDS
    assert _adjusted_ids(migrated_database)


def test_the_registry_response_lists_the_adjusted_definitions(adjusted_api: TestClient) -> None:
    response = adjusted_api.get("/api/v1/metrics")
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["slug"] for item in body["definitions"]] == list(REGISTRY.metrics)
    adjusted = {
        item["slug"]: item for item in body["definitions"] if item["slug"] in ADJUSTED_SLUGS
    }
    assert set(adjusted) == ADJUSTED_SLUGS
    for slug, item in adjusted.items():
        spec = REGISTRY[slug].adjustment
        assert spec is not None
        assert item["kind"] == OBSERVED_EXPECTED and item["unit"] == "ratio"
        assert item["subject_types"] == ["judge"]
        assert item["adjustment"] == {
            "target": spec.target,
            "minimum_expected": spec.minimum_expected,
        }
    assert all(
        item["adjustment"] is None
        for item in body["definitions"]
        if item["slug"] not in ADJUSTED_SLUGS
    )
    assert body["registry_version"] == 2 and body["methodology_version"] == "1.0"


def test_a_judges_adjusted_observations_carry_every_new_field_and_withhold_when_suppressed(
    adjusted_api: TestClient, golden_fixture: GoldenFixture, migrated_database: Engine
) -> None:
    with Session(migrated_database) as session:
        models = {model.id: model for model in session.scalars(select(OutcomeModel))}
    for judge_id in golden_fixture.judge_ids.values():
        response = adjusted_api.get(f"/api/v1/judges/{judge_id}/metrics")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body["observations"]) & ADJUSTED_SLUGS
        for item in _observations(body):
            assert set(ADJUSTED_FIELDS) <= set(item), item["slug"]
            if item["slug"] not in ADJUSTED_SLUGS:
                # Every adjusted field is null for a descriptive kind.
                assert all(item[name] is None for name in ADJUSTED_FIELDS[:-1]), item["slug"]
                assert item["suppression_reason"] == (
                    "below_threshold" if item["suppressed"] else None
                )
                continue
            assert item["kind"] == OBSERVED_EXPECTED and item["unit"] == "ratio"
            assert item["interval_method"] == "bootstrap"
            assert item["suppression_threshold"] == 30
            # The golden cohorts are small: every adjusted row is suppressed and
            # withholds every figure, while its reason and its model survive.
            assert item["suppressed"] is True
            assert item["suppression_reason"] == "below_threshold"
            for name in SUPPRESSED_FIELDS:
                assert item[name] is None, (item["slug"], name)
            model = item["model"]
            assert model is not None
            assert set(model) == {"id", "content_hash", "model_version", "spec_version", "url"}
            stored = models[uuid.UUID(model["id"])]
            assert model["content_hash"] == stored.content_hash
            assert model["spec_version"] == SPEC.version
            assert model["model_version"] == SPEC.model_version
            assert model["url"] == f"/api/v1/models/{model['id']}"
            assert stored.target == REGISTRY[item["slug"]].adjustment.target  # type: ignore[union-attr]
            assert stored.window_days == item["window_days"]
            assert item["eligible_count"] >= 0
            assert item["methodology_url"] == f"/methodology#{item['slug']}"
        windowed = body["observations"].get("new_case_observed_expected", [])
        assert [item["window_days"] for item in windowed] == [30, 90, 180, 365, 730, 1095]
    for court_id in golden_fixture.court_ids.values():
        court = adjusted_api.get(f"/api/v1/courts/{court_id}/metrics").json()
        assert not set(court["observations"]) & ADJUSTED_SLUGS


def test_compare_serves_an_adjusted_metric_sorted_by_ratio_with_suppressed_rows_last(
    adjusted_api: TestClient, golden_fixture: GoldenFixture, migrated_database: Engine
) -> None:
    jurisdiction = str(golden_fixture.jurisdiction_id)
    response = adjusted_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "new_case_observed_expected",
            "window": 365,
            "jurisdiction_id": jurisdiction,
            "limit": 100,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["cohort"]["sort"] == "ratio" and body["cohort"]["order"] == "desc"
    assert body["total"] == len(golden_fixture.judge_ids)
    for item in body["items"]:
        assert item["interval_method"] == "bootstrap"
        assert item["suppressed"] is True and item["suppression_reason"] == "below_threshold"
        assert all(item[name] is None for name in SUPPRESSED_FIELDS)
        assert item["model"]["url"].startswith("/api/v1/models/")
    # The window is required; the release ratio has none; another sort is honoured.
    assert (
        adjusted_api.get(
            "/api/v1/metrics/compare",
            params={"metric": "new_case_observed_expected", "jurisdiction_id": jurisdiction},
        ).status_code
        == 422
    )
    release = adjusted_api.get(
        "/api/v1/metrics/compare",
        params={"metric": "pretrial_release_observed_expected", "jurisdiction_id": jurisdiction},
    ).json()
    assert release["cohort"]["sort"] == "ratio" and release["cohort"]["window_days"] is None
    by_name = adjusted_api.get(
        "/api/v1/metrics/compare",
        params={
            "metric": "pretrial_release_observed_expected",
            "jurisdiction_id": jurisdiction,
            "sort": "name",
            "order": "asc",
        },
    ).json()
    names = [item["name"] for item in by_name["items"]]
    assert names == sorted(names)
    # A descriptive metric still defaults to the rate.
    rate = adjusted_api.get(
        "/api/v1/metrics/compare",
        params={"metric": "new_case_rate", "window": 365, "jurisdiction_id": jurisdiction},
    ).json()
    assert rate["cohort"]["sort"] == "rate"

    # Published ratios order the page (descending and ascending) with the
    # suppressed rows last whatever the direction: two rows are published
    # inside a transaction that is rolled back.
    with Session(migrated_database) as session:
        rows = list(
            session.scalars(
                select(MetricObservation)
                .join(
                    MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id
                )
                .where(
                    MetricDefinition.slug == "pretrial_release_observed_expected",
                    MetricObservation.superseded_at.is_(None),
                    MetricObservation.subject_type == SubjectType.JUDGE,
                )
                .order_by(MetricObservation.subject_id)
            )
        )
        assert len(rows) >= 3
        planted = {rows[0].subject_id: Decimal("0.8"), rows[1].subject_id: Decimal("1.25")}
        try:
            for row in rows[:2]:
                session.execute(
                    update(MetricObservation)
                    .where(MetricObservation.id == row.id)
                    .values(
                        suppressed_flag=False,
                        suppression_reason=None,
                        expected_count=Decimal("12.5"),
                        expected_rate=Decimal("0.25"),
                        standardized_ratio=planted[row.subject_id],
                        lower_confidence_bound=planted[row.subject_id] - Decimal("0.2"),
                        upper_confidence_bound=planted[row.subject_id] + Decimal("0.3"),
                        pooling_weight=Decimal("0.4"),
                    )
                )
            session.commit()
            for order in ("desc", "asc"):
                page = adjusted_api.get(
                    "/api/v1/metrics/compare",
                    params={
                        "metric": "pretrial_release_observed_expected",
                        "jurisdiction_id": jurisdiction,
                        "order": order,
                        "limit": 100,
                    },
                ).json()
                visible = [item for item in page["items"] if not item["suppressed"]]
                ratios = [item["ratio"] for item in visible]
                assert ratios == sorted(ratios, reverse=order == "desc")
                assert ratios == ([1.25, 0.8] if order == "desc" else [0.8, 1.25])
                assert page["items"][: len(visible)] == visible, "suppressed rows sort last"
                top = visible[0]
                assert top["ratio_lower"] == pytest.approx(top["ratio"] - 0.2)
                assert top["ratio_upper"] == pytest.approx(top["ratio"] + 0.3)
                assert top["lower"] is None and top["upper"] is None
                assert top["expected"] == 12.5 and top["pooling_weight"] == 0.4
                assert top["suppression_reason"] is None
        finally:
            for row in rows[:2]:
                session.execute(
                    update(MetricObservation)
                    .where(MetricObservation.id == row.id)
                    .values(
                        suppressed_flag=True,
                        suppression_reason="below_threshold",
                        expected_count=row.expected_count,
                        expected_rate=row.expected_rate,
                        standardized_ratio=row.standardized_ratio,
                        lower_confidence_bound=row.lower_confidence_bound,
                        upper_confidence_bound=row.upper_confidence_bound,
                        pooling_weight=row.pooling_weight,
                    )
                )
            session.commit()


def test_the_model_card_serves_the_catalogue_row_and_never_its_storage_uri(
    adjusted_api: TestClient, golden_metrics: GoldenMetrics, migrated_database: Engine
) -> None:
    with Session(migrated_database) as session:
        models = list(
            session.scalars(
                select(OutcomeModel)
                .join(MetricSnapshot, MetricSnapshot.id == OutcomeModel.snapshot_id)
                .where(MetricSnapshot.content_hash == golden_metrics.result.snapshot.content_hash)
                .order_by(OutcomeModel.target, OutcomeModel.window_days)
            )
        )
    assert len(models) == 13
    for model in models:
        response = adjusted_api.get(f"/api/v1/models/{model.id}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert set(body) == {
            "id",
            "content_hash",
            "snapshot_hash",
            "source",
            "synthetic",
            "target",
            "window_days",
            "spec_version",
            "model_version",
            "seed",
            "status",
            "fitted_at",
            "code_version",
            "training",
            "validation",
            "coefficients",
            "methodology_url",
        }
        assert body["content_hash"] == model.content_hash
        assert body["snapshot_hash"] == golden_metrics.result.snapshot.content_hash
        assert body["source"] == "synthetic" and body["synthetic"] is True
        assert (body["target"], body["window_days"]) == (model.target, model.window_days)
        assert body["status"] == model.status == "insufficient_events"
        assert body["seed"] == SPEC.seed and body["spec_version"] == SPEC.version
        assert body["methodology_url"] == "/methodology#adjusted-statistics"
        assert body["training"]["index_events"] == model.n_train + model.n_test
        assert body["training"]["events"] == model.events_train + model.events_test
        assert body["validation"]["train_index_events"] == model.n_train
        assert body["validation"]["test_events"] == model.events_test
        assert len(body["coefficients"]) == len(model.coefficients or [])
        assert "storage_uri" not in response.text
        assert model.storage_uri not in response.text
        assert "file:" not in response.text
    assert adjusted_api.get(f"/api/v1/models/{uuid.uuid4()}").status_code == 404
    malformed = adjusted_api.get("/api/v1/models/not-a-uuid")
    assert malformed.status_code == 422
    assert set(malformed.json()) == {"code", "message", "request_id"}
    assert adjusted_api.get(f"/api/v1/models/{models[0].id}?x=1").status_code == 422

    # A model of a snapshot no current observation cites is history: 404.
    model = models[0]
    with Session(migrated_database) as session:
        session.execute(
            update(MetricObservation)
            .where(MetricObservation.snapshot_id == model.snapshot_id)
            .where(MetricObservation.superseded_at.is_(None))
            .values(superseded_at=MetricObservation.computed_at)
        )
        try:
            session.flush()
            # The API reads its own connection: commit, check, and restore.
            session.commit()
            gone = adjusted_api.get(f"/api/v1/models/{model.id}")
            assert gone.status_code == 404
            assert gone.json()["code"] == "not_found"
        finally:
            session.execute(
                update(MetricObservation)
                .where(MetricObservation.snapshot_id == model.snapshot_id)
                .where(MetricObservation.superseded_at == MetricObservation.computed_at)
                .values(superseded_at=None)
            )
            session.commit()
    assert adjusted_api.get(f"/api/v1/models/{model.id}").status_code == 200


def test_the_provenance_body_names_an_adjusted_observations_model(
    adjusted_api: TestClient, migrated_database: Engine, golden_metrics: GoldenMetrics
) -> None:
    ids = _adjusted_ids(migrated_database)
    for observation_id in ids[:5]:
        response = adjusted_api.get(f"/api/v1/metrics/{observation_id}/provenance")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["complete"] is True
        assert body["observation"]["kind"] == OBSERVED_EXPECTED
        model = body["model"]
        assert model is not None
        assert model["content_hash"] == body["observation"]["model"]["content_hash"]
        assert model["artifact_ok"] is True
        assert model["status"] == "insufficient_events"
        assert set(model["training"]) == {"index_events", "events", "start", "end"}
        assert model["url"] == f"/api/v1/models/{model['id']}"
        assert "storage_uri" not in response.text
    # A descriptive observation's chain names no model.
    with Session(migrated_database) as session:
        served = session.scalar(
            select(MetricObservation.id)
            .join(MetricDefinition, MetricDefinition.id == MetricObservation.metric_definition_id)
            .where(
                MetricDefinition.slug == "new_case_rate", MetricObservation.superseded_at.is_(None)
            )
            .limit(1)
        )
    descriptive = adjusted_api.get(f"/api/v1/metrics/{served}/provenance").json()
    assert descriptive["model"] is None and descriptive["complete"] is True
    # Without the model artifacts the adjusted chain is incomplete, never a 404.
    elsewhere = make_app(
        golden_metrics.settings.model_copy(
            update={"snapshot_dir": golden_metrics.snapshot_dir / "none"}
        )
    )
    with TestClient(elsewhere) as client:
        missing = client.get(f"/api/v1/metrics/{ids[0]}/provenance").json()
    elsewhere.state.engine.dispose()
    assert missing["complete"] is False and missing["model"]["artifact_ok"] is False


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
