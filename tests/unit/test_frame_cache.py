# tests/unit/test_frame_cache.py
"""A frame's derived tables are built once, and a replaced frame starts afresh.

``Frame.derived(key, build)`` keeps a table that is a pure function of the frame (the disposed
charges, the case dispositions, the incarceration terms, a court's cases, the lead offense of each
case, the persons of each case) so computing a corpus's subjects does not rebuild it per subject
and definition. The cache is invisible: frames compare equal, and a frame built by ``replace``
shares nothing with the frame it came from, so a table derived from the old rows is never read
against the new ones.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import polars as pl
import pytest

from judgemetrics.metrics.attribution import court_case_ids
from judgemetrics.metrics.compute import _case_persons, lead_categories
from judgemetrics.metrics.exposure import incarceration_terms
from judgemetrics.metrics.frame import Frame
from judgemetrics.metrics.index_events import (
    case_dispositions,
    disposed_case_persons,
    disposed_cases,
    disposed_charges,
)

pytestmark = pytest.mark.unit

AT = datetime(2020, 5, 1, tzinfo=UTC)


def _frame() -> Frame:
    frame = Frame.empty(date(2019, 1, 1), date(2021, 12, 31))
    cases = pl.DataFrame(
        {
            "id": ["c1", "c2"],
            "court_id": ["k1", "k2"],
            "filed_at": [AT, AT],
            "closed_at": [None, None],
            "status": ["closed", "open"],
            "case_type": ["felony", "felony"],
        },
        schema=frame.cases.schema,
    )
    charges = pl.DataFrame(
        {
            "id": ["h1", "h2"],
            "case_id": ["c1", "c1"],
            "person_id": ["p1", "p2"],
            "filed_at": [AT, AT],
            "disposed_at": [AT, AT],
            "disposition": ["convicted_plea", "dismissed"],
            "disposition_actor": ["judge", "prosecutor"],
            "offense_category": ["drug", "property"],
            "severity": ["felony_3", "misdemeanor_a"],
            "source_row_id": ["1", "2"],
            "judge_id": ["j1", "j1"],
        },
        schema=frame.charges.schema,
    )
    return frame.replace(cases=cases, charges=charges)


def test_a_derived_table_is_built_once_and_shared() -> None:
    frame = _frame()
    builds: list[int] = []

    def build() -> pl.DataFrame:
        builds.append(1)
        return frame.cases.select("id")

    first = frame.derived("probe", build)
    second = frame.derived("probe", build)
    assert first is second and len(builds) == 1


def test_the_derived_tables_are_the_same_object_on_every_call() -> None:
    frame = _frame()
    for function in (
        disposed_charges,
        case_dispositions,
        disposed_cases,
        disposed_case_persons,
        incarceration_terms,
        lead_categories,
        _case_persons,
    ):
        assert function(frame) is function(frame), function.__name__
    assert court_case_ids(frame, "k1") is court_case_ids(frame, "k1")
    assert court_case_ids(frame, "k1") is not court_case_ids(frame, "k2")


def test_the_derived_tables_have_the_values_the_definition_gives() -> None:
    frame = _frame()
    assert disposed_charges(frame)["id"].to_list() == ["h1", "h2"]
    assert case_dispositions(frame).to_dicts() == [
        {"case_id": "c1", "disposition_at": AT, "disposing_judge_id": "j1"}
    ]
    assert disposed_cases(frame)["id"].to_list() == ["c1"]
    assert sorted(disposed_case_persons(frame)["person_id"].to_list()) == ["p1", "p2"]
    assert lead_categories(frame).to_dicts() == [{"case_id": "c1", "_lead_category": "drug"}]
    assert court_case_ids(frame, "k1")["case_id"].to_list() == ["c1"]
    assert incarceration_terms(frame).height == 0


def test_a_replaced_frame_starts_with_an_empty_cache() -> None:
    frame = _frame()
    assert disposed_charges(frame).height == 2
    replaced = frame.replace(charges=frame.charges.head(1))
    assert disposed_charges(replaced).height == 1
    assert disposed_charges(frame).height == 2
    assert (
        "disposed_charges" not in replaced._derived
        or replaced._derived["disposed_charges"].height == 1
    )
