# tests/unit/test_subgroup_calibration.py
"""The subgroup calibration's arithmetic shows both synthetic controls on the demo world.

The demo world is built in memory from seed 20260916
(``tests/property/support.frame_from_world``) and fitted with Step 2's
``fit_frame`` for the targets and windows the specification's ``recovery``
block names. Each index event (a pretrial decision) is grouped by the
filing-age band and the synthetic group exactly as the synthetic connector
publishes them: the band of the age at the index case's filing
(``normalization.age_bands.age_band``; ``unknown`` when the date of birth is
withheld) and the person's group. ``validation.fairness.calibration_cells``
then aggregates O, E from the published coefficients, O/E, and the bootstrap
interval per value — the function the database path calls.

- The positive control: the generator moves the failure-to-appear log-odds
  and the next-filing exponent by band (``truth/effects.json``
  ``controls.age_band``) and the model omits the band, so for both outcomes
  the youngest band's ratio is above 1, the oldest band's below, and the
  ratios over the five known bands rank like the planted effects (Spearman at
  least 0.8; the demo world measures 0.9 for both — 45-54 sits above 35-44,
  by chance, in both outcomes, whose index events share their persons).
- The negative control: every ``synthetic_group`` cell of every model lies in
  the specification's ``recovery.negative_control_band``; so does every age
  cell of the release model, which no age effect enters.

Nothing is written and no attribute of an index event leaves the test.
"""

from __future__ import annotations

from typing import Any

import pytest

from judgemetrics.metrics.adjustment.expected import ModelParameters
from judgemetrics.metrics.adjustment.fit import FITTED, FittedModel, fit_frame
from judgemetrics.metrics.adjustment.logistic import predict
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.age_bands import UNKNOWN_BAND, age_band
from judgemetrics.synthetic.config import DEMO
from judgemetrics.synthetic.truth import build_timelines, compute_effects
from judgemetrics.validation.fairness import CellFigures, calibration_cells, replicate_draws
from judgemetrics.validation.statistics import spearman
from tests.property.support import build_world, frame_from_world

pytestmark = pytest.mark.unit

DEMO_SEED = 20260916
SOURCE = "synthetic"
SPEC = load_spec()
AGE = "age_band"
GROUP = "synthetic_group"
# The truth's age effect per target (truth/effects.json controls.age_band).
PLANTED = {
    "new_case": "new_case_exponent",
    "failure_to_appear": "failure_to_appear_log_odds",
}
SPEARMAN_MINIMUM = 0.8


Cells = dict[tuple[str, int | None, str], list[CellFigures]]


@pytest.fixture(scope="module")
def controls() -> tuple[Cells, dict[str, Any]]:
    world = build_world(DEMO_SEED, DEMO)
    frame = frame_from_world(world, DEMO)
    keys = {(SOURCE, fit.target, fit.window_days) for fit in SPEC.recovery.fits}
    models: list[FittedModel] = fit_frame(frame, SPEC, seed=SPEC.seed, source=SOURCE, only=keys)
    assert {(model.target, model.window_days) for model in models} == {
        (fit.target, fit.window_days) for fit in SPEC.recovery.fits
    }
    groups: dict[str, tuple[str, str]] = {}
    for case in world.cases:
        person = case.person
        band = age_band(person.age_on(case.filed_date) if person.dob_known else None)
        for decision in case.decisions:
            groups[decision.decision_id] = (band, person.synthetic_group)
    cells: Cells = {}
    for model in models:
        assert model.status == FITTED, model.target
        parameters = ModelParameters.from_fitted(model)
        assert parameters.coefficients is not None
        design = model.design
        predictions = predict(parameters.coefficients, design.matrix)
        draws = list(replicate_draws(design, parameters))
        assert len(draws) == SPEC.bootstrap.replicates
        for position, attribute in enumerate((AGE, GROUP)):
            cells[(model.target, model.window_days, attribute)] = calibration_cells(
                predictions,
                design.outcome,
                [groups[member][position] for member in design.member_ids],
                draws,
                values=vocabulary.values(attribute),
                minimum_cohort=SPEC.thresholds.minimum_cohort,
                minimum_expected=SPEC.thresholds.minimum_expected,
                level=SPEC.bootstrap.level,
            )
    effects = compute_effects(world, build_timelines(world))["controls"][AGE]
    return cells, effects


def _published(cells: list[CellFigures]) -> dict[str, CellFigures]:
    return {cell.value: cell for cell in cells if cell.withheld is None}


def test_every_cell_of_the_demo_world_is_published_with_an_interval(
    controls: tuple[Cells, dict[str, Any]],
) -> None:
    cells, _ = controls
    for key, figures in cells.items():
        assert [cell.value for cell in figures] == list(vocabulary.values(key[2])), key
        for cell in figures:
            assert cell.withheld is None, (key, cell.value)
            assert cell.events is not None and cell.events >= SPEC.thresholds.minimum_cohort
            assert cell.ratio is not None and cell.lower is not None and cell.upper is not None
            assert cell.lower <= cell.ratio <= cell.upper, (key, cell.value)


def test_the_age_band_ratios_rank_like_the_planted_age_effects(
    controls: tuple[Cells, dict[str, Any]],
) -> None:
    cells, effects = controls
    checked = 0
    for fit in SPEC.recovery.fits:
        if fit.target not in PLANTED:
            continue
        planted = effects[PLANTED[fit.target]]
        published = _published(cells[(fit.target, fit.window_days, AGE)])
        bands = [band for band in vocabulary.values(AGE) if band != UNKNOWN_BAND]
        ratios = [float(published[band].ratio or 0.0) for band in bands]
        youngest, oldest = bands[0], bands[-1]
        assert planted[youngest] > 0 > planted[oldest]
        assert ratios[0] > 1.0 > ratios[-1], (fit.target, ratios)
        rho = spearman(ratios, [float(planted[band]) for band in bands])
        assert rho is not None and rho >= SPEARMAN_MINIMUM, (fit.target, rho)
        checked += 1
    assert checked == len(PLANTED)


def test_the_negative_control_and_the_ageless_release_model_are_calibrated(
    controls: tuple[Cells, dict[str, Any]],
) -> None:
    cells, _ = controls
    low, high = SPEC.recovery.negative_control_band
    for fit in SPEC.recovery.fits:
        for cell in cells[(fit.target, fit.window_days, GROUP)]:
            assert cell.ratio is not None and low <= cell.ratio <= high, (fit.target, cell)
    # No age effect enters the release draw (docs/SYNTHETIC_DATA.md "Planted effects"):
    # its age cells are calibrated too.
    for cell in cells[("pretrial_release", None, AGE)]:
        assert cell.ratio is not None and low <= cell.ratio <= high, cell
