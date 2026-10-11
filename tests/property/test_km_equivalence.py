# tests/property/test_km_equivalence.py
"""The vectorized Kaplan-Meier estimator equals the reference loop on drawn cohorts.

Hypothesis draws cohorts with heavy ties (few distinct durations), all-censored
and all-failing members, empty cohorts, and negative durations, and evaluates the
curve at times before, at, and after every duration. The estimator must equal the
Phase 3 loop (``tests/unit/test_censoring_vectorized.reference_product_limit``) to
six decimals; it is in fact bit-identical (the vectorized folds run left to right),
which the first assertion states.
"""

from __future__ import annotations

import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from judgemetrics.metrics.censoring import ProductLimit, product_limit
from judgemetrics.metrics.intervals import round6
from tests.unit.test_censoring_vectorized import reference_product_limit

pytestmark = pytest.mark.property

# Few distinct values force ties; the range includes negatives (deferred starts).
DURATIONS = st.integers(min_value=-5, max_value=12)
COHORTS = st.lists(st.tuples(DURATIONS, st.booleans()), min_size=0, max_size=40)
ALL_FAIL = st.lists(st.tuples(DURATIONS, st.just(True)), min_size=1, max_size=20)
ALL_CENSORED = st.lists(st.tuples(DURATIONS, st.just(False)), min_size=1, max_size=20)


def _split(cohort: list[tuple[int, bool]]) -> tuple[list[int], list[bool]]:
    return [duration for duration, _ in cohort], [event for _, event in cohort]


def _agrees(cohort: list[tuple[int, bool]]) -> None:
    durations, events = _split(cohort)
    curve = ProductLimit.fit(durations, events)
    for at in range(-7, 15):
        survival, variance = curve.at(at)
        expected_survival, expected_variance = reference_product_limit(durations, events, at)
        assert (survival, variance) == (expected_survival, expected_variance), (cohort, at)
        assert product_limit(durations, events, at) == (expected_survival, expected_variance)
        assert round6(1.0 - survival) == round6(1.0 - expected_survival)
        assert round6(math.sqrt(variance)) == round6(math.sqrt(expected_variance))


@given(COHORTS)
def test_the_estimator_equals_the_reference_on_any_cohort(cohort: list[tuple[int, bool]]) -> None:
    _agrees(cohort)


@given(ALL_FAIL)
def test_a_cohort_that_all_fails_collapses_to_zero(cohort: list[tuple[int, bool]]) -> None:
    _agrees(cohort)
    durations, events = _split(cohort)
    assert product_limit(durations, events, max(durations)) == (0.0, 0.0)


@given(ALL_CENSORED)
def test_a_cohort_that_is_all_censored_never_leaves_one(cohort: list[tuple[int, bool]]) -> None:
    _agrees(cohort)
    durations, events = _split(cohort)
    assert product_limit(durations, events, max(durations) + 1) == (1.0, 0.0)


@given(COHORTS)
def test_survival_never_increases_and_its_variance_is_not_negative(
    cohort: list[tuple[int, bool]],
) -> None:
    durations, events = _split(cohort)
    curve = ProductLimit.fit(durations, events)
    previous = 1.0
    for at in range(-7, 15):
        survival, variance = curve.at(at)
        assert 0.0 <= survival <= previous
        assert variance >= 0.0
        previous = survival
