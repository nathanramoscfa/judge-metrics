# src/judgemetrics/synthetic/truth.py
"""``truth/``: what the simulation knows that the source files do not say.

- ``persons.csv`` — the true identity behind every participant id and court;
- ``subsequent_events.csv`` — every true later event after every index event;
- ``resolution_expectations.csv`` — the decision Step 3 must reach for every
  planted person pair;
- ``planted.csv`` — every planted edge case with the ids involved and the
  pipeline behaviour it must produce;
- ``metrics.json`` — the Phase 3 metric set computed from truth, per judge
  and per court, each metric with numerator, denominator, and definition,
  and (``TRUTH_VERSION`` 2) the windowed cohorts of every index kind:
  fixed-window rates and Kaplan-Meier estimates per outcome and window,
  with exposure deferred by every incarceration term of the person
  (``TRUTH_VERSION`` 3), exactly as docs/METHODOLOGY.md states; the
  outcomes the source cannot document are listed under ``not_observable``;
- ``effects.json`` (``TRUTH_VERSION`` 3) — every planted parameter, every
  judge's effects raw and centered on its courts, and per judge, target,
  and window the cohort, the observed count, and the oracle expected counts
  with the judge's effect (``sum(p)``) and with it replaced by the
  case-weighted mean effect of the court's judges (``sum(p0)``); per-judge
  and per-band aggregates only, never a per-person row;
- ``README.md`` — how to read the files and the hand-checkable planted list.

``truth/`` documents the simulation; it never enters the database (Step 2's
connector discovers ``source/`` only). ``TRUTH_VERSION`` is bumped whenever
a truth file's schema or a metric definition changes. The windowed
arithmetic here is an independent oracle: it imports nothing from
``judgemetrics.metrics`` and the golden suite compares the two.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from judgemetrics.synthetic.config import GENERATOR_VERSION
from judgemetrics.synthetic.edge_cases import KINDS, Plants
from judgemetrics.synthetic.effects import (
    EXPONENT_AGE,
    FTA_AGE,
    before,
    exponent,
    logistic,
    parameters,
    skewed_cdf,
    uniform_cdf,
    window_probability,
)
from judgemetrics.synthetic.effects import home_court as judge_home_court
from judgemetrics.synthetic.model import Case, Charge, Decision, Draws, Judge, Sentence, World
from judgemetrics.synthetic.vocabulary import FINAL_CHARGE_DISPOSITIONS, SYNTHETIC_GROUPS
from judgemetrics.synthetic.world import GenerationError
from judgemetrics.synthetic.writer import fmt_ts, write_csv, write_json, write_text

TRUTH_VERSION = "3"

WINDOWS_DAYS: tuple[int, ...] = (30, 90, 180, 365, 730, 1095)
# The outcomes the synthetic source documents, in the order metrics.json lists them.
WINDOWED_OUTCOMES: tuple[str, ...] = (
    "failure_to_appear",
    "new_case",
    "new_charge",
    "reconviction",
    "revocation",
)
INDEX_KINDS: tuple[str, ...] = ("pretrial_release", "disposition", "sentence")
# The justice_event_type values no synthetic row ever records.
NOT_OBSERVABLE: tuple[str, ...] = ("release_violation", "rearrest")
NOT_OBSERVABLE_REASON = "the synthetic source records no such event"
# Outcomes counted only when they occur in another case of the same person.
OTHER_CASE_OUTCOMES: frozenset[str] = frozenset({"new_case", "new_charge", "reconviction"})
# The 97.5th percentile of the standard normal distribution (a 95% interval).
Z_95 = 1.959964
# The planted list is written in full below this many items; above it, counts per kind.
README_PLANTED_LIST_LIMIT = 100

TRUTH_FILES: tuple[str, ...] = (
    "persons.csv",
    "subsequent_events.csv",
    "resolution_expectations.csv",
    "planted.csv",
    "metrics.json",
    "effects.json",
    "README.md",
)
PERSONS_HEADER = ("true_person_id", "participant_id", "court_code")
SUBSEQUENT_HEADER = (
    "true_person_id",
    "index_case_number",
    "index_event_type",
    "index_at",
    "outcome_type",
    "outcome_at",
    "days_after",
)
EXPECTATIONS_HEADER = (
    "left_participant_id",
    "right_participant_id",
    "expected_decision",
    "reason",
)
PLANTED_HEADER = ("kind", "ids", "expected_behaviour")

DEFINITIONS: dict[str, str] = {
    "eligible_cases": (
        "Judge: cases with at least one assignment of the judge. Court: cases filed in the "
        "court. Duplicate source records count once."
    ),
    "eligible_defendants": "Distinct true persons among the eligible cases.",
    "pretrial.decisions": (
        "Pretrial decisions attributed to the subject under the attribution gate: "
        "decision_type pretrial_release, actor judge, discretion discretionary (judge: the "
        "deciding judge; court: decided in the court). Statutory releases "
        "(legislature_or_mandatory_rule, mandatory) and decisions with an unknown actor are "
        "excluded."
    ),
    "pretrial.released_count": "Attributed pretrial decisions with detained = false.",
    "pretrial.detained_count": "Attributed pretrial decisions with detained = true.",
    "pretrial.release_share": "released_count / (released_count + detained_count).",
    "pretrial.statutory_release_count": (
        "Court only: pretrial decisions with actor legislature_or_mandatory_rule and "
        "discretion mandatory (never attributed to a judge)."
    ),
    "pretrial.unknown_actor_count": (
        "Court only: pretrial decisions with actor unknown (the planted missing-judge examples)."
    ),
    "pretrial.windows": (
        "The pretrial_release entry of index_events, repeated here for continuity: for each "
        "window w in days: cohort = attributed released decisions (index_at = release_at; "
        "exposure_start = index_at deferred by every incarceration term of the person that "
        "contains it, as index_events states); followed = cohort members with exposure_start "
        "+ w days strictly before the corpus end (corpus.end_exclusive_at); numerator = "
        "followed members with at least one outcome of the type in (exposure_start, "
        "exposure_start + w days]; value = numerator / "
        "followed (null when followed is 0). failure_to_appear and revocation count events "
        "in any case of the person; new_case counts another case's filed_at, new_charge "
        "another case's charge filed_at, and reconviction a convicted charge's disposed_at "
        "in another case of the person."
    ),
    "index_events": (
        "Per index kind, the windowed cohort. pretrial_release: attributed released "
        "decisions (the pretrial.decisions gate; index_at = release_at); disposition: "
        "disposed cases at the case disposition time, attributed to the judge assigned at "
        "that time (court: the court's disposed cases), one member per defendant; sentence: "
        "attributed sentences at sentence_at (judge: the sentencing judge; court: the "
        "court's cases). Exposure starts at index_at; for the disposition kind it starts at "
        "the end of the index case's own incarceration term (sentence_at + "
        "incarceration_days, the latest when there are several) when its sentence carries a "
        "positive incarceration_days. Then, for every kind, while an incarceration term "
        "[sentence_at, sentence_at + incarceration_days) of the person in any case contains "
        "the exposure start, the start moves to that term's end (the containing term that "
        "ends last). Per window w: cohort; followed = members with exposure_start + w days strictly before "
        "corpus.end_exclusive_at; <outcome>_rate = followed members with an outcome in "
        "(exposure_start, exposure_start + w days] over the followed members; "
        "<outcome>_survival = 1 - S(w) at six decimals, the Kaplan-Meier product-limit "
        "survival over the whole cohort with each member's time to its first outcome (an "
        "event) or to the corpus end (a censoring), events counted before censorings at "
        "the same time, S = 0 once every member at risk fails, with events (at or before "
        "w), censored (strictly before w), at_risk (the rest), the Greenwood standard "
        "error, and a symmetric 95% interval clipped to [0, 1]. new_case, new_charge, and "
        "reconviction count only in another case of the person; failure_to_appear and "
        "revocation in any case. release_violation and rearrest are listed under "
        "not_observable: the synthetic source records no such event."
    ),
    "judicial_dismissal_rate": (
        "numerator = charges disposed as dismissed with disposition_actor judge; denominator "
        "= charges with a disposition other than pending or missing. Judge: charges whose "
        "disposed_at falls inside one of the judge's assignment intervals on that case "
        "(start_at <= disposed_at < end_at). Court: charges of the court's cases."
    ),
    "disposition_distribution": (
        "Counts of the judicial_dismissal_rate denominator charges by disposition value."
    ),
    "median_days_to_disposition": (
        "Median over disposed cases of (case disposition date - filed_date) in whole days, "
        "where the case disposition is the latest disposed_at among its disposed charges. "
        "Judge: cases where the judge was assigned at the case disposition time. Court: the "
        "court's disposed cases."
    ),
    "sentences": (
        "Sentence rows of the subject (judge: sentencing judge_code; court: the court's "
        "cases). incarceration_days_median is over sentences with a non-empty "
        "incarceration_days; by_offense_category groups those by the offense_category of the "
        "case's lead convicted charge (most severe by severity rank, ties broken by "
        "charge_id); probation_days_median likewise over non-empty probation_days."
    ),
}


@dataclass(frozen=True, slots=True)
class IndexEvent:
    case: Case
    event_type: str
    at: datetime


@dataclass(frozen=True, slots=True)
class Outcome:
    case: Case
    outcome_type: str
    at: datetime


@dataclass(slots=True)
class PersonTimeline:
    index_events: list[IndexEvent]
    outcomes: dict[str, list[Outcome]]  # per outcome type, sorted by time
    outcome_times: dict[str, list[datetime]]
    # The person's cases in filing order and incarceration terms (start, end, days).
    cases: list[Case]
    terms: list[tuple[datetime, datetime, int]]

    def has_outcome(self, index: IndexEvent, outcome_type: str, window_days: int) -> bool:
        times = self.outcome_times.get(outcome_type, [])
        outcomes = self.outcomes.get(outcome_type, [])
        limit = index.at + timedelta(days=window_days)
        position = bisect_right(times, index.at)
        while position < len(times) and times[position] <= limit:
            outcome = outcomes[position]
            if outcome_type not in OTHER_CASE_OUTCOMES or outcome.case is not index.case:
                return True
            position += 1
        return False


def index_events(case: Case) -> list[IndexEvent]:
    events: list[IndexEvent] = []
    decision = case.pretrial_decision
    if decision is not None and decision.released and decision.release_at is not None:
        events.append(IndexEvent(case, "pretrial_release", decision.release_at))
    disposition_at = case.disposition_at
    if disposition_at is not None:
        events.append(IndexEvent(case, "disposition", disposition_at))
    if case.sentence is not None:
        events.append(IndexEvent(case, "sentence", case.sentence.sentence_at))
    return events


def outcomes_of(case: Case) -> list[Outcome]:
    found = [Outcome(case, "new_case", case.filed_at)]
    for charge in case.charges:
        found.append(Outcome(case, "new_charge", charge.filed_at))
        if charge.convicted and charge.disposed_at is not None:
            found.append(Outcome(case, "reconviction", charge.disposed_at))
    for event in case.events:
        if event.event_type in ("failure_to_appear", "revocation"):
            found.append(Outcome(case, event.event_type, event.event_at))
    return found


def build_timelines(world: World) -> dict[str, PersonTimeline]:
    timelines: dict[str, PersonTimeline] = {}
    for person in world.persons:
        cases = world.cases_of(person)
        indexes = [event for case in cases for event in index_events(case)]
        outcomes: dict[str, list[Outcome]] = {}
        for case in cases:
            for outcome in outcomes_of(case):
                outcomes.setdefault(outcome.outcome_type, []).append(outcome)
        for values in outcomes.values():
            values.sort(key=lambda o: (o.at, o.case.case_number))
        times = {kind: [o.at for o in values] for kind, values in outcomes.items()}
        terms = sorted(
            (case.sentence.sentence_at, end, days)
            for case in cases
            if case.sentence is not None
            and (days := case.sentence.incarceration_days) is not None
            and days > 0
            and (end := term_end(case.sentence)) is not None
        )
        timelines[person.true_id] = PersonTimeline(indexes, outcomes, times, cases, terms)
    return timelines


def persons_rows(world: World) -> list[list[str]]:
    seen: set[tuple[str, str, str]] = set()
    for case in world.cases:
        seen.add((case.person.true_id, case.participant_id, case.court_code))
    return [list(row) for row in sorted(seen)]


def subsequent_rows(world: World, timelines: dict[str, PersonTimeline]) -> list[list[str]]:
    rows: list[tuple[tuple[str, datetime, str, str, datetime, str], list[str]]] = []
    for person in world.persons:
        timeline = timelines[person.true_id]
        for index in timeline.index_events:
            for outcome_type in sorted(timeline.outcomes):
                for outcome in timeline.outcomes[outcome_type]:
                    if outcome.at <= index.at:
                        continue
                    if outcome_type in OTHER_CASE_OUTCOMES and outcome.case is index.case:
                        continue
                    days_after = days_between(index.at, outcome.at)
                    if days_after < 1:
                        msg = (
                            f"{person.true_id}: {outcome_type} at {outcome.at.isoformat()} is "
                            f"not after {index.event_type} at {index.at.isoformat()}"
                        )
                        raise GenerationError(msg)
                    key = (
                        person.true_id,
                        index.at,
                        index.case.case_number,
                        index.event_type,
                        outcome.at,
                        outcome_type,
                    )
                    rows.append(
                        (
                            key,
                            [
                                person.true_id,
                                index.case.case_number,
                                index.event_type,
                                fmt_ts(index.at),
                                outcome_type,
                                fmt_ts(outcome.at),
                                str(days_after),
                            ],
                        )
                    )
    # One row per distinct (index event, outcome type, outcome time): several
    # charges filed or convicted at the same instant are one outcome.
    distinct = {key: row for key, row in rows}
    return [distinct[key] for key in sorted(distinct)]


def days_between(index_at: datetime, outcome_at: datetime) -> int:
    """The smallest whole number of days d with ``outcome_at <= index_at + d days``.

    An outcome is inside window ``w`` exactly when ``days_between(...) <= w``,
    so a strictly later outcome always counts at least one day.
    """
    seconds = int((outcome_at - index_at).total_seconds())
    return -(-seconds // 86_400)


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    value = None if denominator == 0 else round(numerator / denominator, 6)
    return {"numerator": numerator, "denominator": denominator, "value": value}


def _median(values: Sequence[int]) -> dict[str, Any]:
    return {"n": len(values), "value": None if not values else float(median(values))}


# --- windowed cohorts per index kind (TRUTH_VERSION 2) ------------------------------


@dataclass(frozen=True, slots=True)
class CohortMember:
    """One member of a windowed cohort: the index case, the kind, and its two instants."""

    case: Case
    kind: str
    index_at: datetime
    exposure_start: datetime


def term_end(sentence: Sentence | None) -> datetime | None:
    """``sentence_at + incarceration_days`` when the sentence incarcerates, else ``None``."""
    if sentence is None or sentence.incarceration_days is None or sentence.incarceration_days <= 0:
        return None
    return sentence.sentence_at + timedelta(days=sentence.incarceration_days)


def deferred_start(
    start: datetime, terms: Sequence[tuple[datetime, datetime, int]]
) -> tuple[datetime, int]:
    """``start`` moved past every incarceration term that contains it, and the days applied.

    While a term ``[begin, end)`` contains the start, the start moves to the
    end of the containing term that ends last (ties: the longer term), and
    that term's days are added; the result is the first instant at or after
    ``start`` that no term of the person covers.
    """
    total = 0
    while True:
        containing = [term for term in terms if term[0] <= start < term[1]]
        if not containing:
            return start, total
        _, end, days = max(containing, key=lambda term: (term[1], term[2]))
        start = end
        total += days


def cohort_members(
    world: World,
    kind: str,
    *,
    timelines: dict[str, PersonTimeline],
    pretrial_attributed: Callable[[Case, Decision], bool],
    case_disposition_attributed: Callable[[Case, datetime], bool],
    sentence_attributed: Callable[[Case, Sentence], bool],
) -> list[CohortMember]:
    """The attributed index events of ``kind`` with their exposure starts.

    ``pretrial_release``: a released judicial discretionary pretrial decision
    at its release time. ``disposition``: a disposed case at its
    disposition time, one member per defendant (one per case here), whose
    exposure starts at the end of the case's own incarceration term when it
    has one. ``sentence``: a sentence at ``sentence_at``. Every kind's start
    is then deferred by each incarceration term of the person that contains
    it (``deferred_start``, methodology 0.2).
    """
    if kind not in INDEX_KINDS:
        msg = f"unknown index kind {kind!r}"
        raise GenerationError(msg)
    members: list[CohortMember] = []
    for case in world.cases:
        if kind == "pretrial_release":
            decision = case.pretrial_decision
            if (
                decision is not None
                and decision.judicial_discretionary
                and pretrial_attributed(case, decision)
                and decision.detained is False
                and decision.release_at is not None
            ):
                members.append(_member(case, kind, decision.release_at, None, timelines))
        elif kind == "disposition":
            disposition_at = case.disposition_at
            if disposition_at is not None and case_disposition_attributed(case, disposition_at):
                members.append(
                    _member(case, kind, disposition_at, term_end(case.sentence), timelines)
                )
        else:
            sentence = case.sentence
            if sentence is not None and sentence_attributed(case, sentence):
                members.append(_member(case, kind, sentence.sentence_at, None, timelines))
    return members


def _member(
    case: Case,
    kind: str,
    index_at: datetime,
    own_term_end: datetime | None,
    timelines: dict[str, PersonTimeline],
) -> CohortMember:
    start = index_at if own_term_end is None else own_term_end
    exposure_start, _ = deferred_start(start, timelines[case.person.true_id].terms)
    return CohortMember(case, kind, index_at, exposure_start)


def first_outcome_at(
    timeline: PersonTimeline, member: CohortMember, outcome_type: str
) -> datetime | None:
    """The member's first ``outcome_type`` strictly after its exposure start (other-case rule)."""
    times = timeline.outcome_times.get(outcome_type, [])
    outcomes = timeline.outcomes.get(outcome_type, [])
    position = bisect_right(times, member.exposure_start)
    while position < len(times):
        outcome = outcomes[position]
        if outcome_type not in OTHER_CASE_OUTCOMES or outcome.case is not member.case:
            return outcome.at
        position += 1
    return None


