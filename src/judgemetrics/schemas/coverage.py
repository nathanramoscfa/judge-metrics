# src/judgemetrics/schemas/coverage.py
"""Coverage v0: what each ingested source contributes, and whether any of it is synthetic."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from judgemetrics.db.models.enums import IngestRunStatus


class LastIngest(BaseModel):
    run_id: uuid.UUID
    completed_at: datetime | None
    status: IngestRunStatus


class CoverageSource(BaseModel):
    source: str = Field(description="Source register key (docs/DATA_SOURCES.md).")
    source_type: str
    synthetic: bool = Field(description="True for the in-repo generator's dataset.")
    jurisdictions: int = Field(ge=0)
    courts: int = Field(ge=0)
    judges: int = Field(ge=0)
    cases: int = Field(ge=0)
    persons: int = Field(ge=0, description="Resolved persons (merged rows excluded).")
    earliest_filed: date | None
    latest_filed: date | None
    last_ingest: LastIngest | None = Field(description="The most recent completed run, any status.")


class Coverage(BaseModel):
    sources: list[CoverageSource] = Field(description="Every registered source, by name.")
    synthetic_present: bool = Field(
        description="True when any synthetic source has rows in the canonical tables."
    )
    generated_at: datetime
