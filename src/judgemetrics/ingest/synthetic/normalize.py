# src/judgemetrics/ingest/synthetic/normalize.py
"""Synthetic source rows → canonical drafts.

Source-specific rules live here (the file layout, the ``;`` list
separator, the ``true``/``false`` booleans, the ``court_code`` and
``judge_code`` identity systems); the canonical rules they call — the
case vocabulary, case-number and person-name normalization, identifier
hashing — live in ``judgemetrics.normalization`` and
``judgemetrics.security.identifiers``.

Mapping (one source file → drafts per row):

- ``courts.csv`` → ``JurisdictionDraft`` + ``CourtDraft`` (identity
  ``synthetic_court_code`` in ``external_ids``);
- ``judges.csv`` → ``JudgeDraft`` (identity ``("synthetic_judge_code", code)``)
  + ``JudgeServiceDraft``;
- ``cases.csv`` → ``CaseDraft`` (``related_case_number`` normalized and kept);
- ``participants.csv`` → ``PersonDraft`` (hashes only) + ``CasePartyDraft``;
- ``charges.csv`` → ``ChargeDraft`` and the derived ``JusticeEventDraft``s:
  ``new_case`` when the participant has an earlier case, ``reconviction``
  when a conviction follows an earlier disposition of another case;
- ``assignments.csv`` → ``JudgeAssignmentDraft``;
- ``events.csv`` → ``CourtEventDraft``, plus a ``JusticeEventDraft`` for a
  ``failure_to_appear`` or ``revocation``;
- ``decisions.csv`` → ``DecisionDraft`` (a ``pretrial_release`` row carries
  its ``PretrialReleaseDraft``);
- ``sentences.csv`` → ``SentenceDraft``.

Cross-row facts (court codes → court keys, a participant's other cases)
come from ``SyntheticContext``, built by the connector's ``load_context``
over every artifact of the run, so a single changed file normalizes
against the complete export. The participant id is used as the source
hands it out: the generator assigns one id per person across its courts
(docs/SYNTHETIC_DATA.md), so the namespace is the source, not the court.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import SecretStr

from judgemetrics.db.models.enums import ActorType
from judgemetrics.ingest.base import (
    CanonicalRecord,
    CaseDraft,
    CasePartyDraft,
    ChargeDraft,
    CourtDraft,
    CourtEventDraft,
    DecisionDraft,
    JudgeAssignmentDraft,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    JusticeEventDraft,
    NaturalKey,
    NormalizationError,
    PersonDraft,
    PretrialReleaseDraft,
    SentenceDraft,
    SourceRecordDraft,
)
from judgemetrics.ingest.synthetic.schema import (
    COURT_IDENTITY_SYSTEM,
    FALSE,
    JUDGE_IDENTITY_SYSTEM,
    JURISDICTION_TYPE,
    LIST_SEPARATOR,
    RECORD_TYPE_ASSIGNMENT,
    RECORD_TYPE_CASE,
    RECORD_TYPE_CHARGE,
    RECORD_TYPE_COURT,
    RECORD_TYPE_DECISION,
    RECORD_TYPE_EVENT,
    RECORD_TYPE_JUDGE,
    RECORD_TYPE_MANIFEST,
    RECORD_TYPE_PARTICIPANT,
    RECORD_TYPE_SENTENCE,
    TRUE,
)
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.case_numbers import normalize_case_number
from judgemetrics.normalization.names import normalize_person_name
from judgemetrics.security.identifiers import (
    KIND_DATE_OF_BIRTH,
    KIND_FULL_NAME,
    KIND_NAME_DOB,
    KIND_SOURCE_PARTICIPANT_ID,
    hash_identifier,
    name_dob_value,
    normalize_identifier,
)

DECISION_PRETRIAL_RELEASE = "pretrial_release"
DECISION_DISMISSAL = "dismissal"
DECISION_DISPOSITION = "disposition"
DECISION_SENTENCING = "sentencing"
EVENT_FAILURE_TO_APPEAR = "failure_to_appear"
EVENT_REVOCATION = "revocation"
JUSTICE_NEW_CASE = "new_case"
JUSTICE_RECONVICTION = "reconviction"
CONVICTED_DISPOSITIONS = frozenset({"convicted_plea", "convicted_verdict"})
JUDGE_STATUS_ACTIVE = "active"
JUDGE_STATUS_INACTIVE = "inactive"
ASSIGNMENT_CONFIDENCE = Decimal("1.0000")
DERIVED_EVENT_CONFIDENCE = Decimal("1.0000")


@dataclass(frozen=True, slots=True)
class CaseFacts:
    """What the charges file says about one case of one participant."""

    case_key: NaturalKey
    filed_at: datetime
    disposed_ats: tuple[datetime, ...]


@dataclass(slots=True)
class SyntheticContext:
    """Cross-row lookups built from the whole export before any row is normalized."""

    # court_code → the court's draft (its natural key is the case key prefix).
    courts: dict[str, CourtDraft] = field(default_factory=dict)
    # judge_code → whether any service record is open (no end date).
    judge_active: dict[str, bool] = field(default_factory=dict)
    # normalized participant id → the participant's cases per the charges file.
    participant_cases: dict[str, list[CaseFacts]] = field(default_factory=dict)

    def court_key(self, court_code: str, record_id: str) -> NaturalKey:
        court = self.courts.get(court_code.strip())
        if court is None:
            msg = f"{record_id}: unknown court code {court_code!r}"
            raise NormalizationError(msg)
        return court.natural_key


# --- value parsing ------------------------------------------------------------------


def clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def parse_timestamp(value: object, *, column: str, record_id: str) -> datetime | None:
    """ISO 8601 with an offset → aware ``datetime``; empty → ``None``; else reject the row."""
    text = clean(value)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        msg = f"{record_id}: {column} {text!r} is not an ISO 8601 timestamp"
        raise NormalizationError(msg) from exc
    if parsed.tzinfo is None:
        msg = f"{record_id}: {column} {text!r} has no UTC offset"
        raise NormalizationError(msg)
    return parsed


def require_timestamp(value: object, *, column: str, record_id: str) -> datetime:
    parsed = parse_timestamp(value, column=column, record_id=record_id)
    if parsed is None:
        msg = f"{record_id}: {column} is empty"
        raise NormalizationError(msg)
    return parsed


def parse_date(value: object, *, column: str, record_id: str) -> date | None:
    text = clean(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        msg = f"{record_id}: {column} {text!r} is not an ISO date"
        raise NormalizationError(msg) from exc


def parse_bool(value: object, *, column: str, record_id: str) -> bool | None:
    text = clean(value).lower()
    if not text:
        return None
    if text == TRUE:
        return True
    if text == FALSE:
        return False
    msg = f"{record_id}: {column} {text!r} is not true or false"
    raise NormalizationError(msg)


def parse_int(value: object, *, column: str, record_id: str) -> int | None:
    text = clean(value)
    if not text:
        return None
    try:
        return int(text)
    except ValueError as exc:
        msg = f"{record_id}: {column} {text!r} is not an integer"
        raise NormalizationError(msg) from exc


def parse_decimal(value: object, *, column: str, record_id: str) -> Decimal | None:
    text = clean(value)
    if not text:
        return None
    try:
        return Decimal(text)
    except InvalidOperation as exc:
        msg = f"{record_id}: {column} {text!r} is not a number"
        raise NormalizationError(msg) from exc


def parse_list(value: object, kind: str, *, record_id: str) -> dict[str, Any]:
    """``"check_in;drug_testing"`` → ``{"check_in": True, "drug_testing": True}`` (vocabulary-checked)."""
    text = clean(value)
    if not text:
        return {}
    items = [item.strip() for item in text.split(LIST_SEPARATOR) if item.strip()]
    return {vocabulary.require(kind, item, context=record_id): True for item in items}


def require_value(payload: Mapping[str, Any], column: str, *, record_id: str) -> str:
    text = clean(payload.get(column))
    if not text:
        msg = f"{record_id}: {column} is empty"
        raise NormalizationError(msg)
    return text


def actor_type(value: object, *, record_id: str, required: bool) -> ActorType | None:
    text = clean(value)
    if not text:
        if required:
            return ActorType.UNKNOWN
        return None
    return ActorType(vocabulary.require("actor_type", text, context=record_id))


def case_key_for(
    context: SyntheticContext, payload: Mapping[str, Any], record_id: str
) -> NaturalKey:
    court_key = context.court_key(clean(payload.get("court_code")), record_id)
    number = require_value(payload, "case_number", record_id=record_id)
    return ("case", *court_key[1:], normalize_case_number(number))


def person_key_for(pepper: SecretStr, participant_id: str) -> NaturalKey:
    return (
        "person",
        KIND_SOURCE_PARTICIPANT_ID,
        hash_identifier(pepper, KIND_SOURCE_PARTICIPANT_ID, participant_id),
    )


def judge_key_for(judge_code: object) -> NaturalKey | None:
    code = clean(judge_code)
    if not code:
        return None
    return ("judge", JUDGE_IDENTITY_SYSTEM, code)


# --- per-file mappings ---------------------------------------------------------------


def court_drafts(payload: Mapping[str, Any]) -> tuple[JurisdictionDraft, CourtDraft]:
    code = require_value(payload, "court_code", record_id="court")
    record_id = f"court {code}"
    name = require_value(payload, "name", record_id=record_id)
    state_code = clean(payload.get("state_code")) or None
    jurisdiction = JurisdictionDraft(
        name=require_value(payload, "jurisdiction", record_id=record_id),
        type=JURISDICTION_TYPE,
        state_code=state_code,
    )
    court = CourtDraft(
        canonical_name=name,
        court_type=require_value(payload, "court_type", record_id=record_id),
        jurisdiction_key=jurisdiction.natural_key,
        external_ids={COURT_IDENTITY_SYSTEM: code},
        state_code=state_code,
    )
    return jurisdiction, court


def judge_drafts(
    context: SyntheticContext, payload: Mapping[str, Any]
) -> tuple[JudgeDraft, JudgeServiceDraft]:
    code = require_value(payload, "judge_code", record_id="judge")
    record_id = f"judge {code}"
    name = require_value(payload, "full_name", record_id=record_id)
    active = context.judge_active.get(code, not clean(payload.get("end_date")))
    judge = JudgeDraft(
        canonical_name=name,
        normalized_name=normalize_person_name(name),
        identity_key=(JUDGE_IDENTITY_SYSTEM, code),
        external_ids={JUDGE_IDENTITY_SYSTEM: code},
        status=JUDGE_STATUS_ACTIVE if active else JUDGE_STATUS_INACTIVE,
    )
    service = JudgeServiceDraft(
        judge_key=judge.natural_key,
        court_key=context.court_key(clean(payload.get("court_code")), record_id),
        position_type=vocabulary.require(
            "position", require_value(payload, "position", record_id=record_id), context=record_id
        ),
        start_date=parse_date(payload.get("start_date"), column="start_date", record_id=record_id),
        end_date=parse_date(payload.get("end_date"), column="end_date", record_id=record_id),
    )
    return judge, service


def case_draft(context: SyntheticContext, payload: Mapping[str, Any]) -> CaseDraft:
    number = require_value(payload, "case_number", record_id="case")
    record_id = f"case {number}"
    court_key = context.court_key(clean(payload.get("court_code")), record_id)
    related = clean(payload.get("related_case_number"))
    return CaseDraft(
        court_key=court_key,
        case_number=number,
        case_number_normalized=normalize_case_number(number),
        case_type=vocabulary.require(
            "case_type", require_value(payload, "case_type", record_id=record_id), context=record_id
        ),
        filed_date=parse_date(payload.get("filed_date"), column="filed_date", record_id=record_id),
        closed_date=parse_date(
            payload.get("closed_date"), column="closed_date", record_id=record_id
        ),
        status=vocabulary.require(
            "case_status", require_value(payload, "status", record_id=record_id), context=record_id
        ),
        source_row_id=number,
        related_case_number_normalized=normalize_case_number(related) if related else None,
    )


def person_draft(pepper: SecretStr, participant_id: str, full_name: str, dob: str) -> PersonDraft:
    """Hashes of the participant's identifiers; the name and date never leave this function."""
    hashes = {
        KIND_SOURCE_PARTICIPANT_ID: hash_identifier(
            pepper, KIND_SOURCE_PARTICIPANT_ID, participant_id
        )
    }
    name = clean(full_name)
    birth = clean(dob)
    if name and normalize_person_name(name):
        hashes[KIND_FULL_NAME] = hash_identifier(pepper, KIND_FULL_NAME, name)
    if birth:
        hashes[KIND_DATE_OF_BIRTH] = hash_identifier(pepper, KIND_DATE_OF_BIRTH, birth)
    if KIND_FULL_NAME in hashes and birth:
        hashes[KIND_NAME_DOB] = hash_identifier(pepper, KIND_NAME_DOB, name_dob_value(name, birth))
    return PersonDraft(
        identity=(KIND_SOURCE_PARTICIPANT_ID, hashes[KIND_SOURCE_PARTICIPANT_ID]),
        identifier_hashes=hashes,
        birth_year_known=KIND_DATE_OF_BIRTH in hashes,
    )


