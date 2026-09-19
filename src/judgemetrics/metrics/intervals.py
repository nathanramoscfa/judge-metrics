# src/judgemetrics/metrics/intervals.py
"""Interval arithmetic for published rates: Wilson score and Greenwood-based bounds.

``wilson(numerator, denominator)`` is the 95% Wilson score interval for a
binomial proportion (the interval every fixed-window rate and share
publishes); ``normal_interval(estimate, standard_error)`` is the
symmetric interval a Kaplan-Meier cumulative incidence publishes with its
Greenwood standard error, clipped to ``[0, 1]``. A zero denominator yields
``(None, None)``. Everything is decimal-safe via ``round(x, 6)`` at the
boundary only (``round6``); no intermediate value is rounded.
"""

from __future__ import annotations

import math

# The 97.5th percentile of the standard normal distribution (a 95% interval).
Z_95 = 1.959964
PLACES = 6


def round6(value: float) -> float:
    """Round at the boundary: six decimals, the precision every published rate carries."""
    return round(value, PLACES)


def wilson(numerator: int, denominator: int, z: float = Z_95) -> tuple[float | None, float | None]:
    """The Wilson score interval ``(lower, upper)`` for ``numerator / denominator``.

    ``(None, None)`` when the denominator is zero; otherwise both bounds
    are within ``[0, 1]`` and rounded to six decimals.
    """
    if denominator <= 0:
        return None, None
    if numerator < 0 or numerator > denominator:
        msg = f"numerator {numerator} is outside 0..{denominator}"
        raise ValueError(msg)
    n = float(denominator)
    p = numerator / n
    z2 = z * z
    centre = (p + z2 / (2 * n)) / (1 + z2 / n)
    half = (z / (1 + z2 / n)) * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n))
    return round6(max(0.0, centre - half)), round6(min(1.0, centre + half))


def normal_interval(estimate: float, standard_error: float, z: float = Z_95) -> tuple[float, float]:
    """``estimate ± z · standard_error`` clipped to ``[0, 1]`` and rounded to six decimals."""
    half = z * standard_error
    return round6(max(0.0, estimate - half)), round6(min(1.0, estimate + half))
