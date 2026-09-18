# src/judgemetrics/security/identifiers.py
"""Peppered hashing of person identifiers for the restricted ``person_identifier`` table.

A participant's source identifier, name, and date of birth reach the
database only as ``sha256(pepper || "\\x00" || kind || "\\x00" || normalized value)``
hex digests. The pepper (``JUDGEMETRICS_IDENTIFIER_PEPPER``, a
``SecretStr``) is a per-deployment secret that never enters the database
or the logs, so a leaked table cannot be joined back to a source without
it; the kind is part of the input so a name and an identifier with the
same text never share a digest, and the normalization per kind makes the
formatting variants of one source value (``"FOG MORAVA "`` and
``"Fog Morava"``, ``" pt-000005 "`` and ``"PT-000005"``) collide on purpose.

Kinds and their normalization:

- ``source_participant_id`` — stripped, upper-cased;
- ``full_name`` — ``normalize_person_name`` (NFKD, casefold, no punctuation);
- ``date_of_birth`` — ISO ``YYYY-MM-DD`` (a ``date`` or a parseable string);
- ``name_dob`` — the normalized name, ``|``, the ISO date (present only when
  both exist; the rule stage of entity resolution matches on it, never on
  the name alone).
"""

from __future__ import annotations

import hashlib
from datetime import date

from pydantic import SecretStr

from judgemetrics.config import Settings
from judgemetrics.normalization.names import normalize_person_name

KIND_SOURCE_PARTICIPANT_ID = "source_participant_id"
KIND_FULL_NAME = "full_name"
KIND_DATE_OF_BIRTH = "date_of_birth"
KIND_NAME_DOB = "name_dob"
IDENTIFIER_KINDS: tuple[str, ...] = (
    KIND_SOURCE_PARTICIPANT_ID,
    KIND_FULL_NAME,
    KIND_DATE_OF_BIRTH,
    KIND_NAME_DOB,
)
# The one kind a source keeps stable for a person: the deterministic
# resolution key (partial unique index ``uq_person_identifier_stable``).
STABLE_KINDS: frozenset[str] = frozenset({KIND_SOURCE_PARTICIPANT_ID})

_SEPARATOR = b"\x00"
_NAME_DOB_SEPARATOR = "|"


class IdentifierPepperMissingError(RuntimeError):
    """``JUDGEMETRICS_IDENTIFIER_PEPPER`` is not configured for a process that hashes."""


def require_identifier_pepper(settings: Settings) -> SecretStr:
    """The configured pepper, or a named error the CLI reports at startup."""
    pepper = settings.identifier_pepper
    if pepper is None or not pepper.get_secret_value().strip():
        msg = "JUDGEMETRICS_IDENTIFIER_PEPPER is not configured"
        raise IdentifierPepperMissingError(msg)
    return pepper


def normalize_identifier(kind: str, value: str | date) -> str:
    """The canonical text of ``value`` for ``kind`` (``ValueError`` for an empty or bad value)."""
    if kind == KIND_DATE_OF_BIRTH:
        return _iso_date(value)
    text = value.isoformat() if isinstance(value, date) else value
    if kind == KIND_SOURCE_PARTICIPANT_ID:
        normalized = text.strip().upper()
    elif kind == KIND_FULL_NAME:
        normalized = normalize_person_name(text)
    elif kind == KIND_NAME_DOB:
        normalized = text
    else:
        msg = f"unknown identifier kind {kind!r}"
        raise ValueError(msg)
    if not normalized:
        msg = f"{kind}: empty identifier value"
        raise ValueError(msg)
    return normalized


def name_dob_value(full_name: str, date_of_birth: str | date) -> str:
    """The ``name_dob`` input: normalized name, ``|``, ISO date."""
    name = normalize_identifier(KIND_FULL_NAME, full_name)
    return f"{name}{_NAME_DOB_SEPARATOR}{_iso_date(date_of_birth)}"


def hash_identifier(pepper: SecretStr, kind: str, value: str | date) -> str:
    """The 64-character hex digest of ``value`` under ``kind`` and ``pepper``."""
    secret = pepper.get_secret_value()
    if not secret.strip():
        msg = "the identifier pepper is empty"
        raise IdentifierPepperMissingError(msg)
    normalized = normalize_identifier(kind, value)
    digest = hashlib.sha256()
    digest.update(secret.encode("utf-8"))
    digest.update(_SEPARATOR)
    digest.update(kind.encode("utf-8"))
    digest.update(_SEPARATOR)
    digest.update(normalized.encode("utf-8"))
    return digest.hexdigest()


def _iso_date(value: str | date) -> str:
    if isinstance(value, date):
        return value.isoformat()
    text = value.strip()
    if not text:
        msg = "date_of_birth: empty value"
        raise ValueError(msg)
    return date.fromisoformat(text).isoformat()


__all__ = [
    "IDENTIFIER_KINDS",
    "KIND_DATE_OF_BIRTH",
    "KIND_FULL_NAME",
    "KIND_NAME_DOB",
    "KIND_SOURCE_PARTICIPANT_ID",
    "STABLE_KINDS",
    "IdentifierPepperMissingError",
    "hash_identifier",
    "name_dob_value",
    "normalize_identifier",
    "require_identifier_pepper",
]