def participant_drafts(
    context: SyntheticContext, pepper: SecretStr, payload: Mapping[str, Any]
) -> tuple[PersonDraft, CasePartyDraft]:
    participant_id = require_value(payload, "participant_id", record_id="participant")
    record_id = f"participant {participant_id}"
    case_key = case_key_for(context, payload, record_id)
    party_type = vocabulary.require(
        "party_type", require_value(payload, "party_type", record_id=record_id), context=record_id
    )
    try:
        person = person_draft(
            pepper,
            participant_id,
            clean(payload.get("full_name")),
            clean(payload.get("date_of_birth")),
        )
    except ValueError as exc:
        msg = f"{record_id}: cannot hash identifiers ({exc.__class__.__name__})"
        raise NormalizationError(msg) from exc
    party = CasePartyDraft(
        case_key=case_key,
        person_key=person.natural_key,
        party_type=party_type,
        source_party_label=party_type,
        source_row_id=normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, participant_id),
    )
    return person, party


def charge_drafts(
    context: SyntheticContext, pepper: SecretStr, payload: Mapping[str, Any]
) -> list[CanonicalRecord]:
    charge_id = require_value(payload, "charge_id", record_id="charge")
    record_id = f"charge {charge_id}"
    case_key = case_key_for(context, payload, record_id)
    participant_id = require_value(payload, "participant_id", record_id=record_id)
    person_key = person_key_for(pepper, participant_id)
    disposition = clean(payload.get("disposition")) or None
    if disposition is not None:
        disposition = vocabulary.require("charge_disposition", disposition, context=record_id)
    filed_at = require_timestamp(payload.get("filed_at"), column="filed_at", record_id=record_id)
    disposed_at = parse_timestamp(
        payload.get("disposed_at"), column="disposed_at", record_id=record_id
    )
    charge = ChargeDraft(
        case_key=case_key,
        person_key=person_key,
        statute_code=clean(payload.get("statute_code")) or None,
        description=require_value(payload, "description", record_id=record_id),
        offense_category=vocabulary.require(
            "offense_category",
            require_value(payload, "offense_category", record_id=record_id),
            context=record_id,
        ),
        severity=vocabulary.require(
            "severity", require_value(payload, "severity", record_id=record_id), context=record_id
        ),
        violent_flag=parse_bool(
            payload.get("violent_flag"), column="violent_flag", record_id=record_id
        ),
        filed_at=filed_at,
        disposed_at=disposed_at,
        disposition=disposition,
        disposition_actor=actor_type(
            payload.get("disposition_actor"), record_id=record_id, required=False
        ),
        source_row_id=charge_id,
    )
    drafts: list[CanonicalRecord] = [charge]
    drafts.extend(derived_justice_events(context, participant_id, person_key, charge))
    return drafts


