# src/judgemetrics/quality/checks.py
"""Data-quality checks over the drafts of one ingest run.

Each check returns ``IssueDraft``s that the runner persists as
``data_quality_issue`` rows linked to the run's source records and, once
published, to the entity they concern. Descriptions name identifiers
(node ids, court names, case numbers, dates, source row ids) and never a
raw row, a participant name, a date of birth, or a person hash
(``describe_key`` renders person-keyed drafts without the hash).

Checks from the brief's list (``<data_quality>``) and their codes:

| Brief check                                       | Code                                  | Severity |
|---------------------------------------------------|---------------------------------------|----------|
| Judge service dates temporally valid              | ``service_dates_invalid``             | error    |
| Judge assignment overlaps inspected               | ``service_overlap``                   | warning  |
| (appointments the source has not dated yet)       | ``missing_start_date``                | info     |
| Source provenance complete / hashes present       | ``provenance_incomplete``             | error    |
| Case numbers unique within a court namespace      | ``case_number_duplicate``             | info     |
| Disposition occurs after filing                   | ``disposition_before_filing``         | error    |
| Event timestamps not impossibly ordered           | ``event_order_impossible``            | error    |
| Subsequent outcome occurs after index event       | ``subsequent_before_index``           | error    |
| (a decision a judge should have made, unattributed)| ``missing_judge_on_decision``        | warning  |
| (a closed case's charge without a disposition)    | ``missing_disposition``               | info     |
| Unknown categories measured, not discarded        | ``unknown_category_measured``         | info     |
| Entity-resolution confidence available            | ``person_resolution_confidence_missing`` | warning |

``case_number_duplicate`` runs over the drafts *before* deduplication
(``run_pre_deduplication_checks``), because the planted duplicate collapses
onto one case key at step 9 and would otherwise be invisible; every other
check runs over the resolved drafts (``run_checks``). Checks that need a
case's filing date or status see only the cases drafted in the same run;
a child row of a case that already exists in the database is not checked
against it (recorded as a known limitation).
"""

from __future__ import annotations

import re
import uuid
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime

from judgemetrics.db.models.enums import ActorType, IssueSeverity
from judgemetrics.ingest.base import (
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtEventDraft,
    DecisionDraft,
    JudgeAssignmentDraft,
    JudgeServiceDraft,
    JusticeEventDraft,
    NaturalKey,
    SentenceDraft,
    TaggedRecord,
    describe_key,
)
from judgemetrics.normalization.vocabulary import UNKNOWN

_SHA256 = re.compile(r"^[0-9a-f]{64}$")

SERVICE_DATES_INVALID = "service_dates_invalid"
SERVICE_OVERLAP = "service_overlap"
MISSING_START_DATE = "missing_start_date"
PROVENANCE_INCOMPLETE = "provenance_incomplete"
CASE_NUMBER_DUPLICATE = "case_number_duplicate"
DISPOSITION_BEFORE_FILING = "disposition_before_filing"
EVENT_ORDER_IMPOSSIBLE = "event_order_impossible"
SUBSEQUENT_BEFORE_INDEX = "subsequent_before_index"
MISSING_JUDGE_ON_DECISION = "missing_judge_on_decision"
MISSING_DISPOSITION = "missing_disposition"
UNKNOWN_CATEGORY_MEASURED = "unknown_category_measured"
PERSON_RESOLUTION_CONFIDENCE_MISSING = "person_resolution_confidence_missing"

CASE_STATUS_CLOSED = "closed"
CONVICTED_DISPOSITIONS = frozenset({"convicted_plea", "convicted_verdict"})
# Decisions with one of these actors should name the judge who made them.
JUDGE_EXPECTED_ACTORS = frozenset({ActorType.JUDGE, ActorType.UNKNOWN})


@dataclass(frozen=True, slots=True)
class IssueDraft:
    entity_type: str
    entity_key: NaturalKey | None
    severity: IssueSeverity
    issue_code: str
    description: str
    source_record_id: uuid.UUID | None = None