def product_limit(
    durations: Sequence[timedelta], events: Sequence[bool], at: timedelta
) -> tuple[float, float]:
    """``(S(at), Greenwood variance)``: events before censorings at a tie; ``S = 0`` once all fail."""
    event_times = sorted({t for t, is_event in zip(durations, events, strict=True) if is_event})
    survival = 1.0
    greenwood = 0.0
    for time_i in event_times:
        if time_i > at:
            break
        at_risk = sum(1 for t in durations if t >= time_i)
        failed = sum(
            1 for t, is_event in zip(durations, events, strict=True) if is_event and t == time_i
        )
        if at_risk == failed:
            return 0.0, 0.0
        survival *= 1.0 - failed / at_risk
        greenwood += failed / (at_risk * (at_risk - failed))
    return survival, survival * survival * greenwood


def _survival(
    durations: Sequence[timedelta], events: Sequence[bool], window: int
) -> dict[str, Any]:
    at = timedelta(days=window)
    if not durations:
        return {
            "value": None,
            "events": 0,
            "censored": 0,
            "at_risk": 0,
            "standard_error": None,
            "lower": None,
            "upper": None,
        }
    survival, variance = product_limit(durations, events, at)
    incidence = 1.0 - survival
    standard_error = math.sqrt(variance)
    counted = sum(1 for t, e in zip(durations, events, strict=True) if e and t <= at)
    censored = sum(1 for t, e in zip(durations, events, strict=True) if not e and t < at)
    return {
        "value": round(incidence, 6),
        "events": counted,
        "censored": censored,
        "at_risk": len(durations) - counted - censored,
        "standard_error": round(standard_error, 6),
        "lower": round(max(0.0, incidence - Z_95 * standard_error), 6),
        "upper": round(min(1.0, incidence + Z_95 * standard_error), 6),
    }


