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
the court-level helpers count them explicitly. Registry version 3:
``disposing_judge`` keeps the charges whose recorded judge is the subject and
the cases whose disposing judge is (the judge on the charge that sets the case
disposition time, ties by the source's charge id); a non-final disposition
disposes of nothing; a gate the source does not record is ``NotAttributable``
for a judge and never for a court; a judge with dispositions alone is a
subject; a revocation is observable only in the scopes the source documents.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import pytest

from judgemetrics.capabilities import CASE, SUPERVISION, SourceCapabilities
from judgemetrics.metrics.attribution import (
    DISPOSING_JUDGE,
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
from judgemetrics.metrics.compute import (
    NotAttributableRecord,
    NotObservableRecord,
    compute_frame,
    compute_metric,
    not_attributable,
    subjects_of,
)
from judgemetrics.metrics.frame import SCHEMAS, Frame, FrameError, resolve_dtype
from judgemetrics.metrics.index_events import DISPOSITION_AT, disposed_cases, disposed_charges
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


# --- registry version 3: the disposing judge, finality, NotAttributable (Phase 5 Step 5) -------

DISPOSING = AttributionRule(assignment_gate="disposing_judge")
# The judge each charge's source records as entering its disposition (H4 is pending).
DISPOSING_JUDGES: dict[str, str | None] = {
    "H1": "J1",
    "H2": "J2",
    "H3": "J2",
    "H4": None,
    "H5": "J1",
}


def _with_disposing_judges(frame: Frame, judges: dict[str, str | None] | None = None) -> Frame:
    mapping = DISPOSING_JUDGES if judges is None else judges
    charges = frame.charges.with_columns(
        pl.col("id").replace_strict(mapping, default=None, return_dtype=pl.String).alias("judge_id")
    )
    return frame.replace(charges=charges)


def test_disposing_judge_keeps_the_charges_whose_recorded_judge_is_the_subject(
    frame: Frame,
) -> None:
    disposed = _with_disposing_judges(frame)
    assert _ids(attributed_charges(disposed, DISPOSING, Subject("judge", "J1"))) == ["H1", "H5"]
    assert _ids(attributed_charges(disposed, DISPOSING, Subject("judge", "J2"))) == ["H2", "H3"]
    # A court subject still takes the court's cases, whatever the gate.
    assert _ids(attributed_charges(disposed, DISPOSING, Subject("court", "K1"))) == [
        "H1",
        "H2",
        "H3",
        "H4",
    ]


def test_a_disposed_case_belongs_to_the_judge_on_the_charge_that_sets_its_time(
    frame: Frame,
) -> None:
    disposed = _with_disposing_judges(frame)
    cases = disposed_cases(disposed)
    # The latest final disposition of C1 is H3 at day 20 (J2); C2 has only a pending
    # charge; that of C3 is H5 (J1).
    assert dict(cases.select("id", DISPOSING_JUDGE).iter_rows()) == {"C1": "J2", "C3": "J1"}
    by_j2 = attributed_cases(
        disposed, DISPOSING, Subject("judge", "J2"), rows=cases, time_column=DISPOSITION_AT
    )
    assert _ids(by_j2) == ["C1"]
    # Two charges disposed at the same instant: the source's charge id breaks the tie.
    tied = disposed.replace(
        charges=disposed.charges.with_columns(
            pl.when(pl.col("id") == "H2")
            .then(pl.lit(_at(20)))
            .otherwise(pl.col("disposed_at"))
            .alias("disposed_at"),
            pl.when(pl.col("id") == "H2")
            .then(pl.lit("A-2"))
            .otherwise(pl.col("source_row_id"))
            .alias("source_row_id"),
            pl.when(pl.col("id") == "H2")
            .then(pl.lit("J1"))
            .otherwise(pl.col("judge_id"))
            .alias("judge_id"),
        )
    )
    assert dict(disposed_cases(tied).select("id", DISPOSING_JUDGE).iter_rows())["C1"] == "J1"
    # A case has no deciding or sentencing judge of its own.
    for gate in ("deciding_judge", "sentencing_judge"):
        with pytest.raises(AttributionError, match="cannot attribute a case"):
            attributed_cases(
                disposed, AttributionRule(assignment_gate=gate), Subject("judge", "J1")
            )


def test_a_non_final_disposition_never_disposes_of_a_charge(frame: Frame) -> None:
    for value in ("superseded", "transferred", "pending"):
        changed = frame.replace(
            charges=frame.charges.with_columns(
                pl.when(pl.col("id") == "H5")
                .then(pl.lit(value))
                .otherwise(pl.col("disposition"))
                .alias("disposition")
            )
        )
        assert "H5" not in _ids(disposed_charges(changed)), value
        assert "C3" not in disposed_cases(changed)["id"].to_list(), value
    assert _ids(disposed_charges(frame)) == ["H1", "H2", "H3", "H5"]


def test_a_gate_the_source_does_not_record_is_not_attributable_for_a_judge_only(
    frame: Frame,
) -> None:
    registry = load_registry()
    cook_like = dataclasses.replace(
        _with_disposing_judges(frame),
        capabilities=SourceCapabilities(
            ("disposing_judge", "sentencing_judge"), CASE, (SUPERVISION,)
        ),
    )
    share = registry["pretrial_release_share"]
    record = not_attributable(cook_like, share, Subject("judge", "J1"), "S")
    assert record is not None and record.gate == "deciding_judge"
    assert "deciding judge" in record.reason
    assert not_attributable(cook_like, share, Subject("court", "K1"), "S") is None
    for slug in ("sentence_count", "judicial_dismissal_rate", "median_days_to_disposition"):
        assert not_attributable(cook_like, registry[slug], Subject("judge", "J1"), "S") is None
    computed = compute_metric(cook_like, share, Subject("judge", "J1"), "S")
    assert isinstance(computed, NotAttributableRecord)
    court = compute_metric(cook_like, share, Subject("court", "K1"), "S")
    assert isinstance(court, list) and court and court[0].cohort_size == 2
    result = compute_frame(cook_like, registry, "S")
    unattributed = {(r.slug, r.subject_id) for r in result.not_attributable}
    assert all(r.subject_type == "judge" for r in result.not_attributable)
    for judge in ("J1", "J2"):
        for slug in ("pretrial_decisions", "pretrial_release_share", "eligible_cases"):
            assert (slug, judge) in unattributed
    judge_slugs = {d.slug for d in result.drafts if d.subject_type == "judge"}
    assert not judge_slugs & {"pretrial_decisions", "eligible_cases", "new_case_rate"}
    assert {"judicial_dismissal_rate", "sentence_count"} <= judge_slugs
    # A source that records every gate leaves nothing unattributable.
    assert compute_frame(_with_disposing_judges(frame), registry, "S").not_attributable == []


def test_a_judge_with_dispositions_and_no_sentence_is_a_subject(frame: Frame) -> None:
    only_disposing = _with_disposing_judges(frame, {**DISPOSING_JUDGES, "H5": "J9"})
    judges = {s.subject_id for s in subjects_of(only_disposing) if s.subject_type == "judge"}
    assert "J9" in judges  # no assignment, decision, or sentence: a disposition only
    assert "J9" not in {s.subject_id for s in subjects_of(frame) if s.subject_type == "judge"}


def test_a_revocation_is_observable_only_in_the_scopes_the_source_documents(
    frame: Frame,
) -> None:
    registry = load_registry()
    supervision_only = dataclasses.replace(
        _with_disposing_judges(frame),
        observable_outcomes=frozenset({"revocation"}),
        capabilities=SourceCapabilities(
            ("disposing_judge", "sentencing_judge"), CASE, (SUPERVISION,)
        ),
    )
    court = Subject("court", "K1")
    release = compute_metric(supervision_only, registry["revocation_rate"], court, "S")
    assert isinstance(release, NotObservableRecord)
    assert "scope release" in release.reason
    for slug in ("revocation_rate_after_sentence", "revocation_rate_after_disposition"):
        drafts = compute_metric(supervision_only, registry[slug], court, "S")
        assert isinstance(drafts, list) and drafts, slug
    # A source that documents no revocation at all observes none of them.
    none = dataclasses.replace(supervision_only, observable_outcomes=frozenset())
    blocked = compute_metric(none, registry["revocation_rate_after_sentence"], court, "S")
    assert isinstance(blocked, NotObservableRecord)
    assert blocked.reason == "the source does not document revocation events"