def derived_justice_events(
    context: SyntheticContext, participant_id: str, person_key: NaturalKey, charge: ChargeDraft
) -> list[JusticeEventDraft]:
    """``new_case`` and ``reconviction`` for the charge's case, from the participant's other cases."""
    others = [
        facts
        for facts in context.participant_cases.get(
            normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, participant_id), ()
        )
        if facts.case_key != charge.case_key
    ]
    if not others:
        return []
    events: list[JusticeEventDraft] = []
    this_case = next(
        (
            facts
            for facts in context.participant_cases.get(
                normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, participant_id), ()
            )
            if facts.case_key == charge.case_key
        ),
        None,
    )
    filed_at = this_case.filed_at if this_case is not None else charge.filed_at
    if any(facts.filed_at < filed_at for facts in others):
        events.append(
            JusticeEventDraft(
                person_key=person_key,
                event_type=JUSTICE_NEW_CASE,
                event_at=filed_at,
                related_case_key=charge.case_key,
                description="a new case filed after an earlier case of the same person",
                confidence=DERIVED_EVENT_CONFIDENCE,
            )
        )
    if charge.disposition in CONVICTED_DISPOSITIONS and charge.disposed_at is not None:
        disposed_at = charge.disposed_at
        if any(earlier < disposed_at for facts in others for earlier in facts.disposed_ats):
            events.append(
                JusticeEventDraft(
                    person_key=person_key,
                    event_type=JUSTICE_RECONVICTION,
                    event_at=disposed_at,
                    related_case_key=charge.case_key,
                    description="a conviction after an earlier disposition of another case",
                    confidence=DERIVED_EVENT_CONFIDENCE,
                )
            )
    return events