def windowed_metrics(
    members: Sequence[CohortMember],
    timelines: dict[str, PersonTimeline],
    corpus_end_at: datetime,
) -> dict[str, Any]:
    """Per window: cohort, followed, and each outcome's fixed-window rate and survival."""
    firsts: dict[str, list[datetime | None]] = {
        outcome_type: [
            first_outcome_at(timelines[member.case.person.true_id], member, outcome_type)
            for member in members
        ]
        for outcome_type in WINDOWED_OUTCOMES
    }
    windows: dict[str, Any] = {}
    for window in WINDOWS_DAYS:
        limit = timedelta(days=window)
        followed = [
            index
            for index, member in enumerate(members)
            if member.exposure_start + limit < corpus_end_at
        ]
        entry: dict[str, Any] = {"cohort": len(members), "followed": len(followed)}
        for outcome_type in WINDOWED_OUTCOMES:
            first = firsts[outcome_type]
            numerator = 0
            for index in followed:
                at = first[index]
                if at is not None and at <= members[index].exposure_start + limit:
                    numerator += 1
            entry[f"{outcome_type}_rate"] = _rate(numerator, len(followed))
            durations: list[timedelta] = []
            events: list[bool] = []
            for index, member in enumerate(members):
                at = first[index]
                if at is not None and at < corpus_end_at:
                    durations.append(at - member.exposure_start)
                    events.append(True)
                else:
                    durations.append(corpus_end_at - member.exposure_start)
                    events.append(False)
            entry[f"{outcome_type}_survival"] = _survival(durations, events, window)
        windows[str(window)] = entry
    return windows


