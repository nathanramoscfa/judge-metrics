# tests/unit/test_case_numbers.py
"""Case-number normalization: the planted duplicate formats collapse to one key."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from judgemetrics.normalization.case_numbers import normalize_case_number
from judgemetrics.synthetic.edge_cases import duplicate_case_number

pytestmark = pytest.mark.unit

GOLDEN = Path(__file__).resolve().parents[1] / "fixtures" / "golden"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("SYN-2019-000013", "SYN-2019-000013"),
        ("syn 2019 000013", "SYN-2019-000013"),
        ("  syn-2019-000013  ", "SYN-2019-000013"),
        ("SYN--2019__000013", "SYN-2019-000013"),
        ("1:21-cr-00123-ABC", "1-21-CR-00123-ABC"),
        ("2019 CF 001234", "2019-CF-001234"),
        ("CR/2018/00077", "CR-2018-00077"),
        ("2021.CF.00001-A", "2021-CF-00001-A"),
        ("No. 12345", "NO-12345"),
        ("-leading-and-trailing-", "LEADING-AND-TRAILING"),
    ],
)
def test_normalize_case_number(raw: str, expected: str) -> None:
    assert normalize_case_number(raw) == expected
    assert normalize_case_number(raw, "circuit") == expected


def test_normalization_is_idempotent() -> None:
    once = normalize_case_number("1:21-cr-00123")
    assert normalize_case_number(once) == once


def test_only_hyphens_survive_as_punctuation() -> None:
    normalized = normalize_case_number("a.b,c;d:e f#g/h_i")
    assert normalized == "A-B-C-D-E-F-G-H-I"
    assert all(ch.isalnum() or ch == "-" for ch in normalized)


def test_planted_duplicate_variant_collapses_onto_the_original() -> None:
    assert normalize_case_number(duplicate_case_number("SYN-2019-000013")) == "SYN-2019-000013"


def test_every_golden_duplicate_shares_its_original_key() -> None:
    with (GOLDEN / "truth" / "planted.csv").open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["kind"] == "duplicate_source_record"]
    assert rows, "the golden fixture plants duplicate source records"
    for row in rows:
        ids = dict(pair.split("=", 1) for pair in row["ids"].split(";"))
        assert normalize_case_number(ids["duplicate_case_number"]) == normalize_case_number(
            ids["case_number"]
        )
        assert ids["duplicate_case_number"] != ids["case_number"]
