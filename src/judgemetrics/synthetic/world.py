# src/judgemetrics/synthetic/world.py
"""The synthetic jurisdiction: one state, its circuit courts, judges, and persons.

Draw order is fixed (courts, then judges in code order, then persons in id
order) and every draw comes from the ``world`` or ``persons`` stream, so a
change to the case simulation cannot move a judge's name or a person's date
of birth. Names are unique across judges and persons; only the edge-case
planter (``edge_cases.py``) creates a collision, and it records it.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from judgemetrics.config import REPO_ROOT
from judgemetrics.synthetic.config import ScaleSpec
from judgemetrics.synthetic.model import (
    Court,
    Judge,
    Offense,
    Person,
    ServiceRecord,
    World,
)
from judgemetrics.synthetic.rng import Streams, chance, choice, randint, uniform, weighted_choice
from judgemetrics.synthetic.vocabulary import OFFENSE_CATEGORIES, POSITIONS, SEVERITIES
from judgemetrics.synthetic.wordlists import compose_name, full_name

OFFENSES_PATH = REPO_ROOT / "data" / "reference" / "synthetic_offenses.csv"
OFFENSE_HEADERS = ("statute_code", "description", "offense_category", "severity", "violent_flag")

# Judges: share starting at the corpus start rather than later; share whose
# service ends inside the corpus; share with a second service record.
JUDGE_STARTS_AT_CORPUS_START = 0.6
JUDGE_SERVICE_ENDS_SHARE = 0.25
JUDGE_SECOND_RECORD_SHARE = 0.35
JUDGE_TRANSFER_SHARE = 0.6
MIN_SERVICE_DAYS = 180

# Persons: age bands with their weights and the age (at the corpus start)
# they span; the latent propensity exponent (random() ** 2, mean 1/3).
AGE_BANDS: tuple[tuple[str, float, int, int], ...] = (
    ("18-24", 0.22, 18, 24),
    ("25-34", 0.33, 25, 34),
    ("35-44", 0.22, 35, 44),
    ("45-54", 0.13, 45, 54),
    ("55+", 0.10, 55, 70),
)
PROPENSITY_EXPONENT = 2.0


class GenerationError(RuntimeError):
    """The world cannot satisfy its scale specification (a bug, never silent)."""


def load_offenses(path: Path = OFFENSES_PATH) -> list[Offense]:
    """The curated offense table, validated against the vocabulary."""
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != OFFENSE_HEADERS:
            msg = f"{path} headers {reader.fieldnames} != {OFFENSE_HEADERS}"
            raise GenerationError(msg)
        rows = list(reader)
    offenses: list[Offense] = []
    for row in rows:
        if row["offense_category"] not in OFFENSE_CATEGORIES:
            msg = f"{path}: {row['statute_code']} has unknown category {row['offense_category']!r}"
            raise GenerationError(msg)
        if row["severity"] not in SEVERITIES:
            msg = f"{path}: {row['statute_code']} has unknown severity {row['severity']!r}"
            raise GenerationError(msg)
        offenses.append(
            Offense(
                statute_code=row["statute_code"],
                description=row["description"],
                offense_category=row["offense_category"],
                severity=row["severity"],
                violent_flag=row["violent_flag"] == "true",
            )
        )
    codes = [o.statute_code for o in offenses]
    if len(set(codes)) != len(codes):
        msg = f"{path}: duplicate statute codes"
        raise GenerationError(msg)
    return offenses


def unique_name(rng: random.Random, used: set[str]) -> tuple[str, str]:
    """A composed name not used by any judge or person so far."""
    for _ in range(10_000):
        given, family = compose_name(rng)
        name = full_name(given, family)
        if name not in used:
            used.add(name)
            return given, family
    msg = "could not compose a unique name; the word lists are exhausted"
    raise GenerationError(msg)


def build_courts(world: World) -> None:
    for index in range(1, world.spec.courts + 1):
        world.courts.append(
            Court(
                code=f"C-{index:04d}",
                name=f"Synthetic County Circuit Court, Division {index}",
            )
        )


def _date_within(rng: random.Random, start: date, end: date) -> date:
    return start + timedelta(days=randint(rng, 0, (end - start).days))


def _service_records(
    rng: random.Random,
    spec: ScaleSpec,
    home_court: str,
    courts: list[str],
    *,
    anchor: bool,
    force_second: bool,
) -> list[ServiceRecord]:
    """One or two service records inside the corpus years."""
    if anchor:
        return [ServiceRecord(home_court, "circuit_judge", spec.corpus_start, None)]
    position = weighted_choice(rng, ((POSITIONS[0], 0.6), (POSITIONS[1], 0.4)))
    if chance(rng, JUDGE_STARTS_AT_CORPUS_START):
        start = spec.corpus_start
    else:
        start = _date_within(
            rng, spec.corpus_start, spec.corpus_start + timedelta(days=int(spec.span_days * 0.4))
        )
    end: date | None = None
    if chance(rng, JUDGE_SERVICE_ENDS_SHARE):
        earliest_end = start + timedelta(days=MIN_SERVICE_DAYS)
        if earliest_end <= spec.corpus_end:
            end = _date_within(rng, earliest_end, spec.corpus_end)
    records = [ServiceRecord(home_court, position, start, end)]
    second = chance(rng, JUDGE_SECOND_RECORD_SHARE)
    if not (second or force_second):
        return records
    # A second record: a transfer to another court, or a promotion in place.
    last_day = end if end is not None else spec.corpus_end
    earliest_break = start + timedelta(days=MIN_SERVICE_DAYS)
    latest_break = last_day - timedelta(days=MIN_SERVICE_DAYS)
    if earliest_break > latest_break:
        return records
    break_day = _date_within(rng, earliest_break, latest_break)
    records[0] = ServiceRecord(home_court, position, start, break_day)
    transfer = len(courts) > 1 and (
        position == "circuit_judge" or chance(rng, JUDGE_TRANSFER_SHARE)
    )
    if transfer:
        other = choice(rng, [c for c in courts if c != home_court])
        records.append(ServiceRecord(other, position, break_day + timedelta(days=1), end))
    else:
        records.append(
            ServiceRecord(home_court, "circuit_judge", break_day + timedelta(days=1), end)
        )
    return records


def build_judges(world: World, rng: random.Random, used_names: set[str]) -> None:
    """Judges ``J-0001``..: the first ``courts`` are anchors serving the whole span."""
    spec = world.spec
    courts = world.court_codes
    for index in range(1, spec.judges + 1):
        given, family = unique_name(rng, used_names)
        anchor = index <= spec.courts
        home_court = courts[index - 1] if anchor else choice(rng, courts)
        judge = Judge(
            code=f"J-{index:04d}",
            given=given,
            family=family,
            release_bias=uniform(rng, -0.15, 0.15),
            dismissal_bias=uniform(rng, -0.04, 0.06),
            severity_bias=uniform(rng, 0.7, 1.3),
        )
        # The first non-anchor judge always has two records, so every scale
        # shows a judge with more than one service record.
        judge.services = _service_records(
            rng, spec, home_court, courts, anchor=anchor, force_second=index == spec.courts + 1
        )
        world.judges.append(judge)


def build_persons(world: World, rng: random.Random, used_names: set[str]) -> None:
    """Persons ``P-000001``.. with a unique name, a date of birth, an age band, a propensity."""
    spec = world.spec
    courts = world.court_codes
    for index in range(1, spec.persons + 1):
        given, family = unique_name(rng, used_names)
        band, _, low, high = weighted_choice(rng, tuple((entry, entry[1]) for entry in AGE_BANDS))
        years = randint(rng, low, high)
        date_of_birth = spec.corpus_start - timedelta(days=years * 365 + randint(rng, 0, 364))
        propensity = rng.random() ** PROPENSITY_EXPONENT
        world.persons.append(
            Person(
                true_id=f"P-{index:06d}",
                given=given,
                family=family,
                date_of_birth=date_of_birth,
                age_band=band,
                propensity=propensity,
                home_court=choice(rng, courts),
            )
        )


def build_world(spec: ScaleSpec, seed: int, streams: Streams) -> World:
    world = World(spec=spec, seed=seed, offenses=load_offenses())
    used_names: set[str] = set()
    build_courts(world)
    build_judges(world, streams.world, used_names)
    build_persons(world, streams.persons, used_names)
    for court in world.courts:
        for day in (spec.corpus_start, spec.corpus_end):
            if not world.judges_serving(court.code, day):
                msg = f"{court.code} has no serving judge on {day}"
                raise GenerationError(msg)
    return world
