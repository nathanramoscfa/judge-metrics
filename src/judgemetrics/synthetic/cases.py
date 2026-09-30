# src/judgemetrics/synthetic/cases.py
"""The lifecycle of every case: charges, assignments, decisions, events, sentences.

Each case is simulated from its filed date with seeded offsets from the
``cases`` stream (court, filing, charges, assignments, pretrial decision,
disposition, sentence) and the ``events`` stream (hearings, failures to
appear, bench warrants, revocations, descriptions), in a fixed order per
case. GENERATOR_VERSION 3 plants the judges' effects through
``effects.py``: the initial judge is drawn by the case's observable risk
index and the judges' docket tilts, the release decision and the failure
to appear are logistic in the case's observable features plus the deciding
judge's effect (and, for a failure to appear, the latent propensity and
the filing-age band), and the person's next filing is skewed by the
releasing judge's new-case effect. Each case records what its draws knew
(``Case.draws``) so ``truth.py`` can compute every probability exactly.
Timestamps are strictly ordered by construction::

    filed_at < assignment start < arraignment < pretrial decision
             < disposition <= closed;  sentence > disposition;
    hearings >= pretrial decision + 7 days;  bench warrant > failure to appear;
    revocation >= sentence + 30 days;  a later case is filed >= 14 days after
    the previous case's pretrial decision.

Everything at or after the corpus end (``ScaleSpec.corpus_end_at``) is
truncated the way an export taken on that date would be: charges pending,
the case open, later events absent.
"""

from __future__ import annotations

import random
from bisect import bisect_right
from collections.abc import Sequence
from datetime import UTC, date, datetime, time, timedelta
from itertools import accumulate

from judgemetrics.synthetic.config import MAX_CASES_PER_PERSON, ScaleSpec
from judgemetrics.synthetic.effects import (
    RECOGNIZANCE_SHARE,
    UNPOSTED_BOND_SHARE,
    assignment_weights,
    base_exponent,
    exponent,
    filing_age_band,
    fta_base_logit,
    logistic,
    release_base_logit,
    risk_features,
    risk_index,
    share_below,
)
from judgemetrics.synthetic.model import (
    Assignment,
    Case,
    Charge,
    Decision,
    Draws,
    Event,
    FilingDraw,
    FtaDraw,
    Judge,
    Offense,
    Person,
    ReleaseDraw,
    Sentence,
    World,
)
from judgemetrics.synthetic.rng import (
    Streams,
    chance,
    choice,
    randint,
    skewed_fraction,
    weighted_choice,
)
from judgemetrics.synthetic.vocabulary import (
    FELONY_SEVERITIES,
    MISDEMEANOR_SEVERITIES,
    RELEASE_CONDITIONS,
    SEVERITY_RANK,
)
from judgemetrics.synthetic.world import GenerationError

# Filing: room left at the corpus end for a person's later cases; the minimum
# gap between a case's pretrial decision and the person's next filing; the
# last day any case may be filed (so its assignment lands in the corpus).
LATER_CASE_RESERVE_DAYS = 75
MIN_GAP_DAYS = 14
FILING_MARGIN_DAYS = 3
HOME_COURT_SHARE = 0.65

FELONY_SHARE = 0.45
CHARGE_COUNT_WEIGHTS: tuple[tuple[int, float], ...] = ((1, 0.55), (2, 0.30), (3, 0.15))

STATUTORY_RELEASE_SHARE = 0.10
# Minutes from the pretrial decision to the release (uniform, inclusive): a
# recognizance or statutory release, and a posted bond. The judicial release
# probability and the split are in effects.py (GENERATOR_VERSION 3).
RECOGNIZANCE_RELEASE_MINUTES = (60, 720)
BOND_RELEASE_MINUTES = (120, 120 * 60)
BOND_AMOUNTS: tuple[int, ...] = (500, 1_000, 2_500, 5_000, 10_000, 25_000, 50_000)

