# src/judgemetrics/validation/statistics.py
"""Rank correlations, linear correlation, and percentiles for the validation report.

Ties share their average rank (``diagnostics.average_ranks``), so every
statistic here is a function of the multiset of pairs alone — never of the
order the judges were listed in, which follows their canonical ids. A
statistic that is undefined (fewer than two values, a constant series)
is ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from judgemetrics.metrics.adjustment.diagnostics import average_ranks
from judgemetrics.metrics.adjustment.logistic import FloatArray


def _array(values: Sequence[float] | FloatArray) -> FloatArray:
    return np.asarray(values, dtype=np.float64).reshape(-1)


def pearson(
    left: Sequence[float] | FloatArray, right: Sequence[float] | FloatArray
) -> float | None:
    """The Pearson correlation; ``None`` with fewer than two pairs or a constant series."""
    x, y = _array(left), _array(right)
    if x.size != y.size:
        msg = "a correlation needs one value of each series per item"
        raise ValueError(msg)
    if x.size < 2:
        return None
    dx, dy = x - x.mean(), y - y.mean()
    scale = float(np.sqrt(np.sum(dx * dx) * np.sum(dy * dy)))
    if scale == 0.0:
        return None
    return float(np.sum(dx * dy)) / scale


def spearman(
    left: Sequence[float] | FloatArray, right: Sequence[float] | FloatArray
) -> float | None:
    """The Spearman correlation: Pearson over average ranks (ties share their rank)."""
    x, y = _array(left), _array(right)
    if x.size != y.size:
        msg = "a correlation needs one value of each series per item"
        raise ValueError(msg)
    return pearson(average_ranks(x), average_ranks(y))


def quantile(values: Sequence[float] | FloatArray, q: float) -> float | None:
    """The ``q`` quantile by linear interpolation; ``None`` without values."""
    array = _array(values)
    if array.size == 0:
        return None
    return float(np.quantile(array, q, method="linear"))
