# tests/property/test_period_consistency.py
"""Calendar-year observations agree with the whole window (registry version 3, Phase 5 Step 5).

For a Hypothesis-drawn seed the ``TINY`` world is built in memory and every
descriptive metric computed for every judge and court (``compute_frame``).
Per metric, subject, window, and dimension value:

- every year observation's period is that calendar year's first and last days,
  the year lies within the coverage window's years, and it holds at least one
  member (a year without an anchor publishes nothing);
- the years' members partition the whole window's — the same multiset of
  ``(kind, id, counted, followed)`` — for every kind (Kaplan-Meier estimates and
  medians included: their members are their rows; for a median, the rows with a
  value, since a category is published in a year only when the year has one);
- the years' counts, share numerators and denominators, distribution counts,
  and fixed-window eligible, followed, and counted totals add up to the whole
  window's. A distinct count of persons (``eligible_defendants``), a
  Kaplan-Meier estimate, and a median do not add and are left out.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date
from typing import Any

import pytest
from hypothesis import given

from judgemetrics.metrics.compute import ObservationDraft, compute_frame
from judgemetrics.metrics.registry import load_registry
from judgemetrics.synthetic.config import TINY
from tests.property.support import build_world, frame_from_world, seeds

pytestmark = pytest.mark.property

REGISTRY = load_registry()
# Figures that do not add across years (a distinct count, an estimate, a median).
NOT_ADDITIVE_KINDS = frozenset({"survival", "median"})
NOT_ADDITIVE_SLUGS = frozenset({"eligible_defendants"})

GroupKey = tuple[str, str, str, int | None, str | None]


def _groups(drafts: list[ObservationDraft]) -> dict[GroupKey, dict[str, Any]]:
    groups: dict[GroupKey, dict[str, Any]] = defaultdict(lambda: {"whole": None, "years": []})
    for draft in drafts:
        key = (
            draft.slug,
            draft.subject_type,
            draft.subject_id,
            draft.window_days,
            draft.dimension_value,
        )
        if draft.calendar_year is None:
            assert groups[key]["whole"] is None, key
            groups[key]["whole"] = draft
        else:
            groups[key]["years"].append(draft)
    return groups


@given(seed=seeds)
def test_every_year_agrees_with_the_whole_window(seed: int) -> None:
    frame = frame_from_world(build_world(seed, TINY), TINY)
    result = compute_frame(frame, REGISTRY, "synthetic")
    first, last = frame.coverage_start.year, frame.coverage_end.year
    for key, group in _groups(result.drafts).items():
        whole: ObservationDraft | None = group["whole"]
        years: list[ObservationDraft] = group["years"]
        slug = key[0]
        kind = REGISTRY[slug].kind
        if whole is None:
            # A year never publishes what the whole window does not.
            assert not years, key
            continue
        seen: set[int] = set()
        for draft in years:
            year = draft.calendar_year
            assert year is not None and first <= year <= last, (key, year)
            assert year not in seen, (key, year)
            seen.add(year)
            assert (draft.period_start, draft.period_end) == (
                date(year, 1, 1),
                date(year, 12, 31),
            ), key
            assert draft.members, (key, year)
        # The years partition the whole window's members, flags included. A median by
        # category publishes a category in a year only when the year holds a value for
        # it (the whole window's rule), so its rows without a value may fall in no year.
        keep = (lambda m: m.followed) if kind == "median" else (lambda m: True)
        yearly = Counter(m.as_tuple() for draft in years for m in draft.members if keep(m))
        assert yearly == Counter(m.as_tuple() for m in whole.members if keep(m)), key
        if kind in NOT_ADDITIVE_KINDS:
            continue
        assert sum(d.eligible_count for d in years) == whole.eligible_count, key
        assert sum(d.cohort_size for d in years) == whole.cohort_size, key
        if slug not in NOT_ADDITIVE_SLUGS:
            assert sum(d.observed_count for d in years) == whole.observed_count, key


@given(seed=seeds)
def test_the_adjusted_kind_and_nothing_else_is_whole_window_only(seed: int) -> None:
    frame = frame_from_world(build_world(seed, TINY), TINY)
    result = compute_frame(frame, REGISTRY, "synthetic")
    kinds_with_years = {REGISTRY[d.slug].kind for d in result.drafts if d.calendar_year is not None}
    assert kinds_with_years <= REGISTRY.periods.calendar_year_kinds
    assert "observed_expected" not in kinds_with_years
    # Every descriptive metric with a whole-window member also publishes its years.
    with_members = {
        (d.slug, d.subject_type, d.subject_id)
        for d in result.drafts
        if d.calendar_year is None and d.members
    }
    with_years = {
        (d.slug, d.subject_type, d.subject_id) for d in result.drafts if d.calendar_year is not None
    }
    assert with_members <= with_years
