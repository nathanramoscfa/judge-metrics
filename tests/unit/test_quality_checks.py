# tests/unit/test_quality_checks.py
"""Data-quality checks over judge service drafts and provenance."""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from judgemetrics.db.models.enums import IssueSeverity
from judgemetrics.ingest.base import JudgeDraft, JudgeServiceDraft, Provenance, TaggedRecord
from judgemetrics.quality.checks import (
    MISSING_START_DATE,
    PROVENANCE_INCOMPLETE,
    SERVICE_DATES_INVALID,
    SERVICE_OVERLAP,
    missing_start_date,
    provenance_complete,
    run_checks,
    service_dates_valid,
    service_overlap,
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
