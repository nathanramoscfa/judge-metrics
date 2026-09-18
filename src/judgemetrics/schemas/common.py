# src/judgemetrics/schemas/common.py
"""Shapes shared by every endpoint: the page envelope, provenance, coverage windows, errors."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    """Base for response models built from ORM rows (``from_attributes``).

    ``validate_by_name`` keeps construction by field name working for the
    fields that read an aliased ORM attribute (``metadata`` ← ``metadata_``).
    """

    model_config = ConfigDict(from_attributes=True, validate_by_name=True, validate_by_alias=True)

    @classmethod
    def from_row(cls, row: object, **extra: Any) -> Self:
        """Validate the ORM ``row``'s attributes plus ``extra`` fields the row lacks.

        Detail models carry assembled fields (``provenance``, ``service``)
        that no single row has; those come in through ``extra`` and every
        other field is read from the row by its validation alias or name.
        """
        values: dict[str, Any] = {}
        for name, info in cls.model_fields.items():
            if name in extra:
                continue
            attribute = info.validation_alias if isinstance(info.validation_alias, str) else name
            values[name] = getattr(row, attribute)
        return cls.model_validate({**values, **extra})


class Page[T](BaseModel):
    """The uniform list envelope: a window of ``items`` out of ``total``.

    ``next_offset`` is the ``offset`` of the following page, or ``null``
    when this page is the last one.
    """

    items: list[T]
    total: int = Field(ge=0, description="Rows matching the filters, across all pages.")
    limit: int = Field(ge=1, description="Page size that was applied.")
    offset: int = Field(ge=0, description="Rows skipped before this page.")
    next_offset: int | None = Field(description="Offset of the next page, or null on the last.")

    @classmethod
    def build(cls, items: list[T], *, total: int, limit: int, offset: int) -> Page[T]:
        following = offset + limit
        return cls(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
            next_offset=following if following < total else None,
        )


class Provenance(BaseModel):
    """Where a row's current values came from: one retrieved raw artifact.

    The raw object itself lives in the immutable lake under an internal
    storage key that is never published; ``raw_sha256`` identifies its
    bytes and ``ingest_run_id`` the run that fetched it.
    """

    source: str = Field(description="Source register key (docs/DATA_SOURCES.md), e.g. `fjc`.")
    external_record_id: str | None = Field(description="The artifact's id at the source.")
    retrieved_at: datetime
    raw_sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    parser_version: str
    ingest_run_id: uuid.UUID
    synthetic: bool = Field(
        description=(
            "True when the artifact belongs to a source of type `synthetic` (the in-repo "
            "generator): the row is demo data, never a court record."
        )
    )


class CoverageWindow(BaseModel):
    """The span of filing dates behind a set of cases, with their count."""

    earliest_filed: date | None
    latest_filed: date | None
    case_count: int = Field(ge=0)


class ErrorBody(BaseModel):
    """Every non-2xx response body. Never a stack trace, never SQL."""

    code: str = Field(
        description=(
            "Stable machine-readable code: validation_error, not_found, rate_limited, "
            "database_unavailable, internal_error, or http_error."
        )
    )
    message: str
    request_id: str = Field(description="Matches the `X-Request-ID` response header.")