def assignment_draft(context: SyntheticContext, payload: Mapping[str, Any]) -> JudgeAssignmentDraft:
    assignment_id = require_value(payload, "assignment_id", record_id="assignment")
    record_id = f"assignment {assignment_id}"
    judge_key = judge_key_for(payload.get("judge_code"))
    if judge_key is None:
        msg = f"{record_id}: judge_code is empty"
        raise NormalizationError(msg)
    return JudgeAssignmentDraft(
        case_key=case_key_for(context, payload, record_id),
        judge_key=judge_key,
        assignment_type=vocabulary.require(
            "assignment_type",
            require_value(payload, "assignment_type", record_id=record_id),
            context=record_id,
        ),
        start_at=require_timestamp(payload.get("start_at"), column="start_at", record_id=record_id),
        end_at=parse_timestamp(payload.get("end_at"), column="end_at", record_id=record_id),
        source_row_id=assignment_id,
        confidence=ASSIGNMENT_CONFIDENCE,
    )


def event_drafts(
    context: SyntheticContext, pepper: SecretStr, payload: Mapping[str, Any]
) -> list[CanonicalRecord]:
    event_id = require_value(payload, "event_id", record_id="event")
    record_id = f"event {event_id}"
    case_key = case_key_for(context, payload, record_id)
    participant_id = clean(payload.get("participant_id"))
    person_key = person_key_for(pepper, participant_id) if participant_id else None
    event_type = vocabulary.require(
        "event_type", require_value(payload, "event_type", record_id=record_id), context=record_id
    )
    event_at = require_timestamp(payload.get("event_at"), column="event_at", record_id=record_id)
    event = CourtEventDraft(
        case_key=case_key,
        person_key=person_key,
        judge_key=judge_key_for(payload.get("judge_code")),
        event_type=event_type,
        event_at=event_at,
        description=clean(payload.get("description")) or None,
        actor_type=actor_type(payload.get("actor"), record_id=record_id, required=False),
        source_row_id=event_id,
    )
    drafts: list[CanonicalRecord] = [event]
    if person_key is not None and event_type in (EVENT_FAILURE_TO_APPEAR, EVENT_REVOCATION):
        drafts.append(
            JusticeEventDraft(
                person_key=person_key,
                event_type=vocabulary.require("justice_event_type", event_type, context=record_id),
                event_at=event_at,
                related_case_key=case_key,
                description=event.description,
                confidence=DERIVED_EVENT_CONFIDENCE,
            )
        )
    return drafts


