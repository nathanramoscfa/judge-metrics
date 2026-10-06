# tests/unit/test_judge_aliases.py
"""Every Cook County judge string is resolved once, held as ambiguous, or left unresolved.

``judge_aliases.csv`` lists every distinct ``JUDGE`` and ``SENTENCE_JUDGE``
string of the profile exactly once; resolved rows name a ``judges.csv`` key by
an allowed rule (an exact match, a spacing or case variant, the family name
written first, a middle name present or absent where no other judge shares
the given and family names); two strings whose given names conflict never
share a key; every ``ambiguous`` and ``unresolved`` row carries its reason
and candidates; and every key has exactly one ``judges.csv`` row.
"""

from __future__ import annotations

import csv
from collections import defaultdict

import pytest
import yaml

from judgemetrics.ingest.cook_sao.rules import (
    AMBIGUOUS,
    NOT_IN_TABLE,
    RESOLVED,
    TABLES_DIR,
    UNRESOLVED,
    load_rules,
)
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.names import normalize_person_name

pytestmark = pytest.mark.unit

PROFILE = yaml.safe_load((TABLES_DIR / "profile.yaml").read_text(encoding="utf-8"))
RULES = load_rules()


def _rows(file: str) -> list[dict[str, str]]:
    with (TABLES_DIR / file).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


ALIASES = _rows("judge_aliases.csv")
JUDGES = _rows("judges.csv")


def _profile_strings() -> set[str]:
    columns = PROFILE["datasets"]
    found = {value for value, _ in columns["dispositions.csv"]["columns"]["JUDGE"]["values"]}
    found |= {
        value for value, _ in columns["sentencing.csv"]["columns"]["SENTENCE_JUDGE"]["values"]
    }
    return found


def _given(source: str) -> str:
    """The given name of a source string (the comma form's second part first)."""
    if "," in source:
        family, given = source.split(",", 1)
        source = f"{given} {family}"
    return normalize_person_name(source).split()[0]


def test_every_judge_string_appears_exactly_once() -> None:
    strings = [row["source_string"] for row in ALIASES]
    assert len(strings) == len(set(strings))
    assert set(strings) == _profile_strings()
    assert len(strings) == 538
    for row in ALIASES:
        assert row["normalized"] == normalize_person_name(row["source_string"])


def test_keys_are_unique_and_every_key_has_a_judges_row() -> None:
    keys = [row["judge_key"] for row in JUDGES]
    assert len(keys) == len(set(keys))
    used = {row["judge_key"] for row in ALIASES if row["status"] == RESOLVED}
    assert used == set(keys)
    for row in JUDGES:
        assert vocabulary.is_known("position", row["position"])
        # The source states no rank: never a guessed one.
        assert row["position"] == "unstated"
        assert row["display_name"] == " ".join(row["display_name"].split())


def test_conflicting_given_names_are_never_merged() -> None:
    by_key: dict[str, set[str]] = defaultdict(set)
    for row in ALIASES:
        if row["status"] == RESOLVED:
            by_key[row["judge_key"]].add(_given(row["source_string"]))
    for key, given_names in by_key.items():
        assert len(given_names) == 1, (key, given_names)
    # The near-variants the review found stay apart from their candidates.
    held = {row["source_string"]: row for row in ALIASES if row["status"] != RESOLVED}
    for source in ("Ricky  Jones", "Darren  Bowden", "Ray  Jagielski", "Douglas J Simpson"):
        assert held[source]["rule"] == "given_name_variant", source
        assert RULES.judge(source).judge_key is None  # type: ignore[union-attr]
    # A merge is only a middle name present or absent, with one candidate pair.
    merged = [row for row in ALIASES if row["rule"] == "middle_present_or_absent"]
    assert {row["source_string"] for row in merged} == {"William  Raines", "Maura  Boyle"}


def test_every_held_row_carries_its_reason_and_candidates() -> None:
    keys = {row["judge_key"] for row in JUDGES}
    for row in ALIASES:
        candidates = [c for c in row["candidates"].split(";") if c]
        assert set(candidates) <= keys, row
        if row["status"] == RESOLVED:
            assert row["judge_key"] in keys and not candidates
            if row["rule"] != "exact":
                assert row["reason"], row
        else:
            assert row["status"] in (AMBIGUOUS, UNRESOLVED)
            assert row["judge_key"] == "" and row["reason"], row
            if row["status"] == AMBIGUOUS:
                assert len(candidates) >= 2, row
    held = [row for row in ALIASES if row["status"] != RESOLVED]
    assert len(held) == 15
    assert [row["source_string"] for row in held if row["status"] == AMBIGUOUS] == ["Donnelly"]


def test_the_matcher_resolves_by_string_then_by_normalized_form() -> None:
    assert RULES.judge("James B Linn").judge_key == "james-b-linn"  # type: ignore[union-attr]
    # A spacing or case variant of a listed string resolves to the same key.
    assert RULES.judge("Stanley  Sacks").judge_key == RULES.judge("STANLEY SACKS").judge_key  # type: ignore[union-attr]
    assert RULES.judge("Maura  Boyle").judge_key == "maura-slattery-boyle"  # type: ignore[union-attr]
    assert RULES.judge("Byrne, Thomas").judge_key == "thomas-byrne"  # type: ignore[union-attr]
    held = RULES.judge("J  HYNES")
    assert (
        held is not None and held.status == UNRESOLVED and held.candidates == ("john-joseph-hynes",)
    )
    missing = RULES.judge("A Judge The Source Never Named")
    assert missing is not None and missing.status == UNRESOLVED and missing.reason == NOT_IN_TABLE
    assert RULES.judge(None) is None and RULES.judge("  ") is None
