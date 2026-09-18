# src/judgemetrics/schemas/search.py
"""Search responses."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from judgemetrics.schemas.judges import SYNTHETIC_DESCRIPTION


class SearchResult(BaseModel):
    entity_type: Literal["judge", "court", "case"]
    id: uuid.UUID
    name: str = Field(description="The judge's or court's name, or the case number as filed.")
    score: float = Field(
        ge=0.0,
        le=1.0,
        description="pg_trgm similarity to the query; an exact case-number match scores 1.",
    )
    synthetic: bool = Field(description=SYNTHETIC_DESCRIPTION)


class SearchResponse(BaseModel):
    query: str = Field(description="The query after name normalization, as matched.")
    limit: int
    items: list[SearchResult] = Field(description="Best matches first.")