def pretrial_draft(payload: Mapping[str, Any], record_id: str) -> PretrialReleaseDraft:
    release_type = vocabulary.require(
        "release_type",
        require_value(payload, "release_type", record_id=record_id),
        context=record_id,
    )
    detained = parse_bool(payload.get("detained"), column="detained", record_id=record_id)
    if detained is None:
        msg = f"{record_id}: detained is empty on a pretrial release"
        raise NormalizationError(msg)
    return PretrialReleaseDraft(
        release_type=release_type,
        bond_amount=parse_decimal(
            payload.get("bond_amount"), column="bond_amount", record_id=record_id
        ),
        conditions=parse_list(payload.get("conditions"), "release_condition", record_id=record_id),
        release_at=parse_timestamp(
            payload.get("release_at"), column="release_at", record_id=record_id
        ),
        detained_flag=detained,
    )


def decision_draft(
    context: SyntheticContext, pepper: SecretStr, payload: Mapping[str, Any]
) -> DecisionDraft:
    decision_id = require_value(payload, "decision_id", record_id="decision")
    record_id = f"decision {decision_id}"
    decision_type = vocabulary.require(
        "decision_type",
        require_value(payload, "decision_type", record_id=record_id),
        context=record_id,
    )
    actor = actor_type(payload.get("actor"), record_id=record_id, required=True)
    if actor is None:  # pragma: no cover - required=True never yields None
        actor = ActorType.UNKNOWN
    pretrial = (
        pretrial_draft(payload, record_id) if decision_type == DECISION_PRETRIAL_RELEASE else None
    )
    value: dict[str, Any] = {}
    if pretrial is not None:
        value = {"release_type": pretrial.release_type, "detained": pretrial.detained_flag}
    return DecisionDraft(
        case_key=case_key_for(context, payload, record_id),
        person_key=person_key_for(
            pepper, require_value(payload, "participant_id", record_id=record_id)
        ),
        judge_key=judge_key_for(payload.get("judge_code")),
        decision_type=decision_type,
        decision_at=require_timestamp(
            payload.get("decision_at"), column="decision_at", record_id=record_id
        ),
        decision_value=value,
        actor_type=actor,
        judicial_discretion_classification=vocabulary.require_or_unknown(
            "judicial_discretion_classification",
            clean(payload.get("discretion")),
            context=record_id,
        ),
        pretrial=pretrial,
        source_row_id=decision_id,
    )


