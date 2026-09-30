# tests/unit/test_exposure_deferral.py
"""Any-term exposure deferral (methodology 0.2, Phase 3 finding 1.4) over hand-built frames.

``with_exposure`` moves an index event's exposure start past every
incarceration term ``[sentence_at, sentence_at + incarceration_days)`` of
the same person that contains it — in any case, for every index kind,
pretrial releases included — after the disposition kind's first step to
the end of its own case's term. The cases: a chain of two overlapping
terms, a pretrial release inside another case's term, a disposition whose
own term ends inside an earlier case's term, the half-open boundaries, a
term of another person, and no term at all; each against the truth
generator's independent ``deferred_start`` on the same terms.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

import polars as pl
import pytest

from judgemetrics.metrics.exposure import with_exposure
from judgemetrics.metrics.frame import SCHEMAS, Frame, resolve_dtype
from judgemetrics.metrics.index_events import (
    DISPOSITION,
    INDEX_COLUMNS,
    PRETRIAL_RELEASE,
    SENTENCE,
)
from judgemetrics.synthetic.truth import deferred_start

pytestmark = pytest.mark.unit

T0 = datetime(2020, 3, 2, 9, 0, tzinfo=UTC)
PERSON = "P1"
OTHER_PERSON = "P2"
# (id, case_id, person_id, sentence_at, incarceration_days)
SentenceRow = tuple[str, str, str, datetime, int | None]


def _at(days: int, hours: int = 0) -> datetime:
    return T0 + timedelta(days=days, hours=hours)


def _sentences(rows: Sequence[SentenceRow]) -> pl.DataFrame:
    """``(id, case_id, person_id, sentence_at, incarceration_days)`` rows as the frame table."""
    schema = {
        column: resolve_dtype(spec, pl.String()) for column, spec in SCHEMAS["sentences"].items()
    }
    return pl.DataFrame(
        [
            {
                "id": sentence_id,
                "case_id": case_id,
                "person_id": person_id,
                "judge_id": "J1",
                "sentence_at": sentence_at,
                "incarceration_days": days,
                "probation_days": None,
            }
            for sentence_id, case_id, person_id, sentence_at, days in rows
        ],
        schema=schema,
        orient="row",
    )


def _frame(rows: Sequence[SentenceRow]) -> Frame:
    empty = Frame.empty(date(2019, 1, 1), date(2023, 12, 31))
    return empty.replace(sentences=_sentences(rows))


def _index(rows: list[tuple[str, str, str, datetime]], kind: str) -> pl.DataFrame:
    member_kind = {PRETRIAL_RELEASE: "decision", DISPOSITION: "court_case", SENTENCE: "sentence"}
    return pl.DataFrame(
        [
            {
                "member_kind": member_kind[kind],
                "member_id": member_id,
                "case_id": case_id,
                "person_id": person_id,
                "index_at": index_at,
            }
            for member_id, case_id, person_id, index_at in rows
        ],
        schema={
            "member_kind": pl.String(),
            "member_id": pl.String(),
            "case_id": pl.String(),
            "person_id": pl.String(),
            "index_at": pl.Datetime("us", "UTC"),
        },
        orient="row",
    ).select(INDEX_COLUMNS)


def _one(frame: Frame, index: pl.DataFrame, kind: str) -> dict[str, Any]:
    result = with_exposure(frame, index, kind)
    assert result.height == index.height == 1
    row: dict[str, Any] = result.row(0, named=True)
    return row


def _terms(rows: Sequence[SentenceRow], person: str) -> list[Any]:
    return sorted(
        (at, at + timedelta(days=days), days)
        for _, _, who, at, days in rows
        if who == person and days is not None and days > 0
    )


def test_a_chain_of_two_overlapping_terms_defers_past_both() -> None:
    # A: [T0-10d, T0+20d); B (another case): [T0+15d, T0+75d). A release at T0 sits in A,
    # A's end sits in B, so exposure starts at B's end with both terms' days.
    sentences = [
        ("S-A", "C-A", PERSON, _at(-10), 30),
        ("S-B", "C-B", PERSON, _at(15), 60),
    ]
    row = _one(
        _frame(sentences),
        _index([("D1", "C-R", PERSON, _at(0))], PRETRIAL_RELEASE),
        PRETRIAL_RELEASE,
    )
    assert row["exposure_start"] == _at(75)
    assert row["deferral_days"] == 90
    assert (row["exposure_start"], row["deferral_days"]) == deferred_start(
        _at(0), _terms(sentences, PERSON)
    )


def test_a_pretrial_release_inside_another_cases_term_is_deferred() -> None:
    sentences = [("S-A", "C-A", PERSON, _at(-5), 40)]
    row = _one(
        _frame(sentences),
        _index([("D1", "C-R", PERSON, _at(2, 3))], PRETRIAL_RELEASE),
        PRETRIAL_RELEASE,
    )
    assert row["index_at"] == _at(2, 3)
    assert row["exposure_start"] == _at(35)
    assert row["deferral_days"] == 40


def test_a_release_outside_every_term_starts_at_the_index() -> None:
    sentences = [
        ("S-A", "C-A", PERSON, _at(-50), 10),  # ended before the release
        ("S-B", "C-B", PERSON, _at(5), 30),  # starts after the release
        ("S-C", "C-C", OTHER_PERSON, _at(-5), 40),  # another person's term
        ("S-D", "C-D", PERSON, _at(-5), None),  # no incarceration
    ]
    row = _one(
        _frame(sentences),
        _index([("D1", "C-R", PERSON, _at(0))], PRETRIAL_RELEASE),
        PRETRIAL_RELEASE,
    )
    assert row["exposure_start"] == _at(0)
    assert row["deferral_days"] is None


def test_terms_are_half_open() -> None:
    # A term starting exactly at the index contains it; one ending exactly there does not.
    starts = [("S-A", "C-A", PERSON, _at(0), 10)]
    row = _one(
        _frame(starts), _index([("D1", "C-R", PERSON, _at(0))], PRETRIAL_RELEASE), PRETRIAL_RELEASE
    )
    assert row["exposure_start"] == _at(10) and row["deferral_days"] == 10
    ends = [("S-A", "C-A", PERSON, _at(-10), 10)]
    row = _one(
        _frame(ends), _index([("D1", "C-R", PERSON, _at(0))], PRETRIAL_RELEASE), PRETRIAL_RELEASE
    )
    assert row["exposure_start"] == _at(0) and row["deferral_days"] is None


def test_a_disposition_takes_its_own_term_then_every_containing_term() -> None:
    # The disposition at T0; its case's sentence at T0+10d for 20 days ends at T0+30d,
    # inside an earlier case's term [T0-100d, T0+100d): exposure starts at T0+100d.
    sentences = [
        ("S-OWN", "C-1", PERSON, _at(10), 20),
        ("S-EARLY", "C-0", PERSON, _at(-100), 200),
    ]
    row = _one(
        _frame(sentences), _index([("C-1", "C-1", PERSON, _at(0))], DISPOSITION), DISPOSITION
    )
    assert row["exposure_start"] == _at(100)
    assert row["deferral_days"] == 220
    without_other = _one(
        _frame(sentences[:1]),
        _index([("C-1", "C-1", PERSON, _at(0))], DISPOSITION),
        DISPOSITION,
    )
    assert without_other["exposure_start"] == _at(30)  # the Phase 3 rule, unchanged
    assert without_other["deferral_days"] == 20


def test_a_sentence_takes_its_own_term_and_the_chain_after_it() -> None:
    sentences = [
        ("S-1", "C-1", PERSON, _at(0), 30),
        ("S-2", "C-2", PERSON, _at(20), 30),
    ]
    row = _one(_frame(sentences), _index([("S-1", "C-1", PERSON, _at(0))], SENTENCE), SENTENCE)
    assert row["exposure_start"] == _at(50)
    assert row["deferral_days"] == 60
    assert (row["exposure_start"], row["deferral_days"]) == deferred_start(
        _at(0), _terms(sentences, PERSON)
    )


def test_the_order_of_rows_and_the_empty_cohort_are_kept() -> None:
    sentences = [("S-A", "C-A", PERSON, _at(-5), 40)]
    index = _index(
        [
            ("D2", "C-R2", OTHER_PERSON, _at(1)),
            ("D1", "C-R", PERSON, _at(0)),
        ],
        PRETRIAL_RELEASE,
    )
    result = with_exposure(_frame(sentences), index, PRETRIAL_RELEASE)
    assert result["member_id"].to_list() == ["D2", "D1"]
    assert result["exposure_start"].to_list() == [_at(1), _at(35)]
    empty = with_exposure(_frame(sentences), index.clear(), PRETRIAL_RELEASE)
    assert empty.height == 0
    assert empty.columns == [*INDEX_COLUMNS, "exposure_start", "deferral_days"]
