# tests/unit/test_validation_report.py
"""``docs/VALIDATION.md`` renders deterministically from a ``ValidationReport``.

A hand-built report (no database: two models, one fitted and one with too
few events, a withheld subgroup cell, recovery figures) renders every section
the step names, wrapped at 80 columns, with the synthetic label, the brief's
O/E interpretation verbatim, and the pointer to the limitations; the render
and the committed document name no UUID, hash, code version, judge, judge
code, or local path; ``calibration_cells`` withholds a small cell with its
reason and no figure; and ``judgemetrics validation report --check`` exits 1
with a unified diff against a stale file, 0 against a current one, and 2 when
the report cannot be assembled.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from typer.testing import CliRunner

from judgemetrics.cli import app as cli
from judgemetrics.config import REPO_ROOT
from judgemetrics.metrics.adjustment.diagnostics import CalibrationBin
from judgemetrics.metrics.methodology import INTERPRETATION
from judgemetrics.synthetic.config import DEMO
from judgemetrics.validation import report as report_module
from judgemetrics.validation.fairness import SubgroupCell, calibration_cells
from judgemetrics.validation.recovery import RecoveryResult
from judgemetrics.validation.report import (
    PATH_COMMENT,
    WIDTH,
    DatasetSummary,
    ModelSummary,
    ReportError,
    ReportSettings,
    ValidationReport,
    YearRow,
    render_report,
)
from judgemetrics.validation.sensitivity import Sensitivity
from judgemetrics.validation.stability import BootstrapStability, CoefficientStability, Spread
from tests.property.support import build_world

pytestmark = pytest.mark.unit

COMMITTED = REPO_ROOT / "docs" / "VALIDATION.md"
SECTIONS = (
    "## Dataset and versions",
    "## Summary",
    "## Calibration",
    "## Temporal transport",
    "## Feature stability",
    "## Missing-data sensitivity",
    "## Bootstrap stability of the judge-level estimates",
    "## Subgroup calibration",
    "## Recovery of the planted effects",
    "## Limitations",
)
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
HEX = re.compile(r"\b[0-9a-f]{7,}\b")
JUDGE_CODE = re.compile(r"\bJ-\d{4}\b")
PERSON_CODE = re.compile(r"\bP-\d{6}\b")
LOCAL_PATH = re.compile(r"[A-Za-z]:[\\/]|/home/|/Users/|/tmp/|data/synthetic/|data/snapshots")
CODE_VERSION = re.compile(r"\d+\.\d+\.\d+\+[0-9a-f]+")


def _model(target: str, window: int | None, *, fitted: bool) -> ModelSummary:
    bins = tuple(
        CalibrationBin(bin=index, count=40, mean_predicted=index / 12, observed_rate=index / 11)
        for index in range(1, 11)
    )
    return ModelSummary(
        source="synthetic",
        target=target,
        window_days=window,
        status="fitted" if fitted else "insufficient_events",
        rows=400 if fitted else 12,
        events=150 if fitted else 3,
        eligible=410 if fitted else 12,
        excluded_missing=10 if fitted else 0,
        n_train=300 if fitted else 9,
        events_train=110 if fitted else 2,
        n_test=100 if fitted else 3,
        events_test=40 if fitted else 1,
        temporal_status="fitted" if fitted else None,
        base_rate_train=0.366 if fitted else None,
        brier=0.2012 if fitted else None,
        brier_skill=0.0451 if fitted else None,
        auc=0.6123 if fitted else None,
        calibration_in_the_large=1.0412 if fitted else None,
        calibration_slope=0.8771 if fitted else None,
        bins=bins if fitted else (),
        years=(
            YearRow(year=2020, events=200, observed_rate=0.35, mean_predicted=0.351, split="train"),
            YearRow(year=2021, events=200, observed_rate=0.40, mean_predicted=0.399, split="both"),
        )
        if fitted
        else (),
        coefficients=(
            CoefficientStability("intercept", -0.5, 0.1, 1.0),
            CoefficientStability("court=2", 0.12, 0.08, 0.93),
            CoefficientStability("calendar_year=2021", -0.0, 0.05, 0.5),
        )
        if fitted
        else (),
    )


def _cell(attribute: str, value: str, withheld: str | None = None) -> SubgroupCell:
    published = withheld is None
    return SubgroupCell(
        source="synthetic",
        target="failure_to_appear",
        window_days=365,
        attribute=attribute,
        value=value,
        events=120 if published else None,
        observed=40 if published else None,
        expected=38.25 if published else None,
        ratio=1.045752 if published else None,
        lower=0.9 if published else None,
        upper=1.2 if published else None,
        withheld=withheld,
    )


def fixture_report() -> ValidationReport:
    settings = ReportSettings(
        spec_version=2,
        model_version="expected-logit-v1",
        registry_version=2,
        methodology_version="1.0",
        minimum_cohort=30,
        minimum_expected=5.0,
        minimum_events_per_column=5,
        replicates=500,
        level=0.95,
        test_quantile=0.75,
    )
    fitted = _model("failure_to_appear", 365, fitted=True)
    small = _model("pretrial_release", None, fitted=False)
    return ValidationReport(
        settings=settings,
        datasets=(
            DatasetSummary(
                source="synthetic",
                synthetic=True,
                coverage_start=date(2016, 1, 1),
                coverage_end=date(2023, 12, 31),
                rows=(("cases", 5200), ("charges", 8335), ("persons", 3200)),
                seed=20260916,
                scale="demo",
                generator_version="3",
                truth_version="3",
            ),
        ),
        models=(small, fitted),
        sensitivity=(
            Sensitivity(
                "synthetic", "pretrial_release", None, "model_unavailable", 12, 0, 0, 0, None, None
            ),
            Sensitivity(
                "synthetic", "failure_to_appear", 365, "compared", 400, 10, 4, 19, 0.998, 0.0123
            ),
        ),
        stability=(
            BootstrapStability(
                "synthetic",
                "pretrial_release",
                None,
                "model_unavailable",
                0,
                0,
                0,
                None,
                None,
                None,
            ),
            BootstrapStability(
                "synthetic",
                "failure_to_appear",
                365,
                "summarized",
                498,
                500,
                19,
                Spread(0.289, 0.395, 0.449),
                0.474,
                Spread(4.0, 8.5, 10.0),
            ),
        ),
        subgroups=(
            _cell("age_band", "18-24"),
            _cell("age_band", "55+", withheld="below_threshold"),
            _cell("synthetic_group", "group_a"),
            _cell("synthetic_group", "group_b", withheld="expected_below_minimum"),
        ),
        recovery=(
            RecoveryResult(
                "failure_to_appear",
                365,
                "evaluated",
                19,
                0.963,
                0.9,
                0.871,
                5,
                5,
                0.85,
                0.986,
                0.95,
                0.684,
                0.55,
            ),
            RecoveryResult(
                "new_case",
                365,
                "too_few_judges",
                2,
                None,
                0.7,
                None,
                0,
                0,
                0.85,
                None,
                0.95,
                None,
                0.55,
            ),
        ),
    )


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def test_the_report_renders_every_section_from_fixture_diagnostics() -> None:
    document = render_report(fixture_report())
    assert document == render_report(fixture_report()), "the render is deterministic"
    lines = document.splitlines()
    assert lines[0] == PATH_COMMENT
    assert document.endswith("\n") and not document.endswith("\n\n") and "\r" not in document
    assert all(len(line) <= WIDTH for line in lines), [line for line in lines if len(line) > WIDTH]
    positions = [document.index(f"\n{heading}\n") for heading in SECTIONS]
    assert positions == sorted(positions), "the sections come in the specified order"
    flat = _normalize(document)
    assert "**Synthetic data.**" in document
    assert INTERPRETATION in flat
    assert "describe associations in available records" in flat
    assert "manifest seed 20260916, scale demo, generator version 3, truth version 3" in flat
    assert "methodology version 1.0" in flat
    # Specification version 2 (Phase 5 Step 3) is the one the committed report cites.
    assert "Outcome model specification version 2 (`expected-logit-v1`)" in flat
    # Summary and calibration of the fitted model; the small model is stated, not hidden.
    assert "| failure_to_appear | 365 | fitted | 400 | 150 | 300 | 110 | 100 | 40 |" in lines
    assert "| failure_to_appear | 365 | 0.201 | 0.045 | 0.612 | 1.041 | 0.877 |" in lines
    assert "| pretrial_release | - | insufficient_events | 12 | 3 | 9 | 2 | 3 | 1 |" in lines
    assert "| 10 | 40 | 0.833 | 0.909 |" in lines
    assert "No temporal-split fit (insufficient_events)." in flat
    assert "| 2021 | 200 | 0.400 | 0.399 | both |" in lines
    # Feature stability: rank labels, a negative zero printed as zero.
    assert "| court=2 | 0.120 | 0.080 | 0.930 |" in lines
    assert "| calendar_year=2021 | 0.000 | 0.050 | 0.500 |" in lines
    assert "| failure_to_appear | 365 | 400 | 10 | 4 | 19 | 0.998 | 0.0123 |" in lines
    assert "| pretrial_release | - | 12 | 0 | 0 | 0 | - | model_unavailable |" in lines
    assert "| failure_to_appear | 365 | 498/500 | 19 | 0.395 | 0.289-0.449 | 0.474 |" in lines
    assert "| failure_to_appear | 365 | 19 | 8.5 | 4.0-10.0 |" in lines
    assert "not a confidence interval for the judge's true ratio" in flat
    assert "| age_band | 18-24 | 120 | 40 | 38.2 | 1.046 | 0.900-1.200 |" in lines
    assert "positive control" in flat and "negative control" in flat
    assert "Spearman 0.963 (minimum 0.90; raw rates 0.871)" in flat
    assert "interval coverage 0.684 (minimum 0.55): met." in flat
    assert "too few to evaluate: not met." in flat
    assert '"Adjusted statistics" in docs/METHODOLOGY.md' in flat


def _assert_names_nothing_private(document: str, judge_names: set[str]) -> None:
    assert not UUID.search(document)
    assert not [token for token in HEX.findall(document) if not token.isdigit()]
    assert not JUDGE_CODE.search(document)
    assert not PERSON_CODE.search(document)
    assert not LOCAL_PATH.search(document)
    assert not CODE_VERSION.search(document)
    for name in judge_names:
        assert name not in document, name


def test_the_report_names_no_uuid_hash_judge_or_path() -> None:
    world = build_world(20260916, DEMO)
    names = {f"{judge.given} {judge.family}" for judge in world.judges}
    assert names
    _assert_names_nothing_private(render_report(fixture_report()), names)
    committed = COMMITTED.read_text(encoding="utf-8")
    assert committed.startswith(PATH_COMMENT + "\n")
    assert all(len(line) <= WIDTH for line in committed.splitlines())
    _assert_names_nothing_private(committed, names)
    # The committed report is the demo seed's: it names the manifest, not a path.
    assert "manifest seed 20260916, scale demo" in _normalize(committed)


def test_a_small_subgroup_cell_is_withheld_with_its_reason() -> None:
    rows = 100
    outcomes = np.zeros(rows)
    outcomes[::4] = 1.0
    predictions = np.full(rows, 0.25)
    predictions[90:] = 0.01
    groups = ["a"] * 60 + ["b"] * 10 + [None] * 20 + ["c"] * 10
    weights = np.ones(rows)
    replicates = [(weights, predictions), (weights * 2.0, predictions)]
    cells = calibration_cells(
        predictions,
        outcomes,
        groups,
        replicates,
        values=("a", "b", "c", "d"),
        minimum_cohort=30,
        minimum_expected=5,
    )
    by_value = {cell.value: cell for cell in cells}
    assert [cell.value for cell in cells] == ["a", "b", "c", "d"]
    assert by_value["a"].withheld is None and by_value["a"].events == 60
    for value in ("b", "c", "d"):
        cell = by_value[value]
        assert cell.withheld == "below_threshold", value
        assert (cell.events, cell.observed, cell.expected, cell.ratio) == (None,) * 4
        assert (cell.lower, cell.upper) == (None, None)
    # Enough events but too few expected, and no model at all.
    tiny = calibration_cells(
        np.full(40, 0.01),
        np.zeros(40),
        ["a"] * 40,
        [],
        values=("a",),
        minimum_cohort=30,
        minimum_expected=5,
    )
    assert tiny[0].withheld == "expected_below_minimum" and tiny[0].ratio is None
    unfitted = calibration_cells(
        None, np.zeros(40), ["a"] * 40, [], values=("a",), minimum_cohort=30, minimum_expected=5
    )
    assert unfitted[0].withheld == "model_unavailable" and unfitted[0].events is None
    document = render_report(fixture_report())
    assert "| age_band | 55+ | - | - | - | - | withheld: too few events |" in document
    assert "| synthetic_group | group_b | - | - | - | - | withheld: E too small |" in document


def test_check_reports_a_diff_and_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_module, "build_report", lambda *args, **kwargs: fixture_report())
    out = tmp_path / "nested" / "VALIDATION.md"
    runner = CliRunner()
    result = runner.invoke(cli, ["validation", "report", "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert out.read_bytes() == render_report(fixture_report()).encode("utf-8")
    result = runner.invoke(cli, ["validation", "report", "--out", str(out), "--check"])
    assert result.exit_code == 0, result.output
    assert "is up to date" in result.stdout
    out.write_text(out.read_text(encoding="utf-8").replace("0.963", "0.964"), encoding="utf-8")
    result = runner.invoke(cli, ["validation", "report", "--out", str(out), "--check"])
    assert result.exit_code == 1
    assert "differs from the validation render" in result.output
    assert "-- " in result.output or "--- " in result.output
    assert re.search(r"^-.*0\.964", result.output, re.M) and re.search(
        r"^\+.*0\.963", result.output, re.M
    )
    missing = tmp_path / "missing.md"
    result = runner.invoke(cli, ["validation", "report", "--out", str(missing), "--check"])
    assert result.exit_code == 1 and "is missing" in result.output

    def broken(*args: object, **kwargs: object) -> ValidationReport:
        raise ReportError("no metric snapshot is recorded")

    monkeypatch.setattr(report_module, "build_report", broken)
    result = runner.invoke(cli, ["validation", "report", "--out", str(out), "--check"])
    assert result.exit_code == 2 and "no metric snapshot is recorded" in result.output
    result = runner.invoke(
        cli, ["validation", "report", "--check", "--truth", str(tmp_path / "absent")]
    )
    assert result.exit_code == 2
