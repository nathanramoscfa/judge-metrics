# src/judgemetrics/synthetic/edge_cases.py
"""Planted edge cases: duplicates, ambiguous persons, split persons, missing data.

Planting runs after the clean world is built and identified, from the
``edge_cases`` stream only, in a fixed order: split persons (they need a
person with cases in two courts), ambiguous pairs, duplicate source
records, then the missing-data shares. Every planted item is recorded with
the ids involved and the pipeline behaviour it must produce, and every
planted person pair carries the resolution decision Step 3 must reach.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

from judgemetrics.synthetic.config import ScaleSpec
from judgemetrics.synthetic.model import Case, Charge, Person, World, next_participant_id
from judgemetrics.synthetic.rng import sample, shuffled
from judgemetrics.synthetic.world import GenerationError

# The share of court events whose description is blanked; the ScaleSpec has
# no field for it, so it is the same at every scale.
MISSING_DESCRIPTION_SHARE = 0.02

KIND_DUPLICATE = "duplicate_source_record"
KIND_AMBIGUOUS_SAME_DOB = "ambiguous_person_same_dob"
KIND_AMBIGUOUS_MISSING_DOB = "ambiguous_person_missing_dob"
KIND_SPLIT = "split_person"
KIND_MISSING_DOB = "missing_dob"
KIND_MISSING_JUDGE = "missing_judge"
KIND_MISSING_DISPOSITION = "missing_disposition"
KIND_MISSING_DESCRIPTION = "missing_description"
KINDS: tuple[str, ...] = (
    KIND_DUPLICATE,
    KIND_AMBIGUOUS_SAME_DOB,
    KIND_AMBIGUOUS_MISSING_DOB,
    KIND_SPLIT,
    KIND_MISSING_DOB,
    KIND_MISSING_JUDGE,
    KIND_MISSING_DISPOSITION,
    KIND_MISSING_DESCRIPTION,
)

EXPECTED: dict[str, str] = {
    KIND_DUPLICATE: (
        "the connector normalizes the case number and names, so the second copy collapses "
        "onto the same court_case and child rows (one row each, the second source row "
        "attributed); data_quality_issue case_number_duplicate (info)"
    ),
    KIND_AMBIGUOUS_SAME_DOB: (
        "two distinct persons with the same name and date of birth in different courts and "
        "no shared case: two person rows; the candidate pair is decided review, never merged "
        "automatically"
    ),
    KIND_AMBIGUOUS_MISSING_DOB: (
        "two distinct persons with the same name and one date of birth missing: two person "
        "rows; the candidate pair is decided rejected (reason name_only) - never merge on a "
        "name alone"
    ),
    KIND_SPLIT: (
        "one true person under two participant ids in two courts with the same name and date "
        "of birth and a related_case_number link: the rule stage decides matched and the two "
        "persons merge under one public_person_key"
    ),
    KIND_MISSING_DOB: (
        "every participant row of this person has an empty date_of_birth; the person "
        "resolves by participant id; no candidate is matched on the name alone"
    ),
    KIND_MISSING_JUDGE: (
        "the pretrial decision carries no judge_code, actor unknown, discretion unknown: it "
        "is published with actor_type unknown and excluded from every judge-attributed "
        "metric; data_quality_issue missing_judge_on_decision (warning)"
    ),
    KIND_MISSING_DISPOSITION: (
        "the charge carries no disposition, disposed_at, or disposition_actor in a closed "
        "case: published with a null disposition and excluded from disposition metrics; "
        "data_quality_issue missing_disposition (info)"
    ),
    KIND_MISSING_DESCRIPTION: (
        "the court event carries an empty description: published with a null description; "
        "no data-quality issue"
    ),
}

DECISION_MATCHED = "matched"
DECISION_REJECTED = "rejected"
DECISION_REVIEW = "review"
REASON_SPLIT = "same_name_same_dob_related_case"
REASON_AMBIGUOUS_SAME_DOB = "same_name_same_dob_no_shared_case"
REASON_AMBIGUOUS_MISSING_DOB = "same_name_dob_missing"


@dataclass(frozen=True, slots=True)
class PlantedItem:
    kind: str
    ids: tuple[tuple[str, str], ...]
    expected: str

    @property
    def ids_text(self) -> str:
        return ";".join(f"{key}={value}" for key, value in self.ids)


@dataclass(frozen=True, slots=True)
class ResolutionExpectation:
    left_participant_id: str
    right_participant_id: str
    expected_decision: str
    reason: str


@dataclass(slots=True)
class Plants:
    items: list[PlantedItem] = field(default_factory=list)
    expectations: list[ResolutionExpectation] = field(default_factory=list)

    def count(self, kind: str) -> int:
        return sum(1 for item in self.items if item.kind == kind)


def planted_count(share: float, population: int) -> int:
    """``round(share * population)``, at least one when the share is positive."""
    if share <= 0.0 or population <= 0:
        return 0
    return max(1, round(share * population))


def _courts_of(world: World, person: Person) -> set[str]:
    return {case.court_code for case in world.cases if case.person is person}


def _expectation(left: str, right: str, decision: str, reason: str) -> ResolutionExpectation:
    first, second = sorted((left, right))
    return ResolutionExpectation(first, second, decision, reason)


def _plant_splits(world: World, rng: random.Random, plants: Plants, used: set[str]) -> None:
    spec = world.spec
    candidates = [p for p in world.persons if len(_courts_of(world, p)) >= 2]
    if len(candidates) < spec.split_person_pairs:
        msg = (
            f"{len(candidates)} persons with cases in two courts; {spec.split_person_pairs} needed"
        )
        raise GenerationError(msg)
    for person in sorted(sample(rng, candidates, spec.split_person_pairs), key=lambda p: p.true_id):
        cases = world.cases_of(person)
        first = cases[0]
        second = next(c for c in cases[1:] if c.court_code != first.court_code)
        new_id = next_participant_id(world)
        person.participant_ids[1] = new_id
        split_cases = [c for c in cases if c.court_code == second.court_code]
        for case in split_cases:
            case.participant_alias = 1
        second.related_case_number = first.case_number
        used.add(person.true_id)
        primary = person.participant_ids[0]
        plants.items.append(
            PlantedItem(
                KIND_SPLIT,
                (
                    ("true_person_id", person.true_id),
                    ("participant_ids", f"{primary},{new_id}"),
                    ("first_case_number", first.case_number),
                    ("first_court_code", first.court_code),
                    ("second_case_number", second.case_number),
                    ("second_court_code", second.court_code),
                    ("split_case_numbers", ",".join(c.case_number for c in split_cases)),
                ),
                EXPECTED[KIND_SPLIT],
            )
        )
        plants.expectations.append(_expectation(primary, new_id, DECISION_MATCHED, REASON_SPLIT))


def _ambiguous_pair(
    world: World, rng: random.Random, available: list[Person], *, same_dob: bool
) -> tuple[Person, Person] | None:
    """Two unused persons; with ``same_dob`` their cases must sit in disjoint courts."""
    courts = {p.true_id: _courts_of(world, p) for p in available}
    for first in shuffled(rng, available):
        for candidate in shuffled(rng, [p for p in available if p is not first]):
            if not same_dob or not (courts[candidate.true_id] & courts[first.true_id]):
                return first, candidate
    return None


def _plant_ambiguous(world: World, rng: random.Random, plants: Plants, used: set[str]) -> None:
    for index in range(world.spec.ambiguous_person_pairs):
        same_dob = index % 2 == 0
        available = [p for p in world.persons if p.true_id not in used]
        pair = _ambiguous_pair(world, rng, available, same_dob=same_dob)
        if pair is None:
            msg = "no two unused persons with disjoint courts for an ambiguous pair"
            raise GenerationError(msg)
        first, second = pair
        first_courts = _courts_of(world, first)
        second.given, second.family = first.given, first.family
        if same_dob:
            second.date_of_birth = first.date_of_birth
            second.age_band = first.age_band
            kind, decision, reason = (
                KIND_AMBIGUOUS_SAME_DOB,
                DECISION_REVIEW,
                REASON_AMBIGUOUS_SAME_DOB,
            )
        else:
            second.dob_known = False
            kind, decision, reason = (
                KIND_AMBIGUOUS_MISSING_DOB,
                DECISION_REJECTED,
                REASON_AMBIGUOUS_MISSING_DOB,
            )
        used.update((first.true_id, second.true_id))
        left, right = first.participant_ids[0], second.participant_ids[0]
        plants.items.append(
            PlantedItem(
                kind,
                (
                    ("true_person_ids", f"{first.true_id},{second.true_id}"),
                    ("participant_ids", f"{left},{right}"),
                    ("shared_name", first.full_name),
                    ("courts", ",".join(sorted(first_courts | _courts_of(world, second)))),
                ),
                EXPECTED[kind],
            )
        )
        plants.expectations.append(_expectation(left, right, decision, reason))


def _plant_duplicates(world: World, rng: random.Random, plants: Plants, used: set[str]) -> None:
    candidates = [c for c in world.cases if c.person.true_id not in used]
    count = world.spec.duplicate_source_records
    if len(candidates) < count:
        msg = f"{len(candidates)} cases available for {count} duplicate source records"
        raise GenerationError(msg)
    for case in sorted(sample(rng, candidates, count), key=Case.sort_key):
        case.duplicate = True
        used.add(case.person.true_id)
        plants.items.append(
            PlantedItem(
                KIND_DUPLICATE,
                (
                    ("case_number", case.case_number),
                    ("court_code", case.court_code),
                    ("participant_id", case.participant_id),
                    ("duplicate_case_number", duplicate_case_number(case.case_number)),
                ),
                EXPECTED[KIND_DUPLICATE],
            )
        )


def duplicate_case_number(case_number: str) -> str:
    """The formatting variant the duplicate copy carries (case and separators differ)."""
    return case_number.lower().replace("-", " ")


def duplicate_full_name(name: str) -> str:
    """The name variant of the duplicate copy: upper case with trailing whitespace."""
    return name.upper() + " "


def _plant_missing_dob(world: World, rng: random.Random, plants: Plants, used: set[str]) -> None:
    count = planted_count(world.spec.missing_dob_share, world.spec.persons)
    candidates = [p for p in world.persons if p.true_id not in used]
    if len(candidates) < count:
        msg = f"{len(candidates)} unused persons for {count} missing dates of birth"
        raise GenerationError(msg)
    for person in sorted(sample(rng, candidates, count), key=lambda p: p.true_id):
        person.dob_known = False
        used.add(person.true_id)
        plants.items.append(
            PlantedItem(
                KIND_MISSING_DOB,
                (
                    ("true_person_id", person.true_id),
                    ("participant_id", person.participant_ids[0]),
                ),
                EXPECTED[KIND_MISSING_DOB],
            )
        )


def _plant_missing_judge(world: World, rng: random.Random, plants: Plants) -> None:
    """``round(share * judicial pretrial decisions)`` decisions lose their judge."""
    population = [
        (case, decision)
        for case in world.cases
        for decision in [case.pretrial_decision]
        if decision is not None and decision.actor == "judge"
    ]
    candidates = [(case, decision) for case, decision in population if not case.duplicate]
    count = min(planted_count(world.spec.missing_judge_share, len(population)), len(candidates))
    for case, decision in sorted(
        sample(rng, candidates, count), key=lambda item: item[0].sort_key()
    ):
        former = decision.judge_code
        decision.judge_code = None
        decision.actor = "unknown"
        decision.discretion = "unknown"
        plants.items.append(
            PlantedItem(
                KIND_MISSING_JUDGE,
                (
                    ("decision_id", decision.decision_id),
                    ("case_number", case.case_number),
                    ("court_code", case.court_code),
                    ("former_judge_code", former or ""),
                ),
                EXPECTED[KIND_MISSING_JUDGE],
            )
        )


def _plant_missing_disposition(world: World, rng: random.Random, plants: Plants) -> None:
    """``round(share * charges of closed cases)`` charges lose their disposition."""
    population = [
        (case, charge)
        for case in world.cases
        if case.status == "closed"
        for charge in case.charges
        if charge.disposed
    ]
    # Never blank the only conviction behind a sentence; prefer charges of
    # multi-charge cases so the case keeps a disposition.
    eligible = [
        (case, charge)
        for case, charge in population
        if not case.duplicate
        and (case.sentence is None or any(c.convicted for c in case.charges if c is not charge))
    ]
    preferred = [(case, charge) for case, charge in eligible if len(case.charges) > 1]
    candidates = preferred if preferred else eligible
    count = planted_count(world.spec.missing_disposition_share, len(population))
    # At most one charge per case, so every closed case keeps a disposed charge.
    chosen: list[tuple[Case, Charge]] = []
    taken: set[str] = set()
    for case, charge in shuffled(rng, candidates):
        if len(chosen) == count:
            break
        if case.case_number in taken:
            continue
        taken.add(case.case_number)
        chosen.append((case, charge))
    for case, charge in sorted(chosen, key=lambda item: item[1].charge_id):
        former = charge.disposition or ""
        charge.disposition = None
        charge.disposed_at = None
        charge.disposition_actor = None
        plants.items.append(
            PlantedItem(
                KIND_MISSING_DISPOSITION,
                (
                    ("charge_id", charge.charge_id),
                    ("case_number", case.case_number),
                    ("court_code", case.court_code),
                    ("former_disposition", former),
                ),
                EXPECTED[KIND_MISSING_DISPOSITION],
            )
        )


def _plant_missing_description(world: World, rng: random.Random, plants: Plants) -> None:
    """``round(MISSING_DESCRIPTION_SHARE * court events)`` events lose their description."""
    population = [(case, event) for case in world.cases for event in case.events]
    candidates = [(case, event) for case, event in population if not case.duplicate]
    count = min(planted_count(MISSING_DESCRIPTION_SHARE, len(population)), len(candidates))
    for case, event in sorted(sample(rng, candidates, count), key=lambda item: item[1].event_id):
        event.description = None
        plants.items.append(
            PlantedItem(
                KIND_MISSING_DESCRIPTION,
                (
                    ("event_id", event.event_id),
                    ("case_number", case.case_number),
                    ("court_code", case.court_code),
                    ("event_type", event.event_type),
                ),
                EXPECTED[KIND_MISSING_DESCRIPTION],
            )
        )


def plant_edge_cases(world: World, rng: random.Random) -> Plants:
    """Plant every edge case the scale specifies; returns the record of what was planted."""
    plants = Plants()
    used: set[str] = set()
    _plant_splits(world, rng, plants, used)
    _plant_ambiguous(world, rng, plants, used)
    _plant_duplicates(world, rng, plants, used)
    _plant_missing_dob(world, rng, plants, used)
    _plant_missing_judge(world, rng, plants)
    _plant_missing_disposition(world, rng, plants)
    _plant_missing_description(world, rng, plants)
    plants.expectations.sort(key=lambda e: (e.left_participant_id, e.right_participant_id))
    return plants


def configured_counts(
    spec: ScaleSpec, *, judicial_pretrial_decisions: int, closed_case_charges: int, events: int
) -> dict[str, int]:
    """The quantity of every kind the scale configures, from population sizes.

    The populations are what the source files show before planting: pretrial
    decisions whose actor is a judge (or ``unknown`` after planting), charges
    of closed cases, and court events, each counted once per id.
    """
    same_dob = (spec.ambiguous_person_pairs + 1) // 2
    return {
        KIND_DUPLICATE: spec.duplicate_source_records,
        KIND_AMBIGUOUS_SAME_DOB: same_dob,
        KIND_AMBIGUOUS_MISSING_DOB: spec.ambiguous_person_pairs - same_dob,
        KIND_SPLIT: spec.split_person_pairs,
        KIND_MISSING_DOB: planted_count(spec.missing_dob_share, spec.persons),
        KIND_MISSING_JUDGE: planted_count(spec.missing_judge_share, judicial_pretrial_decisions),
        KIND_MISSING_DISPOSITION: planted_count(
            spec.missing_disposition_share, closed_case_charges
        ),
        KIND_MISSING_DESCRIPTION: planted_count(MISSING_DESCRIPTION_SHARE, events),
    }
