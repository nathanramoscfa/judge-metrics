# src/judgemetrics/normalization/vocabulary.py
"""The versioned case-level vocabulary (``data/reference/case_vocabulary.yaml``).

Every connector maps its source values onto these kinds and values
(``case_type``, ``event_type``, ``charge_disposition``, …) before a draft
leaves ``normalize``; ``require(kind, value)`` raises ``NormalizationError``
for a value outside the vocabulary so an unmapped source value rejects
its row instead of entering a canonical column. ``UNKNOWN`` is a listed
value only for the kinds where the brief allows an explicit unknown
(``actor_type``, ``judicial_discretion_classification``): the pipeline
records it and the ``unknown_category_measured`` check counts it rather
than discarding the row.

The file is read once per process with ``yaml.safe_load``; its ``version``
is bumped whenever a value changes (docs/DATA_MODEL.md "Vocabularies").
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

import yaml

from judgemetrics.ingest.base import NormalizationError

REPO_ROOT = Path(__file__).resolve().parents[3]
CASE_VOCABULARY_PATH = REPO_ROOT / "data" / "reference" / "case_vocabulary.yaml"
UNKNOWN = "unknown"


class VocabularyFileError(RuntimeError):
    """The vocabulary file is missing or malformed (a deployment defect, not a row)."""


@lru_cache(maxsize=1)
def load_vocabulary(path: Path = CASE_VOCABULARY_PATH) -> tuple[int, Mapping[str, tuple[str, ...]]]:
    """``(version, {kind: values})`` from the YAML file; cached for the process."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"cannot read the case vocabulary at {path}: {exc}"
        raise VocabularyFileError(msg) from exc
    if not isinstance(payload, dict) or "version" not in payload or "kinds" not in payload:
        msg = f"{path}: expected a mapping with `version` and `kinds`"
        raise VocabularyFileError(msg)
    version = payload["version"]
    kinds = payload["kinds"]
    if not isinstance(version, int) or version < 1 or not isinstance(kinds, dict):
        msg = f"{path}: `version` must be a positive integer and `kinds` a mapping"
        raise VocabularyFileError(msg)
    vocabulary: dict[str, tuple[str, ...]] = {}
    for kind, values in kinds.items():
        if (
            not isinstance(kind, str)
            or not isinstance(values, list)
            or not values
            or not all(isinstance(value, str) and value for value in values)
            or len(set(values)) != len(values)
        ):
            msg = f"{path}: kind {kind!r} must list distinct non-empty strings"
            raise VocabularyFileError(msg)
        vocabulary[kind] = tuple(values)
    return version, vocabulary


def version() -> int:
    return load_vocabulary()[0]


def kinds() -> tuple[str, ...]:
    return tuple(load_vocabulary()[1])


def values(kind: str) -> tuple[str, ...]:
    """The listed values of ``kind``; ``KeyError`` for an unknown kind (a code defect)."""
    return load_vocabulary()[1][kind]


def is_known(kind: str, value: str) -> bool:
    return value in values(kind)


def allows_unknown(kind: str) -> bool:
    """Whether the brief lets ``kind`` carry an explicit ``unknown`` value."""
    return UNKNOWN in values(kind)


def require(kind: str, value: str, *, context: str = "") -> str:
    """``value`` if it is listed under ``kind``; otherwise ``NormalizationError``."""
    if is_known(kind, value):
        return value
    where = f"{context}: " if context else ""
    msg = f"{where}{kind} {value!r} is not in the case vocabulary (version {version()})"
    raise NormalizationError(msg)


def require_or_unknown(kind: str, value: str, *, context: str = "") -> str:
    """``require`` for kinds that allow ``unknown``, mapping an empty value to it.

    Used only where the brief allows an unknown category (actor type,
    discretion classification): a blank source cell becomes the explicit
    ``unknown`` that the data-quality checks count, never a silent drop.
    """
    if not allows_unknown(kind):
        msg = f"{kind} does not allow an unknown value"
        raise ValueError(msg)
    if not value:
        return UNKNOWN
    return require(kind, value, context=context)