Membership = Callable[[Case], bool]


def _subject_metrics(
    world: World,
    timelines: dict[str, PersonTimeline],
    *,
    eligible: Membership,
    pretrial_attributed: Callable[[Case, Decision], bool],
    charge_attributed: Callable[[Case, Charge], bool],
    case_disposition_attributed: Callable[[Case, datetime], bool],
    sentence_attributed: Callable[[Case, Sentence], bool],
    court_extras: bool,
) -> dict[str, Any]:
    corpus_end_at = world.spec.corpus_end_at
    eligible_cases = [case for case in world.cases if eligible(case)]
    decisions = [
        (case, decision)
        for case in world.cases
        for decision in [case.pretrial_decision]
        if decision is not None
        and decision.judicial_discretionary
        and pretrial_attributed(case, decision)
    ]
    released = [(case, d) for case, d in decisions if d.detained is False]
    detained = [(case, d) for case, d in decisions if d.detained is True]
    index_events_block = {
        kind: {
            "windows": windowed_metrics(
                cohort_members(
                    world,
                    kind,
                    timelines=timelines,
                    pretrial_attributed=pretrial_attributed,
                    case_disposition_attributed=case_disposition_attributed,
                    sentence_attributed=sentence_attributed,
                ),
                timelines,
                corpus_end_at,
            )
        }
        for kind in INDEX_KINDS
    }
    pretrial: dict[str, Any] = {
        "decisions": len(decisions),
        "released_count": len(released),
        "detained_count": len(detained),
        "release_share": _rate(len(released), len(released) + len(detained)),
        # Kept for continuity with TRUTH_VERSION 1: the same object as
        # index_events.pretrial_release.windows.
        "windows": index_events_block["pretrial_release"]["windows"],
    }
    if court_extras:
        all_decisions = [
            (case, d) for case in eligible_cases for d in [case.pretrial_decision] if d is not None
        ]
        pretrial["statutory_release_count"] = sum(
            1 for _, d in all_decisions if d.discretion == "mandatory"
        )
        pretrial["unknown_actor_count"] = sum(1 for _, d in all_decisions if d.actor == "unknown")

    disposed_charges = [
        (case, charge)
        for case in world.cases
        for charge in case.charges
        if charge.disposed and charge_attributed(case, charge)
    ]
    dismissed_by_judge = sum(
        1
        for _, charge in disposed_charges
        if charge.disposition == "dismissed" and charge.disposition_actor == "judge"
    )
    distribution = {
        value: sum(1 for _, charge in disposed_charges if charge.disposition == value)
        for value in FINAL_CHARGE_DISPOSITIONS
    }
    days_to_disposition: list[int] = []
    for case in world.cases:
        disposition_at = case.disposition_at
        if disposition_at is not None and case_disposition_attributed(case, disposition_at):
            days_to_disposition.append((disposition_at.date() - case.filed_date).days)

    sentences = [
        (case, case.sentence)
        for case in world.cases
        if case.sentence is not None and sentence_attributed(case, case.sentence)
    ]
    incarceration = [s.incarceration_days for _, s in sentences if s.incarceration_days is not None]
    probation = [s.probation_days for _, s in sentences if s.probation_days is not None]
    by_category: dict[str, list[int]] = {}
    for case, sentence in sentences:
        if sentence.incarceration_days is None:
            continue
        lead = case.lead_convicted_charge
        category = lead.offense.offense_category if lead is not None else "unknown"
        by_category.setdefault(category, []).append(sentence.incarceration_days)

    return {
        "eligible_cases": len(eligible_cases),
        "eligible_defendants": len({case.person.true_id for case in eligible_cases}),
        "pretrial": pretrial,
        "index_events": index_events_block,
        "judicial_dismissal_rate": _rate(dismissed_by_judge, len(disposed_charges)),
        "disposition_distribution": distribution,
        "median_days_to_disposition": _median(days_to_disposition),
        "sentences": {
            "count": len(sentences),
            "incarceration_days_median": _median(incarceration),
            "probation_days_median": _median(probation),
            "incarceration_days_median_by_offense_category": {
                category: _median(values) for category, values in sorted(by_category.items())
            },
        },
    }


