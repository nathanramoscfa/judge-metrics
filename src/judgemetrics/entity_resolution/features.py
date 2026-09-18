# src/judgemetrics/entity_resolution/features.py
"""The feature vector of a candidate person pair, and the profiles it is computed from.

Every feature is a boolean, a count, or ``None``: a hash is compared for
equality and never copied, so ``PairFeatures.as_dict()`` (what the
candidate row stores) carries no name, date of birth, hash, or
participant id. Profiles are loaded from the database — the restricted
``person_identifier`` rows (kinds ``source_participant_id``,
``full_name``, ``date_of_birth``, ``name_dob``) and the case linkage of
``case_party`` → ``court_case`` → ``court`` — so the ingest hook and
``er run`` compute the same vector from the same rows.

Blocking (``blocking_hashes`` / ``blocks_for``): candidate pairs exist only
among persons that share a ``full_name`` hash or a ``source_participant_id``
hash, which bounds the pair space and is the only place a hash is used as
a key. Merged persons (``merged_into_person_id`` set) are never blocked.

Signals the brief lists that this version does not compute: attorney
relationships, geographic consistency beyond the court, and age
consistency when a date of birth is missing (the source's
``age_at_filing`` is not ingested) — ``age_consistent`` is therefore
``None`` unless both dates of birth are known.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import Base
from judgemetrics.security.identifiers import (
    KIND_DATE_OF_BIRTH,
    KIND_FULL_NAME,
    KIND_NAME_DOB,
    KIND_SOURCE_PARTICIPANT_ID,
)

PERSON = Base.metadata.tables["person"]
PERSON_IDENTIFIER = Base.metadata.tables["person_identifier"]
CASE_PARTY = Base.metadata.tables["case_party"]
COURT_CASE = Base.metadata.tables["court_case"]

BLOCKING_KINDS: tuple[str, ...] = (KIND_FULL_NAME, KIND_SOURCE_PARTICIPANT_ID)
FEATURE_BOOLEANS: tuple[str, ...] = (
    "same_source_id",
    "same_name",
    "same_dob",
    "dob_missing_either",
    "same_name_dob",
    "shared_case",
    "related_case_link",
    "same_court",
)


@dataclass(frozen=True, slots=True)
class PairFeatures:
    """Equality-only signals between two persons; JSON-serializable through ``as_dict``."""

    same_source_id: bool
    same_name: bool
    same_dob: bool
    dob_missing_either: bool
    same_name_dob: bool
    shared_case: bool
    related_case_link: bool
    same_court: bool
    filing_gap_days: int | None
    age_consistent: bool | None

    @property
    def dob_differs(self) -> bool:
        """Both dates of birth are known and they differ: the one contradicting signal."""
        return not self.dob_missing_either and not self.same_dob

    @property
    def has_signal(self) -> bool:
        """Whether the pair carries any signal worth storing (blocking guarantees one)."""
        return self.same_source_id or self.same_name

    def as_dict(self) -> dict[str, Any]:
        return {
            "same_source_id": self.same_source_id,
            "same_name": self.same_name,
            "same_dob": self.same_dob,
            "dob_missing_either": self.dob_missing_either,
            "same_name_dob": self.same_name_dob,
            "shared_case": self.shared_case,
            "related_case_link": self.related_case_link,
            "same_court": self.same_court,
            "filing_gap_days": self.filing_gap_days,
            "age_consistent": self.age_consistent,
        }


@dataclass(frozen=True, slots=True)
class CaseRef:
    """What the features need of one case of a person."""

    case_id: uuid.UUID
    court_id: uuid.UUID
    filed_date: date | None
    case_number_normalized: str
    related_case_number_normalized: str | None


@dataclass(frozen=True, slots=True)
class PersonProfile:
    """A person's identifier hashes by kind and the cases it is a party to."""

    person_id: uuid.UUID
    hashes: Mapping[str, frozenset[str]]
    cases: tuple[CaseRef, ...]

    def of(self, kind: str) -> frozenset[str]:
        return self.hashes.get(kind, frozenset())


def compute_features(a: PersonProfile, b: PersonProfile) -> PairFeatures:
    """The feature vector of the pair ``(a, b)``; symmetric in its arguments."""
    dob_a, dob_b = a.of(KIND_DATE_OF_BIRTH), b.of(KIND_DATE_OF_BIRTH)
    dob_missing_either = not dob_a or not dob_b
    same_dob = bool(dob_a & dob_b)
    cases_a = {ref.case_id for ref in a.cases}
    cases_b = {ref.case_id for ref in b.cases}
    numbers_a = {ref.case_number_normalized for ref in a.cases}
    numbers_b = {ref.case_number_normalized for ref in b.cases}
    cited_a = {ref.related_case_number_normalized for ref in a.cases} - {None}
    cited_b = {ref.related_case_number_normalized for ref in b.cases} - {None}
    filed_a = [ref.filed_date for ref in a.cases if ref.filed_date is not None]
    filed_b = [ref.filed_date for ref in b.cases if ref.filed_date is not None]
    gap = (
        min(abs((first - second).days) for first in filed_a for second in filed_b)
        if filed_a and filed_b
        else None
    )
    return PairFeatures(
        same_source_id=bool(a.of(KIND_SOURCE_PARTICIPANT_ID) & b.of(KIND_SOURCE_PARTICIPANT_ID)),
        same_name=bool(a.of(KIND_FULL_NAME) & b.of(KIND_FULL_NAME)),
        same_dob=same_dob,
        dob_missing_either=dob_missing_either,
        same_name_dob=bool(a.of(KIND_NAME_DOB) & b.of(KIND_NAME_DOB)),
        shared_case=bool(cases_a & cases_b),
        related_case_link=bool(cited_a & numbers_b) or bool(cited_b & numbers_a),
        same_court=bool({ref.court_id for ref in a.cases} & {ref.court_id for ref in b.cases}),
        filing_gap_days=gap,
        age_consistent=None if dob_missing_either else same_dob,
    )


