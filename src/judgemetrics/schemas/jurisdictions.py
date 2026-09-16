# src/judgemetrics/schemas/jurisdictions.py
"""Jurisdiction responses."""

from __future__ import annotations

import uuid

from judgemetrics.db.models.enums import JurisdictionType
from judgemetrics.schemas.common import ApiModel, Provenance


class JurisdictionSummary(ApiModel):
    id: uuid.UUID
    name: str
    type: JurisdictionType
    state_code: str | None
    fips_code: str | None
    parent_jurisdiction_id: uuid.UUID | None


class JurisdictionDetail(JurisdictionSummary):
    provenance: list[Provenance]
