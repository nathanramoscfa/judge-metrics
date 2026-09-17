# src/judgemetrics/synthetic/truth.py
"""``truth/``: what the simulation knows that the source files do not say.

- ``persons.csv`` — the true identity behind every participant id and court;
- ``subsequent_events.csv`` — every true later event after every index event;
- ``resolution_expectations.csv`` — the decision Step 3 must reach for every
  planted person pair;
- ``planted.csv`` — every planted edge case with the ids involved and the
  pipeline behaviour it must produce;
- ``metrics.json`` — the Phase 3 metric set computed from truth, per judge
  and per court, each metric with numerator, denominator, and definition;
- ``README.md`` — how to read the files and the hand-checkable planted list.

``truth/`` documents the simulation; it never enters the database (Step 2's
connector discovers ``source/`` only). ``TRUTH_VERSION`` is bumped whenever
a truth file's schema or a metric definition changes.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

from judgemetrics.synthetic.config import GENERATOR_VERSION
from judgemetrics.synthetic.edge_cases import KINDS, Plants
from judgemetrics.synthetic.model import Case, Charge, Decision, Sentence, World
from judgemetrics.synthetic.vocabulary import CHARGE_DISPOSITIONS
from judgemetrics.synthetic.world import GenerationError
from judgemetrics.synthetic.writer import fmt_ts, write_csv, write_json, write_text

TRUTH_VERSION = "1"

WINDOWS_DAYS: tuple[int, ...] = (30, 90, 180, 365, 730, 1095)
WINDOWED_OUTCOMES: tuple[str, ...] = ("failure_to_appear", "new_case", "reconviction")
# Outcomes counted only when they occur in another case of the same person.
OTHER_CASE_OUTCOMES: frozenset[str] = frozenset({"new_case", "new_charge", "reconviction"})
# The planted list is written in full below this many items; above it, counts per kind.
README_PLANTED_LIST_LIMIT = 100

TRUTH_FILES: tuple[str, ...] = (
    "persons.csv",
    "subsequent_events.csv",
    "resolution_expectations.csv",
    "planted.csv",
    "metrics.json",
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
        "For each window w in days: cohort = attributed released decisions (index_at = "
        "release_at); followed = cohort members with release_at + w days strictly before the "
        "corpus end (corpus.end_exclusive_at); numerator = followed members with at least one "
        "outcome of the type in (index_at, index_at + w days]; value = numerator / followed "
        "(null when followed is 0). failure_to_appear counts events in any case of the "
        "person; new_case counts another case's filed_at; reconviction counts a convicted "
        "charge's disposed_at in another case of the person."
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
        timelines[person.true_id] = PersonTimeline(indexes, outcomes, times)
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
    # A released decision always carries its release time (the corpus-end
    # truncation turns an unposted release into a detention).
    release_times = [(case, d.release_at) for case, d in released if d.release_at is not None]
    windows: dict[str, Any] = {}
    for window in WINDOWS_DAYS:
        followed = [
            (case, at) for case, at in release_times if at + timedelta(days=window) < corpus_end_at
        ]
        entry: dict[str, Any] = {"cohort": len(released), "followed": len(followed)}
        for outcome_type in WINDOWED_OUTCOMES:
            numerator = sum(
                1
                for case, at in followed
                if timelines[case.person.true_id].has_outcome(
                    IndexEvent(case, "pretrial_release", at), outcome_type, window
                )
            )
            entry[f"{outcome_type}_rate"] = _rate(numerator, len(followed))
        windows[str(window)] = entry
    pretrial: dict[str, Any] = {
        "decisions": len(decisions),
        "released_count": len(released),
        "detained_count": len(detained),
        "release_share": _rate(len(released), len(released) + len(detained)),
        "windows": windows,
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
        for value in CHARGE_DISPOSITIONS
        if value != "pending"
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
        "definitions": DEFINITIONS,
        "judges": {
            judge.code: judge_metrics(world, timelines, judge.code) for judge in world.judges
        },
        "courts": {
            court.code: court_metrics(world, timelines, court.code) for court in world.courts
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
        "| `metrics.json` | - | `truth_version`, the corpus, the windows, every metric "
        "definition, and the metric set per `judges.<judge_code>` and "
        "`courts.<court_code>`, each rate with numerator, denominator, and value. |",
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
    write_text(truth_dir / "README.md", readme_text(world, plants, counts))
    return counts