def judge_metrics(world: World, timelines: dict[str, PersonTimeline], code: str) -> dict[str, Any]:
    return _subject_metrics(
        world,
        timelines,
        eligible=lambda case: any(a.judge_code == code for a in case.assignments),
        pretrial_attributed=lambda case, decision: decision.judge_code == code,
        charge_attributed=lambda case, charge: (
            charge.disposed_at is not None and case.assigned_judge_at(charge.disposed_at) == code
        ),
        case_disposition_attributed=lambda case, at: case.assigned_judge_at(at) == code,
        sentence_attributed=lambda case, sentence: sentence.judge_code == code,
        court_extras=False,
    )


def court_metrics(world: World, timelines: dict[str, PersonTimeline], code: str) -> dict[str, Any]:
    in_court: Membership = lambda case: case.court_code == code  # noqa: E731
    return _subject_metrics(
        world,
        timelines,
        eligible=in_court,
        pretrial_attributed=lambda case, decision: in_court(case),
        charge_attributed=lambda case, charge: in_court(case),
        case_disposition_attributed=lambda case, at: in_court(case),
        sentence_attributed=lambda case, sentence: in_court(case),
        court_extras=True,
    )


def compute_metrics(world: World, timelines: dict[str, PersonTimeline]) -> dict[str, Any]:
    spec = world.spec
    return {
        "truth_version": TRUTH_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": world.seed,
        "scale": spec.name,
        "corpus": {
            "start": spec.corpus_start.isoformat(),
            "end": spec.corpus_end.isoformat(),
            "end_exclusive_at": fmt_ts(spec.corpus_end_at),
        },
        "windows_days": list(WINDOWS_DAYS),
        "index_kinds": list(INDEX_KINDS),
        "observable_outcomes": list(WINDOWED_OUTCOMES),
        "not_observable": [
            {"outcome": outcome, "reason": NOT_OBSERVABLE_REASON} for outcome in NOT_OBSERVABLE
        ],
        "definitions": DEFINITIONS,
        "judges": {
            judge.code: judge_metrics(world, timelines, judge.code) for judge in world.judges
        },
        "courts": {
            court.code: court_metrics(world, timelines, court.code) for court in world.courts
        },
    }


# --- truth/effects.json: the planted effects and the oracle (TRUTH_VERSION 3) ------------

EFFECT_NAMES: tuple[str, ...] = ("leniency", "new_case_effect", "fta_effect")
# target -> the judge effect that moves it.
EFFECT_OF_TARGET: dict[str, str] = {
    "pretrial_release": "leniency",
    "new_case": "new_case_effect",
    "failure_to_appear": "fta_effect",
}
WINDOWED_TARGETS: tuple[str, ...] = ("new_case", "failure_to_appear")

