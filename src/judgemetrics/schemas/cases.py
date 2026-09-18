# src/judgemetrics/schemas/cases.py
"""Case responses: the list summary, the detail, and the timeline.

Every person reference is a ``public_person_key``: the pseudonymous key
``person`` carries, never a name, a date of birth, or a source identifier
(those exist only as hashes in the restricted ``person_identifier`` table,
which no route reads). Decisions carry ``actor_type`` and
``judicial_discretion_classification`` so a prosecutor's dismissal is
never mistaken for a judicial one.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from judgemetrics.db.models.enums import ActorType
from judgemetrics.schemas.common import ApiModel, Provenance
from judgemetrics.schemas.judges import SYNTHETIC_DESCRIPTION, CourtRef, JudgeRef

PUBLIC_PERSON_KEY_DESCRIPTION = (
    "The pseudonymous public key of the resolved person; the only person "
    "identifier the API ever returns."
)

TimelineKind = Literal[
    "filed",
    "assignment_start",
    "assignment_end",
    "event",
    "decision",
    "charge_filed",
    "charge_disposed",
    "sentence",
    "closed",
]
# The order two entries at the same instant take: the timeline sorts by
# `at`, then by this rank, then by the row id.
TIMELINE_KIND_ORDER: tuple[TimelineKind, ...] = (
    "filed",
    "assignment_start",
    "assignment_end",
    "event",
    "decision",
    "charge_filed",
    "charge_disposed",
    "sentence",
    "closed",
)


class CaseSummary(ApiModel):
    id: uuid.UUID
    court: CourtRef
    case_number: str = Field(description="The docket number as the source recorded it.")
    case_type: str = Field(
        description="`felony` or `misdemeanor` (data/reference/case_vocabulary.yaml)."
    )
    filed_date: date | None
    closed_date: date | None
    status: str = Field(description="`open` or `closed`.")
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)


class CasePartyOut(BaseModel):
    party_type: str = Field(description="`defendant` in the current vocabulary.")
    public_person_key: str | None = Field(description=PUBLIC_PERSON_KEY_DESCRIPTION)


class AssignmentOut(BaseModel):
    judge: JudgeRef
    assignment_type: str = Field(description="`initial` or `reassignment`.")
    start_at: datetime
    end_at: datetime | None = Field(description="Null while the assignment is current.")


class ChargeOut(ApiModel):
    statute_code: str | None
    description: str
    offense_category: str
    severity: str
    violent_flag: bool | None
    filed_at: datetime
    disposed_at: datetime | None
    disposition: str | None = Field(
        description="`dismissed`, `acquitted`, `convicted_plea`, `convicted_verdict`, `pending`, or null."
    )
    disposition_actor: ActorType | None = Field(
        description="Who disposed of the charge; a prosecutor's dismissal is not a judicial one."
    )


class PretrialReleaseOut(ApiModel):
    release_type: str = Field(
        description="`recognizance`, `monetary_bond`, `detained`, or `statutory`."
    )
    bond_amount: Decimal | None
    conditions: dict[str, Any]
    release_at: datetime | None
    detained_flag: bool


class DecisionOut(BaseModel):
    decision_type: str = Field(
        description="`pretrial_release`, `dismissal`, `disposition`, or `sentencing`."
    )
    decision_at: datetime
    actor_type: ActorType = Field(description="Who decided: the basis of every inclusion rule.")
    judicial_discretion_classification: str = Field(
        description="`discretionary`, `mandatory`, `non_judicial`, or `unknown`."
    )
    judge: JudgeRef | None = Field(
        description="The deciding judge, when the decision was judicial."
    )
    public_person_key: str | None = Field(description=PUBLIC_PERSON_KEY_DESCRIPTION)
    decision_value: dict[str, Any]
    pretrial_release: PretrialReleaseOut | None


class SentenceOut(BaseModel):
    sentence_at: datetime
    judge: JudgeRef | None
    incarceration_days: int | None
    probation_days: int | None
    fine_amount: Decimal | None
    components: dict[str, Any] = Field(
        description="The sentence components as the source listed them."
    )


class CaseDetail(CaseSummary):
    parties: list[CasePartyOut]
    assignments: list[AssignmentOut] = Field(description="Oldest first.")
    charges: list[ChargeOut] = Field(description="By filing time.")
    decisions: list[DecisionOut] = Field(description="By decision time.")
    sentences: list[SentenceOut] = Field(description="By sentencing time.")
    provenance: list[Provenance] = Field(
        description="The distinct raw artifacts behind the case and every row it contains."
    )


class TimelineEntry(BaseModel):
    at: datetime = Field(
        description=(
            "When the entry happened. Date-only facts sit at the start (`filed`) or the "
            "end (`closed`) of their day, so a day's events fall between them."
        )
    )
    kind: TimelineKind
    actor_type: ActorType | None = Field(description="Who acted, when the source records it.")
    judge: JudgeRef | None
    label: str = Field(description="A short human-readable line for the entry.")
    detail: dict[str, Any] = Field(description="The public columns of the underlying row.")
    source: Provenance = Field(description="The raw artifact the underlying row came from.")


class Timeline(BaseModel):
    case_id: uuid.UUID
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)
    entries: list[TimelineEntry] = Field(
        description="Chronological: by `at`, then the documented kind order, then the row id."
    )
