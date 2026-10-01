# tests/unit/test_model_diagnostics.py
"""Model diagnostics against their references.

ROC AUC equals brute-force pair counting with ties counted as one half;
the Brier score and its skill are the hand computation; the ten
calibration bins are equal-count groups of the rows ordered by prediction;
the calibration slope is near one on data drawn from the fitted model; the
temporal cutoff is the nearest-rank 75th percentile; feature stability and
the complete-case refit are what they say.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from judgemetrics.metrics.adjustment.diagnostics import (
    BINS,
    average_ranks,
    brier,
    calibration_bins,
    calibration_slope,
    evaluate,
    refit_complete_cases,
    roc_auc,
    split_cutoff,
    stability,
)
from judgemetrics.metrics.adjustment.features import DesignFrame, design_rows
from judgemetrics.metrics.adjustment.logistic import fit_logistic, predict
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.synthetic.config import GOLDEN
from tests.property.support import build_world, frame_from_world

pytestmark = pytest.mark.unit

SPEC = load_spec()


def _brute_force_auc(predicted: np.ndarray, outcome: np.ndarray) -> float:
    positives = predicted[outcome == 1]
    negatives = predicted[outcome == 0]
    wins = 0.0
    for p in positives:
        for n in negatives:
            wins += 1.0 if p > n else 0.5 if p == n else 0.0
    return float(wins / (positives.size * negatives.size))


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_auc_matches_brute_force_pair_counting_with_ties(seed: int) -> None:
    rng = np.random.default_rng(seed)
    predicted = np.round(rng.random(300), 1)  # heavy ties
    outcome = (rng.random(300) < predicted).astype(np.float64)
    assert roc_auc(predicted, outcome) == pytest.approx(
        _brute_force_auc(predicted, outcome), abs=1e-12
    )
    assert roc_auc(np.full(10, 0.3), np.r_[np.ones(4), np.zeros(6)]) == 0.5
    assert roc_auc(predicted, np.ones(300)) is None
    assert average_ranks(np.array([0.2, 0.1, 0.2, 0.3])).tolist() == [2.5, 1.0, 2.5, 4.0]


def test_the_brier_score_and_its_skill() -> None:
    predicted = np.array([0.1, 0.4, 0.8, 0.9])
    outcome = np.array([0.0, 1.0, 1.0, 0.0])
    expected = ((0.1) ** 2 + (0.6) ** 2 + (0.2) ** 2 + (0.9) ** 2) / 4
    assert brier(predicted, outcome) == pytest.approx(expected)
    evaluation = evaluate(predicted, outcome, 0.25, SPEC.model)
    reference = ((0.25) ** 2 + (0.75) ** 2 + (0.75) ** 2 + (0.25) ** 2) / 4
    assert evaluation.brier_skill == pytest.approx(1 - expected / reference)
    assert evaluation.calibration_in_the_large == pytest.approx(2 / 2.2)
    assert evaluation.rows == 4 and evaluation.events == 2
    assert brier(np.zeros(0), np.zeros(0)) is None


def test_the_decile_bins_are_equal_count_groups_by_prediction() -> None:
    predicted = np.linspace(0.95, 0.0, 20)  # descending: the order is the prediction's
    outcome = np.r_[np.ones(10), np.zeros(10)]
    bins = calibration_bins(predicted, outcome)
    assert len(bins) == BINS
    assert [item.count for item in bins] == [2] * BINS
    assert [item.bin for item in bins] == list(range(1, 11))
    assert bins[0].mean_predicted == pytest.approx((0.0 + 0.05) / 2)
    assert bins[0].observed_rate == 0.0 and bins[-1].observed_rate == 1.0
    # Ties keep the row order; fewer rows than bins leave empty bins.
    few = calibration_bins(np.array([0.5, 0.5, 0.5]), np.array([1.0, 0.0, 1.0]))
    assert sum(item.count for item in few) == 3
    assert sum(1 for item in few if item.count == 0) == 7
    assert all(item.mean_predicted is None for item in few if item.count == 0)


def test_the_calibration_slope_is_near_one_on_data_drawn_from_the_fitted_model() -> None:
    rng = np.random.default_rng(20260930)
    rows = 20_000
    design = np.column_stack([np.ones(rows), (rng.random((rows, 6)) < 0.4).astype(np.float64)])
    truth = np.array([-1.0, 0.8, -0.6, 0.5, 1.1, -0.9, 0.3])
    outcome = (rng.random(rows) < 1 / (1 + np.exp(-(design @ truth)))).astype(np.float64)
    fit = fit_logistic(design, outcome, lam=1.0, max_iterations=50, tolerance=1e-8)
    assert fit.converged
    # A fresh draw from the fitted model: the model is calibrated for it by construction.
    predicted = predict(fit, design)
    drawn = (rng.random(rows) < predicted).astype(np.float64)
    slope = calibration_slope(predicted, drawn, SPEC.model)
    assert slope is not None and slope == pytest.approx(1.0, abs=0.06)
    evaluation = evaluate(predicted, drawn, float(drawn.mean()), SPEC.model)
    assert evaluation.calibration_in_the_large == pytest.approx(1.0, abs=0.03)
    # Overconfident predictions (logits doubled) have a slope near one half.
    doubled = 1 / (1 + np.exp(-2 * np.log(predicted / (1 - predicted))))
    assert calibration_slope(doubled, drawn, SPEC.model) == pytest.approx(0.5, abs=0.05)
    assert calibration_slope(predicted, np.zeros(rows), SPEC.model) is None


def test_the_temporal_cutoff_is_the_nearest_rank_quantile() -> None:
    times = np.array([5, 1, 8, 3, 2, 7, 4, 6], dtype=np.int64)
    assert split_cutoff(times, 0.75) == 6  # ceil(0.75 * 8) = 6th smallest
    test = times >= 6
    assert int(test.sum()) == 3
    assert split_cutoff(np.array([1, 1, 1, 2], dtype=np.int64), 0.75) == 1  # ties all go to test
    assert split_cutoff(np.array([9], dtype=np.int64), 0.75) == 9
    assert split_cutoff(np.zeros(0, dtype=np.int64), 0.75) is None


def test_feature_stability_over_the_replicates() -> None:
    estimate = np.array([0.5, -1.0, 0.0])
    replicates = [
        np.array([0.4, -1.2, 0.1]),
        None,  # a replicate that did not converge is ignored
        np.array([0.6, -0.8, -0.1]),
        np.array([-0.1, -1.0, 0.2]),
    ]
    rows = stability(["a", "b", "c"], estimate, replicates)
    assert [row.column for row in rows] == ["a", "b", "c"]
    assert rows[0].mean == pytest.approx(0.3)
    assert rows[0].sd == pytest.approx(float(np.std([0.4, 0.6, -0.1], ddof=1)))
    assert rows[0].sign_agreement == pytest.approx(2 / 3)
    assert rows[1].sign_agreement == 1.0
    assert rows[2].sign_agreement == 0.0  # no replicate is exactly zero
    empty = stability(["a"], np.array([1.0]), [None])
    assert empty[0].mean is None and empty[0].sign_agreement is None


def test_the_complete_case_refit_drops_the_rows_at_a_missing_level() -> None:
    frame = frame_from_world(build_world(7, GOLDEN), GOLDEN)
    design = design_rows(frame, SPEC, SPEC.target("pretrial_release"), None)
    assert isinstance(design, DesignFrame) and design.rows > 10
    flagged = np.zeros(design.rows, dtype=np.bool_)
    flagged[::4] = True
    marked = replace(design, missing=flagged)
    refit = refit_complete_cases(marked, SPEC.model)
    direct = fit_logistic(
        design.matrix[~flagged],
        design.outcome[~flagged],
        lam=SPEC.model.lam,
        max_iterations=SPEC.model.max_iterations,
        tolerance=SPEC.model.tolerance,
        step_halvings=SPEC.model.step_halvings,
    )
    assert refit.coefficients.tobytes() == direct.coefficients.tobytes()
    # The golden world has no missing level: the complete-case refit is the published fit.
    assert not design.missing.any()
