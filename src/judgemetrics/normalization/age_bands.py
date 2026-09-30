# src/judgemetrics/normalization/age_bands.py
"""An age at filing → the restricted ``age_band`` vocabulary value.

The bands are the ``age_band`` kind of ``data/reference/case_vocabulary.yaml``
(version 2): ``18-24``, ``25-34``, ``35-44``, ``45-54``, ``55+``, and
``unknown`` for a missing age or one below the youngest band. A connector
parses the source's age as a bounded integer (``parse_age``) and publishes
only the band, into the ``restricted`` schema; the raw age never reaches a
draft. ``judgemetrics.synthetic.vocabulary.age_band_of`` is the generator's
own copy of the rule (the generator stays independent of this package) and
a unit test holds the two equal for every age.
"""

from __future__ import annotations

from judgemetrics.ingest.base import NormalizationError
from judgemetrics.normalization import vocabulary

UNKNOWN_BAND = "unknown"
# The youngest age (whole years at filing) of each band, oldest band first.
BAND_FLOORS: tuple[tuple[str, int], ...] = (
    ("55+", 55),
    ("45-54", 45),
    ("35-44", 35),
    ("25-34", 25),
    ("18-24", 18),
)
# The ages a source may report; anything outside rejects the row.
MIN_AGE = 0
MAX_AGE = 130


def age_band(age: int | None) -> str:
    """The band of an age in whole years at filing (``unknown`` without one)."""
    if age is None:
        return UNKNOWN_BAND
    for band, floor in BAND_FLOORS:
        if age >= floor:
            return vocabulary.require("age_band", band)
    return UNKNOWN_BAND


def parse_age(text: str, *, context: str = "") -> int | None:
    """A bounded integer age, ``None`` when blank; anything else raises ``NormalizationError``.

    The message names the column and the bounds, never the value.
    """
    value = text.strip()
    if not value:
        return None
    where = f"{context}: " if context else ""
    if not value.isascii() or not value.isdigit():
        msg = f"{where}age_at_filing is not a whole number"
        raise NormalizationError(msg)
    age = int(value)
    if not MIN_AGE <= age <= MAX_AGE:
        msg = f"{where}age_at_filing is outside {MIN_AGE}..{MAX_AGE}"
        raise NormalizationError(msg)
    return age
