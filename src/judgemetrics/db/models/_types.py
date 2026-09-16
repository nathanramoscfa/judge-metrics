# src/judgemetrics/db/models/_types.py
"""Column-type helpers shared by the model modules."""

from __future__ import annotations

from enum import StrEnum

from sqlalchemy import Enum
from sqlalchemy.dialects.postgresql import JSONB

from judgemetrics.db.models.enums import PG_ENUM_NAMES


def pg_enum(enum_cls: type[StrEnum]) -> Enum:
    """A PostgreSQL ENUM column type storing the enum *values* (not names)."""
    return Enum(
        enum_cls,
        name=PG_ENUM_NAMES[enum_cls],
        values_callable=lambda members: [member.value for member in members],
        validate_strings=True,
    )


JSONBDict = JSONB(none_as_null=True)
