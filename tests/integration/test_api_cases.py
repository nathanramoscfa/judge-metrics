# tests/integration/test_api_cases.py
"""`/api/v1/cases/{id}` and `/cases/{id}/timeline` over the committed golden ingest.

The detail carries parties as public keys only, assignments, charges,
decisions with their actor and discretion classification (a prosecutor's
dismissal beside a judge's disposition), the sentence, and provenance
blocks flagged synthetic; the timeline is chronological with every kind
the case contains; unknown ids are 404; no restricted field name and no
merged person's key appears in any response.
"""

from __future__ import annotations

import json
import re
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from judgemetrics.api.deps import CACHE_CONTROL
from judgemetrics.db.models import Person
from judgemetrics.main import REQUEST_ID_HEADER
from judgemetrics.schemas.cases import TIMELINE_KIND_ORDER
from tests.integration.conftest import GoldenFixture

pytestmark = pytest.mark.integration

# SYN-2020-000005 at C-0003 before J-0003: a judicial detention decision, a
# prosecutor's dismissal of two charges, a judicial disposition of the third
# (plea), a sentence of 113 days probation, and a later revocation event.
CASE = "SYN-2020-000005"
# The case the source links to it (`related_case_number`): the planted split
# person PT-000042 / PT-000017 that entity resolution merges.
RELATED_CASE = "SYN-2020-000013"
JUDGE = "J-0003"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
RESTRICTED_NAMES = (
    "value_hash",
    "encrypted_value",
    "date_of_birth",
    "full_name",
    "person_identifier",
    "raw_object_path",
)


def _keys(value: object) -> set[str]:
    """Every dictionary key anywhere in a JSON value."""
    found: set[str] = set()
    if isinstance(value, dict):
        for key, inner in value.items():
            found.add(str(key))
            found |= _keys(inner)
    elif isinstance(value, list):
        for inner in value:
            found |= _keys(inner)
    return found


