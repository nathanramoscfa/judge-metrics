# tests/integration/test_outcome_models.py
"""``judgemetrics models fit|list|show|verify`` over the golden snapshot.

The module's golden ingest and ``metrics compute`` (``golden_metrics``)
give a committed snapshot, and since Phase 4 Step 3 that compute fits the
snapshot's models itself: one ``outcome_model`` row per source, target, and
window — thirteen for the synthetic source — with the status the golden
cohorts allow (each recomputed here from the snapshot's own design and the
events-per-column gate), so ``models fit`` (the CLI, as the ingest role, the
snapshot directory the fixture wrote) then fits and writes nothing.
``models verify --refit`` reproduces every artifact byte for
byte and exits 1 once an artifact byte is changed; every artifact passes
the inspection test; ``models list`` and ``models show`` read the catalogue
as the app role, which can select ``outcome_model`` and cannot write it.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import get_settings
from judgemetrics.db.models import MetricSnapshot, OutcomeModel, Source
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.adjustment.artifacts import artifact_path
from judgemetrics.metrics.adjustment.catalog import snapshot_parameters, verify_models
from judgemetrics.metrics.adjustment.features import DesignFrame, design_rows
from judgemetrics.metrics.adjustment.fit import INSUFFICIENT_EVENTS
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.snapshot import open_snapshot
from tests.integration.conftest import SYNTHETIC_SOURCE, GoldenMetrics
from tests.unit.test_model_artifacts import inspect_artifact

pytestmark = pytest.mark.integration

SPEC = load_spec()
EXPECTED_MODELS = sum(len(target.windows) for target in SPEC.targets)


def _env(golden_metrics: GoldenMetrics) -> dict[str, str]:
    settings = golden_metrics.settings
    return {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url,
        "JUDGEMETRICS_SNAPSHOT_DIR": str(golden_metrics.snapshot_dir),
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }


def _invoke(golden_metrics: GoldenMetrics, *args: str) -> Any:
    # The module-scoped fixture runs before the per-test settings cache is cleared:
    # clear it here so the command reads the environment given below.
    get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli, ["models", *args], env=_env(golden_metrics))
    finally:
        get_settings.cache_clear()


def _snapshot(golden_metrics: GoldenMetrics) -> str:
    return golden_metrics.result.snapshot.content_hash


def _rows(engine: Engine) -> list[tuple[OutcomeModel, str]]:
    with Session(engine) as session:
        return [
            (model, str(name))
            for model, name in session.execute(
                select(OutcomeModel, Source.name).join(Source, Source.id == OutcomeModel.source_id)
            ).all()
        ]


@pytest.fixture(scope="module")
def fitted(golden_metrics: GoldenMetrics) -> Iterator[dict[str, Any]]:
    """``models fit`` over the module's golden snapshot, once, after the fitting compute."""
    result = _invoke(golden_metrics, "fit", "--snapshot", _snapshot(golden_metrics), "--json")
    assert result.exit_code == 0, result.output
    yield json.loads(result.stdout)


def _designs(golden_metrics: GoldenMetrics) -> dict[tuple[str, int | None], DesignFrame]:
    """Every golden design, rebuilt from the snapshot the models were fitted on."""
    designs: dict[tuple[str, int | None], DesignFrame] = {}
    with open_snapshot(golden_metrics.settings, _snapshot(golden_metrics)) as snapshot:
        source = next(s for s in snapshot.sources() if s.name == SYNTHETIC_SOURCE)
        frame = snapshot.frame(source.id)
        for target in SPEC.targets:
            for window in target.windows:
                design = design_rows(frame, SPEC, target, window)
                assert isinstance(design, DesignFrame)
                designs[(target.name, window)] = design
    return designs