DAYS_TO_DISPOSITION = {"felony": (60, 540), "misdemeanor": (20, 240)}
DISPOSITION_SKEW = 1.3
REASSIGNMENT_SHARE = 0.20
TRACK_PLEA = 0.55
TRACK_PROSECUTOR_DISMISSAL = 0.18
TRACK_JUDGE_DISMISSAL = 0.07
TRACK_TRIAL = 0.12
PLEA_DEAL_DISMISSAL_SHARE = 0.70
VERDICT_CONVICTION_SHARE = 0.65

HEARING_COUNT_WEIGHTS: tuple[tuple[int, float], ...] = ((0, 0.20), (1, 0.35), (2, 0.30), (3, 0.15))
HEARINGS_START_AFTER_DAYS = 7
FTA_LEAD_DAYS = 13  # a failure to appear needs this many days before the disposition
REVOCATION_BASE = 0.06
REVOCATION_PROPENSITY_WEIGHT = 0.20
REVOCATION_MAX_DAYS = 540

HEARING_DESCRIPTIONS: tuple[str, ...] = (
    "Status hearing held",
    "Motion hearing held",
    "Pretrial conference held",
    "Discovery status reviewed",
)
ARRAIGNMENT_DESCRIPTION = "Arraignment held; plea of not guilty entered"
FTA_DESCRIPTION = "Defendant failed to appear; hearing continued"
BENCH_WARRANT_DESCRIPTION = "Bench warrant issued for failure to appear"
TRIAL_DESCRIPTION = "Jury trial commenced"
PLEA_DESCRIPTION = "Plea of guilty accepted"
PROSECUTOR_DISMISSAL_DESCRIPTION = "Nolle prosequi entered on the motion of the prosecution"
JUDGE_DISMISSAL_DESCRIPTION = "Motion to dismiss granted"
SENTENCING_DESCRIPTION = "Sentence imposed"
REVOCATION_DESCRIPTION = "Probation revoked after a violation hearing"


def business_time(rng: random.Random, day: date) -> datetime:
    """A moment on ``day`` between 08:00 and 16:59 UTC."""
    return datetime.combine(day, time(hour=randint(rng, 8, 16), minute=randint(rng, 0, 59)), UTC)


def _minutes(rng: random.Random, low: int, high: int) -> timedelta:
    return timedelta(minutes=randint(rng, low, high))


def _later_business_time(
    rng: random.Random, after: datetime, min_days: int, max_days: int
) -> datetime:
    """A business-hours moment ``min_days``..``max_days`` later, strictly after ``after``."""
    days = randint(rng, min_days, max_days)
    if days == 0:
        return after + _minutes(rng, 30, 240)
    return business_time(rng, after.date() + timedelta(days=days))


def allocate_case_counts(persons: list[Person], spec: ScaleSpec, rng: random.Random) -> list[int]:
    """One case each, then the extra cases by propensity, capped per person."""
    counts = [1] * len(persons)
    weights = [0.2 + person.propensity for person in persons]
    cumulative = list(accumulate(weights))
    total = cumulative[-1]
    for _ in range(spec.cases - spec.persons):
        while True:
            index = bisect_right(cumulative, rng.random() * total)
            index = min(index, len(counts) - 1)
            if counts[index] < MAX_CASES_PER_PERSON:
                counts[index] += 1
                break
    return counts


def _pick_court(
    world: World, person: Person, ordinal: int, *, force_other: bool, rng: random.Random
) -> str:
    others = [code for code in world.court_codes if code != person.home_court]
    if ordinal == 0 or not others:
        return person.home_court
    if force_other or not chance(rng, HOME_COURT_SHARE):
        return choice(rng, others)
    return person.home_court


