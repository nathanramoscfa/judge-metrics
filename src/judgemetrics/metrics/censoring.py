# src/judgemetrics/metrics/censoring.py
"""Right-censoring, adequately followed cohorts, and the Kaplan-Meier estimator.

Follow-up ends at the source's coverage end: nothing after
``coverage_end_exclusive_at`` (the day after ``coverage_end`` at 00:00
UTC) is in the data, so an absent outcome after that instant means
nothing. Two estimators handle this:

- **Fixed-window rate.** A cohort member is *followed* for window ``w``
  when ``exposure_start + w days < coverage_end_exclusive_at`` — the whole
  window is inside the coverage. The rate's denominator is the followed
  members and its numerator the followed members with an outcome in the
  window; ``eligible`` is the whole cohort, published beside the rate so
  a reader sees how much of it the window could observe. The interval is
  Wilson's.
- **Kaplan-Meier.** Over the whole cohort, each member contributes its
  time to first outcome (an event) or its time to the coverage end (a
  censoring), both measured from the exposure start. The product-limit
  survival ``S(t) = Π (1 - d_i / n_i)`` over the distinct event times
  ``t_i <= t`` — ``d_i`` events at ``t_i``, ``n_i`` members at risk (time
  ``>= t_i``); ties are handled by counting events before censorings at
  the same time, so a member censored at ``t_i`` is still at risk there —
  is evaluated at ``t = w`` days and published as the cumulative incidence
  ``1 - S(w)`` with the Greenwood standard error
  ``S(t) · sqrt(Σ d_i / (n_i (n_i - d_i)))`` and a symmetric 95% interval
  clipped to ``[0, 1]``. When every member at risk fails at some time,
  ``S`` is 0 from then on and the standard error is taken as 0 (the
  Greenwood sum is undefined there).

When every member is followed for ``w``, ``1 - S(w)`` equals the
fixed-window rate (no censoring enters the product). Times are compared
in microseconds, so an event exactly at the window's end counts, as the
window rule states. Every function is pure over the output of
``windows.first_outcomes``; values are rounded to six decimals at the
boundary only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Self

import numpy as np
import polars as pl

from judgemetrics.metrics.intervals import normal_interval, round6, wilson
from judgemetrics.metrics.registry import WINDOWS_DAYS
from judgemetrics.metrics.windows import FIRST_OUTCOME_AT, MEMBER_KEY, outcome_flags

MICROSECONDS_PER_DAY = 86_400 * 1_000_000
EVENT_US = "_event_us"
CENSOR_US = "_censor_us"


@dataclass(frozen=True, slots=True)
class WindowRate:
    """A fixed-window rate: the followed denominator, its numerator, the whole cohort."""

    window_days: int
    eligible: int
    followed: int
    numerator: int
    value: float | None
    lower: float | None
    upper: float | None


@dataclass(frozen=True, slots=True)
class SurvivalPoint:
    """The Kaplan-Meier cumulative incidence at one window."""

    window_days: int
    eligible: int
    events: int
    censored: int
    cumulative_incidence: float | None
    standard_error: float | None
    lower: float | None
    upper: float | None


def followed_flags(
    cohort: pl.DataFrame,
    coverage_end_exclusive_at: datetime,
    windows: tuple[int, ...] = WINDOWS_DAYS,
) -> pl.DataFrame:
    """One row per member and window: ``(member key, window_days, followed)``."""
    frames = [
        cohort.select(
            *MEMBER_KEY,
            pl.lit(window, dtype=pl.Int64).alias("window_days"),
            (
                pl.col("exposure_start") + pl.duration(days=window)
                < pl.lit(coverage_end_exclusive_at)
            ).alias("followed"),
        )
        for window in windows
    ]
    return pl.concat(frames)


def member_windows(
    cohort: pl.DataFrame,
    coverage_end_exclusive_at: datetime,
    windows: tuple[int, ...] = WINDOWS_DAYS,
) -> pl.DataFrame:
    """Per member and window: ``has_outcome``, ``followed``, and ``counted`` (both).

    ``cohort`` is the output of ``windows.first_outcomes``. ``counted`` is
    the numerator membership of the fixed-window rate; ``followed`` its
    denominator membership (the member rows Step 2 publishes).
    """
    flags = outcome_flags(cohort, windows).join(
        followed_flags(cohort, coverage_end_exclusive_at, windows),
        on=[*MEMBER_KEY, "window_days"],
        how="inner",
    )
    return flags.with_columns((pl.col("has_outcome") & pl.col("followed")).alias("counted"))


def fixed_window_rates(
    cohort: pl.DataFrame,
    coverage_end_exclusive_at: datetime,
    windows: tuple[int, ...] = WINDOWS_DAYS,
) -> list[WindowRate]:
    """The fixed-window rate per window over the followed members.

    One pass over the cohort: for each window the followed members (``exposure_start + w``
    inside the coverage) and, of those, the members whose first outcome is within the window
    are summed together (the same flags ``member_windows`` lists per member, without
    materializing a row per member and window).
    """
    eligible = cohort.height
    end = pl.lit(coverage_end_exclusive_at)
    sums: list[pl.Expr] = []
    for window in windows:
        reach = pl.col("exposure_start") + pl.duration(days=window)
        followed = reach < end
        outcome = pl.col(FIRST_OUTCOME_AT).is_not_null() & (pl.col(FIRST_OUTCOME_AT) <= reach)
        sums.append(followed.sum().alias(f"followed_{window}"))
        sums.append((followed & outcome.fill_null(False)).sum().alias(f"counted_{window}"))
    totals = cohort.select(sums).row(0, named=True) if windows else {}
    rates: list[WindowRate] = []
    for window in windows:
        followed_members = int(totals[f"followed_{window}"])
        numerator = int(totals[f"counted_{window}"])
        lower, upper = wilson(numerator, followed_members)
        rates.append(
            WindowRate(
                window_days=window,
                eligible=eligible,
                followed=followed_members,
                numerator=numerator,
                value=None if followed_members == 0 else round6(numerator / followed_members),
                lower=lower,
                upper=upper,
            )
        )
    return rates


@dataclass(frozen=True, slots=True)
class ProductLimit:
    """The product-limit curve of one cohort, evaluated at any time in O(log events).

    Built once from the cohort's durations and event flags with sorted arrays
    (``np.unique`` for the distinct event times and their failures, one
    ``searchsorted`` for the members at risk), the curve keeps the survival after
    each event time and the Greenwood sum up to it. ``np.cumprod`` and
    ``np.cumsum`` fold left to right, so every float is the one the plain loop
    ``S *= 1 - d / n``, ``G += d / (n (n - d))`` produces: the vectorized estimator
    equals the reference loop (kept in ``tests/unit/test_censoring_vectorized.py``
    as the oracle) bit for bit, not only to six decimals.
    """

    times: np.ndarray
    survival: np.ndarray
    greenwood: np.ndarray
    # The first event time at which every member at risk fails (``len(times)`` if none).
    exhausted: int

    @classmethod
    def fit(
        cls, durations: Sequence[int] | np.ndarray, events: Sequence[bool] | np.ndarray
    ) -> Self:
        """The curve of ``durations[i]`` ending in an event when ``events[i]``.

        Events at a time are counted before censorings at the same time, so a
        member censored at ``t_i`` is still at risk there.
        """
        spans = np.asarray(durations, dtype=np.int64)
        flags = np.asarray(events, dtype=np.bool_)
        if spans.shape != flags.shape:
            msg = "durations and events must align"
            raise ValueError(msg)
        times, failed = np.unique(spans[flags], return_counts=True)
        failed = failed.astype(np.int64)
        at_risk = spans.size - np.searchsorted(np.sort(spans), times, side="left")
        at_risk = at_risk.astype(np.int64)
        every = at_risk == failed
        exhausted = int(np.argmax(every)) if bool(every.any()) else int(times.size)
        # An exhausted time divides by zero below; no value from it onwards is read.
        survivors = np.where(every, 1, at_risk - failed)
        survival = np.cumprod(1.0 - failed / at_risk)
        greenwood = np.cumsum(failed / (at_risk * survivors))
        return cls(times=times, survival=survival, greenwood=greenwood, exhausted=exhausted)

    def at(self, time: int) -> tuple[float, float]:
        """``(S(time), Greenwood variance of S(time))``; ``(0.0, 0.0)`` once all at risk failed."""
        reached = int(np.searchsorted(self.times, time, side="right"))
        if self.exhausted < reached:
            return 0.0, 0.0
        if reached == 0:
            return 1.0, 0.0
        survival = float(self.survival[reached - 1])
        return survival, survival * survival * float(self.greenwood[reached - 1])


def product_limit(durations: Sequence[int], events: Sequence[bool], at: int) -> tuple[float, float]:
    """``(S(at), Greenwood variance of S(at))`` from durations and event flags.

    ``durations[i]`` is member ``i``'s time to its event or censoring in
    any common unit; ``events[i]`` whether it ended in an event. Events at
    a time are counted before censorings at the same time.
    """
    return ProductLimit.fit(durations, events).at(at)


def _durations(cohort: pl.DataFrame, coverage_end_exclusive_at: datetime) -> pl.DataFrame:
    """Per member: microseconds to the first outcome (or null) and to the coverage end."""
    return cohort.select(
        (pl.col(FIRST_OUTCOME_AT) - pl.col("exposure_start"))
        .dt.total_microseconds()
        .alias(EVENT_US),
        (pl.lit(coverage_end_exclusive_at) - pl.col("exposure_start"))
        .dt.total_microseconds()
        .alias(CENSOR_US),
    )


def kaplan_meier(
    cohort: pl.DataFrame,
    coverage_end_exclusive_at: datetime,
    windows: tuple[int, ...] = WINDOWS_DAYS,
) -> list[SurvivalPoint]:
    """The cumulative incidence ``1 - S(w)`` per window over the whole cohort.

    ``cohort`` is the output of ``windows.first_outcomes``. A member whose
    first outcome lies at or after the coverage end (a loader that keeps
    events beyond the window) is censored, not counted.
    """
    eligible = cohort.height
    if eligible == 0:
        return [SurvivalPoint(window, 0, 0, 0, None, None, None, None) for window in windows]
    table = _durations(cohort, coverage_end_exclusive_at)
    event_us = table[EVENT_US]
    censor_us = table[CENSOR_US]
    # A first outcome at or after the coverage end is a censoring, not an event.
    is_event = (event_us.is_not_null() & (event_us < censor_us)).fill_null(False).to_numpy()
    durations = np.where(is_event, event_us.fill_null(0).to_numpy(), censor_us.to_numpy())
    curve = ProductLimit.fit(durations, is_event)
    points: list[SurvivalPoint] = []
    for window in windows:
        at = window * MICROSECONDS_PER_DAY
        survival, variance = curve.at(at)
        incidence = 1.0 - survival
        standard_error = math.sqrt(variance)
        lower, upper = normal_interval(incidence, standard_error)
        points.append(
            SurvivalPoint(
                window_days=window,
                eligible=eligible,
                events=int(np.count_nonzero(is_event & (durations <= at))),
                censored=int(np.count_nonzero(~is_event & (durations < at))),
                cumulative_incidence=round6(incidence),
                standard_error=round6(standard_error),
                lower=lower,
                upper=upper,
            )
        )
    return points
