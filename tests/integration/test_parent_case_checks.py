# tests/integration/test_parent_case_checks.py
"""The case-level checks read a parent case that is not in the run from the database.

Until Phase 5 Step 4 a child row was checked only against the cases drafted in the same
run, so a run that re-parsed one artifact (Phase 4 carry-over item 2) never saw its
cases' filing dates. A scripted connector publishes a case in its first run and, in a
second run over a different artifact, only a charge, a court event, and a justice event
that precede that case's filing date: the runner reads the parent case from the database
(bounded array lookup) and the checks report all three.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.db.models import DataQualityIssue, IngestRunStatus
from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtDraft,
    CourtEventDraft,
    JurisdictionDraft,
    JusticeEventDraft,
    PersonDraft,
    RawArtifact,
    SourceArtifact,
    SourceInfo,
    SourceRecordDraft,
    ValidationResult,
    utc_now,
)
from judgemetrics.ingest.runner import run_ingest
from judgemetrics.ingest.store import FilesystemRawObjectStore
from judgemetrics.security.identifiers import hash_identifier
from tests.conftest import TEST_IDENTIFIER_PEPPER

pytestmark = pytest.mark.integration

SOURCE = "parent-case-stub"
FILED = date(2020, 5, 1)
JURISDICTION = JurisdictionDraft("Parent Check County", "county", "IL", None)
COURT = CourtDraft("Parent Check Court", "circuit", JURISDICTION.natural_key)
CASE_KEY = ("case", COURT.canonical_name, COURT.court_type, "PC-1")
PERSON_HASH = hash_identifier(
    SecretStr(TEST_IDENTIFIER_PEPPER), "source_participant_id", "parent-1", source=SOURCE
)
PERSON_KEY = ("person", "source_participant_id", PERSON_HASH)


class Scripted:
    """A connector whose one artifact's bytes and drafts are given."""

    source_id = SOURCE
    parser_version = "1"
    source_info = SourceInfo(owner="tests", source_type="fixture", access_method="memory")

    def __init__(self, payload: bytes, drafts: list[CanonicalRecord]) -> None:
        self._payload = payload
        self._drafts = drafts

    async def discover(self) -> list[SourceArtifact]:
        return [SourceArtifact(SOURCE, "rows.csv", "memory://rows", "text/csv")]

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:
        return RawArtifact.from_bytes(artifact, self._payload, retrieved_at=utc_now())

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:
        return ValidationResult.passed()

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:
        return [SourceRecordDraft("row", None, {})]

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:
        return self._drafts


def at(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=UTC)


def test_a_run_that_drafts_only_children_is_checked_against_the_stored_case(
    db_session: Session, tmp_path: Path
) -> None:
    store = FilesystemRawObjectStore(tmp_path / "lake")
    settings = Settings(env="test")
    first_drafts: list[CanonicalRecord] = [
        JURISDICTION,
        COURT,
        CaseDraft(COURT.natural_key, "PC-1", "PC-1", "felony", FILED, None, "open", "PC-1"),
        PersonDraft(("source_participant_id", PERSON_HASH), {"source_participant_id": PERSON_HASH}),
        CasePartyDraft(CASE_KEY, PERSON_KEY, "defendant", None, "defendant:1"),
    ]
    first = run_ingest(
        SOURCE,
        session=db_session,
        store=store,
        settings=settings,
        connector=Scripted(b"first", first_drafts),
    )
    assert first.status is IngestRunStatus.SUCCEEDED, first.failure_reason

    children: list[CanonicalRecord] = [
        ChargeDraft(
            case_key=CASE_KEY,
            person_key=PERSON_KEY,
            statute_code=None,
            description="a charge",
            offense_category="other",
            severity="felony_1",
            violent_flag=None,
            filed_at=at(2020, 3, 1),
            disposed_at=at(2020, 4, 10),
            disposition="dismissed",
            disposition_actor=None,
            source_row_id="1:1:1",
        ),
        CourtEventDraft(
            CASE_KEY, PERSON_KEY, None, "hearing", at(2020, 4, 20), None, None, "event-1"
        ),
        JusticeEventDraft(PERSON_KEY, "rearrest", at(2020, 4, 1), CASE_KEY),
    ]
    second = run_ingest(
        SOURCE,
        session=db_session,
        store=store,
        settings=settings,
        connector=Scripted(b"second", children),
    )
    assert second.status is IngestRunStatus.SUCCEEDED, second.failure_reason
    assert second.records_rejected == 0
    descriptions = {
        issue.issue_code: issue.description
        for issue in db_session.scalars(
            select(DataQualityIssue).where(
                DataQualityIssue.issue_code.in_(
                    [
                        "disposition_before_filing",
                        "event_order_impossible",
                        "subsequent_before_index",
                    ]
                )
            )
        )
    }
    assert set(descriptions) == {
        "disposition_before_filing",
        "event_order_impossible",
        "subsequent_before_index",
    }
    assert "before the case was filed 2020-05-01" in descriptions["disposition_before_filing"]
    assert "before the case was filed 2020-05-01" in descriptions["event_order_impossible"]
    assert "before its case" in descriptions["subsequent_before_index"]
