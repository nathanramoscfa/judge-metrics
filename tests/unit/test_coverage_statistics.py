# tests/unit/test_coverage_statistics.py
"""Coverage statistics over a hand-built frame: every definition, the unknown share, the scopes.

Two courts in two jurisdictions and four cases: C1 is judged, disposed, and fully
classified; C2 names no judge, has only a pending charge, and an unclassified
one; C3 has no charge, decision, or sentence at all (no defendant); C4 is filed
too late in the window for a year of follow-up. Each statistic of
``metrics.coverage`` is checked per source, jurisdiction, and court, with the
share at six decimals, and a recompute that differs is reported by scope and
name.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import polars as pl
import pytest

from judgemetrics.metrics.coverage import (
    ADEQUATE_FOLLOW_UP_DAYS,
    DEFINITIONS,
    STATISTICS,
    CoverageDraft,
    StoredStatistic,
    compare_statistics,
    frame_statistics,
    share,
)
from judgemetrics.metrics.frame import SCHEMAS, Frame, resolve_dtype

pytestmark = pytest.mark.unit

SOURCE = "source-1"


def _at(month: int, day: int = 1, hour: int = 9) -> datetime:
    return datetime(2020, month, day, hour, tzinfo=UTC)


def _table(name: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {column: resolve_dtype(spec, pl.String()) for column, spec in SCHEMAS[name].items()}
    return pl.DataFrame(rows, schema=schema, orient="row")


def _charge(charge_id: str, case_id: str, **values: Any) -> dict[str, Any]:
    row = {
        "id": charge_id,
        "case_id": case_id,
        "person_id": "P1",
        "filed_at": _at(1, 2),
        "disposed_at": None,
        "disposition": None,
        "disposition_actor": None,
        "offense_category": "drug",
        "severity": "felony_3",
        "source_row_id": charge_id,
        "judge_id": None,
    }
    row.update(values)
    return row


def _decision(decision_id: str, case_id: str, actor: str, judge: str | None) -> dict[str, Any]:
    return {
        "id": decision_id,
        "case_id": case_id,
        "person_id": "P1",
        "judge_id": judge,
        "decision_type": "pretrial_release",
        "decision_at": _at(1, 3),
        "actor_type": actor,
        "discretion": "discretionary" if actor == "judge" else "unknown",
        "release_at": None,
        "detained_flag": True,
        "release_type": "detained",
    }


@pytest.fixture
def frame() -> Frame:
    base = Frame.empty(date(2020, 1, 1), date(2021, 6, 30))
    cases = _table(
        "cases",
        [
            {
                "id": case_id,
                "court_id": court,
                "filed_at": filed,
                "closed_at": None,
                "status": "open",
                "case_type": "felony",
            }
            for case_id, court, filed in (
                ("C1", "K1", _at(1, 1, 0)),
                ("C2", "K1", _at(2, 1, 0)),
                ("C3", "K2", _at(3, 1, 0)),
                ("C4", "K2", datetime(2021, 3, 1, tzinfo=UTC)),
            )
        ],
    )
    charges = _table(
        "charges",
        [
            # C1: disposed by a recorded judge (final), classified.
            _charge(
                "H1",
                "C1",
                disposed_at=_at(4),
                disposition="dismissed",
                disposition_actor="judge",
                judge_id="J1",
            ),
            # C1: a final disposition whose actor the source does not record.
            _charge("H2", "C1", disposed_at=_at(4), disposition="convicted_plea"),
            # C2: pending (not final) and unclassified.
            _charge("H3", "C2", disposition="pending", offense_category="unclassified"),
            # C4: superseded (not final), classified.
            _charge(
                "H4",
                "C4",
                disposed_at=datetime(2021, 4, 1, tzinfo=UTC),
                disposition="superseded",
                severity="unclassified",
            ),
        ],
    )
    decisions = _table(
        "decisions",
        [_decision("D1", "C1", "judge", "J1"), _decision("D2", "C2", "unknown", None)],
    )
    courts = _table(
        "courts",
        [{"id": "K1", "jurisdiction_id": "JA"}, {"id": "K2", "jurisdiction_id": "JB"}],
    )
    return base.replace(
        cases=cases,
        charges=charges,
        decisions=decisions,
        courts=courts,
        persons=_table("persons", [{"id": "P1"}]),
    )


def _by_scope(drafts: list[CoverageDraft]) -> dict[tuple[str, str], dict[str, tuple[int, int]]]:
    table: dict[tuple[str, str], dict[str, tuple[int, int]]] = {}
    for draft in drafts:
        table.setdefault((draft.scope_type, draft.scope_id), {})[draft.statistic] = (
            draft.numerator,
            draft.denominator,
        )
    return table


def test_every_statistic_is_defined_and_computed_for_every_scope(frame: Frame) -> None:
    assert tuple(DEFINITIONS) == STATISTICS
    drafts = frame_statistics(frame, SOURCE)
    table = _by_scope(drafts)
    assert set(table) == {
        ("source", SOURCE),
        ("jurisdiction", "JA"),
        ("jurisdiction", "JB"),
        ("court", "K1"),
        ("court", "K2"),
    }
    for statistics in table.values():
        assert tuple(statistics) == STATISTICS
    assert all(draft.source_id == SOURCE for draft in drafts)


def test_each_definition_over_the_hand_built_frame(frame: Frame) -> None:
    source = _by_scope(frame_statistics(frame, SOURCE))[("source", SOURCE)]
    # C1 names a judge (assignment-free: its charge and decision carry J1).
    assert source["cases_with_identified_judge"] == (1, 4)
    # Only C1 has a final, dated disposition: pending and superseded dispose of nothing.
    assert source["cases_with_final_disposition"] == (1, 4)
    # C3 has no defendant row at all.
    assert source["cases_with_person_resolution"] == (3, 4)
    # C1 disposed in April 2020, C2/C3 filed early 2020: a year before 2021-07-01;
    # C4 filed 2021-03-01 is not.
    assert source["cases_with_adequate_follow_up"] == (3, 4)
    # Of the cases with a charge (C1, C2, C4), only C1 is fully classified.
    assert source["cases_with_complete_charge_classification"] == (1, 3)
    # Every case-level row: 4 cases, 4 charges, 2 decisions.
    assert source["records_with_provenance"] == (10, 10)
    # Unknown actors: D2 among two decisions, H2 among the two final dispositions.
    assert source["unknown_actor_share"] == (2, 4)
    assert ADEQUATE_FOLLOW_UP_DAYS == 365


def test_the_jurisdiction_and_court_scopes_split_the_source(frame: Frame) -> None:
    table = _by_scope(frame_statistics(frame, SOURCE))
    assert table[("court", "K1")]["cases_with_identified_judge"] == (1, 2)
    assert table[("court", "K2")]["cases_with_identified_judge"] == (0, 2)
    assert table[("court", "K2")]["cases_with_complete_charge_classification"] == (0, 1)
    assert table[("jurisdiction", "JA")] == table[("court", "K1")]
    assert table[("jurisdiction", "JB")] == table[("court", "K2")]
    # The scopes add up to the source.
    source = table[("source", SOURCE)]
    for statistic in STATISTICS:
        numerators = sum(table[("court", court)][statistic][0] for court in ("K1", "K2"))
        denominators = sum(table[("court", court)][statistic][1] for court in ("K1", "K2"))
        assert (numerators, denominators) == source[statistic], statistic


def test_the_share_is_six_decimals_and_null_without_a_denominator() -> None:
    assert share(1, 3) == Decimal("0.333333")
    assert share(2, 3) == Decimal("0.666667")
    assert share(0, 0) is None
    draft = CoverageDraft(SOURCE, "source", SOURCE, "unknown_actor_share", 1, 8)
    assert draft.share == Decimal("0.125000")


def test_a_tampered_statistic_is_reported_by_scope_and_name(frame: Frame) -> None:
    drafts = frame_statistics(frame, SOURCE)
    stored = [
        StoredStatistic(
            source_id=d.source_id,
            scope_type=d.scope_type,
            scope_id=d.scope_id,
            statistic=d.statistic,
            numerator=d.numerator,
            denominator=d.denominator,
            share=d.share,
            methodology_version="1.1",
        )
        for d in drafts
    ]
    assert compare_statistics("h" * 64, stored, drafts) == []
    tampered = list(stored)
    index = next(
        i
        for i, item in enumerate(tampered)
        if (item.scope_type, item.scope_id, item.statistic)
        == ("court", "K1", "cases_with_final_disposition")
    )
    original = tampered[index]
    tampered[index] = StoredStatistic(
        original.source_id,
        original.scope_type,
        original.scope_id,
        original.statistic,
        original.numerator + 1,
        original.denominator,
        original.share,
        original.methodology_version,
    )
    found = compare_statistics("h" * 64, tampered, drafts)
    assert [(m.scope_type, m.scope_id, m.statistic, m.column) for m in found] == [
        ("court", "K1", "cases_with_final_disposition", "numerator")
    ]
    # A statistic the store lacks, and one the recompute no longer produces.
    missing = compare_statistics("h" * 64, stored[1:], drafts)
    assert [(m.column, m.stored, m.recomputed) for m in missing] == [
        ("statistic", "absent", "present")
    ]
    extra = compare_statistics("h" * 64, stored, drafts[1:])
    assert [(m.column, m.stored, m.recomputed) for m in extra] == [
        ("statistic", "present", "absent")
    ]


def test_no_definition_names_a_person_or_a_restricted_attribute() -> None:
    text = " ".join(DEFINITIONS.values()).lower()
    for word in ("person_id", "participant", "race", "gender", "age band", "name of"):
        assert word not in text, word