def test_the_compute_records_one_model_per_target_and_window_and_models_fit_adds_none(
    fitted: dict[str, Any], golden_metrics: GoldenMetrics, migrated_database: Engine
) -> None:
    # The fitting compute recorded every model; `models fit` found nothing to do.
    assert golden_metrics.result.models_fitted == golden_metrics.result.models_read == 13
    assert fitted["snapshot"] == _snapshot(golden_metrics)
    assert fitted["fitted"] == 0 and fitted["existing"] == EXPECTED_MODELS == 13
    rows = [(model, name) for model, name in _rows(migrated_database) if name == SYNTHETIC_SOURCE]
    assert len(rows) == EXPECTED_MODELS
    keys = {(model.target, model.window_days) for model, _ in rows}
    assert keys == {(t.name, w) for t in SPEC.targets for w in t.windows}
    designs = _designs(golden_metrics)
    gate = SPEC.thresholds.minimum_events_per_column
    for model, _ in rows:
        design = designs[(model.target, model.window_days)]
        limiting = min(design.events, design.rows - design.events)
        expected = INSUFFICIENT_EVENTS if limiting < gate * design.width else model.status
        assert model.status == expected, (model.target, model.window_days)
        assert model.n_train + model.n_test == design.rows
        assert model.events_train + model.events_test == design.events
        assert model.spec_version == SPEC.version and model.seed == SPEC.seed
        assert model.model_version == SPEC.model_version
        assert len(model.content_hash) == 64 and model.storage_uri.startswith("file:")
        if design.rows:
            assert model.train_start is not None and model.split_cutoff is not None
        assert (model.coefficients is None) == (model.status != "fitted")
        assert model.diagnostics is not None and "status" in model.diagnostics
    # The golden cohorts are too small for any model to clear the events-per-column gate.
    assert {model.status for model, _ in rows} == {INSUFFICIENT_EVENTS}
    assert sorted(model.content_hash for model, _ in rows) == sorted(
        model.content_hash for model in golden_metrics_models(golden_metrics)
    )


def golden_metrics_models(golden_metrics: GoldenMetrics) -> list[Any]:
    """The models the module's compute read back, one per target and window."""
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    try:
        with Session(engine) as session:
            snapshot_id = session.scalar(
                select(MetricSnapshot.id).where(
                    MetricSnapshot.content_hash == _snapshot(golden_metrics)
                )
            )
            assert snapshot_id is not None
            parameters = snapshot_parameters(
                session,
                golden_metrics.settings,
                snapshot_id=snapshot_id,
                snapshot_hash=_snapshot(golden_metrics),
            )
    finally:
        engine.dispose()
    return [model for by_target in parameters.values() for model in by_target.values()]


def test_every_artifact_passes_the_inspection(
    fitted: dict[str, Any], golden_metrics: GoldenMetrics, migrated_database: Engine
) -> None:
    designs = _designs(golden_metrics)
    snapshot = _snapshot(golden_metrics)
    for model, _ in _rows(migrated_database):
        path = artifact_path(golden_metrics.snapshot_dir, snapshot, model.content_hash)
        payload = json.loads(path.read_bytes())
        design = designs[(model.target, model.window_days)]
        inspect_artifact(
            payload, snapshot=snapshot, rows=design.rows, persons=design.persons, spec=SPEC
        )
        assert payload["status"] == model.status and payload["source"] == SYNTHETIC_SOURCE


def test_models_verify_refits_byte_for_byte_and_fails_on_a_changed_byte(
    fitted: dict[str, Any], golden_metrics: GoldenMetrics, migrated_database: Engine
) -> None:
    snapshot = _snapshot(golden_metrics)
    clean = _invoke(golden_metrics, "verify", "--snapshot", snapshot, "--refit", "--json")
    assert clean.exit_code == 0, clean.output
    report = json.loads(clean.stdout)
    assert report["ok"] is True
    assert report["models"] == report["verified"] == report["refitted"] == EXPECTED_MODELS
    model, _ = sorted(_rows(migrated_database), key=lambda row: str(row[0].id))[0]
    path = artifact_path(golden_metrics.snapshot_dir, snapshot, model.content_hash)
    original = path.read_bytes()
    position = original.index(b'"target"')
    tampered = original[:position] + b" " + original[position + 1 :]
    try:
        path.write_bytes(tampered)
        broken = _invoke(golden_metrics, "verify", "--snapshot", snapshot, "--refit")
        assert broken.exit_code == 1, broken.output
        assert f"mismatch: model {model.id}" in broken.output
        assert "field=content_hash" in broken.output
        as_json = _invoke(golden_metrics, "verify", "--snapshot", snapshot, "--json")
        assert as_json.exit_code == 1
        problems = json.loads(as_json.stdout)["problems"]
        assert [problem["model_id"] for problem in problems] == [str(model.id)]
    finally:
        path.write_bytes(original)
    assert _invoke(golden_metrics, "verify", "--snapshot", snapshot).exit_code == 0


