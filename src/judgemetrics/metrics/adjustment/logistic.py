# src/judgemetrics/metrics/adjustment/logistic.py
"""L2-penalized logistic regression by Newton-Raphson (iteratively reweighted least squares).

``fit_logistic(design, outcome, *, lam, max_iterations, tolerance)`` maximizes
the penalized log-likelihood

    Q(b) = sum_i w_i [y_i eta_i - log(1 + exp(eta_i))] - (lam / 2) sum_{j >= 1} b_j^2,
    eta = X b,

where column 0 of ``design`` is the intercept, which is never penalized, and
``w`` are optional case weights (a bootstrap replicate's cluster counts;
ones otherwise). Each iteration computes the gradient
``g = X'(w (y - p)) - lam m b`` (``m`` masks the intercept) and stops when
its infinity norm falls below ``tolerance``; otherwise it takes the Newton
step ``H^-1 g`` with ``H = X' diag(w p (1 - p)) X + lam diag(m)``, halving
it until ``Q`` does not decrease (beyond the rounding noise of the sum).
With ``lam > 0`` the objective is strictly concave in the penalized
coefficients, so complete separation still has a finite maximizer.
Without the penalty separated data has no maximizer: the coefficients run
away until the vanishing gradient meets the tolerance, which is why every
published fit is penalized (only the calibration slope, a one-feature fit
on the test set, is not).

Determinism: no global state, no randomness, and no reduction whose order
depends on threads — every matrix product is an ``np.einsum`` with the
default ``optimize=False`` (NumPy's own single-threaded loops, never BLAS)
and the Newton system is solved by the Cholesky factorization below rather
than LAPACK, so two fits of the same arrays are bit-identical. The fit
starts from zero unless ``start`` is given (a bootstrap replicate starts
from the published coefficients). Coefficients are rounded to 12
significant digits only when an artifact serializes them.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
# The objective may fall by this much relative to its size and the step still
# count as an ascent: near the optimum a true increase is below the rounding of the sum.
OBJECTIVE_NOISE = 1e-10


class SolverError(ArithmeticError):
    """The Newton system cannot be solved (the penalized Hessian is not positive definite)."""


@dataclass(frozen=True, slots=True)
class IterationRecord:
    """One accepted Newton step: the objective after it, the gradient norm before it, the step."""

    iteration: int
    objective: float
    gradient_norm: float
    step: float


@dataclass(frozen=True, slots=True)
class LogisticFit:
    """The solver's result; ``coefficients`` is meaningful only when ``converged``."""

    coefficients: FloatArray
    iterations: int
    gradient_norm: float
    converged: bool
    objective: float
    trace: tuple[IterationRecord, ...]


def as_design(values: npt.ArrayLike) -> FloatArray:
    """A C-contiguous float64 copy-free view where possible."""
    return np.ascontiguousarray(values, dtype=np.float64)


def linear_predictor(design: FloatArray, coefficients: FloatArray) -> FloatArray:
    result: FloatArray = np.einsum("ij,j->i", design, coefficients)
    return result


def expit(eta: FloatArray) -> FloatArray:
    """The logistic function, stable for every finite ``eta``."""
    result: FloatArray = np.exp(-np.logaddexp(0.0, -eta))
    return result


def predict(fit: LogisticFit | FloatArray, design: npt.ArrayLike) -> FloatArray:
    """Predicted probabilities of ``design``'s rows under the fit's coefficients."""
    coefficients = fit.coefficients if isinstance(fit, LogisticFit) else fit
    return expit(linear_predictor(as_design(design), as_design(coefficients)))


def penalty_mask(columns: int, *, penalize_intercept: bool = False) -> FloatArray:
    mask = np.ones(columns, dtype=np.float64)
    if columns and not penalize_intercept:
        mask[0] = 0.0
    return mask


def objective(
    design: FloatArray,
    outcome: FloatArray,
    weights: FloatArray,
    coefficients: FloatArray,
    lam: float,
    mask: FloatArray,
) -> float:
    eta = linear_predictor(design, coefficients)
    loglik = float(np.sum(weights * (outcome * eta - np.logaddexp(0.0, eta))))
    return loglik - 0.5 * lam * float(np.einsum("j,j,j->", mask, coefficients, coefficients))


def gradient(
    design: FloatArray,
    outcome: FloatArray,
    weights: FloatArray,
    coefficients: FloatArray,
    lam: float,
    mask: FloatArray,
) -> FloatArray:
    """The gradient of the penalized log-likelihood (zero at the solution)."""
    residual = weights * (outcome - expit(linear_predictor(design, coefficients)))
    result: FloatArray = np.einsum("ij,i->j", design, residual) - lam * mask * coefficients
    return result