def test_detail_carries_every_section_and_synthetic_provenance(
    api: TestClient, golden_fixture: GoldenFixture
) -> None:
    case_id = golden_fixture.case_ids[CASE]
    response = api.get(f"/api/v1/cases/{case_id}")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {
        "id",
        "court",
        "case_number",
        "case_type",
        "filed_date",
        "closed_date",
        "status",
        "synthetic",
        "parties",
        "assignments",
        "charges",
        "decisions",
        "sentences",
        "provenance",
    }
    assert body["case_number"] == CASE
    assert body["court"]["id"] == str(golden_fixture.court_ids["C-0003"])
    assert body["court"]["court_type"] == "circuit"
    assert (body["case_type"], body["status"]) == ("misdemeanor", "closed")
    assert (body["filed_date"], body["closed_date"]) == ("2020-06-20", "2020-09-29")
    assert body["synthetic"] is True

    (party,) = body["parties"]
    assert set(party) == {"party_type", "public_person_key"}
    assert party["party_type"] == "defendant"
    assert re.match(r"^[A-Za-z0-9_-]{8,64}$", party["public_person_key"])

    (assignment,) = body["assignments"]
    assert assignment["judge"] == {
        "id": str(golden_fixture.judge_ids[JUDGE]),
        "canonical_name": "Puce Wingnut",
    }
    assert assignment["assignment_type"] == "initial"
    assert assignment["start_at"] == "2020-06-21T16:50:00Z"

    charges = {charge["statute_code"]: charge for charge in body["charges"]}
    assert set(charges) == {"SYN-505", "SYN-205", "SYN-101"}
    assert (charges["SYN-505"]["disposition"], charges["SYN-505"]["disposition_actor"]) == (
        "convicted_plea",
        "judge",
    )
    assert (charges["SYN-205"]["disposition"], charges["SYN-205"]["disposition_actor"]) == (
        "dismissed",
        "prosecutor",
    )
    assert charges["SYN-101"]["offense_category"] == "drug"
    assert charges["SYN-101"]["violent_flag"] is False

    decisions = [
        (d["decision_type"], d["actor_type"], d["judicial_discretion_classification"])
        for d in body["decisions"]
    ]
    assert decisions == [
        ("pretrial_release", "judge", "discretionary"),
        ("dismissal", "prosecutor", "non_judicial"),
        ("disposition", "judge", "discretionary"),
        ("sentencing", "judge", "discretionary"),
    ]
    pretrial, dismissal, disposition, _ = body["decisions"]
    assert pretrial["judge"]["canonical_name"] == "Puce Wingnut"
    assert pretrial["pretrial_release"] == {
        "release_type": "detained",
        "bond_amount": None,
        "conditions": {},
        "release_at": None,
        "detained_flag": True,
    }
    assert pretrial["decision_value"] == {"release_type": "detained", "detained": True}
    # A prosecutor's dismissal names no judge; a judicial disposition does.
    assert dismissal["judge"] is None
    assert disposition["judge"]["id"] == str(golden_fixture.judge_ids[JUDGE])
    assert {d["public_person_key"] for d in body["decisions"]} == {party["public_person_key"]}

    (sentence,) = body["sentences"]
    assert sentence == {
        "sentence_at": "2020-09-29T10:02:00Z",
        "judge": {"id": str(golden_fixture.judge_ids[JUDGE]), "canonical_name": "Puce Wingnut"},
        "incarceration_days": None,
        "probation_days": 113,
        "fine_amount": None,
        "components": sentence["components"],
    }

    # One block per artifact behind the case: cases, participants, assignments,
    # charges, events, decisions, sentences.
    artifacts = {block["external_record_id"] for block in body["provenance"]}
    assert artifacts == {
        "source/cases.csv",
        "source/participants.csv",
        "source/assignments.csv",
        "source/charges.csv",
        "source/events.csv",
        "source/decisions.csv",
        "source/sentences.csv",
    }
    for block in body["provenance"]:
        assert block["source"] == "synthetic"
        assert block["synthetic"] is True
        assert SHA256.match(block["raw_sha256"])
        assert block["ingest_run_id"] == str(golden_fixture.run_id)


def test_timeline_is_chronological_with_every_kind_the_case_contains(
    api: TestClient, golden_fixture: GoldenFixture
) -> None:
    case_id = golden_fixture.case_ids[CASE]
    response = api.get(f"/api/v1/cases/{case_id}/timeline")
    assert response.status_code == 200, response.text
    assert response.headers["Cache-Control"] == CACHE_CONTROL
    body = response.json()
    assert set(body) == {"case_id", "synthetic", "entries"}
    assert body["case_id"] == str(case_id)
    assert body["synthetic"] is True
    entries = body["entries"]
    assert entries, "empty timeline"
    assert all(
        set(entry) == {"at", "kind", "actor_type", "judge", "label", "detail", "source"}
        for entry in entries
    )
    rank = {kind: index for index, kind in enumerate(TIMELINE_KIND_ORDER)}
    keys = [(entry["at"], rank[entry["kind"]]) for entry in entries]
    assert keys == sorted(keys)
    assert {entry["kind"] for entry in entries} == set(TIMELINE_KIND_ORDER)

    assert entries[0]["kind"] == "filed"
    assert entries[0]["at"] == "2020-06-20T00:00:00Z"
    assert entries[0]["detail"]["date"] == "2020-06-20"
    # The closing date sorts at the end of its own day, after that day's
    # sentencing; the revocation event of 2020-11-22 follows the closing.
    kinds = [entry["kind"] for entry in entries]
    closed = kinds.index("closed")
    assert entries[closed]["at"].startswith("2020-09-29T23:59:59")
    assert kinds[closed - 1] == "sentence"
    assert kinds[closed + 1 :] == ["event"]
    assert entries[-1]["detail"]["event_type"] == "revocation"

    by_kind: dict[str, list[dict[str, object]]] = {}
    for entry in entries:
        by_kind.setdefault(entry["kind"], []).append(entry)
    decisions = {(d["actor_type"], d["detail"]["decision_type"]) for d in by_kind["decision"]}  # type: ignore[index]
    assert ("prosecutor", "dismissal") in decisions
    assert ("judge", "disposition") in decisions
    disposed = {(c["actor_type"], c["detail"]["disposition"]) for c in by_kind["charge_disposed"]}  # type: ignore[index]
    assert disposed == {("prosecutor", "dismissed"), ("judge", "convicted_plea")}
    assert all(entry["judge"] is None for entry in by_kind["filed"] + by_kind["closed"])
    assert all(
        entry["judge"]["canonical_name"] == "Puce Wingnut"  # type: ignore[index]
        for entry in by_kind["assignment_start"] + by_kind["event"] + by_kind["sentence"]
    )
    assert by_kind["sentence"][0]["label"] == "Sentence: 113 days probation"
    sources = {entry["source"]["external_record_id"] for entry in entries}
    assert "source/events.csv" in sources and "source/cases.csv" in sources
    assert all(entry["source"]["synthetic"] is True for entry in entries)


