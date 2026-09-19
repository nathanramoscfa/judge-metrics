# tests/unit/test_attribution.py
"""The attribution gate over hand-built frames: every assignment gate, and the two exclusions.

``deciding_judge`` keeps decisions whose judge is the subject;
``assigned_at_time`` keeps rows whose time falls in one of the subject's
assignment intervals on the case (start inclusive, end exclusive, a null
end open); ``assigned_ever`` keeps rows of cases with any assignment of
the subject; ``sentencing_judge`` keeps sentences whose judge is the
subject; ``court_of_case`` keeps rows of the court's cases and is what a
court subject always gets. A statutory release and an unknown-actor
decision are never attributed to a judge, whatever the rule admits, and
the court-level helpers count them explicitly.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

from judgemetrics.metrics.attribution import (
    AttributionError,
    AttributionRule,
    Subject,
    attributed_cases,
    attributed_charges,
    attributed_decisions,
    attributed_sentences,
    pretrial_decisions_for,
    statutory_releases,
    unknown_actor_pretrial_decisions,
)
from judgemetrics.metrics.frame import SCHEMAS, Frame, FrameError, resolve_dtype
from judgemetrics.metrics.registry import load_registry

pytestmark = pytest.mark.unit


def _at(day: int, hour: int = 9) -> datetime:
    return datetime(2020, 1, day, hour, tzinfo=UTC)


def _table(name: str, rows: list[dict[str, Any]]) -> pl.DataFrame:
    schema = {column: resolve_dtype(spec, pl.String()) for column, spec in SCHEMAS[name].items()}
    return pl.DataFrame(rows, schema=schema, orient="row")


def _decision(
    decision_id: str,
    case_id: str,
    judge_id: str | None,
    *,
    actor: str = "judge",
    discretion: str = "discretionary",
    detained: bool | None = False,
    at: datetime | None = None,
    decision_type: str = "pretrial_release",
) -> dict[str, Any]:
    at = at or _at(5)
    return {
        "id": decision_id,
        "case_id": case_id,
        "person_id": "P1",
        "judge_id": judge_id,
        "decision_type": decision_type,
        "decision_at": at,
        "actor_type": actor,
        "discretion": discretion,
        "release_at": None if detained else at,
        "detained_flag": detained,
        "release_type": "detained" if detained else "recognizance",
    }


@pytest.fixture
def frame() -> Frame:
    """Two courts, two judges, three cases with assignment intervals, decisions, charges, sentences.

    Case C1 (court K1): J1 assigned days 1-10 (end exclusive), then J2 from
    day 10 open-ended. Case C2 (court K1): J2 for the whole case. Case C3
    (court K2): J1 open-ended.
    """
    base = Frame.empty(date(2020, 1, 1), date(2020, 12, 31), frozenset({"new_case"}))
    cases = _table(
        "cases",
        [
            {
                "id": case_id,
                "court_id": court,
                "filed_at": _at(1, 0),
                "closed_at": None,
                "status": "open",
                "case_type": "felony",
            }
            for case_id, court in (("C1", "K1"), ("C2", "K1"), ("C3", "K2"))
        ],
    )
    assignments = _table(
        "assignments",
        [
            {"case_id": "C1", "judge_id": "J1", "start_at": _at(1), "end_at": _at(10)},
            {"case_id": "C1", "judge_id": "J2", "start_at": _at(10), "end_at": None},
            {"case_id": "C2", "judge_id": "J2", "start_at": _at(1), "end_at": None},
            {"case_id": "C3", "judge_id": "J1", "start_at": _at(1), "end_at": None},
        ],
    )
    decisions = _table(
        "decisions",
        [
            _decision("D1", "C1", "J1"),
            _decision("D2", "C2", "J2", detained=True),
            _decision("D3", "C3", "J1"),
            # A statutory release in C1: never a judge's, counted by the court.
            _decision(
                "D4",
                "C1",
                None,
                actor="legislature_or_mandatory_rule",
                discretion="mandatory",
                at=_at(6),
            ),
            # A decision whose actor the source does not identify.
            _decision("D5", "C2", None, actor="unknown", discretion="unknown", at=_at(7)),
            # A non-pretrial decision of J1 (excluded by decision_type).
            _decision("D6", "C1", "J1", decision_type="dismissal", detained=None, at=_at(8)),
        ],
    )
    charges = _table(
        "charges",
        [
            {
                "id": charge_id,
                "case_id": case_id,
                "person_id": "P1",
                "filed_at": _at(1),
                "disposed_at": disposed_at,
                "disposition": disposition,
                "disposition_actor": actor,
                "offense_category": "drug",
                "severity": "felony_3",
                "source_row_id": charge_id,
            }
            for charge_id, case_id, disposed_at, disposition, actor in (
                ("H1", "C1", _at(9), "dismissed", "judge"),  # inside J1's interval
                ("H2", "C1", _at(10), "convicted_plea", "judge"),  # J1's end is exclusive
                ("H3", "C1", _at(20), "dismissed", "prosecutor"),  # J2's open interval
                ("H4", "C2", None, "pending", None),  # no disposition time
                ("H5", "C3", _at(15), "acquitted", "jury"),
            )
        ],
    )
    sentences = _table(
        "sentences",
        [
            {
                "id": sentence_id,
                "case_id": case_id,
                "person_id": "P1",
                "judge_id": judge_id,
                "sentence_at": _at(25),
                "incarceration_days": 30,
                "probation_days": None,
            }
            for sentence_id, case_id, judge_id in (("S1", "C1", "J2"), ("S2", "C3", "J1"))
        ],
    )
    return base.replace(
        cases=cases,
        assignments=assignments,
        decisions=decisions,
        charges=charges,
        sentences=sentences,
        persons=_table("persons", [{"id": "P1"}]),
    )


PRETRIAL = AttributionRule(
    decision_type="pretrial_release",
    actor_types=frozenset({"judge"}),
    discretion=frozenset({"discretionary"}),
    assignment_gate="deciding_judge",
)


def _ids(rows: pl.DataFrame, column: str = "id") -> list[str]:
    return sorted(rows[column].to_list())


def test_deciding_judge_keeps_the_subjects_own_pretrial_decisions(frame: Frame) -> None:
    assert _ids(attributed_decisions(frame, PRETRIAL, Subject("judge", "J1"))) == ["D1", "D3"]
    assert _ids(attributed_decisions(frame, PRETRIAL, Subject("judge", "J2"))) == ["D2"]
    assert _ids(pretrial_decisions_for(frame, "judge", "J1", PRETRIAL)) == ["D1", "D3"]
    # A rule without a decision type is narrowed to pretrial releases.
    assert _ids(
        pretrial_decisions_for(
            frame, "judge", "J1", AttributionRule(assignment_gate="deciding_judge")
        )
    ) == [
        "D1",
        "D3",
    ]
    with pytest.raises(AttributionError, match="not pretrial_release"):
        pretrial_decisions_for(frame, "judge", "J1", AttributionRule(decision_type="dismissal"))


def test_court_of_case_is_what_a_court_subject_always_gets(frame: Frame) -> None:
    court = Subject("court", "K1")
    assert _ids(attributed_decisions(frame, PRETRIAL, court)) == ["D1", "D2"]
    assert _ids(attributed_decisions(frame, PRETRIAL, Subject("court", "K2"))) == ["D3"]
    # A court subject ignores the judge gate the rule names.
    at_time = AttributionRule(assignment_gate="assigned_at_time")
    assert _ids(attributed_charges(frame, at_time, court)) == ["H1", "H2", "H3", "H4"]
    assert _ids(attributed_sentences(frame, at_time, court)) == ["S1"]
    assert _ids(attributed_cases(frame, at_time, court)) == ["C1", "C2"]
    with pytest.raises(AttributionError, match="cannot attribute rows to a judge"):
        attributed_charges(
            frame, AttributionRule(assignment_gate="court_of_case"), Subject("judge", "J1")
        )


def test_assigned_at_time_uses_the_interval_start_inclusive_end_exclusive(frame: Frame) -> None:
    rule = AttributionRule(assignment_gate="assigned_at_time")
    # H1 at day 9 is J1's; H2 at day 10 is exactly J1's end and therefore J2's;
    # H3 at day 20 is J2's open interval; H4 has no disposition time.
    assert _ids(attributed_charges(frame, rule, Subject("judge", "J1"))) == ["H1", "H5"]
    assert _ids(attributed_charges(frame, rule, Subject("judge", "J2"))) == ["H2", "H3"]
    # Cases gated at a caller-supplied time column.
    timed = frame.cases.with_columns(pl.lit(_at(12)).alias("at"))
    assert _ids(
        attributed_cases(frame, rule, Subject("judge", "J1"), rows=timed, time_column="at")
    ) == ["C3"]
    assert _ids(
        attributed_cases(frame, rule, Subject("judge", "J2"), rows=timed, time_column="at")
    ) == [
        "C1",
        "C2",
    ]
    with pytest.raises(AttributionError, match="needs a time column"):
        attributed_cases(frame, rule, Subject("judge", "J1"))


def test_assigned_ever_keeps_cases_with_any_assignment_of_the_subject(frame: Frame) -> None:
    rule = AttributionRule(assignment_gate="assigned_ever")
    assert _ids(attributed_cases(frame, rule, Subject("judge", "J1"))) == ["C1", "C3"]
    assert _ids(attributed_cases(frame, rule, Subject("judge", "J2"))) == ["C1", "C2"]
    assert _ids(attributed_charges(frame, rule, Subject("judge", "J1"))) == ["H1", "H2", "H3", "H5"]


def test_sentencing_judge_keeps_the_subjects_sentences(frame: Frame) -> None:
    rule = AttributionRule(assignment_gate="sentencing_judge")
    assert _ids(attributed_sentences(frame, rule, Subject("judge", "J1"))) == ["S2"]
    assert _ids(attributed_sentences(frame, rule, Subject("judge", "J2"))) == ["S1"]


def test_a_statutory_release_is_never_attributed_to_a_judge(frame: Frame) -> None:
    permissive = AttributionRule(decision_type="pretrial_release", assignment_gate="deciding_judge")
    for judge in ("J1", "J2"):
        rows = attributed_decisions(frame, permissive, Subject("judge", judge))
        assert "legislature_or_mandatory_rule" not in rows["actor_type"].to_list()
        assert "mandatory" not in rows["discretion"].to_list()
    # Even a rule that admits the statutory actor explicitly.
    admitting = AttributionRule(
        decision_type="pretrial_release",
        actor_types=frozenset({"judge", "legislature_or_mandatory_rule"}),
        assignment_gate="deciding_judge",
    )
    assert _ids(attributed_decisions(frame, admitting, Subject("judge", "J1"))) == ["D1", "D3"]
    # The court counts it explicitly.
    assert _ids(statutory_releases(frame, "K1")) == ["D4"]
    assert _ids(statutory_releases(frame, "K2")) == []


def test_an_unknown_actor_is_never_attributed_to_a_judge(frame: Frame) -> None:
    admitting = AttributionRule(
        decision_type="pretrial_release",
        actor_types=frozenset({"judge", "unknown"}),
        discretion=None,
        assignment_gate="deciding_judge",
    )
    for judge in ("J1", "J2"):
        rows = attributed_decisions(frame, admitting, Subject("judge", judge))
        assert "unknown" not in rows["actor_type"].to_list()
    assert _ids(unknown_actor_pretrial_decisions(frame, "K1")) == ["D5"]
    assert _ids(unknown_actor_pretrial_decisions(frame, "K2")) == []


def test_registry_rules_convert_and_the_court_only_rules_reach_their_helpers(frame: Frame) -> None:
    registry = load_registry()
    rule = AttributionRule.from_spec(registry["pretrial_decisions"].attribution)
    assert rule == PRETRIAL
    statutory = AttributionRule.from_spec(registry["statutory_release_count"].attribution)
    assert _ids(attributed_decisions(frame, statutory, Subject("court", "K1"))) == ["D4"]
    unknown = AttributionRule.from_spec(registry["unknown_actor_pretrial_count"].attribution)
    assert _ids(attributed_decisions(frame, unknown, Subject("court", "K1"))) == ["D5"]
    with pytest.raises(AttributionError, match="unknown assignment gate"):
        AttributionRule(assignment_gate="nearest_judge")
    with pytest.raises(AttributionError, match="unknown subject type"):
        Subject("jurisdiction", "X")


def test_frames_validate_their_schemas() -> None:
    base = Frame.empty(date(2020, 1, 1), date(2020, 12, 31))
    assert base.coverage_end_exclusive_at == datetime(2021, 1, 1, tzinfo=UTC)
    with pytest.raises(FrameError, match="lacks column"):
        base.replace(persons=pl.DataFrame({"person": ["P1"]}))
    with pytest.raises(FrameError, match="not a UTC Datetime"):
        base.replace(events=base.events.with_columns(pl.col("event_at").dt.replace_time_zone(None)))
    with pytest.raises(FrameError, match="id dtype"):
        base.replace(persons=pl.DataFrame({"id": [1, 2]}))
    with pytest.raises(FrameError, match="inverted"):
        Frame.empty(date(2020, 1, 2), date(2020, 1, 1))
    with pytest.raises(FrameError, match="not justice_event_type"):
        Frame.empty(date(2020, 1, 1), date(2020, 1, 2), frozenset({"recidivism"}))
