# src/judgemetrics/schemas/coverage.py
"""Coverage: what each ingested source contributes and covers, whether any of it is
synthetic, and which snapshot and methodology its numbers come from (v1, Phase 3 Step 3)."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from judgemetrics.db.models.enums import IngestRunStatus


class LastIngest(BaseModel):
    run_id: uuid.UUID
    completed_at: datetime | None
    status: IngestRunStatus


class LatestSnapshotOut(BaseModel):
    """The newest hashed export a source's current observations were computed from."""

    content_hash: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    exported_at: datetime


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
    coverage_start: date | None = Field(
        description="First day the source's records cover, as the connector declares it."
    )
    coverage_end: date | None = Field(
        description=(
            "Last day the source's records cover; the metrics engine censors follow-up the "
            "day after. Null for a source that declares no window (no metric is computed)."
        )
    )
    observable_outcomes: list[str] = Field(
        description="The justice_event_type values the source can document, sorted."
    )
    latest_snapshot: LatestSnapshotOut | None = Field(
        description="The newest snapshot behind the source's current observations, if any."
    )
    methodology_version: str | None = Field(
        description="The methodology version of that snapshot; null before the first compute."
    )


class Coverage(BaseModel):
    sources: list[CoverageSource] = Field(description="Every registered source, by name.")
    synthetic_present: bool = Field(
        description="True when any synthetic source has rows in the canonical tables."
    )
    registry_version: int = Field(ge=1, description="The metric registry the API serves.")
    methodology_version: str = Field(description="The registry's methodology version.")
    generated_at: datetime