def sentence_draft(
    context: SyntheticContext, pepper: SecretStr, payload: Mapping[str, Any]
) -> SentenceDraft:
    sentence_id = require_value(payload, "sentence_id", record_id="sentence")
    record_id = f"sentence {sentence_id}"
    return SentenceDraft(
        case_key=case_key_for(context, payload, record_id),
        person_key=person_key_for(
            pepper, require_value(payload, "participant_id", record_id=record_id)
        ),
        judge_key=judge_key_for(payload.get("judge_code")),
        sentence_at=require_timestamp(
            payload.get("sentence_at"), column="sentence_at", record_id=record_id
        ),
        incarceration_days=parse_int(
            payload.get("incarceration_days"), column="incarceration_days", record_id=record_id
        ),
        probation_days=parse_int(
            payload.get("probation_days"), column="probation_days", record_id=record_id
        ),
        fine_amount=parse_decimal(
            payload.get("fine_amount"), column="fine_amount", record_id=record_id
        ),
        components=parse_list(payload.get("components"), "sentence_component", record_id=record_id),
        source_row_id=sentence_id,
    )


def normalize_record(
    context: SyntheticContext, pepper: SecretStr, record: SourceRecordDraft
) -> list[CanonicalRecord]:
    """The drafts a parsed synthetic row yields (dispatch on ``record_type``)."""
    payload = record.payload
    kind = record.record_type
    if kind == RECORD_TYPE_MANIFEST:
        return []
    if kind == RECORD_TYPE_COURT:
        return list(court_drafts(payload))
    if kind == RECORD_TYPE_JUDGE:
        return list(judge_drafts(context, payload))
    if kind == RECORD_TYPE_CASE:
        return [case_draft(context, payload)]
    if kind == RECORD_TYPE_PARTICIPANT:
        return list(participant_drafts(context, pepper, payload))
    if kind == RECORD_TYPE_CHARGE:
        return charge_drafts(context, pepper, payload)
    if kind == RECORD_TYPE_ASSIGNMENT:
        return [assignment_draft(context, payload)]
    if kind == RECORD_TYPE_EVENT:
        return event_drafts(context, pepper, payload)
    if kind == RECORD_TYPE_DECISION:
        return [decision_draft(context, pepper, payload)]
    if kind == RECORD_TYPE_SENTENCE:
        return [sentence_draft(context, pepper, payload)]
    msg = f"unknown synthetic record type {kind!r}"
    raise NormalizationError(msg)


