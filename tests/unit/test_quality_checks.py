# tests/unit/test_quality_checks.py
"""Data-quality checks: judge service and provenance (Phase 1), the case-level checks (Phase 2)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

import pytest

from judgemetrics.db.models.enums import ActorType, IssueSeverity
from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtEventDraft,
    DecisionDraft,
    JudgeAssignmentDraft,
    JudgeDraft,
    JudgeServiceDraft,
    JusticeEventDraft,
    NaturalKey,
    PretrialReleaseDraft,
    Provenance,
    SentenceDraft,
    TaggedRecord,
)
from judgemetrics.quality.checks import (
    CASE_NUMBER_DUPLICATE,
    CHECKS,
    DISPOSITION_BEFORE_FILING,
    EVENT_ORDER_IMPOSSIBLE,
    MISSING_DISPOSITION,
    MISSING_JUDGE_ON_DECISION,
    MISSING_START_DATE,
    PERSON_RESOLUTION_CONFIDENCE_MISSING,
    PROVENANCE_INCOMPLETE,
    SERVICE_DATES_INVALID,
    SERVICE_OVERLAP,
    SUBSEQUENT_BEFORE_INDEX,
    disposition_before_filing,
    event_order_impossible,
    missing_disposition,
    missing_judge_on_decision,
    missing_start_date,
    person_resolution_confidence_missing,
    provenance_complete,
    run_checks,
    run_pre_deduplication_checks,
    service_dates_valid,
    service_overlap,
    subsequent_before_index,
    unknown_category_measured,
)

pytestmark = pytest.mark.unit

RECORD = Provenance(source_record_id=uuid.uuid4(), raw_sha256="a" * 64)


def _service(
    *,
    judge: str = "1",
    court: str = "Court A",
    position: str = "Judge",
    start: date | None = date(2000, 1, 1),
    end: date | None = None,
    provenance: Provenance | None = RECORD,
) -> TaggedRecord:
    draft = JudgeServiceDraft(
        judge_key=("judge", "fjc_nid", judge),
        court_key=("court", court, "district"),
        position_type=position,
        start_date=start,
        end_date=end,
    )
    return TaggedRecord(record=draft, provenance=provenance)


def test_service_dates_valid_flags_end_before_start() -> None:
    bad = _service(start=date(2000, 1, 2), end=date(2000, 1, 1))
    issues = service_dates_valid([bad, _service(end=date(2001, 1, 1)), _service(start=None)])
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_code == SERVICE_DATES_INVALID
    assert issue.severity is IssueSeverity.ERROR
    assert issue.entity_type == "judge_service"
    assert issue.entity_key == bad.record.natural_key
    assert issue.source_record_id == RECORD.source_record_id
    assert "2000-01-01 precedes start date 2000-01-02" in issue.description


def test_service_dates_valid_accepts_same_day_service() -> None:
    assert service_dates_valid([_service(start=date(2000, 1, 1), end=date(2000, 1, 1))]) == []


def test_service_overlap_flags_the_later_of_two_overlapping_intervals() -> None:
    earlier = _service(position="Associate Justice", start=date(1931, 2, 21), end=date(1938, 1, 15))
    later = _service(position="Chief Justice", start=date(1937, 12, 7), end=date(1957, 7, 17))
    issues = service_overlap([later, earlier])
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_code == SERVICE_OVERLAP
    assert issue.severity is IssueSeverity.WARNING
    assert issue.entity_key == later.record.natural_key
    assert "Chief Justice" in issue.description and "Associate Justice" in issue.description


def test_service_overlap_ignores_touching_intervals() -> None:
    first = _service(start=date(1958, 10, 25), end=date(1959, 9, 8))
    second = _service(start=date(1959, 9, 8), end=date(1975, 3, 24))
    assert service_overlap([first, second]) == []


def test_service_overlap_treats_open_ended_service_as_ongoing() -> None:
    ongoing = _service(start=date(2000, 1, 1), end=None)
    later = _service(position="Chief Judge", start=date(2010, 1, 1), end=None)
    assert len(service_overlap([ongoing, later])) == 1


def test_service_overlap_needs_the_same_judge_and_court() -> None:
    a = _service(start=date(2000, 1, 1), end=date(2010, 1, 1))
    other_court = _service(court="Court B", start=date(2005, 1, 1))
    other_judge = _service(judge="2", start=date(2005, 1, 1))
    assert service_overlap([a, other_court, other_judge]) == []


def test_service_overlap_skips_undated_service() -> None:
    assert (
        service_overlap([_service(start=None), _service(start=None, position="Chief Judge")]) == []
    )


def test_missing_start_date_is_informational() -> None:
    undated = _service(start=None)
    issues = missing_start_date([undated, _service()])
    assert len(issues) == 1
    assert issues[0].issue_code == MISSING_START_DATE
    assert issues[0].severity is IssueSeverity.INFO
    assert issues[0].entity_key == undated.record.natural_key


def test_provenance_complete_requires_a_record_with_a_sha256() -> None:
    judge = JudgeDraft("A B", "a b", ("fjc_nid", "1"), {"fjc_nid": "1"})
    missing = TaggedRecord(record=judge, provenance=None)
    bad_hash = TaggedRecord(record=judge, provenance=Provenance(uuid.uuid4(), "nope"))
    good = TaggedRecord(record=judge, provenance=RECORD)
    issues = provenance_complete([missing, bad_hash, good])
    assert [issue.issue_code for issue in issues] == [PROVENANCE_INCOMPLETE] * 2
    assert all(issue.severity is IssueSeverity.ERROR for issue in issues)
    assert issues[0].entity_type == "judge"
    assert "no source record" in issues[0].description
    assert "without a sha256" in issues[1].description


def test_run_checks_concatenates_every_check_in_order() -> None:
    bad_dates = _service(start=date(2000, 1, 2), end=date(2000, 1, 1))
    undated = _service(start=None, provenance=None)
    issues = run_checks([bad_dates, undated])
    assert [issue.issue_code for issue in issues] == [
        SERVICE_DATES_INVALID,
        MISSING_START_DATE,
        PROVENANCE_INCOMPLETE,
    ]


# --- case-level checks (Phase 2) ------------------------------------------------------


COURT_KEY = ("court", "Court A", "circuit")
CASE_KEY = ("case", "Court A", "circuit", "SYN-2019-000001")
OTHER_CASE_KEY = ("case", "Court A", "circuit", "SYN-2020-000002")
PERSON_KEY = ("person", "source_participant_id", "c" * 64)
JUDGE_KEY = ("judge", "synthetic_judge_code", "J-0001")
FILED = date(2019, 3, 1)
AT = datetime(2019, 3, 5, 10, 0, tzinfo=UTC)


def _tag(record: CanonicalRecord) -> TaggedRecord:
    return TaggedRecord(record=record, provenance=RECORD)


def _case(
    key: NaturalKey = CASE_KEY,
    *,
    number: str = "SYN-2019-000001",
    filed: date | None = FILED,
    closed: date | None = None,
    status: str = "open",
) -> TaggedRecord:
    return _tag(
        CaseDraft(
            court_key=COURT_KEY,
            case_number=number,
            case_number_normalized=key[3],
            case_type="felony",
            filed_date=filed,
            closed_date=closed,
            status=status,
            source_row_id=number,
        )
    )


def _charge(
    *,
    filed_at: datetime = AT,
    disposed_at: datetime | None = None,
    disposition: str | None = None,
    row: str = "CH-1",
) -> TaggedRecord:
    return _tag(
        ChargeDraft(
            case_key=CASE_KEY,
            person_key=PERSON_KEY,
            statute_code=None,
            description="Theft",
            offense_category="property",
            severity="felony_3",
            violent_flag=False,
            filed_at=filed_at,
            disposed_at=disposed_at,
            disposition=disposition,
            disposition_actor=ActorType.JUDGE if disposition else None,
            source_row_id=row,
        )
    )


def _decision(
    *,
    actor: ActorType = ActorType.JUDGE,
    judge: NaturalKey | None = JUDGE_KEY,
    discretion: str = "discretionary",
    at: datetime = AT,
    pretrial: PretrialReleaseDraft | None = None,
    row: str = "DC-1",
) -> TaggedRecord:
    return _tag(
        DecisionDraft(
            case_key=CASE_KEY,
            person_key=PERSON_KEY,
            judge_key=judge,
            decision_type="pretrial_release",
            decision_at=at,
            decision_value={},
            actor_type=actor,
            judicial_discretion_classification=discretion,
            pretrial=pretrial,
            source_row_id=row,
        )
    )


def test_case_number_duplicate_runs_before_deduplication() -> None:
    original = _case(number="SYN-2019-000001")
    copy = _case(number="syn 2019 000001")
    issues = run_pre_deduplication_checks([original, copy, _case(OTHER_CASE_KEY)])
    assert len(issues) == 1
    issue = issues[0]
    assert issue.issue_code == CASE_NUMBER_DUPLICATE
    assert issue.severity is IssueSeverity.INFO
    assert issue.entity_type == "case"
    assert issue.entity_key == CASE_KEY
    assert "'SYN-2019-000001', 'syn 2019 000001'" in issue.description
    assert issue.source_record_id == RECORD.source_record_id
    assert run_pre_deduplication_checks([original, _case(OTHER_CASE_KEY)]) == []


def test_disposition_before_filing_is_an_error() -> None:
    before_charge = _charge(
        filed_at=AT, disposed_at=AT - timedelta(days=1), disposition="dismissed"
    )
    before_case = _charge(
        filed_at=AT - timedelta(days=10),
        disposed_at=AT - timedelta(days=9),
        disposition="dismissed",
    )
    fine = _charge(disposed_at=AT + timedelta(days=30), disposition="dismissed")
    issues = disposition_before_filing([_case(), before_charge, before_case, fine, _charge()])
    assert [issue.issue_code for issue in issues] == [DISPOSITION_BEFORE_FILING] * 2
    assert all(issue.severity is IssueSeverity.ERROR for issue in issues)
    assert "before the charge was filed" in issues[0].description
    assert "before the case was filed" in issues[1].description
    assert issues[0].entity_type == "charge"


def test_event_order_impossible_covers_the_documented_orderings() -> None:
    closed_early = _case(
        OTHER_CASE_KEY, number="SYN-2020-000002", filed=FILED, closed=FILED - timedelta(days=1)
    )
    assignment = _tag(
        JudgeAssignmentDraft(CASE_KEY, JUDGE_KEY, "initial", AT, AT - timedelta(hours=1), "AS-1")
    )
    early_event = _tag(
        CourtEventDraft(
            CASE_KEY,
            PERSON_KEY,
            JUDGE_KEY,
            "hearing",
            AT - timedelta(days=30),
            None,
            ActorType.JUDGE,
            "EV-1",
        )
    )
    released_early = _decision(
        pretrial=PretrialReleaseDraft("recognizance", None, {}, AT - timedelta(hours=2), False)
    )
    conviction = _charge(disposed_at=AT + timedelta(days=10), disposition="convicted_plea")
    early_sentence = _tag(
        SentenceDraft(
            CASE_KEY, PERSON_KEY, JUDGE_KEY, AT + timedelta(days=5), 10, None, None, {}, "SN-1"
        )
    )
    issues = event_order_impossible(
        [_case(), closed_early, assignment, early_event, released_early, conviction, early_sentence]
    )
    assert [issue.entity_type for issue in issues] == [
        "case",
        "judge_assignment",
        "court_event",
        "decision",
        "sentence",
    ]
    assert all(issue.issue_code == EVENT_ORDER_IMPOSSIBLE for issue in issues)
    assert all(issue.severity is IssueSeverity.ERROR for issue in issues)
    assert "before the conviction" in issues[-1].description
    assert event_order_impossible([_case(), conviction, _decision()]) == []


def test_subsequent_before_index_is_an_error() -> None:
    party = _tag(CasePartyDraft(CASE_KEY, PERSON_KEY, "defendant", "defendant", "PT-1"))
    early = _tag(JusticeEventDraft(PERSON_KEY, "rearrest", AT - timedelta(days=60), None))
    before_case = _tag(
        JusticeEventDraft(PERSON_KEY, "new_case", AT - timedelta(days=60), OTHER_CASE_KEY)
    )
    fine = _tag(
        JusticeEventDraft(PERSON_KEY, "failure_to_appear", AT + timedelta(days=9), CASE_KEY)
    )
    later_case = _case(OTHER_CASE_KEY, number="SYN-2020-000002", filed=FILED + timedelta(days=200))
    issues = subsequent_before_index([_case(), later_case, party, early, before_case, fine])
    assert [issue.issue_code for issue in issues] == [SUBSEQUENT_BEFORE_INDEX] * 2
    assert "first case was filed" in issues[0].description
    assert "before its case" in issues[1].description
    assert all("c" * 64 not in issue.description for issue in issues)


def test_missing_judge_on_decision_warns_only_for_judge_or_unknown_actors() -> None:
    issues = missing_judge_on_decision(
        [
            _decision(judge=None, actor=ActorType.UNKNOWN, discretion="unknown", row="DC-1"),
            _decision(judge=None, actor=ActorType.JUDGE, row="DC-2"),
            _decision(judge=None, actor=ActorType.LEGISLATURE_OR_MANDATORY_RULE, row="DC-3"),
            _decision(judge=None, actor=ActorType.PROSECUTOR, row="DC-4"),
            _decision(row="DC-5"),
        ]
    )
    assert [issue.entity_key[-1] for issue in issues if issue.entity_key] == ["DC-1", "DC-2"]
    assert all(issue.issue_code == MISSING_JUDGE_ON_DECISION for issue in issues)
    assert all(issue.severity is IssueSeverity.WARNING for issue in issues)


def test_missing_disposition_is_informational_for_closed_cases_only() -> None:
    closed = _case(status="closed", closed=FILED + timedelta(days=90))
    issues = missing_disposition(
        [closed, _charge(row="CH-1"), _charge(row="CH-2", disposition="pending")]
    )
    assert [issue.issue_code for issue in issues] == [MISSING_DISPOSITION]
    assert issues[0].severity is IssueSeverity.INFO
    assert issues[0].entity_key == ("charge", *CASE_KEY[1:], "CH-1")
    assert missing_disposition([_case(status="open"), _charge()]) == []


def test_unknown_category_measured_counts_per_field() -> None:
    issues = unknown_category_measured(
        [
            _decision(actor=ActorType.UNKNOWN, discretion="unknown", judge=None, row="DC-1"),
            _decision(row="DC-2"),
            _decision(row="DC-3"),
            _charge(),
        ]
    )
    assert [(issue.entity_type, issue.description) for issue in issues] == [
        ("decision", "decision.actor_type: 1 of 3 values are 'unknown'"),
        ("decision", "decision.judicial_discretion_classification: 1 of 3 values are 'unknown'"),
    ]
    assert all(
        issue.entity_key is None and issue.severity is IssueSeverity.INFO for issue in issues
    )
    assert unknown_category_measured([_decision(), _charge()]) == []


def test_person_resolution_confidence_missing_warns_for_unresolved_parties() -> None:
    resolved = _tag(CasePartyDraft(CASE_KEY, PERSON_KEY, "defendant", "defendant", "PT-1"))
    unresolved = _tag(CasePartyDraft(CASE_KEY, None, "defendant", "defendant", "PT-2"))
    issues = person_resolution_confidence_missing([resolved, unresolved])
    assert [issue.entity_key for issue in issues] == [unresolved.record.natural_key]
    assert issues[0].issue_code == PERSON_RESOLUTION_CONFIDENCE_MISSING
    assert issues[0].severity is IssueSeverity.WARNING


def test_run_checks_includes_the_case_level_checks() -> None:
    issues = run_checks([_case(status="closed", closed=FILED + timedelta(days=1)), _charge()])
    assert [issue.issue_code for issue in issues] == [MISSING_DISPOSITION]
    assert CHECKS[-7:] == (
        disposition_before_filing,
        event_order_impossible,
        subsequent_before_index,
        missing_judge_on_decision,
        missing_disposition,
        unknown_category_measured,
        person_resolution_confidence_missing,
    )
