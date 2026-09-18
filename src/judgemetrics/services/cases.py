# src/judgemetrics/services/cases.py
"""Case responses: the detail, the timeline, and a judge's case list.

The detail and the timeline are two views over one ``repositories.cases.load_case``
result: the timeline is assembled here from the rows that load already
holds, never from a second round of queries. Every timeline entry cites
the artifact its row came from, so the page can show a source beside
each line.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from judgemetrics.db.models import Case, Charge, Court, Decision, Judge, PretrialRelease, Sentence
from judgemetrics.repositories.cases import CaseRows, list_judge_cases, load_case
from judgemetrics.repositories.provenance import ProvenanceRow
from judgemetrics.schemas.cases import (
    TIMELINE_KIND_ORDER,
    AssignmentOut,
    CaseDetail,
    CasePartyOut,
    CaseSummary,
    ChargeOut,
    DecisionOut,
    PretrialReleaseOut,
    SentenceOut,
    Timeline,
    TimelineEntry,
    TimelineKind,
)
from judgemetrics.schemas.common import Page, Provenance
from judgemetrics.schemas.judges import CourtRef, JudgeRef

_KIND_RANK = {kind: rank for rank, kind in enumerate(TIMELINE_KIND_ORDER)}


def _summary(case: Case, court: Court, synthetic: bool) -> CaseSummary:
    return CaseSummary.from_row(case, court=CourtRef.model_validate(court), synthetic=synthetic)


def _judge_ref(judge: Judge | None) -> JudgeRef | None:
    return None if judge is None else JudgeRef.model_validate(judge)


def _pretrial(pretrial: PretrialRelease | None) -> PretrialReleaseOut | None:
    return None if pretrial is None else PretrialReleaseOut.model_validate(pretrial)


def _decision_out(
    decision: Decision, pretrial: PretrialRelease | None, judge: Judge | None, key: str | None
) -> DecisionOut:
    return DecisionOut(
        decision_type=decision.decision_type,
        decision_at=decision.decision_at,
        actor_type=decision.actor_type,
        judicial_discretion_classification=decision.judicial_discretion_classification,
        judge=_judge_ref(judge),
        public_person_key=key,
        decision_value=decision.decision_value,
        pretrial_release=_pretrial(pretrial),
    )


def _sentence_out(sentence: Sentence, judge: Judge | None) -> SentenceOut:
    return SentenceOut(
        sentence_at=sentence.sentence_at,
        judge=_judge_ref(judge),
        incarceration_days=sentence.incarceration_days,
        probation_days=sentence.probation_days,
        fine_amount=sentence.fine_amount,
        components=sentence.sentence_components,
    )


def case_detail(session: Session, case_id: uuid.UUID) -> CaseDetail | None:
    rows = load_case(session, case_id)
    if rows is None:
        return None
    summary = _summary(rows.case, rows.court, rows.synthetic)
    return CaseDetail(
        **summary.model_dump(),
        parties=[
            CasePartyOut(party_type=party.party_type, public_person_key=key)
            for party, key in rows.parties
        ],
        assignments=[
            AssignmentOut(
                judge=JudgeRef.model_validate(judge),
                assignment_type=assignment.assignment_type,
                start_at=assignment.start_at,
                end_at=assignment.end_at,
            )
            for assignment, judge in rows.assignments
        ],
        charges=[ChargeOut.model_validate(charge) for charge in rows.charges],
        decisions=[_decision_out(*decision) for decision in rows.decisions],
        sentences=[_sentence_out(sentence, judge) for sentence, judge in rows.sentences],
        provenance=[Provenance(**row._asdict()) for row in rows.provenance.values()],
    )


def judge_cases_page(
    session: Session,
    judge_id: uuid.UUID,
    *,
    filed_from: date | None,
    filed_to: date | None,
    status: str | None,
    case_type: str | None,
    limit: int,
    offset: int,
) -> Page[CaseSummary] | None:
    """The judge's cases, newest filing first, or ``None`` when the judge does not exist."""
    found = list_judge_cases(
        session,
        judge_id,
        filed_from=filed_from,
        filed_to=filed_to,
        status=status,
        case_type=case_type,
        limit=limit,
        offset=offset,
    )
    if found is None:
        return None
    rows, total = found
    items = [_summary(case, court, synthetic) for case, court, synthetic in rows]
    return Page[CaseSummary].build(items, total=total, limit=limit, offset=offset)


# --- the timeline -----------------------------------------------------------------


def _plain(value: object) -> Any:
    """A JSON-ready copy of a column value for an entry's ``detail``."""
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    return value


def _title(value: str) -> str:
    return value.replace("_", " ").capitalize()