EFFECTS_DEFINITIONS: dict[str, str] = {
    "parameters": (
        "Every constant of the generator's functional forms (docs/SYNTHETIC_DATA.md "
        '"Planted effects"): the judge-effect ranges, the risk features and their numeric '
        "codes, the risk-index weights, the release, failure-to-appear, and next-filing forms, "
        "and the age effects by filing-age band."
    ),
    "judges": (
        "Per judge: the courts it served, its planted leniency (release log-odds), "
        "new_case_effect (next-filing skew exponent), fta_effect (failure-to-appear log-odds), "
        "and docket_tilt (assignment log-weight per unit of risk index), and under centered "
        "each effect minus the decision-weighted mean of its courts' means (the effect the "
        "ratios rank). decisions_by_court counts the judicial discretionary release decisions "
        "the generator drew for the judge per court (the weights)."
    ),
    "courts": (
        "Per court: the case-weighted mean of each effect over the judges who drew its "
        "judicial discretionary release decisions (each judge weighted by those decisions), "
        "the value p0 substitutes for the deciding judge's effect."
    ),
    "targets.pretrial_release": (
        "Per judge, over the attributed judicial discretionary pretrial decisions "
        "(metrics.json pretrial.decisions): decisions, released (detained = false), expected "
        "= sum over the decisions of p = logistic(base + leniency) x the chance the release "
        "takes effect before the corpus end, expected_centered = the same sum with the court's "
        "mean leniency (p0), oracle_ratio = released / expected_centered, true_ratio = "
        "expected / expected_centered."
    ),
    "targets.windowed": (
        "new_case and failure_to_appear, per window w and judge, over the pretrial_release "
        "cohort of metrics.json (index_events.pretrial_release.windows.<w>): cohort, followed, "
        "observed (the fixed-window numerator), expected and expected_centered summed over the "
        "followed members, oracle_ratio = observed / expected_centered, true_ratio = expected / "
        "expected_centered. A member's p is the probability of its outcome in (exposure_start, "
        "exposure_start + w days] under the generator's draws given the realized exposure "
        "start. new_case: 0 without a next case; else the chance the next filing (earliest "
        "day + int(U ** k x (span + 1)) days, a business-hour minute, k = max(floor, "
        "base_exponent + the releasing judge's effect)) falls in the window, plus the chance "
        "it falls before the exposure start times whether a later case was filed in the "
        "window. failure_to_appear: 1 - (1 - q) x (1 - o), q = logistic(base + the judge's "
        "fta_effect) x the chance its date (the rule's hearing, or a uniform day and minute) "
        "falls in the window, o = 1 when another case of the person records a failure to "
        "appear in the window. p0 substitutes the court's mean effect for the judge's."
    ),
    "controls": (
        "The restricted controls: age_band is the positive control (the planted effects of "
        "the filing-age band on the failure-to-appear log-odds and the next-filing exponent, "
        "which no model feature carries); synthetic_group is the negative control (drawn on "
        "its own stream after the persons; no draw reads it)."
    ),
}


@dataclass(frozen=True, slots=True)
class CourtMeans:
    """Per court, the judges' release-decision counts and the weighted mean of each effect."""

    weights: dict[str, dict[str, int]]
    means: dict[str, dict[str, float]]

    def mean(self, court_code: str, effect: str) -> float:
        return self.means.get(court_code, {}).get(effect, 0.0)


def _effect(judge: Judge, name: str) -> float:
    value: float = getattr(judge, name)
    return value


def court_means(world: World) -> CourtMeans:
    """The case-weighted mean effects: each judge weighted by the release decisions it drew."""
    weights: dict[str, dict[str, int]] = {court: {} for court in world.court_codes}
    for case in world.cases:
        draws = case.draws
        if draws is not None and draws.release is not None:
            per_court = weights.setdefault(case.court_code, {})
            per_court[draws.release.judge_code] = per_court.get(draws.release.judge_code, 0) + 1
    means: dict[str, dict[str, float]] = {}
    for court, per_judge in sorted(weights.items()):
        total = sum(per_judge.values())
        means[court] = {
            name: (
                sum(count * _effect(world.judge(code), name) for code, count in per_judge.items())
                / total
                if total
                else 0.0
            )
            for name in EFFECT_NAMES
        }
    return CourtMeans(weights, means)


def centered_effects(world: World, means: CourtMeans, judge: Judge) -> dict[str, float]:
    """Each effect minus the decision-weighted mean of the judge's courts' means."""
    counts = {
        court: per_judge[judge.code]
        for court, per_judge in means.weights.items()
        if judge.code in per_judge
    }
    total = sum(counts.values())
    centered: dict[str, float] = {}
    for name in EFFECT_NAMES:
        if total:
            reference = sum(n * means.mean(court, name) for court, n in counts.items()) / total
        else:
            reference = means.mean(judge_home_court(judge), name)
        centered[name] = _effect(judge, name) - reference
    return centered


def _draws_of(case: Case) -> Draws:
    if case.draws is None:  # pragma: no cover - every simulated case records its draws
        msg = f"case {case.case_number} has no draw record"
        raise GenerationError(msg)
    return case.draws


def release_probability(case: Case, leniency: float) -> float:
    """The chance the judge's decision shows a release: the draw times its taking effect."""
    release = _draws_of(case).release
    if release is None:
        msg = f"case {case.case_number} has no judicial release draw"
        raise GenerationError(msg)
    return logistic(release.base_logit + leniency) * release.observed_share


def own_fta_probability(case: Case, effect: float, low: datetime, high: datetime) -> float:
    """The chance the case's own failure-to-appear draw lands in ``(low, high]``."""
    fta = _draws_of(case).fta
    if fta is None:
        msg = f"case {case.case_number} has no failure-to-appear draw"
        raise GenerationError(msg)
    probability = logistic(fta.base_logit + effect)
    if fta.fixed_at is not None:
        return probability if low < fta.fixed_at <= high else 0.0
    if fta.first_day is not None and fta.last_day is not None:
        days = (fta.last_day - fta.first_day).days + 1
        return probability * window_probability(fta.first_day, days, uniform_cdf(days), low, high)
    return 0.0


def fta_probability(
    timeline: PersonTimeline, case: Case, effect: float, low: datetime, high: datetime
) -> float:
    """``1 - (1 - q) * (1 - o)``: the own draw, or another case's failure to appear."""
    other = any(
        outcome.case is not case and low < outcome.at <= high
        for outcome in timeline.outcomes.get("failure_to_appear", [])
    )
    if other:
        return 1.0
    return own_fta_probability(case, effect, low, high)


def new_case_probability(
    timeline: PersonTimeline, case: Case, effect: float, low: datetime, high: datetime
) -> float:
    """The chance another case of the person is filed in ``(low, high]`` after ``case``."""
    position = next(i for i, other in enumerate(timeline.cases) if other is case)
    if position + 1 >= len(timeline.cases):
        return 0.0
    following = timeline.cases[position + 1]
    filing = _draws_of(following).filing
    if filing is None or filing.previous is not case:
        msg = f"case {following.case_number} records no filing draw after {case.case_number}"
        raise GenerationError(msg)
    days = filing.span + 1
    cdf = skewed_cdf(filing.span, exponent(filing.base_exponent, effect))
    inside = window_probability(filing.earliest, days, cdf, low, high)
    early = window_probability(filing.earliest, days, cdf, before(filing.earliest), low)
    later = any(low < other.filed_at <= high for other in timeline.cases[position + 2 :])
    return inside + (early if later else 0.0)