def _latest_filing(spec: ScaleSpec, ordinal: int, total: int) -> date:
    """Every filing leaves room for the person's later cases and its own assignment."""
    remaining = total - 1 - ordinal
    return min(
        spec.corpus_end - timedelta(days=remaining * LATER_CASE_RESERVE_DAYS),
        spec.corpus_end - timedelta(days=FILING_MARGIN_DAYS),
    )


def _first_filed_date(spec: ScaleSpec, total: int, rng: random.Random) -> date:
    first_span = (_latest_filing(spec, 0, total) - spec.corpus_start).days
    return spec.corpus_start + timedelta(days=randint(rng, 0, first_span))


def _later_filing(
    world: World,
    person: Person,
    ordinal: int,
    total: int,
    previous: Case,
    previous_anchor: date,
    rng: random.Random,
) -> tuple[date, FilingDraw]:
    """The next filing day, skewed by the previous case's releasing judge (``FilingDraw``)."""
    latest = _latest_filing(world.spec, ordinal, total)
    earliest = previous_anchor + timedelta(days=MIN_GAP_DAYS)
    if latest < earliest:
        msg = f"{person.true_id}: no room for case {ordinal + 1} of {total} after {previous_anchor}"
        raise GenerationError(msg)
    span = (latest - earliest).days
    decision = previous.pretrial_decision
    judge_code = (
        decision.judge_code
        if decision is not None and decision.judicial_discretionary and decision.released
        else None
    )
    effect = world.judge(judge_code).new_case_effect if judge_code is not None else 0.0
    draws = _draws(previous)
    base = base_exponent(draws.risk_index, person.propensity, draws.filing_age_band)
    fraction = skewed_fraction(rng, exponent(base, effect))
    filed = earliest + timedelta(days=int(fraction * (span + 1)))
    return filed, FilingDraw(previous, judge_code, base, earliest, span)


def _draw_charges(
    world: World, case_type: str, filed_at: datetime, rng: random.Random
) -> list[Charge]:
    severities = FELONY_SEVERITIES if case_type == "felony" else MISDEMEANOR_SEVERITIES
    same_class = [o for o in world.offenses if o.severity in severities]
    pool = world.offenses if case_type == "felony" else same_class
    count = weighted_choice(rng, CHARGE_COUNT_WEIGHTS)
    offenses: list[Offense] = [choice(rng, same_class)]
    offenses.extend(choice(rng, pool) for _ in range(count - 1))
    return [Charge(offense=offense, filed_at=filed_at) for offense in offenses]


def _lead_offense(charges: list[Charge]) -> Charge:
    return min(charges, key=lambda c: SEVERITY_RANK[c.offense.severity])


def _draws(case: Case) -> Draws:
    if case.draws is None:  # pragma: no cover - generate_case records the draws first
        msg = f"a case of {case.person.true_id} has no draw record"
        raise GenerationError(msg)
    return case.draws


def _bond_amount(case: Case, rng: random.Random) -> int:
    lead = _lead_offense(case.charges)
    rank = SEVERITY_RANK[lead.offense.severity]
    # More severe lead charges draw from the upper end of the schedule.
    low = max(0, len(BOND_AMOUNTS) - 3 - rank)
    return choice(rng, BOND_AMOUNTS[low : low + 3])


def released_before(case_type: str, decision_at: datetime, end_at: datetime) -> float:
    """The chance a judicial release decided at ``decision_at`` takes effect before ``end_at``."""
    gap = (end_at - decision_at) // timedelta(minutes=1)
    recognizance = RECOGNIZANCE_SHARE[case_type]
    return recognizance * share_below(*RECOGNIZANCE_RELEASE_MINUTES, gap) + (
        1.0 - recognizance
    ) * share_below(*BOND_RELEASE_MINUTES, gap)


