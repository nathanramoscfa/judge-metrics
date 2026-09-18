# tests/property/test_case_numbers.py
"""Case-number normalization is format-insensitive and idempotent.

A docket number reaches the pipeline in whatever shape a source exported
it: different case, spaces or punctuation between its parts, leading and
trailing separators. Every such variant of one number must normalize to
the same key (the natural key of ``court_case``), normalizing a key again
must leave it unchanged, and a key holds only upper-case ASCII letters,
digits, and single hyphens. The strategies build numbers from alphanumeric
segments and insert formatting only at segment boundaries, where the rule
promises to collapse it.
"""

from __future__ import annotations

import re
import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from judgemetrics.normalization.case_numbers import normalize_case_number

pytestmark = pytest.mark.property

KEY = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)*$")
ALNUM = string.ascii_letters + string.digits
# Everything the rule treats as a separator, including the runs and mixes
# real exports produce ("1:21-cr-00123", "2019 CF 001234", "CR/2018/00077").
SEPARATORS = " -_:/.,;#\t"

segments = st.lists(st.text(alphabet=ALNUM, min_size=1, max_size=8), min_size=1, max_size=6)
separator_runs = st.text(alphabet=SEPARATORS, min_size=1, max_size=3)
edges = st.text(alphabet=SEPARATORS + " ", min_size=0, max_size=3)
cases = st.sampled_from([str.upper, str.lower, str.swapcase, str.title, str.capitalize])


@st.composite
def formatted_variants(draw: st.DrawFn) -> tuple[str, str]:
    """A canonical spelling of a case number and one formatting variant of it."""
    parts = draw(segments)
    canonical = "-".join(parts)
    joins = draw(st.lists(separator_runs, min_size=len(parts) - 1, max_size=len(parts) - 1))
    change_case = draw(cases)
    body = parts[0]
    for join, part in zip(joins, parts[1:], strict=True):
        body += join + part
    variant = draw(edges) + change_case(body) + draw(edges)
    return canonical, variant


@given(formatted_variants())
def test_every_formatting_variant_normalizes_to_the_same_key(pair: tuple[str, str]) -> None:
    canonical, variant = pair
    assert normalize_case_number(variant) == normalize_case_number(canonical)
    assert normalize_case_number(canonical) == canonical.upper()


@given(st.text(max_size=40))
def test_normalization_is_idempotent(raw: str) -> None:
    once = normalize_case_number(raw)
    assert normalize_case_number(once) == once


@given(st.text(max_size=40))
def test_a_key_holds_only_upper_alphanumerics_and_single_hyphens(raw: str) -> None:
    key = normalize_case_number(raw)
    assert key == "" or KEY.match(key), key
    assert "--" not in key
    assert key == key.strip("-")


@given(formatted_variants())
def test_court_type_does_not_change_the_rule(pair: tuple[str, str]) -> None:
    canonical, variant = pair
    assert normalize_case_number(variant, "circuit") == normalize_case_number(canonical)