def _round(value: float) -> float:
    return round(value, 6)


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator <= 0 else _round(numerator / denominator)


def _release_target(world: World, means: CourtMeans, judge: Judge) -> dict[str, Any]:
    decisions = [
        case
        for case in world.cases
        for decision in [case.pretrial_decision]
        if decision is not None
        and decision.judicial_discretionary
        and decision.judge_code == judge.code
    ]
    released = sum(
        1 for case in decisions if case.pretrial_decision and case.pretrial_decision.released
    )
    expected = sum(release_probability(case, judge.leniency) for case in decisions)
    centered = sum(
        release_probability(case, means.mean(case.court_code, "leniency")) for case in decisions
    )
    return {
        "decisions": len(decisions),
        "released": released,
        "expected": _round(expected),
        "expected_centered": _round(centered),
        "oracle_ratio": _ratio(released, centered),
        "true_ratio": _ratio(expected, centered),
    }


def _windowed_targets(
    world: World,
    timelines: dict[str, PersonTimeline],
    means: CourtMeans,
    judge: Judge,
) -> dict[str, dict[str, dict[str, Any]]]:
    """Per windowed target and window: the judge's entry (the pretrial_release cohort)."""
    members = cohort_members(
        world,
        "pretrial_release",
        timelines=timelines,
        pretrial_attributed=lambda case, decision: decision.judge_code == judge.code,
        case_disposition_attributed=lambda case, at: False,
        sentence_attributed=lambda case, sentence: False,
    )
    corpus_end_at = world.spec.corpus_end_at
    result: dict[str, dict[str, dict[str, Any]]] = {target: {} for target in WINDOWED_TARGETS}
    for target in WINDOWED_TARGETS:
        effect_name = EFFECT_OF_TARGET[target]
        firsts = [
            first_outcome_at(timelines[member.case.person.true_id], member, target)
            for member in members
        ]
        probability = new_case_probability if target == "new_case" else fta_probability
        for window in WINDOWS_DAYS:
            limit = timedelta(days=window)
            observed = 0
            expected = 0.0
            centered = 0.0
            followed = 0
            for member, first in zip(members, firsts, strict=True):
                high = member.exposure_start + limit
                if not high < corpus_end_at:
                    continue
                followed += 1
                if first is not None and first <= high:
                    observed += 1
                timeline = timelines[member.case.person.true_id]
                low = member.exposure_start
                expected += probability(
                    timeline, member.case, _effect(judge, effect_name), low, high
                )
                centered += probability(
                    timeline,
                    member.case,
                    means.mean(member.case.court_code, effect_name),
                    low,
                    high,
                )
            result[target][str(window)] = {
                "cohort": len(members),
                "followed": followed,
                "observed": observed,
                "expected": _round(expected),
                "expected_centered": _round(centered),
                "oracle_ratio": _ratio(observed, centered),
                "true_ratio": _ratio(expected, centered),
            }
    return result


def compute_effects(world: World, timelines: dict[str, PersonTimeline]) -> dict[str, Any]:
    """``truth/effects.json``: the planted parameters, the effects, and the oracle targets."""
    means = court_means(world)
    judges: dict[str, Any] = {}
    release: dict[str, Any] = {}
    windowed: dict[str, dict[str, dict[str, Any]]] = {
        target: {str(window): {} for window in WINDOWS_DAYS} for target in WINDOWED_TARGETS
    }
    for judge in world.judges:
        judges[judge.code] = {
            "courts": sorted({service.court_code for service in judge.services}),
            "leniency": _round(judge.leniency),
            "new_case_effect": _round(judge.new_case_effect),
            "fta_effect": _round(judge.fta_effect),
            "docket_tilt": _round(judge.docket_tilt),
            "centered": {
                name: _round(value) for name, value in centered_effects(world, means, judge).items()
            },
            "decisions_by_court": {
                court: per_judge[judge.code]
                for court, per_judge in sorted(means.weights.items())
                if judge.code in per_judge
            },
        }
        release[judge.code] = _release_target(world, means, judge)
        for target, by_window in _windowed_targets(world, timelines, means, judge).items():
            for window, entry in by_window.items():
                windowed[target][window][judge.code] = entry
    spec = world.spec
    return {
        "truth_version": TRUTH_VERSION,
        "generator_version": GENERATOR_VERSION,
        "seed": world.seed,
        "scale": spec.name,
        "windows_days": list(WINDOWS_DAYS),
        "definitions": EFFECTS_DEFINITIONS,
        "parameters": parameters(),
        "judges": judges,
        "courts": {
            court: {
                "mean": {name: _round(value) for name, value in court_mean.items()},
                "decisions_by_judge": dict(sorted(means.weights.get(court, {}).items())),
            }
            for court, court_mean in sorted(means.means.items())
        },
        "targets": {
            "pretrial_release": {"effect": EFFECT_OF_TARGET["pretrial_release"], "judges": release},
            **{
                target: {
                    "effect": EFFECT_OF_TARGET[target],
                    "windows": {
                        window: {"judges": entries} for window, entries in by_window.items()
                    },
                }
                for target, by_window in windowed.items()
            },
        },
        "controls": {
            "age_band": {
                "role": "positive control",
                "failure_to_appear_log_odds": dict(FTA_AGE),
                "new_case_exponent": dict(EXPONENT_AGE),
            },
            "synthetic_group": {
                "role": "negative control",
                "values": list(SYNTHETIC_GROUPS),
                "feeds_no_draw": True,
            },
        },
    }


