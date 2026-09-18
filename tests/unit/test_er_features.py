# tests/unit/test_er_features.py
"""Pair features: equality-only signals, never a hash; blocking pairs."""

from __future__ import annotations

import json
import re
import uuid
from datetime import date

import pytest

from judgemetrics.entity_resolution.features import (
    FEATURE_BOOLEANS,
    CaseRef,
    PairFeatures,
    PersonProfile,
    candidate_pairs,
    compute_features,
)

pytestmark = pytest.mark.unit

HEX64 = re.compile(r"[0-9a-f]{64}")
NAME = "a" * 64
DOB = "b" * 64
NAME_DOB = "c" * 64
OTHER_DOB = "d" * 64
OTHER_NAME_DOB = "e" * 64
PID_A = "1" * 64
PID_B = "2" * 64
COURT_1 = uuid.UUID(int=1)
COURT_2 = uuid.UUID(int=2)


def _profile(
    person: int,
    *,
    pid: str = PID_A,
    name: str | None = NAME,
    dob: str | None = DOB,
    name_dob: str | None = NAME_DOB,
    cases: tuple[CaseRef, ...] = (),
) -> PersonProfile:
    hashes: dict[str, frozenset[str]] = {"source_participant_id": frozenset({pid})}
    if name:
        hashes["full_name"] = frozenset({name})
    if dob:
        hashes["date_of_birth"] = frozenset({dob})
    if name_dob and name and dob:
        hashes["name_dob"] = frozenset({name_dob})
    return PersonProfile(person_id=uuid.UUID(int=person), hashes=hashes, cases=cases)


def _case(number: str, court: uuid.UUID, filed: date, related: str | None = None) -> CaseRef:
    return CaseRef(
        case_id=uuid.uuid5(uuid.NAMESPACE_URL, number),
        court_id=court,
        filed_date=filed,
        case_number_normalized=number,
        related_case_number_normalized=related,
    )


def test_same_source_id_and_same_name_dob() -> None:
    features = compute_features(_profile(1), _profile(2))
    assert features.same_source_id
    assert features.same_name and features.same_dob and features.same_name_dob
    assert not features.dob_missing_either
    assert features.age_consistent is True
    assert not features.dob_differs
    assert features.has_signal


def test_missing_dob_and_differing_dob() -> None:
    missing = compute_features(_profile(1, pid=PID_A), _profile(2, pid=PID_B, dob=None))
    assert missing.same_name and missing.dob_missing_either
    assert not missing.same_dob and not missing.same_name_dob
    assert missing.age_consistent is None
    assert not missing.dob_differs
    differs = compute_features(
        _profile(1, pid=PID_A), _profile(2, pid=PID_B, dob=OTHER_DOB, name_dob=OTHER_NAME_DOB)
    )
    assert differs.same_name and not differs.same_dob and not differs.dob_missing_either
    assert differs.dob_differs and differs.age_consistent is False


def test_case_linkage_features() -> None:
    first = _case("SYN-2021-000007", COURT_1, date(2021, 3, 1))
    second = _case("SYN-2021-000021", COURT_2, date(2021, 8, 11), related="SYN-2021-000007")
    shared = _case("SYN-2020-000001", COURT_1, date(2020, 1, 5))
    a = _profile(1, pid=PID_A, cases=(first, shared))
    b = _profile(2, pid=PID_B, cases=(second,))
    features = compute_features(a, b)
    assert features.related_case_link and not features.shared_case
    assert not features.same_court
    assert features.filing_gap_days == (date(2021, 8, 11) - date(2021, 3, 1)).days
    both = compute_features(a, _profile(3, pid=PID_B, cases=(shared,)))
    assert both.shared_case and both.same_court and both.filing_gap_days == 0
    assert compute_features(b, a).related_case_link, "symmetric"
    unlinked = compute_features(_profile(1, pid=PID_A), _profile(2, pid=PID_B))
    assert unlinked.filing_gap_days is None and not unlinked.same_court


def test_as_dict_is_json_serializable_without_hashes() -> None:
    features = compute_features(_profile(1), _profile(2, pid=PID_B))
    payload = json.dumps(features.as_dict())
    assert not HEX64.search(payload)
    assert set(json.loads(payload)) == {*FEATURE_BOOLEANS, "filing_gap_days", "age_consistent"}
    assert all(isinstance(getattr(features, name), bool) for name in FEATURE_BOOLEANS)


def test_no_signal_when_nothing_is_shared() -> None:
    features = compute_features(
        _profile(1, pid=PID_A), _profile(2, pid=PID_B, name="f" * 64, name_dob=OTHER_NAME_DOB)
    )
    assert not features.has_signal


def test_candidate_pairs_are_ordered_and_anchored() -> None:
    a, b, c = uuid.UUID(int=3), uuid.UUID(int=1), uuid.UUID(int=2)
    blocks = {("full_name", NAME): {a, b, c}, ("source_participant_id", PID_A): {a, b}}
    assert candidate_pairs(blocks) == [(b, c), (b, a), (c, a)]
    assert candidate_pairs(blocks, anchor={c}) == [(b, c), (c, a)]
    assert all(left < right for left, right in candidate_pairs(blocks))


def test_pair_features_is_frozen() -> None:
    features = compute_features(_profile(1), _profile(2))
    with pytest.raises(AttributeError):
        features.same_name = False  # type: ignore[misc]
    assert isinstance(features, PairFeatures)
