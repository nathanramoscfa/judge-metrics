# tests/golden/test_golden_resolution.py
"""Entity resolution over the golden fixture, one test per planted pair.

The permanent regression gate for ``docs/ENTITY_RESOLUTION.md``:
parametrized over every row of ``truth/resolution_expectations.csv``, the
stored candidate's decision equals the expected one, with the stage,
actor, and features the decision implies. The split persons then share
one public key and their case parties, the ambiguous pairs are in the
review queue as public keys only, distinct persons keep distinct keys,
and the planted pairs are the only candidates the fixture produces. The
Step 3 integration test keeps its narrower, transactional assertions;
this suite runs over the committed module ingest on the scratch database.
"""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from judgemetrics.db.models import CaseParty, EntityResolutionCandidate, Person, PersonIdentifier
from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution.config import STAGE_RULE, SYSTEM_ACTOR
from judgemetrics.entity_resolution.queue import list_review
from judgemetrics.security.identifiers import KIND_SOURCE_PARTICIPANT_ID
from tests.golden.conftest import (
    GoldenFixture,
    candidate_for,
    canonical,
    family,
    person_of,
    read_rows,
)

pytestmark = [pytest.mark.golden, pytest.mark.integration]

EXPECTATIONS = read_rows("truth/resolution_expectations.csv")
EXPECTATION_IDS = [
    f"{row['left_participant_id']}-{row['right_participant_id']}-{row['expected_decision']}"
    for row in EXPECTATIONS
]


@pytest.mark.parametrize("row", EXPECTATIONS, ids=EXPECTATION_IDS)
def test_the_stored_decision_matches_the_expectation(
    session: Session, golden_fixture: GoldenFixture, row: dict[str, str]
) -> None:
    left = person_of(session, row["left_participant_id"])
    right = person_of(session, row["right_participant_id"])
    candidate = candidate_for(session, left, right)
    expected = ResolutionDecision(row["expected_decision"])
    assert candidate.decision is expected, row
    assert candidate.ingest_run_id == golden_fixture.run_id
    assert candidate.match_probability is not None
    assert candidate.features and "stage_trace" in candidate.features
    if expected is ResolutionDecision.MATCHED:
        assert left.id == right.id, "both participant ids hash to the survivor"
        assert len(family(session, left)) == 2
        assert candidate.stage == STAGE_RULE
        assert candidate.decided_by == SYSTEM_ACTOR and candidate.decided_at is not None
        assert candidate.features["same_name_dob"] is True
        assert candidate.features["related_case_link"] is True
    elif expected is ResolutionDecision.REVIEW:
        assert left.id != right.id
        assert left.merged_into_person_id is None and right.merged_into_person_id is None
        assert candidate.decided_by is None and candidate.decided_at is None
        assert candidate.features["same_name_dob"] is True
        assert candidate.features["shared_case"] is False
        assert candidate.features["related_case_link"] is False
    else:
        assert left.id != right.id
        assert left.merged_into_person_id is None and right.merged_into_person_id is None
        assert candidate.reason == "name_only"
        assert candidate.features["dob_missing_either"] is True
        assert candidate.decided_by == SYSTEM_ACTOR


@pytest.mark.parametrize(
    "row",
    [row for row in EXPECTATIONS if row["expected_decision"] == "matched"],
    ids=[i for i, row in zip(EXPECTATION_IDS, EXPECTATIONS, strict=True) if "matched" in i],
)
def test_split_persons_share_one_public_key_and_their_parties(
    session: Session, row: dict[str, str]
) -> None:
    left = person_of(session, row["left_participant_id"])
    right = person_of(session, row["right_participant_id"])
    keep = canonical(session, left)
    assert canonical(session, right).id == keep.id
    assert keep.public_person_key == left.public_person_key == right.public_person_key
    assert keep.resolution_status == STAGE_RULE
    dropped = list(session.scalars(select(Person).where(Person.merged_into_person_id == keep.id)))
    assert len(dropped) == 1
    assert dropped[0].resolution_status == "merged"
    assert dropped[0].public_person_key != keep.public_person_key
    # Every party and identifier row moved to the survivor.
    assert not list(session.scalars(select(CaseParty).where(CaseParty.person_id == dropped[0].id)))
    assert not list(
        session.scalars(select(PersonIdentifier).where(PersonIdentifier.person_id == dropped[0].id))
    )
    stable = [
        identifier.value_hash
        for identifier in session.scalars(
            select(PersonIdentifier).where(
                PersonIdentifier.person_id == keep.id,
                PersonIdentifier.identifier_type == KIND_SOURCE_PARTICIPANT_ID,
            )
        )
    ]
    assert len(stable) == 2
    parties = list(session.scalars(select(CaseParty).where(CaseParty.person_id == keep.id)))
    assert len({party.case_id for party in parties}) >= 2


def test_ambiguous_pairs_wait_in_review_as_public_keys(session: Session) -> None:
    review_rows = [row for row in EXPECTATIONS if row["expected_decision"] == "review"]
    assert review_rows, "the golden fixture plants an ambiguous same-date-of-birth pair"
    items = list_review(session)
    assert len(items) == len(review_rows)
    expected_keys = {
        frozenset(
            {
                person_of(session, row["left_participant_id"]).public_person_key,
                person_of(session, row["right_participant_id"]).public_person_key,
            }
        )
        for row in review_rows
    }
    assert {frozenset({i.left_public_key, i.right_public_key}) for i in items} == expected_keys
    for item in items:
        assert item.stage == "review" and item.score is not None
        stored = session.get(EntityResolutionCandidate, item.candidate_id)
        assert stored is not None and stored.decision is ResolutionDecision.REVIEW
        rendered = repr(item.as_dict())
        for row in read_rows("source/participants.csv"):
            assert row["full_name"].strip() not in rendered
            assert row["participant_id"] not in rendered
            if row["date_of_birth"]:
                assert row["date_of_birth"] not in rendered


def test_distinct_persons_keep_distinct_keys_and_the_planted_pairs_are_the_only_candidates(
    session: Session, golden_fixture: GoldenFixture
) -> None:
    for row in EXPECTATIONS:
        if row["expected_decision"] == "matched":
            continue
        left = person_of(session, row["left_participant_id"])
        right = person_of(session, row["right_participant_id"])
        assert left.id != right.id
        assert left.public_person_key != right.public_person_key
    total = session.scalar(
        select(func.count())
        .select_from(EntityResolutionCandidate)
        .where(EntityResolutionCandidate.ingest_run_id == golden_fixture.run_id)
    )
    assert total == len(EXPECTATIONS)
    participants = {row["participant_id"] for row in read_rows("source/participants.csv")}
    merged = {row["right_participant_id"] for row in EXPECTATIONS if "matched" in row.values()}
    keys = {person_of(session, pid).public_person_key for pid in participants}
    assert len(keys) == len(participants) - len(merged)
