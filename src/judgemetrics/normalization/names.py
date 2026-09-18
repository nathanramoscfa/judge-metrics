# src/judgemetrics/normalization/names.py
"""Person-name normalization used by entity resolution.

Source-specific parsing lives in the connectors; these functions are the
canonical-domain rules that every connector's output passes through, so two
sources spelling the same judge differently land on the same normalized
key. Normalization is one *signal* for resolution — never merge persons on
name alone. Case numbers are normalized by ``case_numbers`` (re-exported
here for the Phase 1 call sites).
"""

from __future__ import annotations

import re
import unicodedata

from judgemetrics.normalization.case_numbers import normalize_case_number

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE = re.compile(r"\s+")


def normalize_person_name(raw: str) -> str:
    """Unicode NFKD, strip diacritics, casefold, drop punctuation, collapse spaces.

    ``"José  Núñez-Ortíz, Jr."`` → ``"jose nunez ortiz jr"``.
    """
    decomposed = unicodedata.normalize("NFKD", raw)
    ascii_only = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    folded = ascii_only.casefold()
    # Hyphens and apostrophes become spaces so hyphenated names keep their parts.
    spaced = _PUNCTUATION.sub(" ", folded)
    return _WHITESPACE.sub(" ", spaced).strip()


def canonical_person_name(
    first: str | None,
    middle: str | None,
    last: str | None,
    suffix: str | None = None,
) -> str:
    """Display form ``"First Middle Last, Suffix"`` from separately sourced parts.

    Parts are trimmed and inner whitespace collapsed; empty parts are skipped.
    The result is *not* normalized (it keeps case and diacritics) — it is the
    ``canonical_name`` shown to readers, while ``normalize_person_name`` gives
    the ``normalized_name`` used for matching.
    """
    parts = [_WHITESPACE.sub(" ", part).strip() for part in (first, middle, last) if part]
    name = " ".join(part for part in parts if part)
    suffix_clean = _WHITESPACE.sub(" ", suffix).strip() if suffix else ""
    if suffix_clean:
        return f"{name}, {suffix_clean}" if name else suffix_clean
    return name


__all__ = ["canonical_person_name", "normalize_case_number", "normalize_person_name"]
