# src/judgemetrics/synthetic/model.py
"""The in-memory world the generator builds before anything is written.

Plain mutable dataclasses: ``world.py`` fills courts, judges, and persons,
``cases.py`` fills cases with their children, ``edge_cases.py`` mutates and
marks them, ``truth.py`` reads them, and ``writer.py`` renders them. Every
timestamp is a timezone-aware UTC ``datetime``; every identifier is a
formatted counter assigned by ``assign_identifiers`` in a fixed order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from judgemetrics.synthetic.config import ScaleSpec
from judgemetrics.synthetic.wordlists import full_name

JURISDICTION_NAME = "Synthetic State"
JURISDICTION_TYPE = "state"
STATE_CODE = "ZZ"
COURT_TYPE = "circuit"


@dataclass(slots=True)
class Offense:
    statute_code: str
    description: str
    offense_category: str
    severity: str
    violent_flag: bool


@dataclass(slots=True)
class Court:
    code: str
    name: str
    court_type: str = COURT_TYPE
    jurisdiction: str = JURISDICTION_NAME
    state_code: str = STATE_CODE


@dataclass(slots=True)
class ServiceRecord:
    court_code: str
    position: str
    start_date: date
    end_date: date | None

    def covers(self, day: date) -> bool:
        return self.start_date <= day and (self.end_date is None or day <= self.end_date)


@dataclass(slots=True)
class Judge:
    code: str
    given: str
    family: str
    services: list[ServiceRecord] = field(default_factory=list)
    # Latent tendencies (Phase 4's planted effects): added to the recognizance
    # share, added to the judicial-dismissal share, multiplied into
    # incarceration lengths.
    release_bias: float = 0.0
    dismissal_bias: float = 0.0
    severity_bias: float = 1.0

    @property
    def full_name(self) -> str:
        return full_name(self.given, self.family)

    def serves(self, court_code: str, day: date) -> bool:
        return any(s.court_code == court_code and s.covers(day) for s in self.services)

    def serving_until(self, court_code: str, day: date) -> date | None:
        """Last day of continuous service at ``court_code`` from ``day``; None if open-ended."""
        records = sorted(
            (s for s in self.services if s.court_code == court_code), key=lambda s: s.start_date
        )
        end: date | None = None
        found = False
        for record in records:
            if not found:
                if record.covers(day):
                    found = True
                    end = record.end_date
                continue
            if end is None:
                break
            if record.start_date <= end + timedelta(days=1):
                end = None if record.end_date is None else max(end, record.end_date)
        if not found:
            msg = f"{self.code} does not serve at {court_code} on {day}"
            raise ValueError(msg)
        return end


@dataclass(slots=True)
class Person:
    true_id: str
    given: str
    family: str
    date_of_birth: date
    age_band: str
    propensity: float
    home_court: str
    dob_known: bool = True
    # Source participant ids by alias (0 = the primary id; a split person
    # carries alias 1 for the cases of its second court).
    participant_ids: dict[int, str] = field(default_factory=dict)

    @property
    def full_name(self) -> str:
        return full_name(self.given, self.family)

    def age_on(self, day: date) -> int:
        years = day.year - self.date_of_birth.year
        if (day.month, day.day) < (self.date_of_birth.month, self.date_of_birth.day):
            years -= 1
        return years


@dataclass(slots=True)
class Charge:
    offense: Offense
    filed_at: datetime
    charge_id: str = ""
    disposed_at: datetime | None = None
    # A vocabulary value, "pending" for an open case, or None when the source
    # row carries no disposition (the planted missing-data example).
    disposition: str | None = None
    disposition_actor: str | None = None

    @property
    def disposed(self) -> bool:
        return self.disposed_at is not None and self.disposition not in (None, "pending")

    @property
    def convicted(self) -> bool:
        return self.disposition in ("convicted_plea", "convicted_verdict")


@dataclass(slots=True)
class Assignment:
    judge_code: str
    assignment_type: str
    start_at: datetime
    end_at: datetime | None
    assignment_id: str = ""

    def active_at(self, moment: datetime) -> bool:
        return self.start_at <= moment and (self.end_at is None or moment < self.end_at)


@dataclass(slots=True)
class Event:
    event_type: str
    event_at: datetime
    actor: str | None
    judge_code: str | None
    description: str | None
    event_id: str = ""


@dataclass(slots=True)
class Decision:
    decision_type: str
    decision_at: datetime
    actor: str
    discretion: str
    judge_code: str | None
    decision_id: str = ""
    release_type: str | None = None
    bond_amount: int | None = None
    detained: bool | None = None
    release_at: datetime | None = None
    conditions: tuple[str, ...] = ()

    @property
    def released(self) -> bool:
        return self.decision_type == "pretrial_release" and self.detained is False

    @property
    def judicial_discretionary(self) -> bool:
        return self.actor == "judge" and self.discretion == "discretionary"


@dataclass(slots=True)
class Sentence:
    judge_code: str
    sentence_at: datetime
    incarceration_days: int | None
    probation_days: int | None
    fine_amount: int | None
    components: tuple[str, ...]
    sentence_id: str = ""


@dataclass(slots=True)
class Case:
    person: Person
    ordinal: int  # 0-based index among the person's cases, chronological
    court_code: str
    case_type: str
    filed_date: date
    filed_at: datetime
    case_number: str = ""
    participant_alias: int = 0
    closed_date: date | None = None
    status: str = "open"
    related_case_number: str | None = None
    charges: list[Charge] = field(default_factory=list)
    assignments: list[Assignment] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)
    sentence: Sentence | None = None
    # Set by the edge-case planter: the writer emits a second, reformatted copy.
    duplicate: bool = False

    @property
    def participant_id(self) -> str:
        return self.person.participant_ids[self.participant_alias]

    def assigned_judge_at(self, moment: datetime) -> str | None:
        for assignment in self.assignments:
            if assignment.active_at(moment):
                return assignment.judge_code
        return None

    @property
    def pretrial_decision(self) -> Decision | None:
        for decision in self.decisions:
            if decision.decision_type == "pretrial_release":
                return decision
        return None

    @property
    def disposition_at(self) -> datetime | None:
        """The case-level disposition time: the latest disposed charge."""
        times = [c.disposed_at for c in self.charges if c.disposed and c.disposed_at is not None]
        return max(times) if times else None

    @property
    def lead_convicted_charge(self) -> Charge | None:
        """The most severe convicted charge (ties broken by charge id)."""
        from judgemetrics.synthetic.vocabulary import SEVERITY_RANK

        convicted = [c for c in self.charges if c.convicted]
        if not convicted:
            return None
        return min(convicted, key=lambda c: (SEVERITY_RANK[c.offense.severity], c.charge_id))

    def sort_key(self) -> tuple[datetime, str, int]:
        return (self.filed_at, self.person.true_id, self.ordinal)


@dataclass(slots=True)
class World:
    spec: ScaleSpec
    seed: int
    courts: list[Court] = field(default_factory=list)
    judges: list[Judge] = field(default_factory=list)
    persons: list[Person] = field(default_factory=list)
    cases: list[Case] = field(default_factory=list)
    offenses: list[Offense] = field(default_factory=list)

    @property
    def court_codes(self) -> list[str]:
        return [court.code for court in self.courts]

    def judges_serving(self, court_code: str, day: date) -> list[Judge]:
        return [judge for judge in self.judges if judge.serves(court_code, day)]

    def judge(self, code: str) -> Judge:
        for judge in self.judges:
            if judge.code == code:
                return judge
        msg = f"unknown judge {code}"
        raise KeyError(msg)

    def cases_of(self, person: Person) -> list[Case]:
        return sorted((c for c in self.cases if c.person is person), key=Case.sort_key)


def assign_identifiers(world: World) -> None:
    """Number every case and row in a fixed order: filed time, person, ordinal.

    Case numbers are ``SYN-<year>-<seq>`` with the sequence restarting each
    filing year; row ids (``AS-``, ``CH-``, ``EV-``, ``DC-``, ``SN-``) are
    global counters in the same order; participant ids (``PT-``) are assigned
    on a person's first appearance.
    """
    world.cases.sort(key=Case.sort_key)
    per_year: dict[int, int] = {}
    assignment_seq = charge_seq = event_seq = decision_seq = sentence_seq = 0
    participant_seq = 0
    for case in world.cases:
        year = case.filed_date.year
        per_year[year] = per_year.get(year, 0) + 1
        case.case_number = f"SYN-{year}-{per_year[year]:06d}"
        if case.participant_alias not in case.person.participant_ids:
            participant_seq += 1
            case.person.participant_ids[case.participant_alias] = f"PT-{participant_seq:06d}"
        for assignment in case.assignments:
            assignment_seq += 1
            assignment.assignment_id = f"AS-{assignment_seq:06d}"
        for charge in case.charges:
            charge_seq += 1
            charge.charge_id = f"CH-{charge_seq:06d}"
        case.events.sort(key=lambda e: (e.event_at, e.event_type))
        for event in case.events:
            event_seq += 1
            event.event_id = f"EV-{event_seq:06d}"
        case.decisions.sort(key=lambda d: (d.decision_at, d.decision_type, d.actor))
        for decision in case.decisions:
            decision_seq += 1
            decision.decision_id = f"DC-{decision_seq:06d}"
        if case.sentence is not None:
            sentence_seq += 1
            case.sentence.sentence_id = f"SN-{sentence_seq:06d}"


def next_participant_id(world: World) -> str:
    """The next unused ``PT-`` id (used by the split-person plant)."""
    used = {pid for person in world.persons for pid in person.participant_ids.values()}
    return f"PT-{len(used) + 1:06d}"
