# src/judgemetrics/schemas/courts.py
"""Court responses."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from pydantic import Field

from judgemetrics.schemas.common import ApiModel, Provenance
from judgemetrics.schemas.judges import SYNTHETIC_DESCRIPTION


class CourtSummary(ApiModel):
    id: uuid.UUID
    canonical_name: str
    court_type: str = Field(description="district | appeals | supreme | other (federal, Phase 1).")
    state_code: str | None = Field(description="USPS code parsed from a district-court name.")
    jurisdiction_id: uuid.UUID
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)


class CourtDetail(CourtSummary):
    external_ids: dict[str, Any]
    active_from: date | None
    active_to: date | None
    provenance: list[Provenance]
