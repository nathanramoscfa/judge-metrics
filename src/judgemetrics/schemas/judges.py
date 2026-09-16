# src/judgemetrics/schemas/judges.py
"""Judge responses: the list summary, the detail, and service records."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import Field

from judgemetrics.schemas.common import ApiModel, Provenance

# The vocabulary `judge.status` is derived into (ingest/fjc/schema.py).
JudgeStatus = Literal[
    "active", "senior", "deceased", "retired", "resigned", "removed", "inactive", "unknown"
]


class CourtRef(ApiModel):
    """The court a service record belongs to, enough to link and label it."""

    id: uuid.UUID
    canonical_name: str
    court_type: str


class ServiceRecord(ApiModel):
    """One appointment: a judge at a court in a position over an interval."""

    id: uuid.UUID
    court: CourtRef
    position_type: str
    start_date: date | None
    end_date: date | None = Field(description="Null while the appointment is current.")
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_",
        description="Public appointment facts with no column of their own.",
    )


class JudgeSummary(ApiModel):
    id: uuid.UUID
    canonical_name: str
    status: JudgeStatus


class JudgeDetail(JudgeSummary):
    normalized_name: str
    external_ids: dict[str, Any] = Field(description="Public source identifiers, e.g. `fjc_nid`.")
    metadata: dict[str, Any] = Field(
        validation_alias="metadata_", description="Public biographical facts only."
    )
    service: list[ServiceRecord]
    provenance: list[Provenance] = Field(
        description="The raw artifacts behind this judge and each service record."
    )