def hessian(
    design: FloatArray,
    weights: FloatArray,
    coefficients: FloatArray,
    lam: float,
    mask: FloatArray,
) -> FloatArray:
    """The negative Hessian ``X' diag(w p (1 - p)) X + lam diag(mask)``."""
    probability = expit(linear_predictor(design, coefficients))
    scaled = design * (weights * probability * (1.0 - probability))[:, np.newaxis]
    information: FloatArray = np.einsum("ij,ik->jk", scaled, design)
    return information + np.diag(lam * mask)


def cholesky_solve(matrix: FloatArray, vector: FloatArray) -> FloatArray:
    """``matrix^-1 vector`` for a symmetric positive-definite ``matrix`` (column Cholesky)."""
    size = matrix.shape[0]
    lower = np.zeros((size, size), dtype=np.float64)
    for column in range(size):
        row = lower[column, :column]
        diagonal = float(matrix[column, column]) - float(np.einsum("k,k->", row, row))
        if not diagonal > 0.0 or not math.isfinite(diagonal):
            msg = "the penalized Hessian is not positive definite"
            raise SolverError(msg)
        pivot = math.sqrt(diagonal)
        lower[column, column] = pivot
        if column + 1 < size:
            below = lower[column + 1 :, :column]
            lower[column + 1 :, column] = (
                matrix[column + 1 :, column] - np.einsum("ik,k->i", below, row)
            ) / pivot
    forward = np.zeros(size, dtype=np.float64)
    for index in range(size):
        done = float(np.einsum("k,k->", lower[index, :index], forward[:index]))
        forward[index] = (float(vector[index]) - done) / lower[index, index]
    solution = np.zeros(size, dtype=np.float64)
    for index in reversed(range(size)):
        done = float(np.einsum("k,k->", lower[index + 1 :, index], solution[index + 1 :]))
        solution[index] = (forward[index] - done) / lower[index, index]
    return solution


def fit_logistic(
    design: npt.ArrayLike,
    outcome: npt.ArrayLike,
    *,
    lam: float,
    max_iterations: int,
    tolerance: float,
    weights: npt.ArrayLike | None = None,
    start: npt.ArrayLike | None = None,
    step_halvings: int = 30,
    penalize_intercept: bool = False,
) -> LogisticFit:
    """Maximize the penalized log-likelihood of ``outcome`` (0/1) on ``design``.

    Iterations run in a fixed order; the result carries the coefficients,
    the number of Newton steps taken, the final gradient's infinity norm,
    ``converged`` (that norm below ``tolerance``), the final objective, and
    the per-step trace.
    """
    matrix = as_design(design)
    response = as_design(outcome)
    if matrix.ndim != 2 or response.shape != (matrix.shape[0],):
        msg = "the design must be (rows, columns) and the outcome one value per row"
        raise ValueError(msg)
    case_weights = (
        np.ones(matrix.shape[0], dtype=np.float64) if weights is None else as_design(weights)
    )
    coefficients = (
        np.zeros(matrix.shape[1], dtype=np.float64) if start is None else as_design(start).copy()
    )
    mask = penalty_mask(matrix.shape[1], penalize_intercept=penalize_intercept)
    current = objective(matrix, response, case_weights, coefficients, lam, mask)
    trace: list[IterationRecord] = []
    norm = math.inf
    for iteration in range(max_iterations + 1):
        step_gradient = gradient(matrix, response, case_weights, coefficients, lam, mask)
        norm = float(np.max(np.abs(step_gradient))) if step_gradient.size else 0.0
        if not math.isfinite(norm):
            break
        if norm < tolerance or iteration == max_iterations:
            break
        try:
            direction = cholesky_solve(
                hessian(matrix, case_weights, coefficients, lam, mask), step_gradient
            )
        except SolverError:
            break
        step = 1.0
        accepted = False
        noise = OBJECTIVE_NOISE * max(1.0, abs(current))
        for _ in range(step_halvings + 1):
            candidate = coefficients + step * direction
            value = objective(matrix, response, case_weights, candidate, lam, mask)
            if math.isfinite(value) and value >= current - noise:
                accepted = True
                break
            step /= 2.0
        if not accepted:
            break
        coefficients, current = candidate, value
        trace.append(IterationRecord(len(trace) + 1, current, norm, step))
    return LogisticFit(
        coefficients=coefficients,
        iterations=len(trace),
        gradient_norm=norm,
        converged=math.isfinite(norm) and norm < tolerance,
        objective=current,
        trace=tuple(trace),
    )