def _pretrial_decision(
    case: Case, judge: Judge, decision_at: datetime, end_at: datetime, rng: random.Random
) -> Decision:
    if chance(rng, STATUTORY_RELEASE_SHARE):
        return Decision(
            decision_type="pretrial_release",
            decision_at=decision_at,
            actor="legislature_or_mandatory_rule",
            discretion="mandatory",
            judge_code=None,
            release_type="statutory",
            detained=False,
            release_at=decision_at + _minutes(rng, *RECOGNIZANCE_RELEASE_MINUTES),
        )
    draws = _draws(case)
    base = release_base_logit(case.case_type, draws.features)
    draws.release = ReleaseDraw(
        judge.code, base, released_before(case.case_type, decision_at, end_at)
    )
    decision = Decision(
        decision_type="pretrial_release",
        decision_at=decision_at,
        actor="judge",
        discretion="discretionary",
        judge_code=judge.code,
    )
    if chance(rng, logistic(base + judge.leniency)):
        decision.detained = False
        if chance(rng, RECOGNIZANCE_SHARE[case.case_type]):
            decision.release_type = "recognizance"
            decision.release_at = decision_at + _minutes(rng, *RECOGNIZANCE_RELEASE_MINUTES)
        else:
            decision.release_type = "monetary_bond"
            decision.bond_amount = _bond_amount(case, rng)
            decision.release_at = decision_at + _minutes(rng, *BOND_RELEASE_MINUTES)
        decision.conditions = _conditions(rng)
    elif chance(rng, UNPOSTED_BOND_SHARE[case.case_type]):
        decision.release_type = "monetary_bond"
        decision.bond_amount = _bond_amount(case, rng)
        decision.detained = True
    else:
        decision.release_type = "detained"
        decision.detained = True
    return decision


def _conditions(rng: random.Random) -> tuple[str, ...]:
    count = weighted_choice(rng, ((0, 0.4), (1, 0.4), (2, 0.2)))
    chosen: list[str] = []
    for _ in range(count):
        condition = choice(rng, RELEASE_CONDITIONS)
        if condition not in chosen:
            chosen.append(condition)
    return tuple(sorted(chosen))


def _build_assignments(
    world: World,
    case: Case,
    initial: Judge,
    start_at: datetime,
    planned: tuple[datetime, Judge] | None,
) -> None:
    """Assignments from the initial judge, breaking at a planned reassignment
    and whenever the sitting judge's service at the court ends."""
    end_at = world.spec.corpus_end_at
    current = initial
    current_start = start_at
    assignment_type = "initial"
    planned_pending = planned
    while True:
        breaks: list[tuple[datetime, Judge | None]] = []
        served_until = current.serving_until(case.court_code, current_start.date())
        if served_until is not None:
            service_break = datetime.combine(served_until + timedelta(days=1), time(0, 0), UTC)
            if service_break < end_at:
                breaks.append((service_break, None))
        if (
            planned_pending is not None
            and planned_pending[0] > current_start
            and planned_pending[0] < end_at
        ):
            breaks.append(planned_pending)
        if not breaks:
            case.assignments.append(Assignment(current.code, assignment_type, current_start, None))
            return
        break_at, replacement = min(breaks, key=lambda item: item[0])
        if replacement is None:
            candidates = [
                j
                for j in world.judges_serving(case.court_code, break_at.date())
                if j is not current
            ]
            if not candidates:
                msg = f"{case.court_code} has no replacement judge on {break_at.date()}"
                raise GenerationError(msg)
            replacement = candidates[0]
        else:
            planned_pending = None
        case.assignments.append(Assignment(current.code, assignment_type, current_start, break_at))
        current = replacement
        current_start = break_at
        assignment_type = "reassignment"


def _finalize_assignments(case: Case, case_end_at: datetime | None) -> None:
    """Trim the assignment chain at the case's closing (or leave it open)."""
    if case_end_at is None:
        return
    kept: list[Assignment] = []
    for assignment in case.assignments:
        if assignment.start_at >= case_end_at:
            continue
        if assignment.end_at is None or assignment.end_at > case_end_at:
            assignment.end_at = case_end_at
        kept.append(assignment)
    case.assignments = kept