# --- profiles and blocking, from the database ------------------------------------------


def load_profiles(
    session: Session, person_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, PersonProfile]:
    """Profiles of ``person_ids`` from ``person_identifier`` and the case-party linkage."""
    wanted = set(person_ids)
    if not wanted:
        return {}
    hashes: dict[uuid.UUID, dict[str, set[str]]] = {pid: {} for pid in wanted}
    rows = session.execute(
        select(
            PERSON_IDENTIFIER.c.person_id,
            PERSON_IDENTIFIER.c.identifier_type,
            PERSON_IDENTIFIER.c.value_hash,
        ).where(PERSON_IDENTIFIER.c.person_id.in_(wanted))
    ).all()
    for person_id, kind, value_hash in rows:
        hashes[person_id].setdefault(kind, set()).add(value_hash)
    cases: dict[uuid.UUID, list[CaseRef]] = {pid: [] for pid in wanted}
    case_rows = session.execute(
        select(
            CASE_PARTY.c.person_id,
            COURT_CASE.c.id,
            COURT_CASE.c.court_id,
            COURT_CASE.c.filed_date,
            COURT_CASE.c.case_number_normalized,
            COURT_CASE.c.related_case_number_normalized,
        )
        .join(COURT_CASE, COURT_CASE.c.id == CASE_PARTY.c.case_id)
        .where(CASE_PARTY.c.person_id.in_(wanted))
    ).all()
    for person_id, case_id, court_id, filed, number, related in case_rows:
        cases[person_id].append(CaseRef(case_id, court_id, filed, number, related))
    return {
        pid: PersonProfile(
            person_id=pid,
            hashes={kind: frozenset(values) for kind, values in hashes[pid].items()},
            cases=tuple(
                sorted(cases[pid], key=lambda ref: (ref.case_number_normalized, ref.case_id))
            ),
        )
        for pid in wanted
    }


def blocking_hashes(session: Session, person_ids: Iterable[uuid.UUID]) -> set[tuple[str, str]]:
    """The ``(kind, hash)`` blocking keys held by ``person_ids``."""
    wanted = set(person_ids)
    if not wanted:
        return set()
    rows = session.execute(
        select(PERSON_IDENTIFIER.c.identifier_type, PERSON_IDENTIFIER.c.value_hash).where(
            PERSON_IDENTIFIER.c.person_id.in_(wanted),
            PERSON_IDENTIFIER.c.identifier_type.in_(BLOCKING_KINDS),
        )
    ).all()
    return {(kind, value_hash) for kind, value_hash in rows}


def blocks_for(
    session: Session, keys: Iterable[tuple[str, str]] | None
) -> dict[tuple[str, str], set[uuid.UUID]]:
    """Unmerged persons per blocking key: all keys when ``keys`` is ``None``, else those keys.

    The hash is used only to group persons; it never leaves this function.
    """
    stmt = (
        select(
            PERSON_IDENTIFIER.c.identifier_type,
            PERSON_IDENTIFIER.c.value_hash,
            PERSON_IDENTIFIER.c.person_id,
        )
        .join(PERSON, PERSON.c.id == PERSON_IDENTIFIER.c.person_id)
        .where(
            PERSON_IDENTIFIER.c.identifier_type.in_(BLOCKING_KINDS),
            PERSON.c.merged_into_person_id.is_(None),
        )
    )
    if keys is not None:
        wanted = set(keys)
        if not wanted:
            return {}
        stmt = stmt.where(PERSON_IDENTIFIER.c.value_hash.in_({value for _, value in wanted}))
    blocks: dict[tuple[str, str], set[uuid.UUID]] = {}
    for kind, value_hash, person_id in session.execute(stmt).all():
        key = (kind, value_hash)
        if keys is not None and key not in wanted:
            continue
        blocks.setdefault(key, set()).add(person_id)
    return {key: members for key, members in blocks.items() if len(members) > 1}


def candidate_pairs(
    blocks: Mapping[tuple[str, str], set[uuid.UUID]], anchor: set[uuid.UUID] | None = None
) -> list[tuple[uuid.UUID, uuid.UUID]]:
    """Ordered pairs ``(left < right)`` within blocks; with ``anchor``, pairs touching it."""
    pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for members in blocks.values():
        ordered = sorted(members)
        for index, left in enumerate(ordered):
            for right in ordered[index + 1 :]:
                if anchor is None or left in anchor or right in anchor:
                    pairs.add((left, right))
    return sorted(pairs)