def _label(service: JudgeServiceDraft) -> str:
    judge = ":".join(service.judge_key[1:])
    court = service.court_key[1] if len(service.court_key) > 1 else "?"
    return f"judge {judge} at {court!r} as {service.position_type}"


def _record_id(item: TaggedRecord) -> uuid.UUID | None:
    return item.provenance.source_record_id if item.provenance else None


def _of_type[R](tagged: Iterable[TaggedRecord], kind: type[R]) -> list[tuple[R, TaggedRecord]]:
    return [(item.record, item) for item in tagged if isinstance(item.record, kind)]


def _services(tagged: Iterable[TaggedRecord]) -> list[tuple[JudgeServiceDraft, uuid.UUID | None]]:
    return [(service, _record_id(item)) for service, item in _of_type(tagged, JudgeServiceDraft)]


def _issue(item: TaggedRecord, code: str, severity: IssueSeverity, detail: str) -> IssueDraft:
    key = item.record.natural_key
    return IssueDraft(
        entity_type=key[0],
        entity_key=key,
        severity=severity,
        issue_code=code,
        description=f"{describe_key(key)}: {detail}",
        source_record_id=_record_id(item),
    )


def _case_label(case_key: NaturalKey) -> str:
    return ":".join(case_key[1:])


# --- reference checks (Phase 1) ----------------------------------------------------