def _judge_at(world: World, case: Case, moment: datetime) -> Judge:
    code = case.assigned_judge_at(moment)
    if code is None:
        msg = f"no judge assigned to a case of {case.person.true_id} at {moment.isoformat()}"
        raise GenerationError(msg)
    return world.judge(code)


def _dispose_charges(case: Case, judge: Judge, disposed_at: datetime, rng: random.Random) -> str:
    judge_dismissal = max(0.01, TRACK_JUDGE_DISMISSAL + judge.dismissal_bias)
    track = weighted_choice(
        rng,
        (
            ("plea", TRACK_PLEA),
            ("prosecutor_dismissal", TRACK_PROSECUTOR_DISMISSAL),
            ("judge_dismissal", judge_dismissal),
            ("trial", TRACK_TRIAL),
        ),
    )
    lead = _lead_offense(case.charges)
    for charge in case.charges:
        charge.disposed_at = disposed_at
        if track == "plea":
            if charge is lead or not chance(rng, PLEA_DEAL_DISMISSAL_SHARE):
                charge.disposition, charge.disposition_actor = "convicted_plea", "judge"
            else:
                charge.disposition, charge.disposition_actor = "dismissed", "prosecutor"
        elif track == "prosecutor_dismissal":
            charge.disposition, charge.disposition_actor = "dismissed", "prosecutor"
        elif track == "judge_dismissal":
            charge.disposition, charge.disposition_actor = "dismissed", "judge"
        elif chance(rng, VERDICT_CONVICTION_SHARE):
            charge.disposition, charge.disposition_actor = "convicted_verdict", "jury"
        else:
            charge.disposition, charge.disposition_actor = "acquitted", "jury"
    return track


def _disposition_decisions(case: Case, judge: Judge, disposed_at: datetime, track: str) -> None:
    actors = {c.disposition_actor for c in case.charges if c.disposition == "dismissed"}
    for actor in sorted(a for a in actors if a is not None):
        case.decisions.append(
            Decision(
                decision_type="dismissal",
                decision_at=disposed_at,
                actor=actor,
                discretion="discretionary" if actor == "judge" else "non_judicial",
                judge_code=judge.code if actor == "judge" else None,
            )
        )
    if any(
        c.disposition in ("convicted_plea", "convicted_verdict", "acquitted") for c in case.charges
    ):
        if track == "trial":
            case.decisions.append(
                Decision("disposition", disposed_at, "jury", "non_judicial", None)
            )
        else:
            case.decisions.append(
                Decision("disposition", disposed_at, "judge", "discretionary", judge.code)
            )


def _disposition_event(case: Case, judge: Judge, disposed_at: datetime, track: str) -> Event:
    if track == "plea":
        return Event("plea_hearing", disposed_at, "judge", judge.code, PLEA_DESCRIPTION)
    if track == "prosecutor_dismissal":
        return Event(
            "hearing", disposed_at, "prosecutor", judge.code, PROSECUTOR_DISMISSAL_DESCRIPTION
        )
    if track == "judge_dismissal":
        return Event("hearing", disposed_at, "judge", judge.code, JUDGE_DISMISSAL_DESCRIPTION)
    return Event("hearing", disposed_at, "judge", judge.code, "Verdict returned")


