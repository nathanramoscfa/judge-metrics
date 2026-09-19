# tests/golden/test_golden_counts.py
"""Canonical row counts, the planted data-quality issues, and provenance hashes
after the golden ingest.

Per canonical table, the rows the golden run published equal the
manifest's count for the file they come from minus the rows of the
planted duplicate source records (which collapse onto their originals);
persons are the distinct participant ids; every predicted data-quality
issue exists, linked to its entity, with no error-severity issue at all;
and every case-level row cites a source record whose sha256 is the
fixture file's own digest and the manifest's. Counts are scoped to the
module's run through ``source_record_id``, so the suite also holds on
the fallback database beside a live ingest.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import (
    Base,
    Case,
    Charge,
    CourtEvent,
    DataQualityIssue,
    Decision,
    IssueSeverity,
    Person,
    SourceRecord,
)
from judgemetrics.db.models.enums import ActorType
from judgemetrics.normalization.case_numbers import normalize_case_number
from judgemetrics.synthetic.generate import Manifest
from tests.golden.conftest import GOLDEN, GoldenFixture, planted_ids, read_rows

pytestmark = [pytest.mark.golden, pytest.mark.integration]

MANIFEST = Manifest.load(GOLDEN / "manifest.json")
PLANTED = read_rows("truth/planted.csv")
DUPLICATE_VARIANTS = frozenset(
    planted_ids(row)["duplicate_case_number"]
    for row in PLANTED
    if row["kind"] == "duplicate_source_record"
)

# Canonical table → the source file it is published from.
TABLE_FILES: dict[str, str] = {
    "court_case": "cases.csv",
    "case_party": "participants.csv",
    "judge_assignment": "assignments.csv",
    "charge": "charges.csv",
    "court_event": "events.csv",
    "decision": "decisions.csv",
    "sentence": "sentences.csv",
    "judge_service": "judges.csv",
    "court": "courts.csv",
}
# The tables whose source rows carry a case number, where a duplicate copy collapses.
CASE_LEVEL_TABLES = frozenset(
    {
        "court_case",
        "case_party",
        "judge_assignment",
        "charge",
        "court_event",
        "decision",
        "sentence",
    }
)
# Predicted issue code per planted kind; the other kinds raise no issue.
ISSUE_CODES: dict[str, str] = {
    "duplicate_source_record": "case_number_duplicate",
    "missing_judge": "missing_judge_on_decision",
    "missing_disposition": "missing_disposition",
}


def _duplicate_rows(file_name: str) -> int:
    """Rows of ``file_name`` that belong to a planted duplicate copy."""
    return sum(
        1 for row in read_rows(f"source/{file_name}") if row["case_number"] in DUPLICATE_VARIANTS
    )


def _run_records(session: Session, fixture: GoldenFixture) -> dict[str, SourceRecord]:
    return {
        record.external_record_id or "": record
        for record in session.scalars(
            select(SourceRecord).where(SourceRecord.ingest_run_id == fixture.run_id)
        )
    }


def _published(session: Session, table: str, fixture: GoldenFixture) -> int:
    model = Base.metadata.tables[table]
    records = select(SourceRecord.id).where(SourceRecord.ingest_run_id == fixture.run_id)
    return (
        session.scalar(
            select(func.count()).select_from(model).where(model.c.source_record_id.in_(records))
        )
        or 0
    )


@pytest.mark.parametrize("table", sorted(TABLE_FILES))
def test_canonical_counts_equal_the_manifest_minus_planted_duplicates(
    session: Session, golden_fixture: GoldenFixture, table: str
) -> None:
    file_name = TABLE_FILES[table]
    expected = MANIFEST.counts[f"source/{file_name}"]
    if table in CASE_LEVEL_TABLES:
        expected -= _duplicate_rows(file_name)
    assert _published(session, table, golden_fixture) == expected, table


def test_persons_are_the_distinct_participant_ids_and_judges_the_distinct_codes(
    session: Session, golden_fixture: GoldenFixture
) -> None:
    participants = {row["participant_id"] for row in read_rows("source/participants.csv")}
    assert _published(session, "person", golden_fixture) == len(participants)
    merged = session.scalar(
        select(func.count())
        .select_from(Person)
        .where(
            Person.merged_into_person_id.is_not(None),
            Person.source_record_id.in_(
                select(SourceRecord.id).where(SourceRecord.ingest_run_id == golden_fixture.run_id)
            ),
        )
    )
    assert merged == sum(
        1 for row in read_rows("truth/resolution_expectations.csv") if "matched" in row.values()
    )
    assert _published(session, "judge", golden_fixture) == len(
        {row["judge_code"] for row in read_rows("source/judges.csv")}
    )
    assert _published(session, "jurisdiction", golden_fixture) == 1
    pretrial = session.scalar(
        select(func.count())
        .select_from(Decision)
        .where(
            Decision.decision_type == "pretrial_release",
            Decision.source_record_id.in_(
                select(SourceRecord.id).where(SourceRecord.ingest_run_id == golden_fixture.run_id)
            ),
        )
    )
    assert pretrial == sum(
        1
        for row in read_rows("source/decisions.csv")
        if row["decision_type"] == "pretrial_release"
        and row["case_number"] not in DUPLICATE_VARIANTS
    )


def test_every_predicted_data_quality_issue_exists(
    session: Session, golden_fixture: GoldenFixture
) -> None:
    records = select(SourceRecord.id).where(SourceRecord.ingest_run_id == golden_fixture.run_id)
    issues = list(
        session.scalars(
            select(DataQualityIssue).where(DataQualityIssue.source_record_id.in_(records))
        )
    )
    by_code = Counter(issue.issue_code for issue in issues)
    planted = Counter(row["kind"] for row in PLANTED)
    for kind, code in ISSUE_CODES.items():
        assert by_code[code] == planted[kind] > 0, kind
    assert set(by_code) == set(ISSUE_CODES.values())
    assert not [issue for issue in issues if issue.severity is IssueSeverity.ERROR]

    for row in PLANTED:
        ids = planted_ids(row)
        kind = row["kind"]
        if kind == "duplicate_source_record":
            case = session.scalar(
                select(Case).where(
                    Case.case_number_normalized == normalize_case_number(ids["case_number"]),
                    Case.id.in_(golden_fixture.case_ids.values()),
                )
            )
            assert case is not None and case.case_number == ids["case_number"]
            matching = [
                issue
                for issue in issues
                if issue.issue_code == "case_number_duplicate" and issue.entity_id == case.id
            ]
            assert len(matching) == 1 and ids["duplicate_case_number"] in matching[0].description
        elif kind == "missing_judge":
            decision = session.scalar(
                select(Decision).where(
                    Decision.source_row_id == ids["decision_id"],
                    Decision.source_record_id.in_(records),
                )
            )
            assert decision is not None
            assert decision.actor_type is ActorType.UNKNOWN and decision.judge_id is None
            assert any(
                issue.issue_code == "missing_judge_on_decision" and issue.entity_id == decision.id
                for issue in issues
            )
        elif kind == "missing_disposition":
            charge = session.scalar(
                select(Charge).where(
                    Charge.source_row_id == ids["charge_id"], Charge.source_record_id.in_(records)
                )
            )
            assert charge is not None and charge.disposition is None
            assert any(
                issue.issue_code == "missing_disposition" and issue.entity_id == charge.id
                for issue in issues
            )
        elif kind == "missing_description":
            event = session.scalar(
                select(CourtEvent).where(
                    CourtEvent.source_row_id == ids["event_id"],
                    CourtEvent.source_record_id.in_(records),
                )
            )
            assert event is not None and event.description is None
            assert not any(issue.entity_id == event.id for issue in issues)


@pytest.mark.parametrize("table", sorted(TABLE_FILES))
def test_every_row_cites_the_fixture_file_it_came_from(
    session: Session, golden_fixture: GoldenFixture, table: str
) -> None:
    file_name = TABLE_FILES[table]
    records = _run_records(session, golden_fixture)
    record = records[f"source/{file_name}"]
    on_disk = hashlib.sha256((GOLDEN / "source" / file_name).read_bytes()).hexdigest()
    assert record.raw_sha256 == on_disk == MANIFEST.files[f"source/{file_name}"]
    model = Base.metadata.tables[table]
    cited = set(
        session.scalars(
            select(model.c.source_record_id)
            .where(model.c.source_record_id.in_([r.id for r in records.values()]))
            .distinct()
        )
    )
    assert cited == {record.id}, table


def test_truth_index_event_cohorts_agree_with_the_source_files() -> None:
    """The TRUTH_VERSION 2 cohorts recounted from the fixture's own CSVs, per subject."""
    truth = json.loads((GOLDEN / "truth" / "metrics.json").read_text(encoding="utf-8"))
    decisions = [
        r for r in read_rows("source/decisions.csv") if r["case_number"] not in DUPLICATE_VARIANTS
    ]
    sentences = [
        r for r in read_rows("source/sentences.csv") if r["case_number"] not in DUPLICATE_VARIANTS
    ]
    charges = [
        r for r in read_rows("source/charges.csv") if r["case_number"] not in DUPLICATE_VARIANTS
    ]
    cases = {
        r["case_number"]: r
        for r in read_rows("source/cases.csv")
        if r["case_number"] not in DUPLICATE_VARIANTS
    }
    disposed_cases = {
        r["case_number"]
        for r in charges
        if r["disposition"] not in ("", "pending") and r["disposed_at"]
    }
    for code, block in truth["courts"].items():
        released = [
            r
            for r in decisions
            if r["court_code"] == code
            and r["decision_type"] == "pretrial_release"
            and r["actor"] == "judge"
            and r["discretion"] == "discretionary"
            and r["detained"] == "false"
        ]
        windows = block["index_events"]
        assert windows["pretrial_release"]["windows"]["30"]["cohort"] == len(released)
        assert windows["sentence"]["windows"]["30"]["cohort"] == sum(
            1 for r in sentences if r["court_code"] == code
        )
        assert windows["disposition"]["windows"]["30"]["cohort"] == sum(
            1 for number in disposed_cases if cases[number]["court_code"] == code
        )
    for code, block in truth["judges"].items():
        windows = block["index_events"]
        assert windows["sentence"]["windows"]["30"]["cohort"] == sum(
            1 for r in sentences if r["judge_code"] == code
        )
        assert windows["pretrial_release"]["windows"]["30"]["cohort"] == sum(
            1
            for r in decisions
            if r["judge_code"] == code
            and r["decision_type"] == "pretrial_release"
            and r["actor"] == "judge"
            and r["discretion"] == "discretionary"
            and r["detained"] == "false"
        )
    assert {item["outcome"] for item in truth["not_observable"]} == {
        "release_violation",
        "rearrest",
    }


def test_no_truth_file_was_ingested(session: Session, golden_fixture: GoldenFixture) -> None:
    records = _run_records(session, golden_fixture)
    assert not any("truth" in Path(name).parts for name in records)
    assert set(records) == {"manifest.json", *(f"source/{n}" for n in TABLE_FILES.values())}
