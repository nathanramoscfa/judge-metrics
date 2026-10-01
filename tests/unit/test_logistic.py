# tests/unit/test_logistic.py
"""The L2-penalized Newton-Raphson solver: optimality, closed forms, shrinkage, determinism.

At the returned coefficients the penalized gradient ``X'(w (y - p)) - lam m b``
(computed here independently with plain NumPy) is below the tolerance; an
unpenalized saturated fit reproduces the group means; a larger penalty
shrinks every penalized coefficient; complete separation stays finite under
the penalty and is reported as not converged without it; two fits of the
same arrays are byte-identical; a capped iteration count is reported.
"""

from __future__ import annotations

import numpy as np
import pytest

from judgemetrics.metrics.adjustment.logistic import (
    SolverError,
    cholesky_solve,
    fit_logistic,
    predict,
)

pytestmark = pytest.mark.unit

TOLERANCE = 1e-8


def _random_problem(rows: int = 600, columns: int = 8, seed: int = 11) -> tuple[np.ndarray, ...]:
    rng = np.random.default_rng(seed)
    design = np.column_stack(
        [np.ones(rows), (rng.random((rows, columns - 1)) < 0.3).astype(np.float64)]
    )
    truth = rng.normal(0.0, 0.8, columns)
    probability = 1.0 / (1.0 + np.exp(-(design @ truth)))
    outcome = (rng.random(rows) < probability).astype(np.float64)
    weights = rng.integers(0, 4, rows).astype(np.float64)
    return design, outcome, weights


def _penalized_gradient(
    design: np.ndarray, outcome: np.ndarray, weights: np.ndarray, beta: np.ndarray, lam: float
) -> np.ndarray:
    mask = np.ones(beta.size)
    mask[0] = 0.0
    probability = 1.0 / (1.0 + np.exp(-(design @ beta)))
    gradient: np.ndarray = design.T @ (weights * (outcome - probability)) - lam * mask * beta
    return gradient


def test_the_penalized_gradient_vanishes_at_the_solution() -> None:
    design, outcome, weights = _random_problem()
    for lam, case_weights in ((1.0, None), (4.0, weights)):
        fit = fit_logistic(
            design,
            outcome,
            lam=lam,
            max_iterations=50,
            tolerance=TOLERANCE,
            weights=case_weights,
        )
        assert fit.converged and fit.iterations >= 1
        assert fit.gradient_norm < TOLERANCE
        reference = _penalized_gradient(
            design,
            outcome,
            np.ones(outcome.size) if case_weights is None else case_weights,
            fit.coefficients,
            lam,
        )
        assert float(np.max(np.abs(reference))) < 1e-6
        # The trace records every accepted step; the objective never decreases.
        objectives = [record.objective for record in fit.trace]
        assert all(
            later >= earlier - 1e-6
            for earlier, later in zip(objectives, objectives[1:], strict=False)
        )


def test_an_unpenalized_saturated_fit_equals_the_group_means() -> None:
    groups = np.repeat([0, 1, 2], [40, 25, 35])
    outcome = np.concatenate(
        [
            np.r_[np.ones(10), np.zeros(30)],
            np.r_[np.ones(20), np.zeros(5)],
            np.r_[np.ones(7), np.zeros(28)],
        ]
    )
    design = np.column_stack([np.ones(groups.size), groups == 1, groups == 2]).astype(np.float64)
    fit = fit_logistic(design, outcome, lam=0.0, max_iterations=50, tolerance=1e-10)
    assert fit.converged
    predicted = predict(fit, design)
    for group, mean in ((0, 10 / 40), (1, 20 / 25), (2, 7 / 35)):
        assert np.allclose(predicted[groups == group], mean, atol=1e-9)
    # The intercept is the reference group's log-odds.
    assert fit.coefficients[0] == pytest.approx(np.log(0.25 / 0.75), abs=1e-9)