def _sentence(case: Case, judge: Judge, sentence_at: datetime, rng: random.Random) -> Sentence:
    lead = case.lead_convicted_charge
    severity = lead.offense.severity if lead is not None else "misdemeanor_b"
    incarceration_ranges = {
        "felony_1": (0.95, 365, 2000),
        "felony_2": (0.80, 90, 900),
        "felony_3": (0.50, 30, 365),
        "misdemeanor_a": (0.25, 1, 90),
        "misdemeanor_b": (0.10, 1, 30),
    }
    probation_ranges = {
        "felony_1": (0.30, 365, 1095),
        "felony_2": (0.60, 365, 1095),
        "felony_3": (0.75, 180, 730),
        "misdemeanor_a": (0.70, 90, 365),
        "misdemeanor_b": (0.50, 60, 365),
    }
    fine_range = (0.40, 500, 10_000) if severity.startswith("felony") else (0.70, 100, 2_500)
    incarceration: int | None = None
    probation: int | None = None
    fine: int | None = None
    share, low, high = incarceration_ranges[severity]
    if chance(rng, share):
        incarceration = max(1, round(randint(rng, low, high) * judge.severity_bias))
    share, low, high = probation_ranges[severity]
    if chance(rng, share):
        probation = randint(rng, low, high)
    share, low, high = fine_range
    if chance(rng, share):
        fine = randint(rng, low // 50, high // 50) * 50
    if incarceration is None and probation is None and fine is None:
        probation = probation_ranges[severity][1]
    components = tuple(
        name
        for name, value in (
            ("incarceration", incarceration),
            ("probation", probation),
            ("fine", fine),
        )
        if value is not None
    )
    return Sentence(judge.code, sentence_at, incarceration, probation, fine, components)


def _hearings(
    case: Case,
    world: World,
    decision_at: datetime,
    disposed_at: datetime,
    rng: random.Random,
) -> list[Event]:
    first_day = decision_at.date() + timedelta(days=HEARINGS_START_AFTER_DAYS)
    last_day = disposed_at.date() - timedelta(days=1)
    count = weighted_choice(rng, HEARING_COUNT_WEIGHTS)
    window = (last_day - first_day).days + 1
    if window < 1:
        return []
    count = min(count, window)
    days: list[date] = []
    while len(days) < count:
        day = first_day + timedelta(days=randint(rng, 0, window - 1))
        if day not in days:
            days.append(day)
    events: list[Event] = []
    for day in sorted(days):
        at = business_time(rng, day)
        judge = _judge_at(world, case, at)
        events.append(Event("hearing", at, "judge", judge.code, choice(rng, HEARING_DESCRIPTIONS)))
    return events


def _plant_failure_to_appear(
    case: Case,
    world: World,
    hearings: list[Event],
    decision_at: datetime,
    disposed_at: datetime,
    rng: random.Random,
) -> None:
    decision = case.pretrial_decision
    if decision is None or not decision.released:
        return
    judge_code = decision.judge_code if decision.judicial_discretionary else None
    effect = world.judge(judge_code).fta_effect if judge_code is not None else 0.0
    draws = _draws(case)
    base = fta_base_logit(draws.features, case.person.propensity, draws.filing_age_band)
    latest_day = disposed_at.date() - timedelta(days=FTA_LEAD_DAYS)
    candidates = [event for event in hearings if event.event_at.date() <= latest_day]
    first_day = decision_at.date() + timedelta(days=HEARINGS_START_AFTER_DAYS)
    if candidates:
        draws.fta = FtaDraw(judge_code, base, candidates[0].event_at, None, None)
    elif first_day <= latest_day:
        draws.fta = FtaDraw(judge_code, base, None, first_day, latest_day)
    else:
        draws.fta = FtaDraw(judge_code, base, None, None, None)
    if not chance(rng, logistic(base + effect)):
        return
    if candidates:
        target = candidates[0]
    else:
        if first_day > latest_day:
            return
        day = first_day + timedelta(days=randint(rng, 0, (latest_day - first_day).days))
        at = business_time(rng, day)
        target = Event("hearing", at, "judge", _judge_at(world, case, at).code, "")
        hearings.append(target)
    target.event_type = "failure_to_appear"
    target.actor = "defense"
    target.description = FTA_DESCRIPTION
    warrant_at = business_time(rng, target.event_at.date() + timedelta(days=randint(rng, 1, 10)))
    judge = _judge_at(world, case, warrant_at)
    hearings.append(
        Event("bench_warrant", warrant_at, "judge", judge.code, BENCH_WARRANT_DESCRIPTION)
    )


def _truncate(case: Case, corpus_end_at: datetime) -> None:
    """Apply the export-date view: nothing at or after the corpus end exists yet."""
    case.events = [event for event in case.events if event.event_at < corpus_end_at]
    case.decisions = [d for d in case.decisions if d.decision_at < corpus_end_at]
    case.assignments = [a for a in case.assignments if a.start_at < corpus_end_at]
    for assignment in case.assignments:
        if assignment.end_at is not None and assignment.end_at >= corpus_end_at:
            assignment.end_at = None
    decision = case.pretrial_decision
    if decision is not None and decision.release_at is not None:
        if decision.release_at >= corpus_end_at:
            decision.release_at = None
            decision.detained = True
    for charge in case.charges:
        if charge.disposed_at is not None and charge.disposed_at >= corpus_end_at:
            charge.disposed_at = None
            charge.disposition = "pending"
            charge.disposition_actor = None
    if case.sentence is not None and case.sentence.sentence_at >= corpus_end_at:
        case.sentence = None


def generate_case(
    world: World,
    person: Person,
    ordinal: int,
    total: int,
    previous_anchor: date | None,
    *,
    force_other_court: bool,
    streams: Streams,
    previous: Case | None = None,
    history: Sequence[Case] = (),
) -> Case:
    """One case of ``person``; ``previous`` and ``history`` are the person's earlier cases."""
    spec = world.spec
    rng = streams.cases
    ev = streams.events
    court_code = _pick_court(world, person, ordinal, force_other=force_other_court, rng=rng)
    filing: FilingDraw | None = None
    if ordinal == 0 or previous is None or previous_anchor is None:
        filed_date = _first_filed_date(spec, total, rng)
    else:
        filed_date, filing = _later_filing(
            world, person, ordinal, total, previous, previous_anchor, rng
        )
    filed_at = business_time(rng, filed_date)
    case_type = "felony" if chance(rng, FELONY_SHARE) else "misdemeanor"
    case = Case(
        person=person,
        ordinal=ordinal,
        court_code=court_code,
        case_type=case_type,
        filed_date=filed_date,
        filed_at=filed_at,
    )
    case.charges = _draw_charges(world, case_type, filed_at, rng)
    features = risk_features(case, history)
    index = risk_index(features)
    case.draws = Draws(features, index, filing_age_band(case), filing=filing)

    assign_at = _later_business_time(rng, filed_at, 0, 2)
    # The initial judge by the observable risk index alone (planted confounding).
    initial = weighted_choice(
        rng, assignment_weights(world.judges_serving(court_code, assign_at.date()), index)
    )
    arraignment_at = _later_business_time(rng, assign_at, 1, 5)
    decision_at = _later_business_time(rng, arraignment_at, 0, 3)
    pretrial = _pretrial_decision(case, initial, decision_at, spec.corpus_end_at, rng)
    case.decisions.append(pretrial)
    case.events.append(
        Event("arraignment", arraignment_at, "judge", initial.code, ARRAIGNMENT_DESCRIPTION)
    )

    low, high = DAYS_TO_DISPOSITION[case_type]
    days = low + int(skewed_fraction(rng, DISPOSITION_SKEW) * (high - low + 1))
    disposed_at = business_time(rng, decision_at.date() + timedelta(days=days))

    planned: tuple[datetime, Judge] | None = None
    if chance(rng, REASSIGNMENT_SHARE):
        first_day = decision_at.date() + timedelta(days=1)
        last_day = disposed_at.date() - timedelta(days=1)
        if first_day <= last_day:
            day = first_day + timedelta(days=randint(rng, 0, (last_day - first_day).days))
            reassign_at = business_time(rng, day)
            alternatives = [
                j for j in world.judges_serving(court_code, reassign_at.date()) if j is not initial
            ]
            if alternatives:
                planned = (reassign_at, choice(rng, alternatives))
    _build_assignments(world, case, initial, assign_at, planned)

    disposing_judge = _judge_at(world, case, disposed_at)
    track = _dispose_charges(case, disposing_judge, disposed_at, rng)
    _disposition_decisions(case, disposing_judge, disposed_at, track)
    case.events.append(_disposition_event(case, disposing_judge, disposed_at, track))
    if track == "trial":
        trial_at = business_time(rng, disposed_at.date() - timedelta(days=randint(rng, 1, 4)))
        case.events.append(
            Event(
                "trial", trial_at, "judge", _judge_at(world, case, trial_at).code, TRIAL_DESCRIPTION
            )
        )

    closed_at = disposed_at
    if any(c.convicted for c in case.charges):
        gap_days = randint(rng, 0, 60)
        if gap_days == 0:
            sentence_at = disposed_at + _minutes(rng, 30, 180)
        else:
            sentence_at = business_time(rng, disposed_at.date() + timedelta(days=gap_days))
        sentencing_judge = _judge_at(world, case, sentence_at)
        case.sentence = _sentence(case, sentencing_judge, sentence_at, rng)
        case.decisions.append(
            Decision("sentencing", sentence_at, "judge", "discretionary", sentencing_judge.code)
        )
        case.events.append(
            Event(
                "sentencing_hearing",
                sentence_at,
                "judge",
                sentencing_judge.code,
                SENTENCING_DESCRIPTION,
            )
        )
        closed_at = sentence_at

    hearings = _hearings(case, world, decision_at, disposed_at, ev)
    _plant_failure_to_appear(case, world, hearings, decision_at, disposed_at, ev)
    case.events.extend(hearings)

    if case.sentence is not None and case.sentence.probation_days:
        if chance(ev, REVOCATION_BASE + REVOCATION_PROPENSITY_WEIGHT * person.propensity):
            span = min(case.sentence.probation_days, REVOCATION_MAX_DAYS)
            if span >= 30:
                day = closed_at.date() + timedelta(days=randint(ev, 30, span))
                case.events.append(
                    Event(
                        "revocation",
                        business_time(ev, day),
                        "judge",
                        case.sentence.judge_code,
                        REVOCATION_DESCRIPTION,
                    )
                )

    if closed_at < spec.corpus_end_at:
        case.status = "closed"
        case.closed_date = closed_at.date()
        _finalize_assignments(case, closed_at)
    else:
        case.status = "open"
        case.closed_date = None
    _truncate(case, spec.corpus_end_at)
    return case


def build_cases(world: World, streams: Streams) -> None:
    """Every person's cases in id order; the first split candidates get a second court."""
    spec = world.spec
    counts = allocate_case_counts(world.persons, spec, streams.cases)
    reserved = 0
    for person, total in zip(world.persons, counts, strict=True):
        force_cross_court = False
        if total >= 2 and reserved < spec.split_person_pairs and len(world.courts) > 1:
            force_cross_court = True
            reserved += 1
        previous_anchor: date | None = None
        history: list[Case] = []
        for ordinal in range(total):
            case = generate_case(
                world,
                person,
                ordinal,
                total,
                previous_anchor,
                force_other_court=force_cross_court and ordinal == 1,
                streams=streams,
                previous=history[-1] if history else None,
                history=history,
            )
            world.cases.append(case)
            history.append(case)
            decision = case.pretrial_decision
            anchor_at = (
                decision.decision_at if decision is not None else case.filed_at + timedelta(days=10)
            )
            previous_anchor = anchor_at.date()
    if reserved < spec.split_person_pairs and len(world.courts) > 1:
        msg = f"only {reserved} persons with two or more cases; {spec.split_person_pairs} splits needed"
        raise GenerationError(msg)
