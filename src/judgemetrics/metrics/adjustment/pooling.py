# src/judgemetrics/metrics/adjustment/pooling.py
"""Partial pooling of observed-to-expected ratios: the gamma–Poisson shape and the pooled ratio.

Judge ``j`` has an observed count ``O_j`` and a model-expected count ``E_j``.
The pooling model is ``O_j | theta_j ~ Poisson(theta_j E_j)`` with
``theta_j ~ Gamma(alpha, alpha)`` (mean 1, variance ``1 / alpha``), whose
marginal is the negative binomial

    log P(O | E, alpha) = log Gamma(alpha + O) - log Gamma(alpha) - log O!
                          + alpha log(alpha / (alpha + E)) + O log(E / (alpha + E)).

For an integer count ``log Gamma(alpha + O) - log Gamma(alpha)`` is
``sum_{k < O} log(alpha + k)`` and ``log O!`` is ``sum_{k = 1..O} log k``,
which is how ``marginal_log_likelihood`` evaluates it — exactly, with no
special function and no scipy. ``fit_shape`` maximizes the sum over the
judges with ``E > 0`` (suppressed or not: every such judge informs the
shape) on ``grid`` points evenly spaced in ``log alpha`` over ``bounds``,
then refines the best grid point by golden-section search in ``log alpha``
between its two neighbours and keeps whichever of the two is higher. A
maximum at the upper bound is reported ``pooled_fully``: no between-judge
variation is detectable, and every ratio is pulled almost all the way to 1.

The posterior mean of ``theta_j`` is the pooled ratio
``(alpha + O_j) / (alpha + E_j)`` (``pooled_ratio``), and ``E_j / (E_j +
alpha)`` (``pooling_weight``) is the share of it that is the judge's own
``O_j / E_j`` — the rest is the prior mean, 1.

Determinism: the judges enter every sum in one canonical order — sorted by
``(E, O)`` — so the shape is a function of the multiset of ``(O, E)`` pairs
alone, never of a judge's id or of the order the judges were listed in; the
grid, the bracket, the search's stopping rule, and its iteration limit are
fixed, and every reduction is NumPy's own single-threaded loop.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import overload

import numpy as np
import numpy.typing as npt

FloatArray = npt.NDArray[np.float64]
# The golden-section ratio (sqrt 5 - 1) / 2 and the search's stopping rule in log alpha.
GOLDEN = (math.sqrt(5.0) - 1.0) / 2.0
SEARCH_TOLERANCE = 1e-10
SEARCH_ITERATIONS = 200


class PoolingError(ValueError):
    """The counts cannot be pooled (no judge with a positive expected count, bad input)."""


@dataclass(frozen=True, slots=True)
class ShapeFit:
    """The fitted gamma shape ``alpha`` and how it was found."""

    shape: float
    log_likelihood: float
    pooled_fully: bool
    at_lower_bound: bool
    judges: int


@dataclass(frozen=True, slots=True)
class _Counts:
    """The informative judges' counts in canonical order, with the alpha-free terms."""

    observed: npt.NDArray[np.int64]
    expected: FloatArray
    constant: FloatArray  # O log E - log O! per judge


def _rising_logs(shapes: FloatArray, top: int) -> FloatArray:
    """``out[g, m] = sum_{k < m} log(shapes[g] + k)`` for ``m = 0..top``."""
    out = np.zeros((shapes.size, top + 1), dtype=np.float64)
    if top > 0:
        steps = np.arange(top, dtype=np.float64)
        np.cumsum(np.log(shapes[:, np.newaxis] + steps[np.newaxis, :]), axis=1, out=out[:, 1:])
    return out


def _counts(observed: npt.ArrayLike, expected: npt.ArrayLike) -> _Counts:
    o = np.asarray(observed, dtype=np.float64).reshape(-1)
    e = np.asarray(expected, dtype=np.float64).reshape(-1)
    if o.shape != e.shape:
        msg = "observed and expected must have one value per judge"
        raise PoolingError(msg)
    if not np.all(np.isfinite(o)) or not np.all(np.isfinite(e)):
        msg = "observed and expected counts must be finite"
        raise PoolingError(msg)
    if np.any(o < 0) or np.any(o != np.floor(o)):
        msg = "observed counts must be non-negative integers"
        raise PoolingError(msg)
    if np.any(e < 0):
        msg = "expected counts must be non-negative"
        raise PoolingError(msg)
    keep = e > 0.0
    o, e = o[keep], e[keep]
    order = np.lexsort((o, e))  # by E, then O: independent of how the judges were listed
    counts = o[order].astype(np.int64)
    expected_sorted = np.ascontiguousarray(e[order])
    log_factorial = _rising_logs(np.ones(1), int(counts.max()) if counts.size else 0)[0, counts]
    constant = counts * np.log(expected_sorted) - log_factorial
    return _Counts(counts, expected_sorted, np.ascontiguousarray(constant))