def _day_start(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


def _day_end(day: date) -> datetime:
    return datetime.combine(day, time.max, tzinfo=UTC)


class _Builder:
    """Collects entries with their sort keys, then orders them."""

    def __init__(self, provenance: dict[uuid.UUID, ProvenanceRow]) -> None:
        self._provenance = provenance
        self._entries: list[tuple[datetime, int, str, TimelineEntry]] = []

    def add(
        self,
        *,
        at: datetime,
        kind: TimelineKind,
        row_id: uuid.UUID,
        source_record_id: uuid.UUID,
        label: str,
        detail: dict[str, Any],
        actor_type: Any = None,
        judge: Judge | None = None,
    ) -> None:
        entry = TimelineEntry(
            at=at,
            kind=kind,
            actor_type=actor_type,
            judge=_judge_ref(judge),
            label=label,
            detail={key: _plain(value) for key, value in detail.items()},
            source=Provenance(**self._provenance[source_record_id]._asdict()),
        )
        self._entries.append((at, _KIND_RANK[kind], str(row_id), entry))

    def sorted(self) -> list[TimelineEntry]:
        return [entry for _, _, _, entry in sorted(self._entries, key=lambda item: item[:3])]


def _charge_label(charge: Charge, disposition: str | None) -> str:
    what = charge.description or charge.statute_code or "charge"
    return (
        f"Charge {_title(disposition).lower()}: {what}" if disposition else f"Charge filed: {what}"
    )


def build_timeline(rows: CaseRows) -> list[TimelineEntry]:
    """Every dated fact of the case, chronological, each citing its artifact."""
    case = rows.case
    build = _Builder(rows.provenance)
    if case.filed_date is not None:
        build.add(
            at=_day_start(case.filed_date),
            kind="filed",
            row_id=case.id,
            source_record_id=case.source_record_id,
            label=f"Case {case.case_number} filed",
            detail={
                "date": case.filed_date,
                "case_number": case.case_number,
                "case_type": case.case_type,
            },
        )
    for assignment, assigned in rows.assignments:
        detail: dict[str, Any] = {
            "assignment_type": assignment.assignment_type,
            "start_at": assignment.start_at,
            "end_at": assignment.end_at,
        }
        build.add(
            at=assignment.start_at,
            kind="assignment_start",
            row_id=assignment.id,
            source_record_id=assignment.source_record_id,
            label=f"Assigned to {assigned.canonical_name} ({_title(assignment.assignment_type)})",
            detail=detail,
            judge=assigned,
        )
        if assignment.end_at is not None:
            build.add(
                at=assignment.end_at,
                kind="assignment_end",
                row_id=assignment.id,
                source_record_id=assignment.source_record_id,
                label=f"Assignment of {assigned.canonical_name} ended",
                detail=detail,
                judge=assigned,
            )
    for charge in rows.charges:
        detail = {
            "statute_code": charge.statute_code,
            "description": charge.description,
            "offense_category": charge.offense_category,
            "severity": charge.severity,
            "violent_flag": charge.violent_flag,
            "disposition": charge.disposition,
            "disposition_actor": charge.disposition_actor,
        }
        build.add(
            at=charge.filed_at,
            kind="charge_filed",
            row_id=charge.id,
            source_record_id=charge.source_record_id,
            label=_charge_label(charge, None),
            detail=detail,
        )
        if charge.disposed_at is not None and charge.disposition is not None:
            build.add(
                at=charge.disposed_at,
                kind="charge_disposed",
                row_id=charge.id,
                source_record_id=charge.source_record_id,
                label=_charge_label(charge, charge.disposition),
                detail=detail,
                actor_type=charge.disposition_actor,
            )
    for event, judge in rows.events:
        label = _title(event.event_type)
        if event.description:
            label = f"{label}: {event.description}"
        build.add(
            at=event.event_at,
            kind="event",
            row_id=event.id,
            source_record_id=event.source_record_id,
            label=label,
            detail={"event_type": event.event_type, "description": event.description},
            actor_type=event.actor_type,
            judge=judge,
        )
    for decision, pretrial, judge, key in rows.decisions:
        label = f"Decision: {_title(decision.decision_type).lower()}"
        if pretrial is not None:
            label = f"{label} ({_title(pretrial.release_type).lower()})"
        detail = {
            "decision_type": decision.decision_type,
            "judicial_discretion_classification": decision.judicial_discretion_classification,
            "decision_value": decision.decision_value,
            "public_person_key": key,
        }
        if pretrial is not None:
            detail["pretrial_release"] = PretrialReleaseOut.model_validate(pretrial).model_dump(
                mode="json"
            )
        build.add(
            at=decision.decision_at,
            kind="decision",
            row_id=decision.id,
            source_record_id=decision.source_record_id,
            label=label,
            detail=detail,
            actor_type=decision.actor_type,
            judge=judge,
        )
    for sentence, judge in rows.sentences:
        parts = [
            f"{sentence.incarceration_days} days incarceration"
            if sentence.incarceration_days
            else None,
            f"{sentence.probation_days} days probation" if sentence.probation_days else None,
            f"fine {sentence.fine_amount}" if sentence.fine_amount is not None else None,
        ]
        described = ", ".join(part for part in parts if part) or "recorded"
        build.add(
            at=sentence.sentence_at,
            kind="sentence",
            row_id=sentence.id,
            source_record_id=sentence.source_record_id,
            label=f"Sentence: {described}",
            detail={
                "incarceration_days": sentence.incarceration_days,
                "probation_days": sentence.probation_days,
                "fine_amount": sentence.fine_amount,
                "components": sentence.sentence_components,
            },
            judge=judge,
        )
    if case.closed_date is not None:
        build.add(
            at=_day_end(case.closed_date),
            kind="closed",
            row_id=case.id,
            source_record_id=case.source_record_id,
            label=f"Case {case.case_number} closed",
            detail={"date": case.closed_date, "status": case.status},
        )
    return build.sorted()


def case_timeline(session: Session, case_id: uuid.UUID) -> Timeline | None:
    rows = load_case(session, case_id)
    if rows is None:
        return None
    return Timeline(case_id=rows.case.id, synthetic=rows.synthetic, entries=build_timeline(rows))