def service_dates_valid(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: a service record whose end date precedes its start date."""
    issues: list[IssueDraft] = []
    for service, record_id in _services(tagged):
        if (
            service.start_date is not None
            and service.end_date is not None
            and service.end_date < service.start_date
        ):
            issues.append(
                IssueDraft(
                    entity_type="judge_service",
                    entity_key=service.natural_key,
                    severity=IssueSeverity.ERROR,
                    issue_code=SERVICE_DATES_INVALID,
                    description=(
                        f"{_label(service)}: end date {service.end_date.isoformat()} precedes "
                        f"start date {service.start_date.isoformat()}"
                    ),
                    source_record_id=record_id,
                )
            )
    return issues


def _overlaps(first: JudgeServiceDraft, second: JudgeServiceDraft) -> bool:
    """Strict overlap: two intervals that merely touch (end == start) do not overlap."""
    if first.start_date is None or second.start_date is None:
        return False
    first_end = first.end_date or date.max
    second_end = second.end_date or date.max
    return first.start_date < second_end and second.start_date < first_end


def service_overlap(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Warning: the same judge at the same court in overlapping intervals."""
    groups: dict[tuple[NaturalKey, NaturalKey], list[tuple[JudgeServiceDraft, uuid.UUID | None]]]
    groups = defaultdict(list)
    for service, record_id in _services(tagged):
        groups[(service.judge_key, service.court_key)].append((service, record_id))
    issues: list[IssueDraft] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        ordered = sorted(
            members, key=lambda pair: (pair[0].start_date or date.min, pair[0].position_type)
        )
        for index, (later, record_id) in enumerate(ordered):
            for earlier, _ in ordered[:index]:
                if _overlaps(earlier, later):
                    issues.append(
                        IssueDraft(
                            entity_type="judge_service",
                            entity_key=later.natural_key,
                            severity=IssueSeverity.WARNING,
                            issue_code=SERVICE_OVERLAP,
                            description=(
                                f"{_label(later)} from {_iso(later.start_date)} to "
                                f"{_iso(later.end_date)} overlaps service as "
                                f"{earlier.position_type} from {_iso(earlier.start_date)} to "
                                f"{_iso(earlier.end_date)}"
                            ),
                            source_record_id=record_id,
                        )
                    )
    return issues


def missing_start_date(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Info: a service record the source has not dated (no commission or recess date)."""
    return [
        IssueDraft(
            entity_type="judge_service",
            entity_key=service.natural_key,
            severity=IssueSeverity.INFO,
            issue_code=MISSING_START_DATE,
            description=f"{_label(service)}: no start date in the source",
            source_record_id=record_id,
        )
        for service, record_id in _services(tagged)
        if service.start_date is None
    ]


def provenance_complete(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: a draft without a source record, or one whose record lacks a sha256."""
    issues: list[IssueDraft] = []
    for item in tagged:
        if item.provenance is None:
            problem = "no source record"
        elif not _SHA256.match(item.provenance.raw_sha256):
            problem = "source record without a sha256"
        else:
            continue
        issues.append(_issue(item, PROVENANCE_INCOMPLETE, IssueSeverity.ERROR, problem))
    return issues


# --- case-level checks (Phase 2) ----------------------------------------------------


def case_number_duplicate(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Info: two source case rows of one court normalize to the same case number.

    Runs before deduplication. The first draft is the one published; the
    issue is attributed to it (and its source record) and names every raw
    spelling so the collapse is auditable.
    """
    groups: dict[NaturalKey, list[TaggedRecord]] = defaultdict(list)
    for case, item in _of_type(tagged, CaseDraft):
        groups[case.natural_key].append(item)
    issues: list[IssueDraft] = []
    for key, items in groups.items():
        if len(items) < 2:
            continue
        spellings = sorted({case.case_number for case, _ in _of_type(items, CaseDraft)})
        rendered = ", ".join(repr(spelling) for spelling in spellings)
        issues.append(
            IssueDraft(
                entity_type=key[0],
                entity_key=key,
                severity=IssueSeverity.INFO,
                issue_code=CASE_NUMBER_DUPLICATE,
                description=(
                    f"{describe_key(key)}: {len(items)} source rows normalize to the same "
                    f"case number ({rendered}); the first is published"
                ),
                source_record_id=_record_id(items[0]),
            )
        )
    return issues


def _cases(tagged: Iterable[TaggedRecord]) -> dict[NaturalKey, CaseDraft]:
    return {case.natural_key: case for case, _ in _of_type(tagged, CaseDraft)}


def disposition_before_filing(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: a charge disposed before it, or its case, was filed."""
    cases = _cases(tagged)
    issues: list[IssueDraft] = []
    for charge, item in _of_type(tagged, ChargeDraft):
        if charge.disposed_at is None:
            continue
        if charge.disposed_at < charge.filed_at:
            detail = (
                f"disposed {_iso(charge.disposed_at)} before the charge was filed "
                f"{_iso(charge.filed_at)}"
            )
        elif (
            (case := cases.get(charge.case_key)) is not None
            and case.filed_date is not None
            and charge.disposed_at.date() < case.filed_date
        ):
            detail = (
                f"disposed {_iso(charge.disposed_at)} before the case was filed "
                f"{_iso(case.filed_date)}"
            )
        else:
            continue
        issues.append(_issue(item, DISPOSITION_BEFORE_FILING, IssueSeverity.ERROR, detail))
    return issues


def event_order_impossible(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: an ordering no case can have.

    A case closed before it was filed; an assignment ending before it
    started; a court event, decision, or sentence before its case was
    filed; a release before the decision that granted it; a sentence
    before the conviction it follows.
    """
    cases = _cases(tagged)
    issues: list[IssueDraft] = []

    def before_filing(case_key: NaturalKey, moment: datetime) -> str | None:
        case = cases.get(case_key)
        if case is None or case.filed_date is None or moment.date() >= case.filed_date:
            return None
        return f"at {_iso(moment)}, before the case was filed {_iso(case.filed_date)}"

    for case, item in _of_type(tagged, CaseDraft):
        if (
            case.filed_date is not None
            and case.closed_date is not None
            and case.closed_date < case.filed_date
        ):
            detail = f"closed {_iso(case.closed_date)} before it was filed {_iso(case.filed_date)}"
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, detail))
    for assignment, item in _of_type(tagged, JudgeAssignmentDraft):
        if assignment.end_at is not None and assignment.end_at < assignment.start_at:
            detail = f"ends {_iso(assignment.end_at)} before it starts {_iso(assignment.start_at)}"
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, detail))
        elif (problem := before_filing(assignment.case_key, assignment.start_at)) is not None:
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, problem))
    for event, item in _of_type(tagged, CourtEventDraft):
        if (problem := before_filing(event.case_key, event.event_at)) is not None:
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, problem))
    for decision, item in _of_type(tagged, DecisionDraft):
        pretrial = decision.pretrial
        if (
            pretrial is not None
            and pretrial.release_at is not None
            and pretrial.release_at < decision.decision_at
        ):
            detail = (
                f"released {_iso(pretrial.release_at)} before the decision "
                f"{_iso(decision.decision_at)}"
            )
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, detail))
        elif (problem := before_filing(decision.case_key, decision.decision_at)) is not None:
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, problem))

    convictions: dict[NaturalKey, datetime] = {}
    for charge, _ in _of_type(tagged, ChargeDraft):
        if charge.disposition in CONVICTED_DISPOSITIONS and charge.disposed_at is not None:
            latest = convictions.get(charge.case_key)
            if latest is None or charge.disposed_at > latest:
                convictions[charge.case_key] = charge.disposed_at
    for sentence, item in _of_type(tagged, SentenceDraft):
        conviction = convictions.get(sentence.case_key)
        if conviction is not None and sentence.sentence_at < conviction:
            detail = (
                f"sentenced {_iso(sentence.sentence_at)} before the conviction {_iso(conviction)}"
            )
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, detail))
        elif (problem := before_filing(sentence.case_key, sentence.sentence_at)) is not None:
            issues.append(_issue(item, EVENT_ORDER_IMPOSSIBLE, IssueSeverity.ERROR, problem))
    return issues


def subsequent_before_index(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Error: a justice event dated before its related case, or before the person's first case.

    The index of a subsequent event is the case it is documented in and,
    for the person, the earliest filing among the person's cases in the
    run: an outcome cannot precede either.
    """
    cases = _cases(tagged)
    first_filing: dict[NaturalKey, date] = {}
    for party, _ in _of_type(tagged, CasePartyDraft):
        case = cases.get(party.case_key)
        if party.person_key is None or case is None or case.filed_date is None:
            continue
        earliest = first_filing.get(party.person_key)
        if earliest is None or case.filed_date < earliest:
            first_filing[party.person_key] = case.filed_date
    issues: list[IssueDraft] = []
    for event, item in _of_type(tagged, JusticeEventDraft):
        related = cases.get(event.related_case_key) if event.related_case_key else None
        if (
            related is not None
            and related.filed_date is not None
            and event.event_at.date() < related.filed_date
        ):
            detail = (
                f"before its case {_case_label(related.natural_key)} was filed "
                f"{_iso(related.filed_date)}"
            )
        elif (
            earliest := first_filing.get(event.person_key)
        ) is not None and event.event_at.date() < earliest:
            detail = f"before the person's first case was filed {_iso(earliest)}"
        else:
            continue
        issues.append(_issue(item, SUBSEQUENT_BEFORE_INDEX, IssueSeverity.ERROR, detail))
    return issues


def missing_judge_on_decision(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Warning: a decision by a judge (or an unknown actor) that names no judge.

    A statutory release, a prosecutor's dismissal, and a jury verdict
    legitimately carry no judge and are not flagged.
    """
    return [
        _issue(
            item,
            MISSING_JUDGE_ON_DECISION,
            IssueSeverity.WARNING,
            f"{decision.decision_type} at {_iso(decision.decision_at)} by actor "
            f"{decision.actor_type.value} names no judge",
        )
        for decision, item in _of_type(tagged, DecisionDraft)
        if decision.judge_key is None and decision.actor_type in JUDGE_EXPECTED_ACTORS
    ]


def missing_disposition(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Info: a charge of a closed case with no disposition."""
    cases = _cases(tagged)
    return [
        _issue(
            item,
            MISSING_DISPOSITION,
            IssueSeverity.INFO,
            f"no disposition although case {_case_label(charge.case_key)} is closed",
        )
        for charge, item in _of_type(tagged, ChargeDraft)
        if charge.disposition is None
        and (case := cases.get(charge.case_key)) is not None
        and case.status == CASE_STATUS_CLOSED
    ]


def unknown_category_measured(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Info: how many values of each categorical field are the explicit ``unknown``.

    One issue per (entity type, field) with a count, so an unknown
    category is measured rather than silently discarded; the issue has no
    entity of its own.
    """
    totals: Counter[tuple[str, str]] = Counter()
    unknowns: Counter[tuple[str, str]] = Counter()
    fields: list[tuple[str, str, str | None]] = []
    for decision, _ in _of_type(tagged, DecisionDraft):
        fields.append(("decision", "actor_type", decision.actor_type.value))
        fields.append(
            (
                "decision",
                "judicial_discretion_classification",
                decision.judicial_discretion_classification,
            )
        )
    for event, _ in _of_type(tagged, CourtEventDraft):
        fields.append(
            ("court_event", "actor_type", event.actor_type.value if event.actor_type else None)
        )
    for charge, _ in _of_type(tagged, ChargeDraft):
        fields.append(("charge", "offense_category", charge.offense_category))
        fields.append(("charge", "severity", charge.severity))
        fields.append(
            (
                "charge",
                "disposition_actor",
                charge.disposition_actor.value if charge.disposition_actor else None,
            )
        )
    for entity_type, field_name, value in fields:
        if value is None:
            continue
        totals[(entity_type, field_name)] += 1
        if value == UNKNOWN:
            unknowns[(entity_type, field_name)] += 1
    return [
        IssueDraft(
            entity_type=entity_type,
            entity_key=None,
            severity=IssueSeverity.INFO,
            issue_code=UNKNOWN_CATEGORY_MEASURED,
            description=(
                f"{entity_type}.{field_name}: {count} of {totals[(entity_type, field_name)]} "
                f"values are {UNKNOWN!r}"
            ),
        )
        for (entity_type, field_name), count in sorted(unknowns.items())
    ]


def person_resolution_confidence_missing(tagged: Iterable[TaggedRecord]) -> list[IssueDraft]:
    """Warning: a case party that resolved to no person (no resolution, no confidence)."""
    return [
        _issue(
            item,
            PERSON_RESOLUTION_CONFIDENCE_MISSING,
            IssueSeverity.WARNING,
            f"{party.party_type} party resolved to no person",
        )
        for party, item in _of_type(tagged, CasePartyDraft)
        if party.person_key is None
    ]


PRE_DEDUPLICATION_CHECKS = (case_number_duplicate,)
CHECKS = (
    service_dates_valid,
    service_overlap,
    missing_start_date,
    provenance_complete,
    disposition_before_filing,
    event_order_impossible,
    subsequent_before_index,
    missing_judge_on_decision,
    missing_disposition,
    unknown_category_measured,
    person_resolution_confidence_missing,
)


def run_pre_deduplication_checks(tagged: Sequence[TaggedRecord]) -> list[IssueDraft]:
    """The checks that must see every draft as parsed, before step 9 collapses duplicates."""
    issues: list[IssueDraft] = []
    for check in PRE_DEDUPLICATION_CHECKS:
        issues.extend(check(tagged))
    return issues


def run_checks(tagged: Sequence[TaggedRecord]) -> list[IssueDraft]:
    """Every check over the run's resolved drafts, in a fixed order."""
    issues: list[IssueDraft] = []
    for check in CHECKS:
        issues.extend(check(tagged))
    return issues


def _iso(value: datetime | date | None) -> str:
    if value is None:
        return "open"
    return value.isoformat()
