# tests/unit/test_pooling.py
"""The gamma–Poisson pooling: the marginal likelihood, the shape, the pooled ratio, the weight.

``marginal_log_likelihood`` equals a direct evaluation with ``math.lgamma``;
``fit_shape`` recovers a known shape from counts simulated under it (a
seeded NumPy generator, so the test is deterministic), reports
``pooled_fully`` when the counts show no between-judge variation, refuses
input it cannot pool, and is invariant to the order the judges are listed
in, bit for bit; a judge with ``O = 0`` gets a finite ratio below 1; the
pooled ratio and the weight are the formulas.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from judgemetrics.metrics.adjustment.pooling import (
    PoolingError,
    fit_shape,
    marginal_log_likelihood,
    pooled_ratio,
    pooling_weight,
)
from judgemetrics.metrics.adjustment.spec import load_spec

pytestmark = pytest.mark.unit

SPEC = load_spec()
BOUNDS = SPEC.pooling.shape_bounds
GRID = SPEC.pooling.shape_grid
OBSERVED = [0, 3, 12, 7, 41, 1, 19]
EXPECTED = [2.5, 4.2, 9.75, 7.0, 33.1, 0.4, 25.0]


def _direct(shape: float, observed: list[int], expected: list[float]) -> float:
    """The negative-binomial marginal log-likelihood with ``math.lgamma``."""
    total = 0.0
    for o, e in zip(observed, expected, strict=True):
        if e <= 0:
            continue
        total += (
            math.lgamma(shape + o)
            - math.lgamma(shape)
            - math.lgamma(o + 1)
            + shape * math.log(shape / (shape + e))
            + o * math.log(e / (shape + e))
        )
    return total


@pytest.mark.parametrize("shape", [0.5, 1.0, 3.7, 25.0, 999.0])
def test_the_marginal_likelihood_equals_a_direct_lgamma_evaluation(shape: float) -> None:
    ours = marginal_log_likelihood(shape, OBSERVED, EXPECTED)
    assert ours == pytest.approx(_direct(shape, OBSERVED, EXPECTED), rel=1e-12, abs=1e-9)


def test_judges_without_a_positive_expected_count_do_not_inform_the_shape() -> None:
    with_zero = marginal_log_likelihood(4.0, [*OBSERVED, 5], [*EXPECTED, 0.0])
    assert with_zero == marginal_log_likelihood(4.0, OBSERVED, EXPECTED)
    assert fit_shape([*OBSERVED, 5], [*EXPECTED, 0.0], bounds=BOUNDS, grid=GRID).judges == len(
        OBSERVED
    )


@pytest.mark.parametrize(("shape", "seed"), [(2.0, 11), (10.0, 12), (40.0, 13)])
def test_the_shape_is_recovered_from_counts_simulated_under_it(shape: float, seed: int) -> None:
    generator = np.random.default_rng(seed)
    judges = 600
    expected = generator.uniform(10.0, 80.0, size=judges)
    theta = generator.gamma(shape, 1.0 / shape, size=judges)
    observed = generator.poisson(theta * expected)
    fit = fit_shape(observed, expected, bounds=BOUNDS, grid=GRID)
    assert not fit.pooled_fully and not fit.at_lower_bound
    assert math.log(fit.shape) == pytest.approx(math.log(shape), abs=0.35), fit
    # The fit is the maximum: nearby shapes are no more likely.
    for factor in (0.9, 1.1):
        assert marginal_log_likelihood(fit.shape * factor, observed, expected) <= (
            fit.log_likelihood + 1e-9
        )


def test_counts_without_between_judge_variation_are_pooled_fully() -> None:
    expected = [10.0, 20.0, 30.0, 45.0]
    observed = [10, 20, 30, 45]
    fit = fit_shape(observed, expected, bounds=BOUNDS, grid=GRID)
    assert fit.pooled_fully and fit.shape == BOUNDS[1]
    assert fit.log_likelihood == marginal_log_likelihood(BOUNDS[1], observed, expected)
    # Fully pooled, every ratio sits at about 1 whatever the judge's own counts.
    assert pooled_ratio(45.0, 30.0, fit.shape) == pytest.approx(1.0, abs=0.02)


def test_wildly_overdispersed_counts_reach_the_lower_bound() -> None:
    fit = fit_shape([0, 0, 0, 200, 0, 150], [50.0] * 6, bounds=BOUNDS, grid=GRID)
    assert fit.at_lower_bound and fit.shape == BOUNDS[0] and not fit.pooled_fully


def test_a_judge_with_no_outcome_gets_a_finite_ratio_below_one() -> None:
    fit = fit_shape(OBSERVED, EXPECTED, bounds=BOUNDS, grid=GRID)
    ratio = pooled_ratio(0.0, 2.5, fit.shape)
    assert math.isfinite(ratio) and 0.0 < ratio < 1.0


def test_the_pooled_ratio_and_the_weight_are_the_formulas() -> None:
    assert pooled_ratio(12.0, 9.75, 4.0) == (4.0 + 12.0) / (4.0 + 9.75)
    assert pooling_weight(9.75, 4.0) == 9.75 / (9.75 + 4.0)
    observed = np.array([0.0, 12.0])
    expected = np.array([2.5, 9.75])
    assert np.array_equal(
        pooled_ratio(observed, expected, 4.0), (4.0 + observed) / (4.0 + expected)
    )
    assert np.array_equal(pooling_weight(expected, 4.0), expected / (expected + 4.0))
    # The pooled ratio is the weighted mean of the judge's own ratio and 1.
    weight = pooling_weight(9.75, 4.0)
    assert pooled_ratio(12.0, 9.75, 4.0) == pytest.approx(weight * 12.0 / 9.75 + (1 - weight))


def test_the_shape_does_not_depend_on_the_order_of_the_judges() -> None:
    fit = fit_shape(OBSERVED, EXPECTED, bounds=BOUNDS, grid=GRID)
    for order in ([6, 5, 4, 3, 2, 1, 0], [3, 0, 6, 1, 5, 2, 4]):
        again = fit_shape(
            [OBSERVED[i] for i in order], [EXPECTED[i] for i in order], bounds=BOUNDS, grid=GRID
        )
        assert again == fit  # bit for bit: the judges are summed in one canonical order


def test_input_that_cannot_be_pooled_is_refused() -> None:
    with pytest.raises(PoolingError, match="no judge has a positive expected count"):
        fit_shape([1, 2], [0.0, 0.0], bounds=BOUNDS, grid=GRID)
    with pytest.raises(PoolingError, match="non-negative integers"):
        fit_shape([1.5], [2.0], bounds=BOUNDS, grid=GRID)
    with pytest.raises(PoolingError, match="one value per judge"):
        fit_shape([1, 2], [2.0], bounds=BOUNDS, grid=GRID)
    with pytest.raises(PoolingError, match="0 < low < high"):
        fit_shape([1], [2.0], bounds=(5.0, 1.0), grid=GRID)
    with pytest.raises(PoolingError, match="positive finite"):
        marginal_log_likelihood(0.0, [1], [2.0])
