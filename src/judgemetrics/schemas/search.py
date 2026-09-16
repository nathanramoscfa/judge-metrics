# src/judgemetrics/schemas/search.py
"""Search responses."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    entity_type: Literal["judge", "court"]
    id: uuid.UUID
    name: str
    score: float = Field(ge=0.0, le=1.0, description="pg_trgm similarity to the query.")


class SearchResponse(BaseModel):
    query: str = Field(description="The query after name normalization, as matched.")
    limit: int
    items: list[SearchResult] = Field(description="Best matches first.")
