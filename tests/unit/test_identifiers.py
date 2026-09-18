# tests/unit/test_identifiers.py
"""Peppered identifier hashing: kind- and pepper-dependent, normalization applied."""

from __future__ import annotations

import hashlib
import re
from datetime import date

import pytest
from pydantic import SecretStr

from judgemetrics.config import Settings
from judgemetrics.security.identifiers import (
    IDENTIFIER_KINDS,
    KIND_DATE_OF_BIRTH,
    KIND_FULL_NAME,
    KIND_NAME_DOB,
    KIND_SOURCE_PARTICIPANT_ID,
    STABLE_KINDS,
    IdentifierPepperMissingError,
    hash_identifier,
    name_dob_value,
    normalize_identifier,
    require_identifier_pepper,
)

pytestmark = pytest.mark.unit

PEPPER = SecretStr("unit-test-pepper")
OTHER_PEPPER = SecretStr("another-unit-test-pepper")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def test_hash_is_sha256_of_pepper_kind_and_normalized_value() -> None:
    digest = hash_identifier(PEPPER, KIND_SOURCE_PARTICIPANT_ID, " pt-000005 ")
    expected = hashlib.sha256(b"unit-test-pepper\x00source_participant_id\x00PT-000005").hexdigest()
    assert digest == expected
    assert HEX64.match(digest)


def test_hash_differs_per_pepper_and_per_kind() -> None:
    value = "1991-07-26"
    assert hash_identifier(PEPPER, KIND_DATE_OF_BIRTH, value) != hash_identifier(
        OTHER_PEPPER, KIND_DATE_OF_BIRTH, value
    )
    same_text = "2000-01-01"
    assert hash_identifier(PEPPER, KIND_DATE_OF_BIRTH, same_text) != hash_identifier(
        PEPPER, KIND_SOURCE_PARTICIPANT_ID, same_text
    )


def test_name_normalization_is_applied_before_hashing() -> None:
    assert hash_identifier(PEPPER, KIND_FULL_NAME, "FOG MORAVA ") == hash_identifier(
        PEPPER, KIND_FULL_NAME, "Fog Morava"
    )
    assert hash_identifier(PEPPER, KIND_FULL_NAME, "José  Núñez-Ortíz, Jr.") == hash_identifier(
        PEPPER, KIND_FULL_NAME, "jose nunez ortiz jr"
    )
    assert hash_identifier(PEPPER, KIND_FULL_NAME, "Fog Morava") != hash_identifier(
        PEPPER, KIND_FULL_NAME, "Fog Moravia"
    )


def test_dates_are_hashed_in_iso_form() -> None:
    assert hash_identifier(PEPPER, KIND_DATE_OF_BIRTH, date(1991, 7, 26)) == hash_identifier(
        PEPPER, KIND_DATE_OF_BIRTH, " 1991-07-26 "
    )
    with pytest.raises(ValueError, match="Invalid isoformat|invalid"):
        hash_identifier(PEPPER, KIND_DATE_OF_BIRTH, "26/07/1991")


def test_participant_ids_are_stripped_and_upper_cased() -> None:
    assert normalize_identifier(KIND_SOURCE_PARTICIPANT_ID, " pt-000005\n") == "PT-000005"


def test_name_dob_combines_normalized_name_and_iso_date() -> None:
    assert name_dob_value("FOG MORAVA ", "1979-10-21") == "fog morava|1979-10-21"
    assert hash_identifier(PEPPER, KIND_NAME_DOB, name_dob_value("Fog Morava", "1979-10-21")) == (
        hash_identifier(PEPPER, KIND_NAME_DOB, "fog morava|1979-10-21")
    )


def test_empty_values_and_unknown_kinds_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty"):
        hash_identifier(PEPPER, KIND_FULL_NAME, "   ")
    with pytest.raises(ValueError, match="unknown identifier kind"):
        hash_identifier(PEPPER, "shoe_size", "42")


def test_empty_pepper_is_refused() -> None:
    with pytest.raises(IdentifierPepperMissingError):
        hash_identifier(SecretStr("  "), KIND_FULL_NAME, "Fog Morava")


def test_require_identifier_pepper_names_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("JUDGEMETRICS_IDENTIFIER_PEPPER", raising=False)
    with pytest.raises(IdentifierPepperMissingError, match="JUDGEMETRICS_IDENTIFIER_PEPPER"):
        require_identifier_pepper(Settings(env="test"))
    assert require_identifier_pepper(Settings(env="test", identifier_pepper=PEPPER)) is PEPPER


def test_pepper_never_appears_in_settings_rendering() -> None:
    settings = Settings(env="test", identifier_pepper=SecretStr("render-me-not"))
    rendered = repr(settings) + str(settings) + settings.model_dump_json()
    assert "render-me-not" not in rendered


def test_kinds_are_the_four_documented_ones() -> None:
    assert IDENTIFIER_KINDS == (
        "source_participant_id",
        "full_name",
        "date_of_birth",
        "name_dob",
    )
    assert STABLE_KINDS == frozenset({"source_participant_id"})
