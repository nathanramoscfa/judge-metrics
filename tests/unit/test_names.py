# tests/unit/test_names.py
"""Name and case-number normalization."""

from __future__ import annotations

import pytest

from judgemetrics.normalization.names import (
    canonical_person_name,
    normalize_case_number,
    normalize_person_name,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Ruth Bader Ginsburg", "ruth bader ginsburg"),
        ("José  Núñez-Ortíz, Jr.", "jose nunez ortiz jr"),
        ("Sonia Sotomayor", "sonia sotomayor"),
        ("O'Connor, Sandra Day", "o connor sandra day"),
        ("Jean-Luc   D'Amour", "jean luc d amour"),
        ("  MÜLLER, Hans  ", "muller hans"),
        ("Łukasz Żółć", "łukasz zołc"),
        ("Smith III", "smith iii"),
        ("", ""),
    ],
)
def test_normalize_person_name(raw: str, expected: str) -> None:
    assert normalize_person_name(raw) == expected


def test_normalize_person_name_is_idempotent() -> None:
    once = normalize_person_name("Édouard  Le-Roy, Sr.")
    assert normalize_person_name(once) == once


def test_accented_and_unaccented_spellings_collide() -> None:
    assert normalize_person_name("Renée Zellweger") == normalize_person_name("Renee Zellweger")


@pytest.mark.parametrize(
    ("parts", "expected"),
    [
        (("Ruth", "Bader", "Ginsburg", None), "Ruth Bader Ginsburg"),
        (("John", None, "Roberts", "Jr."), "John Roberts, Jr."),
        (("  Sandra ", " Day ", " O'Connor ", ""), "Sandra Day O'Connor"),
        (("Thurgood", "", "Marshall", "III"), "Thurgood Marshall, III"),
        ((None, None, "Cher", None), "Cher"),
        ((None, None, None, "Jr."), "Jr."),
        (("Anne", "Marie  Louise", "Dubois-Lefèvre", None), "Anne Marie Louise Dubois-Lefèvre"),
    ],
)
def test_canonical_person_name(parts: tuple[str | None, ...], expected: str) -> None:
    assert canonical_person_name(*parts) == expected


@pytest.mark.parametrize(
    ("raw", "court_type", "expected"),
    [
        # Phase 2 rule (normalization/case_numbers.py): separators become one
        # hyphen so formatting variants of a docket collapse to one key.
        ("1:21-cr-00123-ABC", "federal_district", "1-21-CR-00123-ABC"),
        ("2019 CF 001234", "state_circuit", "2019-CF-001234"),
        ("19-CR-1234", "state_circuit", "19-CR-1234"),
        ("  2020-cf-000456  ", None, "2020-CF-000456"),
        ("CR/2018/00077", "county", "CR-2018-00077"),
        ("18_cf_9", None, "18-CF-9"),
        ("2021.CF.00001-A", None, "2021-CF-00001-A"),
        ("No. 12345", None, "NO-12345"),
    ],
)
def test_normalize_case_number(raw: str, court_type: str | None, expected: str) -> None:
    assert normalize_case_number(raw, court_type) == expected


def test_normalize_case_number_keeps_year_and_sequence() -> None:
    normalized = normalize_case_number("2019-CF-001234", "state_circuit")
    assert "2019" in normalized
    assert "001234" in normalized


def test_normalize_case_number_is_idempotent() -> None:
    once = normalize_case_number("1:21-cr-00123", "federal_district")
    assert normalize_case_number(once, "federal_district") == once
