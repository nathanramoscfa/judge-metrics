# tests/unit/test_vocabulary.py
"""The versioned case vocabulary equals the generator's constants and rejects unknown values."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from judgemetrics.db.models.enums import ActorType
from judgemetrics.ingest.base import NormalizationError
from judgemetrics.normalization import vocabulary
from judgemetrics.normalization.vocabulary import (
    CASE_VOCABULARY_PATH,
    UNKNOWN,
    VocabularyFileError,
    load_vocabulary,
)
from judgemetrics.synthetic.vocabulary import CASE_VOCABULARY_VERSION, VOCABULARY

pytestmark = pytest.mark.unit

REQUIRED_KINDS = {
    "case_type",
    "case_status",
    "party_type",
    "assignment_type",
    "event_type",
    "decision_type",
    "judicial_discretion_classification",
    "release_type",
    "charge_disposition",
    "severity",
    "offense_category",
    "justice_event_type",
}


def test_file_exists_and_is_loaded_with_safe_load() -> None:
    assert CASE_VOCABULARY_PATH == Path("data/reference/case_vocabulary.yaml").resolve()
    payload = yaml.safe_load(CASE_VOCABULARY_PATH.read_text(encoding="utf-8"))
    assert payload["version"] == CASE_VOCABULARY_VERSION == vocabulary.version()
    assert CASE_VOCABULARY_PATH.read_text(encoding="utf-8").startswith(
        "# data/reference/case_vocabulary.yaml\n"
    )


def test_file_equals_the_generator_constants() -> None:
    _, kinds = load_vocabulary()
    assert dict(kinds) == VOCABULARY
    assert REQUIRED_KINDS <= set(kinds)
    for kind in VOCABULARY:
        assert vocabulary.values(kind) == VOCABULARY[kind]


def test_required_values_are_listed() -> None:
    assert vocabulary.values("decision_type") == (
        "pretrial_release",
        "dismissal",
        "disposition",
        "sentencing",
    )
    assert set(vocabulary.values("judicial_discretion_classification")) >= {
        "discretionary",
        "mandatory",
        "unknown",
    }
    assert vocabulary.values("release_type") == (
        "recognizance",
        "monetary_bond",
        "detained",
        "statutory",
    )
    assert vocabulary.values("charge_disposition") == (
        "dismissed",
        "acquitted",
        "convicted_plea",
        "convicted_verdict",
        "pending",
    )
    assert set(vocabulary.values("event_type")) >= {
        "arraignment",
        "hearing",
        "failure_to_appear",
        "bench_warrant",
        "trial",
        "revocation",
    }
    assert vocabulary.values("justice_event_type") == (
        "new_case",
        "new_charge",
        "reconviction",
        "failure_to_appear",
        "release_violation",
        "revocation",
        "rearrest",
    )
    assert vocabulary.values("actor_type") == tuple(member.value for member in ActorType)


def test_require_accepts_listed_values_and_rejects_others() -> None:
    assert vocabulary.require("case_type", "felony") == "felony"
    with pytest.raises(NormalizationError, match="case_type 'infraction' is not in the case"):
        vocabulary.require("case_type", "infraction")
    with pytest.raises(NormalizationError, match="charge CH-1: severity 'x'"):
        vocabulary.require("severity", "x", context="charge CH-1")
    with pytest.raises(KeyError):
        vocabulary.require("no_such_kind", "value")


def test_unknown_is_allowed_only_where_the_brief_allows_it() -> None:
    assert UNKNOWN == "unknown"
    assert vocabulary.allows_unknown("actor_type")
    assert vocabulary.allows_unknown("judicial_discretion_classification")
    assert not vocabulary.allows_unknown("case_type")
    assert vocabulary.require_or_unknown("actor_type", "") == UNKNOWN
    assert vocabulary.require_or_unknown("actor_type", "judge") == "judge"
    with pytest.raises(NormalizationError):
        vocabulary.require_or_unknown("actor_type", "bailiff")
    with pytest.raises(ValueError, match="does not allow an unknown value"):
        vocabulary.require_or_unknown("case_type", "")


def test_malformed_files_are_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "vocab.yaml"
    bad.write_text("version: 1\nkinds:\n  case_type: [felony, felony]\n", encoding="utf-8")
    with pytest.raises(VocabularyFileError, match="distinct non-empty strings"):
        load_vocabulary(bad)
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(VocabularyFileError, match="version"):
        load_vocabulary(bad)
    with pytest.raises(VocabularyFileError, match="cannot read"):
        load_vocabulary(tmp_path / "missing.yaml")
    load_vocabulary.cache_clear()
