# tests/integration/test_fairness_analysis.py
"""The subgroup calibration on the golden database: the ingest role only, cells only.

After the module's golden ingest and its committed ``metrics compute`` (the
shared ``golden_metrics`` fixture: thirteen outcome models, every one
``insufficient_events`` on the golden cohorts):

- as the ingest role, ``subgroup_calibration`` returns one cell per model and
  restricted attribute value, and every golden cell is withheld with its
  reason (too few index events, or no fitted model) and carries no figure;
- as the app role it is refused before any statement runs, and the app role
  running the attribute statement itself fails with ``InsufficientPrivilege``;
- the function returns ``SubgroupCell``s only, whose fields name no member,
  decision, case, or person;
- ``judgemetrics validation report`` renders the golden database's report
  (every subgroup cell withheld, the recovery too small to evaluate) and
  ``--check`` accepts it; ``validation recovery`` exits 1 because the golden
  cohorts are below the minimum followed cohort, and 2 for a truth directory
  no source ingested.
"""

from __future__ import annotations

import dataclasses
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from psycopg.errors import InsufficientPrivilege
from sqlalchemy import Engine, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import REPO_ROOT, get_settings
from judgemetrics.db.session import make_engine
from judgemetrics.metrics.adjustment.catalog import resolve_snapshot
from judgemetrics.metrics.adjustment.fit import FITTED
from judgemetrics.metrics.adjustment.spec import RESTRICTED_KIND, load_spec
from judgemetrics.metrics.snapshot import open_snapshot
from judgemetrics.normalization import vocabulary
from judgemetrics.validation.fairness import (
    FairnessError,
    SubgroupCell,
    attribute_statement,
    subgroup_calibration,
)
from judgemetrics.validation.inputs import ModelInput, load_inputs
from tests.integration.conftest import GoldenMetrics

pytestmark = [pytest.mark.golden, pytest.mark.integration]

GOLDEN = REPO_ROOT / "tests" / "fixtures" / "golden"
APP_ROLE = "judgemetrics_app"
SPEC = load_spec()
REASONS = {"below_threshold", "expected_below_minimum", "model_unavailable"}
FIGURES = ("events", "observed", "expected", "ratio", "lower", "upper")


def _calibrate(
    engine: Engine, golden_metrics: GoldenMetrics
) -> tuple[list[SubgroupCell], list[ModelInput]]:
    settings = golden_metrics.settings
    content_hash = golden_metrics.result.snapshot.content_hash
    with Session(engine) as session:
        row = resolve_snapshot(session, content_hash)
        with open_snapshot(settings, content_hash) as snapshot:
            inputs = load_inputs(session, settings, snapshot, row.id, spec=SPEC)
            models = [model for item in inputs for model in item.models]
            try:
                cells = subgroup_calibration(session, snapshot, models, settings=settings)
            finally:
                session.rollback()
    return cells, models


@pytest.fixture(scope="module")
def ingest_engine(golden_metrics: GoldenMetrics) -> Iterator[Engine]:
    engine = make_engine(golden_metrics.settings.effective_ingest_database_url)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def calibrated(
    ingest_engine: Engine, golden_metrics: GoldenMetrics
) -> tuple[list[SubgroupCell], list[ModelInput]]:
    return _calibrate(ingest_engine, golden_metrics)


def test_the_ingest_role_runs_the_analysis_and_every_golden_cell_is_withheld(
    calibrated: tuple[list[SubgroupCell], list[ModelInput]],
) -> None:
    cells, models = calibrated
    assert len(models) == 13
    assert all(model.status != FITTED for model in models)
    attributes = vocabulary.values(RESTRICTED_KIND)
    expected = [
        (model.target.name, model.window_days, attribute, value)
        for model in models
        for attribute in attributes
        for value in vocabulary.values(attribute)
    ]
    assert [(c.target, c.window_days, c.attribute, c.value) for c in cells] == expected
    for cell in cells:
        assert cell.withheld in REASONS, cell
        assert all(getattr(cell, name) is None for name in FIGURES), cell
    # The golden models are not fitted: a cell is withheld for its size or for the model.
    assert {cell.withheld for cell in cells} <= {"below_threshold", "model_unavailable"}
    assert any(cell.withheld == "below_threshold" for cell in cells)


