# tests/unit/test_schemas_metrics.py
"""The metric schemas: suppression at the serializer, interval methods, the corrections body."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from judgemetrics.schemas.metrics import (
    SUPPRESSED_FIELDS,
    CompareRow,
    CorrectionIn,
    Observation,
    ObservationCoverage,
    TracedObservation,
    interval_method_for,
)

pytestmark = pytest.mark.unit

FIGURES: dict[str, Any] = {
    "numerator": 3,
    "denominator": 7,
    "rate": 0.428571,
    "value": None,
    "distribution": None,
    "lower": 0.157889,
    "upper": 0.749971,
}


def _observation(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        **FIGURES,
        "suppressed": False,
        "suppression_threshold": 10,
        "id": uuid.uuid4(),
        "slug": "new_case_rate",
        "name": "New-case rate after pretrial release",
        "kind": "windowed_rate",
        "unit": "share",
        "version": "1",
        "subject_type": "judge",
        "subject_id": uuid.uuid4(),
        "source": "synthetic",
        "synthetic": True,
        "period_start": "2019-01-01",
        "period_end": "2021-12-31",
        "window_days": 365,
        "dimension_value": None,
        "eligible_count": 9,
        "interval_method": "wilson",
        "coverage": ObservationCoverage(
            coverage_start="2019-01-01", coverage_end="2021-12-31", observable=True
        ),
        "methodology_version": "0.1",
        "methodology_url": "/methodology#new_case_rate",
        "snapshot_hash": "a" * 64,
        "computed_at": datetime.now(UTC),
    }
    base.update(overrides)
    return base


def test_suppressed_observation_carries_no_number_whatever_the_caller_passed() -> None:
    kept = Observation(**_observation())
    assert (kept.numerator, kept.denominator, kept.rate) == (3, 7, 0.428571)
    withheld = Observation(**_observation(suppressed=True))
    for name in SUPPRESSED_FIELDS:
        assert getattr(withheld, name) is None, name
    assert withheld.suppressed is True
    # The sample size and the threshold stay: a reader learns why.
    assert withheld.eligible_count == 9
    assert withheld.suppression_threshold == 10
    dumped = withheld.model_dump(mode="json")
    assert all(dumped[name] is None for name in SUPPRESSED_FIELDS)
    assert set(SUPPRESSED_FIELDS) == {
        "numerator",
        "denominator",
        "rate",
        "value",
        "distribution",
        "lower",
        "upper",
    }


def test_suppression_applies_to_medians_distributions_and_every_suppressible_shape() -> None:
    median = Observation(
        **_observation(
            suppressed=True,
            kind="median",
            unit="days",
            rate=None,
            lower=None,
            upper=None,
            value=41.5,
            interval_method=None,
            window_days=None,
        )
    )
    assert median.value is None and median.numerator is None
    distribution = Observation(
        **_observation(
            suppressed=True,
            kind="distribution",
            unit="count",
            rate=None,
            lower=None,
            upper=None,
            distribution={"dismissed": 2, "convicted_plea": 1},
            interval_method=None,
            window_days=None,
            dimension_value="dismissed",
        )
    )
    assert distribution.distribution is None
    row = CompareRow(
        **FIGURES,
        suppressed=True,
        suppression_threshold=10,
        subject_id=uuid.uuid4(),
        name="Scheelite Kite",
        court={"id": uuid.uuid4(), "canonical_name": "Court 1", "court_type": "circuit"},
        synthetic=True,
        observation_id=uuid.uuid4(),
        source="synthetic",
        period_start="2019-01-01",
        period_end="2021-12-31",
        window_days=365,
        dimension_value=None,
        eligible_count=9,
        interval_method="wilson",
        coverage_warning=None,
    )
    assert all(getattr(row, name) is None for name in SUPPRESSED_FIELDS)
    traced = TracedObservation(
        **_observation(suppressed=True),
        registry_version=1,
        code_version="0.1.0",
        superseded_at=None,
    )
    assert traced.rate is None and traced.denominator is None


def test_interval_method_follows_the_kind() -> None:
    assert interval_method_for("share") == "wilson"
    assert interval_method_for("windowed_rate") == "wilson"
    assert interval_method_for("survival") == "greenwood"
    assert interval_method_for("count") is None
    assert interval_method_for("distribution") is None
    assert interval_method_for("median") is None


def test_observation_rejects_a_person_field_and_an_unknown_kind() -> None:
    assert "public_person_key" not in Observation.model_fields
    assert not any(name.startswith("person") for name in Observation.model_fields)
    with pytest.raises(ValidationError):
        Observation(**_observation(kind="ratio"))
    with pytest.raises(ValidationError):
        Observation(**_observation(snapshot_hash="not-a-hash"))


# --- the corrections body -----------------------------------------------------------------


VALID: dict[str, Any] = {
    "target_type": "judge",
    "target_id": str(uuid.uuid4()),
    "reason": "The appointment date on this profile is a year off.",
    "contact": "requester@example.invalid",
}


def test_correction_body_accepts_a_valid_request_and_strips_whitespace() -> None:
    body = CorrectionIn(**{**VALID, "contact": "  requester@example.invalid  "})
    assert body.contact == "requester@example.invalid"
    assert body.supporting_material is None
    with_link = CorrectionIn(**VALID, supporting_material="https://example.invalid/evidence.pdf")
    assert str(with_link.supporting_material) == "https://example.invalid/evidence.pdf"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("target_type", "person"),
        ("target_type", "judge_service"),
        ("target_id", "not-a-uuid"),
        ("reason", "too short"),
        ("reason", "x" * 4001),
        ("reason", "a reason with a control\x00character in it"),
        ("contact", "ab"),
        ("contact", "x" * 321),
        ("supporting_material", "ftp://example.invalid/file"),
        ("supporting_material", "not a url"),
        ("supporting_material", "https://example.invalid/" + "p" * 2000),
        ("public_person_key", "abc"),
    ],
)
def test_correction_body_rejects_every_invalid_field(field: str, value: Any) -> None:
    with pytest.raises(ValidationError) as caught:
        CorrectionIn(**{**VALID, field: value})
    locations = {str(error["loc"][0]) for error in caught.value.errors() if error["loc"]}
    assert field in locations or (field == "public_person_key" and "public_person_key" in locations)
