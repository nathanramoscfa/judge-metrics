# src/judgemetrics/normalization/case_numbers.py
"""Case-number normalization: the key on which a court's cases are unique.

Two source rows for the same docket may differ only in formatting
(``SYN-2019-000013`` and ``syn 2019 000013``; ``1:21-cr-00123`` and
``1 21 CR 00123``). The rule maps them to one key: upper-case, every run
of whitespace or punctuation becomes a single ``-``, and leading or
trailing separators are dropped, so the year and sequence survive and the
only punctuation left is the hyphen. The raw value is always kept on the
row (``court_case.case_number``); the normalized form is the natural key
(``court_case.case_number_normalized``). Court-specific rules can be added
by ``court_type`` without changing call sites; every court type currently
shares this rule.
"""

from __future__ import annotations

import re

# Every character that is not a letter or digit (ASCII) is a separator.
_SEPARATORS = re.compile(r"[^A-Z0-9]+")


def normalize_case_number(raw: str, court_type: str | None = None) -> str:
    """``" syn 2019 000013 "`` → ``"SYN-2019-000013"``; ``"1:21-cr-00123"`` → ``"1-21-CR-00123"``."""
    del court_type  # reserved for court-specific rules
    upper = raw.strip().upper()
    return _SEPARATORS.sub("-", upper).strip("-")
