# tests/unit/test_censoring_vectorized.py
"""The vectorized product-limit estimator equals the reference loop it replaced.

``reference_product_limit`` is the Phase 3 implementation, kept here verbatim as
the oracle (O(event times x members) per call, plain Python); ``censoring.product_limit``
and ``ProductLimit`` are the sorted-array estimator the engine uses at corpus
scale. Ties (events before censorings), all-censored and all-failing cohorts, empty
cohorts, and negative durations (a start deferred past the coverage end) are the
cases the loop's rules were written for; ``tests/property/test_km_equivalence.py``
draws cohorts against the same oracle.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import numpy as np
import polars as pl
import pytest

from judgemetrics.metrics.censoring import (
    MICROSECONDS_PER_DAY,
    ProductLimit,
    kaplan_meier,
    product_limit,
)
from judgemetrics.metrics.intervals import normal_interval, round6
from judgemetrics.metrics.windows import FIRST_OUTCOME_AT

pytestmark = pytest.mark.unit

END = datetime(2024, 1, 1, tzinfo=UTC)
WINDOWS = (30, 90, 365)


def reference_product_limit(
    durations: Sequence[int], events: Sequence[bool], at: int
) -> tuple[float, float]:
    """The Phase 3 loop: ``(S(at), Greenwood variance of S(at))``, events before censorings."""
    if len(durations) != len(events):
        msg = "durations and events must align"
        raise ValueError(msg)
    event_times = sorted({t for t, is_event in zip(durations, events, strict=True) if is_event})
    survival = 1.0
    greenwood = 0.0
    for time_i in event_times:
        if time_i > at:
            break
        at_risk = sum(1 for t in durations if t >= time_i)
        failed = sum(
            1 for t, is_event in zip(durations, events, strict=True) if is_event and t == time_i
        )
        if at_risk == failed:
            return 0.0, 0.0
        survival *= 1.0 - failed / at_risk
        greenwood += failed / (at_risk * (at_risk - failed))
    return survival, survival * survival * greenwood


CASES: dict[str, tuple[list[int], list[bool]]] = {
    "empty": ([], []),
    "all censored": ([5, 9, 9, 12], [False, False, False, False]),
    "all failing": ([3, 3, 7, 7, 7], [True, True, True, True, True]),
    "ties, events before censorings": (
        [4, 4, 4, 8, 8, 10],
        [True, False, True, True, False, False],
    ),
    "one event": ([6], [True]),
    "last member fails alone": ([2, 5, 9], [False, False, True]),
    "negative durations": ([-4, -1, 0, 3, 3], [True, False, True, False, True]),
    "singleton censored": ([7], [False]),
}


@pytest.mark.parametrize("name", list(CASES))
def test_the_estimator_equals_the_reference_at_every_time(name: str) -> None:
    durations, events = CASES[name]
    curve = ProductLimit.fit(durations, events)
    for at in range(-6, 16):
        expected = reference_product_limit(durations, events, at)
        assert product_limit(durations, events, at) == expected, (name, at)
        assert curve.at(at) == expected, (name, at)


def test_all_failing_cohort_has_zero_survival_and_zero_variance() -> None:
    durations, events = CASES["all failing"]
    # Two of five fail at 3, so the curve is still positive there; the last three fail at 7.
    assert product_limit(durations, events, 3) == (0.6, 0.6 * 0.6 * (2 / (5 * 3)))
    assert product_limit(durations, events, 7) == (0.0, 0.0)
    assert product_limit(durations, events, 99) == (0.0, 0.0)


def test_the_curve_before_the_first_event_is_one() -> None:
    assert product_limit([5, 6], [True, False], 4) == (1.0, 0.0)


def test_misaligned_inputs_are_refused() -> None:
    with pytest.raises(ValueError, match="align"):
        product_limit([1, 2], [True], 1)


def _cohort(rows: list[tuple[int, int | None]]) -> pl.DataFrame:
    """Members as ``kaplan_meier`` reads them: exposure start and first outcome (days after)."""
    start = END - timedelta(days=400)
    return pl.DataFrame(
        {
            "exposure_start": [start + timedelta(days=offset) for offset, _ in rows],
            FIRST_OUTCOME_AT: [
                None if after is None else start + timedelta(days=offset + after)
                for offset, after in rows
            ],
        },
        schema={
            "exposure_start": pl.Datetime("us", "UTC"),
            FIRST_OUTCOME_AT: pl.Datetime("us", "UTC"),
        },
    )


def test_kaplan_meier_matches_the_reference_loop_on_a_cohort() -> None:
    members: list[tuple[int, int | None]] = [
        (0, 10),
        (0, 10),
        (5, None),
        (20, 80),
        (30, 340),
        (60, 500),  # an outcome after the coverage end: censored, not counted
        (390, None),  # too little follow-up for any window
        (399, 1),
    ]
    cohort = _cohort(members)
    points = kaplan_meier(cohort, END, WINDOWS)
    start = END - timedelta(days=400)
    durations: list[int] = []
    events: list[bool] = []
    for offset, after in members:
        censor = int((END - (start + timedelta(days=offset))).total_seconds() * 1_000_000)
        event = None if after is None else after * MICROSECONDS_PER_DAY
        if event is not None and event < censor:
            durations.append(event)
            events.append(True)
        else:
            durations.append(censor)
            events.append(False)
    for point in points:
        at = point.window_days * MICROSECONDS_PER_DAY
        survival, variance = reference_product_limit(durations, events, at)
        standard_error = math.sqrt(variance)
        lower, upper = normal_interval(1.0 - survival, standard_error)
        assert point.cumulative_incidence == round6(1.0 - survival)
        assert point.standard_error == round6(standard_error)
        assert (point.lower, point.upper) == (lower, upper)
        assert point.eligible == len(members)
        assert point.events == sum(
            1 for t, e in zip(durations, events, strict=True) if e and t <= at
        )
        assert point.censored == sum(
            1 for t, e in zip(durations, events, strict=True) if not e and t < at
        )


def test_an_empty_cohort_has_no_estimates() -> None:
    points = kaplan_meier(_cohort([]), END, WINDOWS)
    assert [p.cumulative_incidence for p in points] == [None, None, None]
    assert [p.eligible for p in points] == [0, 0, 0]


def test_a_cohort_in_which_everyone_fails_has_standard_error_zero() -> None:
    points = kaplan_meier(_cohort([(0, 5), (1, 5), (2, 5)]), END, WINDOWS)
    assert all(p.cumulative_incidence == 1.0 and p.standard_error == 0.0 for p in points)


def test_the_curve_is_built_from_numpy_arrays_without_python_loops_over_members() -> None:
    """A large cohort is a few array operations: it fits in a unit test's budget."""
    rng = np.random.default_rng(7)
    durations = rng.integers(1, 1_000, size=300_000)
    events = rng.random(300_000) < 0.4
    curve = ProductLimit.fit(durations, events)
    survival, variance = curve.at(500)
    assert 0.0 < survival < 1.0 and variance > 0.0