def test_a_model_of_an_earlier_specification_is_unverifiable_not_a_mismatch(
    fitted: dict[str, Any], golden_metrics: GoldenMetrics, migrated_database: Engine
) -> None:
    # After a specification bump (Phase 5 Step 3 made version 2) the earlier models
    # stay as the history superseded observations cite: their artifacts are still
    # checked against their rows, but no refit under the new file can reproduce them.
    later = dataclasses.replace(SPEC, version=SPEC.version + 1)
    with Session(migrated_database) as session:
        result = verify_models(
            session,
            golden_metrics.settings,
            snapshot_hash=_snapshot(golden_metrics),
            refit=True,
            spec=later,
        )
        session.rollback()
    assert result.ok, result.problems
    assert result.models == result.verified == result.unverifiable == EXPECTED_MODELS
    assert result.refitted == 0
    assert result.as_dict()["unverifiable"] == EXPECTED_MODELS


def test_list_and_show_read_the_catalogue_without_the_storage_uri(
    fitted: dict[str, Any], golden_metrics: GoldenMetrics
) -> None:
    snapshot = _snapshot(golden_metrics)
    listed = _invoke(golden_metrics, "list", "--snapshot", snapshot, "--json")
    assert listed.exit_code == 0, listed.output
    models = json.loads(listed.stdout)["models"]
    # By source, then the specification's target order, then window (none first).
    assert [(m["target"], m["window_days"]) for m in models] == [
        (target.name, window) for target in SPEC.targets for window in target.windows
    ]
    text_listing = _invoke(golden_metrics, "list", "--snapshot", snapshot)
    assert text_listing.exit_code == 0 and "insufficient_events" in text_listing.output
    first = models[0]
    for identifier in (first["id"], first["content_hash"]):
        shown = _invoke(golden_metrics, "show", identifier, "--json")
        assert shown.exit_code == 0, shown.output
        card = json.loads(shown.stdout)
        assert card["id"] == first["id"] and "storage_uri" not in card
        assert card["status"] == first["status"]
    text_card = _invoke(golden_metrics, "show", first["id"])
    assert text_card.exit_code == 0 and "storage_uri" not in text_card.output
    assert text_card.output.startswith(f"model {first['id']}")
    unknown = _invoke(golden_metrics, "show", str(uuid.uuid4()))
    assert unknown.exit_code == 2 and "no outcome model" in unknown.output


def test_the_app_role_selects_outcome_model_and_cannot_write_it(
    fitted: dict[str, Any], app_engine: Engine
) -> None:
    with app_engine.connect() as connection:
        if connection.execute(text("SELECT current_user")).scalar() != "judgemetrics_app":
            pytest.skip("JUDGEMETRICS_DATABASE_URL does not connect as judgemetrics_app")
        assert connection.execute(text("SELECT count(*) FROM outcome_model")).scalar_one() > 0
    for statement in (
        "UPDATE outcome_model SET status = 'fitted'",
        "DELETE FROM outcome_model",
        "INSERT INTO outcome_model (content_hash) VALUES ('x')",
    ):
        with app_engine.connect() as connection:
            with pytest.raises(ProgrammingError, match="permission denied"):
                connection.execute(text(statement))
            connection.rollback()
