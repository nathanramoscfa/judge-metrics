# tests/unit/test_drafts.py
"""Natural keys of the case-level drafts, and key descriptions without person hashes."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest

from judgemetrics.db.models.enums import ActorType
from judgemetrics.ingest.base import (
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtEventDraft,
    DecisionDraft,
    JudgeAssignmentDraft,
    JusticeEventDraft,
    PersonDraft,
    PretrialReleaseDraft,
    SentenceDraft,
    describe_key,
)

pytestmark = pytest.mark.unit

HASH = "a" * 64
COURT_KEY = ("court", "Synthetic County Circuit Court, Division 2", "circuit")
CASE_KEY = ("case", "Synthetic County Circuit Court, Division 2", "circuit", "SYN-2019-000005")
PERSON_KEY = ("person", "source_participant_id", HASH)
JUDGE_KEY = ("judge", "synthetic_judge_code", "J-0002")
AT = datetime(2019, 5, 25, 10, 30, tzinfo=UTC)


def _case() -> CaseDraft:
    return CaseDraft(
        court_key=COURT_KEY,
        case_number="syn 2019 000005",
        case_number_normalized="SYN-2019-000005",
        case_type="misdemeanor",
        filed_date=date(2019, 5, 25),
        closed_date=None,
        status="open",
        source_row_id="syn 2019 000005",
        related_case_number_normalized=None,
    )


def test_person_key_is_the_stable_identifier_hash() -> None:
    person = PersonDraft(
        identity=("source_participant_id", HASH),
        identifier_hashes={"source_participant_id": HASH, "full_name": "b" * 64},
        birth_year_known=False,
    )
    assert person.natural_key == PERSON_KEY
    assert describe_key(person.natural_key) == "person by source_participant_id"
    assert HASH not in describe_key(person.natural_key)


def test_case_key_is_court_plus_normalized_number() -> None:
    case = _case()
    assert case.natural_key == CASE_KEY
    variant = dataclasses.replace(
        case, case_number="SYN-2019-000005", source_row_id="SYN-2019-000005"
    )
    assert variant.natural_key == case.natural_key
    assert describe_key(case.natural_key) == (
        "case Synthetic County Circuit Court, Division 2:circuit:SYN-2019-000005"
    )


def test_rows_of_a_case_are_keyed_by_case_and_source_row_id() -> None:
    party = CasePartyDraft(CASE_KEY, PERSON_KEY, "defendant", "defendant", "PT-000005")
    assert party.natural_key == ("case_party", *CASE_KEY[1:], "PT-000005")
    assignment = JudgeAssignmentDraft(CASE_KEY, JUDGE_KEY, "initial", AT, None, "AS-000001")
    assert assignment.natural_key == ("judge_assignment", *CASE_KEY[1:], "AS-000001")
    charge = ChargeDraft(
        case_key=CASE_KEY,
        person_key=PERSON_KEY,
        statute_code="SYN-201",
        description="Theft",
        offense_category="property",
        severity="misdemeanor_a",
        violent_flag=False,
        filed_at=AT,
        disposed_at=None,
        disposition=None,
        disposition_actor=None,
        source_row_id="CH-000009",
    )
    assert charge.natural_key == ("charge", *CASE_KEY[1:], "CH-000009")
    event = CourtEventDraft(
        CASE_KEY, PERSON_KEY, JUDGE_KEY, "hearing", AT, None, ActorType.JUDGE, "EV-000010"
    )
    assert event.natural_key == ("court_event", *CASE_KEY[1:], "EV-000010")
    decision = DecisionDraft(
        case_key=CASE_KEY,
        person_key=PERSON_KEY,
        judge_key=None,
        decision_type="pretrial_release",
        decision_at=AT,
        decision_value={"release_type": "statutory"},
        actor_type=ActorType.LEGISLATURE_OR_MANDATORY_RULE,
        judicial_discretion_classification="mandatory",
        pretrial=PretrialReleaseDraft("statutory", None, {}, AT, False),
        source_row_id="DC-000011",
    )
    assert decision.natural_key == ("decision", *CASE_KEY[1:], "DC-000011")
    sentence = SentenceDraft(
        case_key=CASE_KEY,
        person_key=PERSON_KEY,
        judge_key=JUDGE_KEY,
        sentence_at=AT,
        incarceration_days=None,
        probation_days=210,
        fine_amount=Decimal("600"),
        components={"probation": True, "fine": True},
        source_row_id="SN-000001",
    )
    assert sentence.natural_key == ("sentence", *CASE_KEY[1:], "SN-000001")


def test_justice_event_key_uses_the_person_hash_type_instant_and_case_in_utc() -> None:
    event = JusticeEventDraft(PERSON_KEY, "failure_to_appear", AT, CASE_KEY)
    assert event.natural_key == (
        "justice_event",
        "source_participant_id",
        HASH,
        "failure_to_appear",
        "2019-05-25T10:30:00+00:00",
        *CASE_KEY[1:],
    )
    # The same instant expressed in another zone yields the same key.
    shifted = dataclasses.replace(event, event_at=AT.astimezone(timezone(timedelta(hours=-5))))
    assert shifted.natural_key == event.natural_key
    unrelated = JusticeEventDraft(PERSON_KEY, "rearrest", AT, None)
    assert unrelated.natural_key == (
        "justice_event",
        "source_participant_id",
        HASH,
        "rearrest",
        "2019-05-25T10:30:00+00:00",
    )
    described = describe_key(event.natural_key)
    assert HASH not in described
    assert described == (
        "justice_event failure_to_appear at 2019-05-25T10:30:00+00:00 for case "
        "Synthetic County Circuit Court, Division 2:circuit:SYN-2019-000005"
    )
    assert describe_key(unrelated.natural_key) == (
        "justice_event rearrest at 2019-05-25T10:30:00+00:00"
    )


def test_drafts_are_frozen() -> None:
    case = _case()
    with pytest.raises(dataclasses.FrozenInstanceError):
        case.status = "closed"  # type: ignore[misc]