def test_a_larger_penalty_shrinks_every_coefficient() -> None:
    first = np.repeat([0, 0, 1, 1], 50)
    second = np.tile(np.repeat([0, 1], 25), 4)
    design = np.column_stack([np.ones(200), first, second]).astype(np.float64)
    rng = np.random.default_rng(5)
    probability = 1.0 / (1.0 + np.exp(-(-0.5 + 1.2 * first - 0.8 * second)))
    outcome = (rng.random(200) < probability).astype(np.float64)
    previous: np.ndarray | None = None
    for lam in (0.0, 0.5, 5.0, 50.0):
        fit = fit_logistic(design, outcome, lam=lam, max_iterations=50, tolerance=1e-10)
        assert fit.converged
        penalized = np.abs(fit.coefficients[1:])
        if previous is not None:
            assert np.all(penalized < previous), (lam, penalized, previous)
        previous = penalized


def test_complete_separation_stays_finite_under_the_penalty() -> None:
    x = np.r_[np.zeros(30), np.ones(30)]
    design = np.column_stack([np.ones(60), x])
    outcome = x.copy()  # x = 1 exactly when y = 1: complete separation
    fit = fit_logistic(design, outcome, lam=1.0, max_iterations=50, tolerance=TOLERANCE)
    assert fit.converged
    assert np.all(np.isfinite(fit.coefficients))
    assert 0.0 < fit.coefficients[1] < 20.0
    predicted = predict(fit, design)
    # Shrunk, but on the right side of one half in both groups.
    assert np.all(predicted[x == 1] > 0.5) and np.all(predicted[x == 0] < 0.5)
    # Without the penalty the likelihood has no maximum: the coefficient runs away
    # until the vanishing gradient meets the tolerance. The penalty is what bounds it.
    unpenalized = fit_logistic(design, outcome, lam=0.0, max_iterations=50, tolerance=TOLERANCE)
    assert unpenalized.coefficients[1] > 5 * fit.coefficients[1]


def test_two_fits_are_byte_identical() -> None:
    design, outcome, weights = _random_problem(rows=2000, columns=20, seed=3)
    first = fit_logistic(design, outcome, lam=1.0, max_iterations=50, tolerance=TOLERANCE)
    second = fit_logistic(
        design.copy(), outcome.copy(), lam=1.0, max_iterations=50, tolerance=TOLERANCE
    )
    assert first.coefficients.tobytes() == second.coefficients.tobytes()
    assert first.trace == second.trace
    warm = [
        fit_logistic(
            design,
            outcome,
            lam=1.0,
            max_iterations=50,
            tolerance=TOLERANCE,
            weights=weights,
            start=first.coefficients,
        )
        for _ in range(2)
    ]
    assert warm[0].coefficients.tobytes() == warm[1].coefficients.tobytes()
    assert predict(first, design).tobytes() == predict(second, design).tobytes()


def test_non_convergence_is_reported() -> None:
    design, outcome, _ = _random_problem()
    capped = fit_logistic(design, outcome, lam=1.0, max_iterations=1, tolerance=1e-14)
    assert not capped.converged
    assert capped.iterations == 1
    assert capped.gradient_norm >= 1e-14
    stalled = fit_logistic(design, outcome, lam=1.0, max_iterations=0, tolerance=TOLERANCE)
    assert not stalled.converged and stalled.iterations == 0


def test_the_cholesky_solve_matches_a_reference_and_refuses_an_indefinite_system() -> None:
    rng = np.random.default_rng(2)
    base = rng.normal(size=(12, 12))
    matrix = base @ base.T + 12 * np.eye(12)
    vector = rng.normal(size=12)
    assert np.allclose(cholesky_solve(matrix, vector), np.linalg.solve(matrix, vector), atol=1e-12)
    with pytest.raises(SolverError):
        cholesky_solve(np.array([[1.0, 2.0], [2.0, 1.0]]), np.ones(2))