def readme_text(world: World, plants: Plants, counts: dict[str, int]) -> str:
    spec = world.spec
    lines = [
        "<!-- truth/README.md (generated by `judgemetrics synthetic generate`; never hand-edited) -->",
        f"# Truth for the `{spec.name}` synthetic dataset, seed {world.seed}",
        "",
        "This directory documents the simulation behind `../source/`. It is",
        "written by the generator alongside the source files, it never enters",
        "the database (the synthetic connector discovers `source/` only), and",
        "it changes only when `GENERATOR_VERSION` or `TRUTH_VERSION` changes.",
        "",
        f"- Generator version: `{GENERATOR_VERSION}`; truth version: `{TRUTH_VERSION}`.",
        f"- Corpus: cases filed from {spec.corpus_start.isoformat()} to "
        f"{spec.corpus_end.isoformat()}; every timestamp is strictly before "
        f"`{fmt_ts(spec.corpus_end_at)}`, the corpus end used for follow-up.",
        f"- World: {spec.courts} courts, {spec.judges} judges, {spec.persons} persons, "
        f"{spec.cases} cases (plus {spec.duplicate_source_records} duplicate source "
        "records emitted as formatting variants).",
        "",
        "## Files",
        "",
        "| File | Rows | Contents |",
        "|------|------|----------|",
        f"| `persons.csv` | {counts['truth/persons.csv']} | `true_person_id`, `participant_id`, "
        "`court_code`: the true identity behind every participant id in every court. |",
        f"| `subsequent_events.csv` | {counts['truth/subsequent_events.csv']} | one row per "
        "(index event, later outcome) pair of a person: `index_event_type` is "
        "`pretrial_release` (index_at = release_at of a released pretrial decision), "
        "`disposition`, or `sentence`; `outcome_type` is `new_case`, `new_charge`, "
        "`reconviction` (in another case of the person), `failure_to_appear`, or "
        "`revocation` (any case); `days_after` is the smallest whole number of days d with "
        "outcome_at <= index_at + d days (an outcome is inside window w exactly when "
        "days_after <= w) and is always at least 1. |",
        f"| `resolution_expectations.csv` | {counts['truth/resolution_expectations.csv']} | "
        "the decision (`matched`, `rejected`, `review`) entity resolution must reach for "
        "every planted participant pair, ordered by participant id, with the reason. |",
        f"| `planted.csv` | {counts['truth/planted.csv']} | every planted edge case: `kind`, "
        "`ids` (`key=value` pairs separated by `;`), and the pipeline behaviour it must "
        "produce. |",
        "| `metrics.json` | - | `truth_version`, the corpus, the windows, the index kinds, "
        "the observable and `not_observable` outcomes, every metric definition, and the "
        "metric set per `judges.<judge_code>` and `courts.<court_code>`: each rate with "
        "numerator, denominator, and value, and under `index_events.<kind>.windows.<w>` "
        "the cohort, the followed count, every `<outcome>_rate`, and every "
        "`<outcome>_survival` (`1 - S(w)` with events, censored, at_risk, the Greenwood "
        "standard error, and the interval). |",
        "| `effects.json` | - | the planted effects (`TRUTH_VERSION` 3): every constant of "
        "the generator's functional forms under `parameters`; per `judges.<judge_code>` the "
        "courts, `leniency`, `new_case_effect`, `fta_effect`, `docket_tilt`, and each effect "
        "centered on the judge's courts; per `courts.<court_code>` the case-weighted mean "
        "effects; under `targets` the release target per judge and the `new_case` and "
        "`failure_to_appear` targets per window and judge - the cohort, the observed count, "
        "`expected` (sum of p, the oracle with the judge's effect), `expected_centered` "
        "(sum of p0, the effect replaced by the court's mean), `oracle_ratio` (observed / "
        "expected_centered), and `true_ratio` (expected / expected_centered); and the "
        "restricted `controls`. Aggregates only: no per-person row. |",
        "",
        "## Planted edge cases",
        "",
    ]
    by_kind = {kind: plants.count(kind) for kind in KINDS}
    lines.append("| Kind | Count |")
    lines.append("|------|-------|")
    lines.extend(f"| `{kind}` | {count} |" for kind, count in by_kind.items())
    lines.append("")
    if len(plants.items) <= README_PLANTED_LIST_LIMIT:
        lines.append("Every planted item, hand-checkable against `../source/`:")
        lines.append("")
        for index, item in enumerate(plants.items, start=1):
            ids = "; ".join(f"`{key}` = `{value}`" for key, value in item.ids)
            lines.append(f"{index}. **{item.kind}** - {ids}.")
            lines.append(f"   Expected: {item.expected}")
    else:
        lines.append(
            f"More than {README_PLANTED_LIST_LIMIT} items were planted at this scale; "
            "`planted.csv` lists every one with its ids and expected behaviour."
        )
    lines.append("")
    lines.append("## Metric definitions (`metrics.json`)")
    lines.append("")
    for key, definition in DEFINITIONS.items():
        lines.append(f"- `{key}`: {definition}")
    lines.append("")
    return "\n".join(lines)


def write_truth(world: World, plants: Plants, truth_dir: Path) -> dict[str, int]:
    """Write every truth file; returns ``{"truth/<file>": rows}`` for the CSVs."""
    truth_dir.mkdir(parents=True, exist_ok=True)
    timelines = build_timelines(world)
    counts: dict[str, int] = {}
    counts["truth/persons.csv"] = write_csv(
        truth_dir / "persons.csv", PERSONS_HEADER, persons_rows(world)
    )
    counts["truth/subsequent_events.csv"] = write_csv(
        truth_dir / "subsequent_events.csv", SUBSEQUENT_HEADER, subsequent_rows(world, timelines)
    )
    counts["truth/resolution_expectations.csv"] = write_csv(
        truth_dir / "resolution_expectations.csv",
        EXPECTATIONS_HEADER,
        (
            [e.left_participant_id, e.right_participant_id, e.expected_decision, e.reason]
            for e in plants.expectations
        ),
    )
    counts["truth/planted.csv"] = write_csv(
        truth_dir / "planted.csv",
        PLANTED_HEADER,
        ([item.kind, item.ids_text, item.expected] for item in plants.items),
    )
    write_json(truth_dir / "metrics.json", compute_metrics(world, timelines))
    write_json(truth_dir / "effects.json", compute_effects(world, timelines))
    write_text(truth_dir / "README.md", readme_text(world, plants, counts))
    return counts