def test_the_function_returns_cells_only(
    calibrated: tuple[list[SubgroupCell], list[ModelInput]],
) -> None:
    cells, _ = calibrated
    assert cells and all(type(cell) is SubgroupCell for cell in cells)
    names = {field.name for field in dataclasses.fields(SubgroupCell)}
    assert names == {
        "source",
        "target",
        "window_days",
        "attribute",
        "value",
        "withheld",
        *FIGURES,
    }
    for cell in cells:
        assert cell.source == "synthetic"
        assert cell.value in vocabulary.values(cell.attribute)
        for name in ("source", "target", "attribute", "value"):
            value = getattr(cell, name)
            with pytest.raises(ValueError):
                uuid.UUID(str(value))


def test_the_app_role_cannot_run_the_analysis(
    golden_metrics: GoldenMetrics, calibrated: tuple[list[SubgroupCell], list[ModelInput]]
) -> None:
    _, models = calibrated
    settings = golden_metrics.settings
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            user = session.scalar(text("SELECT current_user"))
            if user == make_engine(settings.effective_ingest_database_url).url.username:
                pytest.skip("the app and ingest URLs connect as the same role")
            with open_snapshot(settings, golden_metrics.result.snapshot.content_hash) as snapshot:
                with pytest.raises(FairnessError, match="ingest role only"):
                    subgroup_calibration(session, snapshot, models, settings=settings)
            if user != APP_ROLE:
                pytest.skip("the app URL does not connect as judgemetrics_app")
            ids = [uuid.UUID(member) for member in models[0].design.member_ids[:5]]
            with pytest.raises(ProgrammingError) as caught:
                session.execute(
                    attribute_statement(vocabulary.values(RESTRICTED_KIND)), {"member_ids": ids}
                )
            assert isinstance(caught.value.orig, InsufficientPrivilege)
            session.rollback()
    finally:
        engine.dispose()


def _cli(golden_metrics: GoldenMetrics, *args: str) -> Any:
    settings = golden_metrics.settings
    env = {
        "JUDGEMETRICS_ENV": "test",
        "JUDGEMETRICS_DATABASE_URL": settings.database_url,
        "JUDGEMETRICS_INGEST_DATABASE_URL": settings.effective_ingest_database_url,
        "JUDGEMETRICS_SNAPSHOT_DIR": str(golden_metrics.snapshot_dir),
        "JUDGEMETRICS_LOG_FORMAT": "json",
    }
    get_settings.cache_clear()
    try:
        return CliRunner().invoke(cli, list(args), env=env)
    finally:
        get_settings.cache_clear()


def test_the_report_and_the_recovery_commands_on_the_golden_database(
    golden_metrics: GoldenMetrics, tmp_path: Path
) -> None:
    out = tmp_path / "VALIDATION.md"
    result = _cli(golden_metrics, "validation", "report", "--out", str(out), "--truth", str(GOLDEN))
    assert result.exit_code == 0, result.output
    document = out.read_text(encoding="utf-8")
    assert "manifest seed 7, scale golden" in " ".join(document.split())
    assert "| insufficient_events |" in document
    assert "withheld: too few events" in document
    assert "too few to evaluate: not met." in document
    check = _cli(
        golden_metrics, "validation", "report", "--out", str(out), "--truth", str(GOLDEN), "--check"
    )
    assert check.exit_code == 0, check.output
    recovery = _cli(golden_metrics, "validation", "recovery", "--truth", str(GOLDEN), "--json")
    assert recovery.exit_code == 1, recovery.output
    payload = json.loads(recovery.stdout)
    assert payload["passed"] is False
    assert [(fit["target"], fit["window_days"]) for fit in payload["fits"]] == [
        (fit.target, fit.window_days) for fit in SPEC.recovery.fits
    ]
    assert all(fit["status"] == "too_few_judges" for fit in payload["fits"])
    # A truth directory whose manifest no source ingested is refused.
    other = tmp_path / "other"
    (other / "truth").mkdir(parents=True)
    (other / "manifest.json").write_text('{"seed": 1}', encoding="utf-8")
    (other / "truth" / "effects.json").write_text('{"targets": {}, "judges": {}}', encoding="utf-8")
    refused = _cli(golden_metrics, "validation", "recovery", "--truth", str(other))
    assert refused.exit_code == 2
    assert "not the one any synthetic source ingested" in refused.output
