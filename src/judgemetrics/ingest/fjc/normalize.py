# src/judgemetrics/ingest/fjc/normalize.py
"""FJC source rows → canonical drafts.

Source-specific parsing lives here (FJC column names, its date and
court-name conventions, its termination vocabulary); the canonical rules
it calls — name canonicalization and normalization, the state-code
lookup — live in ``judgemetrics.normalization``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from judgemetrics.ingest.base import (
    CanonicalRecord,
    CourtDraft,
    JudgeDraft,
    JudgeServiceDraft,
    JurisdictionDraft,
    NormalizationError,
    SourceRecordDraft,
)
from judgemetrics.ingest.fjc.schema import (
    COURT_TYPES,
    DATE_PATTERN,
    DEFAULT_COURT_TYPE,
    JID,
    NID,
    RECORD_TYPE_JUDGE,
    RECORD_TYPE_SERVICE,
    SEQUENCE,
    SERVICE_GROUP_COUNT,
    TERMINATION_STATUSES,
    group_header,
)
from judgemetrics.normalization.geography import state_code_for_name
from judgemetrics.normalization.names import canonical_person_name, normalize_person_name

FEDERAL_JURISDICTION = JurisdictionDraft(name="United States federal courts", type="federal")

# "U.S. District Court for the Southern District of New York" → "New York";
# "... District of Columbia (Supreme Court of the District of Columbia)" → "Columbia".
_DISTRICT_OF = re.compile(r"Districts? of (?:the )?(?P<name>[^()]+?)\s*(?:\(.*\))?\s*$")
_BIRTH_YEAR = re.compile(r"^(?P<approx>ca\.?\s*)?(?P<year>\d{4})$")
_DATE = re.compile(DATE_PATTERN)


def clean(value: object) -> str:
    return str(value).strip() if value is not None else ""


def parse_fjc_date(value: object, *, column: str, record_id: str) -> date | None:
    """``YYYY-MM-DD`` → ``date``; empty → ``None``; anything else rejects the row."""
    text = clean(value)
    if not text:
        return None
    if not _DATE.match(text):
        msg = f"{record_id}: {column} {text!r} is not an ISO date"
        raise NormalizationError(msg)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        msg = f"{record_id}: {column} {text!r} is not a valid date"
        raise NormalizationError(msg) from exc


def court_type_for(raw: str) -> str:
    """FJC "Court Type" → district | appeals | supreme | other."""
    return COURT_TYPES.get(clean(raw), DEFAULT_COURT_TYPE)


def state_code_for_court(court_name: str, court_type: str) -> str | None:
    """USPS code parsed from a district-court name; ``None`` for other courts or unknown places."""
    if court_type != "district":
        return None
    match = _DISTRICT_OF.search(clean(court_name))
    if match is None:
        return None
    name = match.group("name")
    # "District of Columbia" is itself the place name; every state follows it.
    return state_code_for_name(f"District of {name}") or state_code_for_name(name)


def birth_year_metadata(raw: str) -> dict[str, Any]:
    """``"1950"`` → ``{"birth_year": 1950}``; ``"ca. 1793"`` adds the approximate flag."""
    match = _BIRTH_YEAR.match(clean(raw))
    if match is None:
        return {}
    metadata: dict[str, Any] = {"birth_year": int(match.group("year"))}
    if match.group("approx"):
        metadata["birth_year_approximate"] = True
    return metadata


@dataclass(frozen=True, slots=True)
class ServiceGroup:
    """One appointment as recorded inline in a judges.csv row."""

    index: int
    court_name: str
    start_date: date | None
    senior_status_date: date | None
    termination: str


def service_groups(payload: Mapping[str, Any], record_id: str) -> list[ServiceGroup]:
    groups: list[ServiceGroup] = []
    for index in range(1, SERVICE_GROUP_COUNT + 1):
        court_name = clean(payload.get(group_header("Court Name", index)))
        if not court_name:
            continue
        commission = parse_fjc_date(
            payload.get(group_header("Commission Date", index)),
            column=group_header("Commission Date", index),
            record_id=record_id,
        )
        recess = parse_fjc_date(
            payload.get(group_header("Recess Appointment Date", index)),
            column=group_header("Recess Appointment Date", index),
            record_id=record_id,
        )
        senior = parse_fjc_date(
            payload.get(group_header("Senior Status Date", index)),
            column=group_header("Senior Status Date", index),
            record_id=record_id,
        )
        groups.append(
            ServiceGroup(
                index=index,
                court_name=court_name,
                start_date=commission or recess,
                senior_status_date=senior,
                termination=clean(payload.get(group_header("Termination", index))),
            )
        )
    return groups


def judge_status(groups: list[ServiceGroup]) -> str:
    """Status from the latest appointment: its termination, else senior status, else active."""
    if not groups:
        return "unknown"
    latest = max(groups, key=lambda group: (group.start_date or date.min, group.index))
    if latest.termination:
        return TERMINATION_STATUSES.get(latest.termination, "unknown")
    return "senior" if latest.senior_status_date else "active"


def judge_draft(payload: Mapping[str, Any]) -> JudgeDraft:
    nid = clean(payload.get(NID))
    if not nid:
        msg = "judge row without an nid"
        raise NormalizationError(msg)
    canonical = canonical_person_name(
        clean(payload.get("First Name")) or None,
        clean(payload.get("Middle Name")) or None,
        clean(payload.get("Last Name")) or None,
        clean(payload.get("Suffix")) or None,
    )
    if not canonical:
        msg = f"judge {nid}: no name parts"
        raise NormalizationError(msg)
    external_ids = {"fjc_nid": nid}
    jid = clean(payload.get(JID))
    if jid:
        external_ids["fjc_jid"] = jid
    return JudgeDraft(
        canonical_name=canonical,
        normalized_name=normalize_person_name(canonical),
        identity_key=("fjc_nid", nid),
        external_ids=external_ids,
        status=judge_status(service_groups(payload, f"judge {nid}")),
        metadata=birth_year_metadata(clean(payload.get("Birth Year"))),
    )


def court_draft(court_name: str, court_type_raw: str) -> CourtDraft:
    name = clean(court_name)
    court_type = court_type_for(court_type_raw)
    return CourtDraft(
        canonical_name=name,
        court_type=court_type,
        jurisdiction_key=FEDERAL_JURISDICTION.natural_key,
        external_ids={"fjc_court_name": name},
        state_code=state_code_for_court(name, court_type),
    )


def service_drafts(payload: Mapping[str, Any]) -> tuple[CourtDraft, JudgeServiceDraft]:
    nid = clean(payload.get(NID))
    sequence = clean(payload.get(SEQUENCE))
    record_id = f"service {nid}:{sequence}"
    if not nid:
        msg = "service row without an nid"
        raise NormalizationError(msg)
    court_name = clean(payload.get("Court Name"))
    if not court_name:
        msg = f"{record_id}: no court name"
        raise NormalizationError(msg)
    court = court_draft(court_name, clean(payload.get("Court Type")))
    position_type = clean(payload.get("Appointment Title"))
    if not position_type:
        msg = f"{record_id}: no appointment title"
        raise NormalizationError(msg)
    commission = parse_fjc_date(
        payload.get("Commission Date"), column="Commission Date", record_id=record_id
    )
    recess = parse_fjc_date(
        payload.get("Recess Appointment Date"),
        column="Recess Appointment Date",
        record_id=record_id,
    )
    termination_date = parse_fjc_date(
        payload.get("Termination Date"), column="Termination Date", record_id=record_id
    )
    senior = parse_fjc_date(
        payload.get("Senior Status Date"), column="Senior Status Date", record_id=record_id
    )
    metadata: dict[str, Any] = {"fjc_sequence": sequence}
    if commission is not None:
        metadata["start_date_basis"] = "commission_date"
    elif recess is not None:
        metadata["start_date_basis"] = "recess_appointment_date"
    if senior is not None:
        metadata["senior_status_date"] = senior.isoformat()
    termination = clean(payload.get("Termination"))
    if termination:
        metadata["termination"] = termination
    service = JudgeServiceDraft(
        judge_key=("judge", "fjc_nid", nid),
        court_key=court.natural_key,
        position_type=position_type,
        start_date=commission or recess,
        end_date=termination_date,
        metadata=metadata,
    )
    return court, service


def normalize_record(record: SourceRecordDraft) -> list[CanonicalRecord]:
    """The drafts a parsed FJC row yields (dispatch on ``record_type``)."""
    if record.record_type == RECORD_TYPE_JUDGE:
        return [judge_draft(record.payload)]
    if record.record_type == RECORD_TYPE_SERVICE:
        court, service = service_drafts(record.payload)
        return [FEDERAL_JURISDICTION, court, service]
    msg = f"unknown FJC record type {record.record_type!r}"
    raise NormalizationError(msg)
