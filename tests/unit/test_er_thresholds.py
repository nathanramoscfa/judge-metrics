# tests/unit/test_er_thresholds.py
"""The versioned thresholds file equals the constants; decision boundaries hold."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from judgemetrics.db.models.enums import ResolutionDecision
from judgemetrics.entity_resolution import scoring
from judgemetrics.entity_resolution.config import (
    ENTITY_TYPES,
    MODEL_VERSION,
    SYSTEM_ACTOR,
    THRESHOLDS,
    THRESHOLDS_PATH,
    THRESHOLDS_VERSION,
    Thresholds,
    ThresholdsFileError,
    load_thresholds,
    thresholds_for,
)
from judgemetrics.entity_resolution.features import PairFeatures

pytestmark = pytest.mark.unit


class FixedScorer:
    def __init__(self, value: float) -> None:
        self.value = value

    def score(self, features: PairFeatures) -> float | None:
        del features
        return self.value


FEATURES = PairFeatures(
    same_source_id=False,
    same_name=True,
    same_dob=True,
    dob_missing_either=False,
    same_name_dob=True,
    shared_case=False,
    related_case_link=False,
    same_court=False,
    filing_gap_days=None,
    age_consistent=True,
)


def test_yaml_equals_the_constants() -> None:
    assert THRESHOLDS_PATH == Path("data/reference/entity_resolution_thresholds.yaml").resolve()
    version, loaded = load_thresholds()
    assert version == THRESHOLDS_VERSION == 1
    assert dict(loaded) == dict(THRESHOLDS)
    assert set(loaded) == set(ENTITY_TYPES) == {"person", "judge", "court", "case"}
    raw = yaml.safe_load(THRESHOLDS_PATH.read_text(encoding="utf-8"))
    assert raw["thresholds"]["person"] == {"auto_match": 0.95, "auto_reject": 0.20}
    assert THRESHOLDS_PATH.read_text(encoding="utf-8").startswith(
        "# data/reference/entity_resolution_thresholds.yaml\n"
    )


def test_defaults_are_deliberately_high_and_low() -> None:
    person = thresholds_for("person")
    assert person == Thresholds(auto_match=0.95, auto_reject=0.20)
    assert person.auto_match >= 0.9 and person.auto_reject <= 0.3
    with pytest.raises(ValueError, match="auto_reject < auto_match"):
        Thresholds(auto_match=0.2, auto_reject=0.5)
    with pytest.raises(KeyError):
        thresholds_for("attorney")
    assert MODEL_VERSION == "person-rules-v0"
    assert SYSTEM_ACTOR == "system:person-rules-v0"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.0, ResolutionDecision.MATCHED),
        (0.95, ResolutionDecision.MATCHED),
        (0.9499, ResolutionDecision.REVIEW),
        (0.5, ResolutionDecision.REVIEW),
        (0.20, ResolutionDecision.REVIEW),
        (0.1999, ResolutionDecision.REJECTED),
        (0.0, ResolutionDecision.REJECTED),
    ],
)
def test_decision_boundaries(value: float, expected: ResolutionDecision) -> None:
    result = scoring.decide(FEATURES, FixedScorer(value), thresholds_for("person"))
    assert result is not None
    assert result.decision is expected
    assert result.score == value


def test_malformed_files_are_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "thresholds.yaml"
    bad.write_text("version: 1\nthresholds:\n  person: {auto_match: 0.1, auto_reject: 0.5}\n")
    with pytest.raises(ThresholdsFileError, match="person"):
        load_thresholds(bad)
    bad.write_text("version: 0\nthresholds: {}\n")
    with pytest.raises(ThresholdsFileError, match="positive"):
        load_thresholds(bad)
    bad.write_text("version: 1\nthresholds:\n  person: {auto_match: 0.9}\n")
    with pytest.raises(ThresholdsFileError, match="auto_match and auto_reject"):
        load_thresholds(bad)
    with pytest.raises(ThresholdsFileError, match="cannot read"):
        load_thresholds(tmp_path / "missing.yaml")
    load_thresholds.cache_clear()
