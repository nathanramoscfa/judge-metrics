# src/judgemetrics/metrics/adjustment/bootstrap.py
"""The pooled ratio's interval: percentiles over the person-cluster bootstrap replicates.

``interval(expectations, design, replicate_coefficients, ...)`` takes the
replicate coefficients as an argument — from a ``FittedModel`` in memory or
from the stored artifact (``expected.ModelParameters``) — and, for each
replicate ``r``:

1. the person-cluster weights ``w`` from ``resample.replicates`` over the
   design's cluster keys, with the seed and the stream the fit used
   (``resample.replicate_stream(target, window)``), so replicate ``r`` here is
   replicate ``r`` of the fit;
2. the replicate's predicted probabilities ``p_r = expit(X b_r)`` from its
   coefficients (a replicate whose refit did not converge has none and is
   skipped — its weights are still drawn, so the streams stay aligned);
3. per judge the weighted ``O_r = sum w y`` and ``E_r = sum w p_r`` (whole
   integers for ``O_r``, the weights being draw counts), the shape refitted
   over those counts (``pooling.fit_shape``), and the pooled ratio
   ``(alpha_r + O_r) / (alpha_r + E_r)``.

The published interval is the lower and upper ``(1 - level) / 2`` quantiles
(2.5% and 97.5% at the specification's 0.95) of each judge's pooled ratios
over the converged replicates, by linear interpolation between order
statistics. The model is not refitted here — the fit refitted it per
replicate and the artifact stores the coefficients — so ``metrics verify``,
reading the artifact, reproduces the interval exactly. Nothing here is
random beyond the seeded stream, and no sum depends on a canonical id: the
rows are in the design's source-key order and the shape sums the judges in
the canonical order ``pooling`` fixes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from judgemetrics.metrics.adjustment.expected import Expectations
from judgemetrics.metrics.adjustment.features import DesignFrame
from judgemetrics.metrics.adjustment.logistic import FloatArray, predict
from judgemetrics.metrics.adjustment.pooling import fit_shape, pooled_ratio
from judgemetrics.metrics.adjustment.resample import replicate_stream, replicates


class BootstrapError(ValueError):
    """The replicates cannot be replayed against this design."""


@dataclass(frozen=True, slots=True)
class BootstrapInterval:
    """Per judge (in ``Expectations.judges`` order): the interval bounds, NaN where undefined."""

    lower: FloatArray
    upper: FloatArray
    replicates: int  # the converged replicates the percentiles are taken over
    requested: int
    ratios: FloatArray  # (replicates, judges): every replicate's pooled ratios


def replicate_ratios(
    expectations: Expectations,
    design: DesignFrame,
    replicate_coefficients: Sequence[FloatArray | None],
    *,
    seed: int,
    bounds: tuple[float, float],
    grid: int,
) -> FloatArray:
    """Every converged replicate's pooled ratio per judge: shape (replicates, judges)."""
    count = len(expectations.judges)
    stream = replicate_stream(design.target, design.window_days)
    draws: list[FloatArray] = []
    weights_of = replicates(
        design.clusters, seed=seed, stream=stream, count=len(replicate_coefficients)
    )
    for coefficients, weights in zip(replicate_coefficients, weights_of, strict=True):
        if coefficients is None:
            continue
        if coefficients.shape != (design.width,):
            msg = f"a replicate has {coefficients.size} coefficients; the design {design.width}"
            raise BootstrapError(msg)
        predicted = predict(coefficients, design.matrix)
        observed = np.bincount(expectations.rows, weights=weights * design.outcome, minlength=count)
        expected = np.bincount(expectations.rows, weights=weights * predicted, minlength=count)
        shape = fit_shape(observed, expected, bounds=bounds, grid=grid).shape
        draws.append(pooled_ratio(observed, expected, shape))
    if not draws:
        return np.zeros((0, count), dtype=np.float64)
    return np.vstack(draws)


def interval(
    expectations: Expectations,
    design: DesignFrame,
    replicate_coefficients: Sequence[FloatArray | None],
    *,
    seed: int,
    bounds: tuple[float, float],
    grid: int,
    level: float,
) -> BootstrapInterval:
    """The percentile interval of every judge's pooled ratio (see the module docstring)."""
    if not 0.0 < level < 1.0:
        msg = "the interval level must lie strictly between 0 and 1"
        raise BootstrapError(msg)
    ratios = replicate_ratios(
        expectations, design, replicate_coefficients, seed=seed, bounds=bounds, grid=grid
    )
    count = len(expectations.judges)
    lower = np.full(count, np.nan, dtype=np.float64)
    upper = np.full(count, np.nan, dtype=np.float64)
    if ratios.shape[0]:
        tail = (1.0 - level) / 2.0
        quantiles = np.quantile(ratios, [tail, 1.0 - tail], axis=0, method="linear")
        lower, upper = quantiles[0], quantiles[1]
    return BootstrapInterval(
        lower=np.ascontiguousarray(lower),
        upper=np.ascontiguousarray(upper),
        replicates=int(ratios.shape[0]),
        requested=len(replicate_coefficients),
        ratios=ratios,
    )