def _log_likelihoods(shapes: FloatArray, counts: _Counts) -> FloatArray:
    """The marginal log-likelihood at every shape in ``shapes`` (one sum per shape)."""
    o, e = counts.observed, counts.expected
    rising = _rising_logs(shapes, int(o.max()) if o.size else 0)[:, o]
    alpha = shapes[:, np.newaxis]
    terms = (
        rising
        - alpha * np.log1p(e[np.newaxis, :] / alpha)
        - o[np.newaxis, :] * np.log(alpha + e[np.newaxis, :])
        + counts.constant[np.newaxis, :]
    )
    result: FloatArray = np.ascontiguousarray(terms).sum(axis=1)
    return result


def marginal_log_likelihood(
    shape: float, observed: npt.ArrayLike, expected: npt.ArrayLike
) -> float:
    """The gamma–Poisson marginal log-likelihood of the judges with ``E > 0`` at ``shape``."""
    if not shape > 0.0 or not math.isfinite(shape):
        msg = "the shape must be a positive finite number"
        raise PoolingError(msg)
    counts = _counts(observed, expected)
    if counts.observed.size == 0:
        return 0.0
    return float(_log_likelihoods(np.array([shape], dtype=np.float64), counts)[0])


def _golden_section(
    low: float, high: float, value: Callable[[float], float]
) -> tuple[float, float]:
    """The maximizer and maximum of a unimodal ``value`` on ``[low, high]`` (fixed rules)."""
    a, b = low, high
    c = b - GOLDEN * (b - a)
    d = a + GOLDEN * (b - a)
    fc, fd = value(c), value(d)
    for _ in range(SEARCH_ITERATIONS):
        if b - a <= SEARCH_TOLERANCE:
            break
        if fc >= fd:
            b, d, fd = d, c, fc
            c = b - GOLDEN * (b - a)
            fc = value(c)
        else:
            a, c, fc = c, d, fd
            d = a + GOLDEN * (b - a)
            fd = value(d)
    return (c, fc) if fc >= fd else (d, fd)


def fit_shape(
    observed: npt.ArrayLike,
    expected: npt.ArrayLike,
    *,
    bounds: tuple[float, float],
    grid: int,
) -> ShapeFit:
    """The maximum-marginal-likelihood gamma shape over the judges with ``E > 0`` (module doc)."""
    low, high = float(bounds[0]), float(bounds[1])
    if not 0.0 < low < high or not math.isfinite(high):
        msg = "the shape bounds must satisfy 0 < low < high"
        raise PoolingError(msg)
    if grid < 2:
        msg = "the shape grid needs at least two points"
        raise PoolingError(msg)
    counts = _counts(observed, expected)
    if counts.observed.size == 0:
        msg = "no judge has a positive expected count: the shape cannot be fitted"
        raise PoolingError(msg)
    points = np.linspace(math.log(low), math.log(high), grid)
    shapes = np.exp(points)
    # The grid's end points are the bounds themselves, not exp(log(bound)).
    shapes[0], shapes[-1] = low, high
    values = _log_likelihoods(shapes, counts)
    best = int(np.argmax(values))

    def at(log_shape: float) -> float:
        return float(_log_likelihoods(np.array([math.exp(log_shape)]), counts)[0])

    refined, refined_value = _golden_section(
        float(points[max(best - 1, 0)]), float(points[min(best + 1, grid - 1)]), at
    )
    if refined_value > float(values[best]):
        shape, value = math.exp(refined), refined_value
    else:
        shape, value = float(shapes[best]), float(values[best])
    return ShapeFit(
        shape=shape,
        log_likelihood=value,
        pooled_fully=shape == high,
        at_lower_bound=shape == low,
        judges=int(counts.observed.size),
    )


@overload
def pooled_ratio(observed: float, expected: float, shape: float) -> float: ...
@overload
def pooled_ratio(observed: FloatArray, expected: FloatArray, shape: float) -> FloatArray: ...
def pooled_ratio(
    observed: float | FloatArray, expected: float | FloatArray, shape: float
) -> float | FloatArray:
    """The posterior mean ``(alpha + O) / (alpha + E)``: the judge's ratio pulled toward 1."""
    return (shape + observed) / (shape + expected)


@overload
def pooling_weight(expected: float, shape: float) -> float: ...
@overload
def pooling_weight(expected: FloatArray, shape: float) -> FloatArray: ...
def pooling_weight(expected: float | FloatArray, shape: float) -> float | FloatArray:
    """``E / (E + alpha)``: the share of the pooled ratio that is the judge's own ``O / E``."""
    return expected / (expected + shape)