def test_no_restricted_field_name_or_merged_key_in_any_response(
    api: TestClient, golden_fixture: GoldenFixture, migrated_database: Engine
) -> None:
    with Session(migrated_database) as session:
        merged_keys = set(
            session.scalars(
                select(Person.public_person_key).where(Person.merged_into_person_id.is_not(None))
            )
        )
    assert merged_keys, "the golden fixture plants split persons that merge"

    surviving: set[str] = set()
    for number in (CASE, RELATED_CASE):
        case_id = golden_fixture.case_ids[number]
        for path in (f"/api/v1/cases/{case_id}", f"/api/v1/cases/{case_id}/timeline"):
            response = api.get(path)
            assert response.status_code == 200, response.text
            text = response.text
            assert not any(name in text for name in RESTRICTED_NAMES), path
            assert not (_keys(json.loads(text)) & set(RESTRICTED_NAMES)), path
            assert not (merged_keys & set(re.findall(r'"public_person_key":\s*"([^"]+)"', text)))
        detail = api.get(f"/api/v1/cases/{case_id}").json()
        surviving |= {party["public_person_key"] for party in detail["parties"]}
    # The two linked cases belong to one resolved person under one public key.
    assert len(surviving) == 1


def test_judge_cases_and_search_never_name_a_person(
    api: TestClient, golden_fixture: GoldenFixture
) -> None:
    judge_id = golden_fixture.judge_ids[JUDGE]
    page = api.get(f"/api/v1/judges/{judge_id}/cases", params={"limit": 100})
    assert page.status_code == 200
    assert not (_keys(page.json()) & {*RESTRICTED_NAMES, "public_person_key"})
    hit = api.get("/api/v1/search", params={"q": CASE})
    assert not (_keys(hit.json()) & set(RESTRICTED_NAMES))


@pytest.mark.parametrize("suffix", ["", "/timeline"])
def test_missing_case_is_404_with_the_error_envelope(api: TestClient, suffix: str) -> None:
    missing = uuid.UUID(int=0)
    response = api.get(f"/api/v1/cases/{missing}{suffix}")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "request_id"}
    assert body["code"] == "not_found"
    assert str(missing) in body["message"]
    assert body["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert "Cache-Control" not in response.headers


def test_malformed_id_and_unknown_parameters_are_422(
    api: TestClient, golden_fixture: GoldenFixture
) -> None:
    assert api.get("/api/v1/cases/not-a-uuid").status_code == 422
    case_id = golden_fixture.case_ids[CASE]
    response = api.get(f"/api/v1/cases/{case_id}", params={"expand": "x"})
    assert response.status_code == 422
    assert response.json()["message"] == "unknown query parameter(s): expand"
    response = api.get(f"/api/v1/cases/{case_id}/timeline", params={"kind": "event"})
    assert response.status_code == 422