# --- context ----------------------------------------------------------------------------


def build_context(
    court_rows: Sequence[Mapping[str, Any]],
    judge_rows: Sequence[Mapping[str, Any]],
    charge_rows: Sequence[Mapping[str, Any]],
) -> SyntheticContext:
    """The lookups ``normalize_record`` needs, from the parsed rows of three files.

    Rows that cannot be read are skipped here; they are rejected with an
    issue when their own normalization runs.
    """
    context = SyntheticContext()
    for row in court_rows:
        try:
            _, court = court_drafts(row)
        except NormalizationError:
            continue
        context.courts[clean(row.get("court_code"))] = court
    for row in judge_rows:
        code = clean(row.get("judge_code"))
        if not code:
            continue
        context.judge_active[code] = context.judge_active.get(code, False) or not clean(
            row.get("end_date")
        )
    per_case: dict[tuple[str, NaturalKey], list[tuple[datetime, datetime | None]]] = {}
    for row in charge_rows:
        participant_id = clean(row.get("participant_id"))
        if not participant_id:
            continue
        try:
            case_key = case_key_for(context, row, "charge")
            filed_at = require_timestamp(row.get("filed_at"), column="filed_at", record_id="charge")
            disposed_at = parse_timestamp(
                row.get("disposed_at"), column="disposed_at", record_id="charge"
            )
            normalized = normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, participant_id)
        except (NormalizationError, ValueError):
            continue
        per_case.setdefault((normalized, case_key), []).append((filed_at, disposed_at))
    for (normalized, case_key), moments in per_case.items():
        context.participant_cases.setdefault(normalized, []).append(
            CaseFacts(
                case_key=case_key,
                filed_at=min(filed for filed, _ in moments),
                disposed_ats=tuple(sorted(d for _, d in moments if d is not None)),
            )
        )
    return context
