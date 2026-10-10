# tests/unit/test_outcome_model_spec.py
"""The expected-outcome model specification: it loads, validates, and refuses what it must.

``data/reference/outcome_model.yaml`` is parsed with ``yaml.safe_load`` and
validated on load; a tampered copy that names a restricted attribute (every
value of the vocabulary's ``restricted_attribute`` kind), an excluded
variable or column, or an unknown field is rejected with ``SpecError``
naming the feature and the field; every feature states its known-at
instant and a leakage justification, and the code implements exactly the
features the file names. Version 3 (Phase 5 Step 5): ``availability`` states
the three conditions a source must meet, the person-history features are
marked as their builders read, the first failing condition is the reason a
target is unavailable, and an unavailable model's artifact reads back as
unfitted parameters.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from typing import Any

import pytest
import yaml

from judgemetrics.capabilities import CASE, CROSS_CASE, JUDGE_GATES, SourceCapabilities
from judgemetrics.metrics.adjustment.artifacts import content_hash
from judgemetrics.metrics.adjustment.availability import unavailable_reason
from judgemetrics.metrics.adjustment.expected import ModelParameters
from judgemetrics.metrics.adjustment.features import FEATURE_BUILDERS
from judgemetrics.metrics.adjustment.fit import UNAVAILABLE, UnavailableModel, model_rows
from judgemetrics.metrics.adjustment.spec import (
    DEFAULT_PATH,
    FEATURE_CONTRACTS,
    FILED_AT,
    KNOWN_AT,
    RESTRICTED_KIND,
    SpecError,
    load_spec,
    parse_spec,
)
from judgemetrics.metrics.registry import WINDOWS_DAYS
from judgemetrics.metrics.snapshot import SourceRow
from judgemetrics.normalization import vocabulary

pytestmark = pytest.mark.unit

# The version-1 fixed levels, in their version-1 order (reference first).
V1_SEVERITY = ("misdemeanor_b", "misdemeanor_a", "felony_3", "felony_2", "felony_1")
V1_CATEGORY = ("public_order", "traffic", "drug", "property", "financial", "weapon", "person")
HISTORY_FEATURES = (
    "prior_cases",
    "prior_convictions",
    "prior_failures_to_appear",
    "pending_case",
    "history_truncated",
)


def _payload() -> dict[str, Any]:
    loaded = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict)
    return copy.deepcopy(loaded)


def _feature(payload: dict[str, Any], name: str) -> dict[str, Any]:
    for entry in payload["features"]:
        if entry["name"] == name:
            return dict(entry)
    raise AssertionError(name)


def _feature_entry(payload: dict[str, Any], name: str) -> dict[str, Any]:
    """The feature's own entry in ``payload`` (edited in place)."""
    for entry in payload["features"]:
        if entry["name"] == name:
            found: dict[str, Any] = entry
            return found
    raise AssertionError(name)


def test_the_specification_loads_and_validates() -> None:
    spec = load_spec()
    assert spec.version == 3
    assert spec.model_version == "expected-logit-v1"
    assert [target.name for target in spec.targets] == [
        "pretrial_release",
        "new_case",
        "failure_to_appear",
    ]
    release, new_case, fta = spec.targets
    assert release.population == "pretrial_decisions" and release.windows == (None,)
    assert new_case.windows_days == WINDOWS_DAYS == fta.windows_days
    assert {feature.name for feature in spec.features} == set(FEATURE_CONTRACTS)
    assert set(FEATURE_BUILDERS) == set(FEATURE_CONTRACTS)
    assert spec.model.penalty == "l2" and spec.model.lam > 0 and not spec.model.penalize_intercept
    assert spec.temporal_split.test_quantile == 0.75
    assert spec.bootstrap.replicates == 500 and spec.bootstrap.cluster == "person"
    assert spec.pooling.family == "gamma_poisson"
    assert spec.thresholds.minimum_events_per_column == 5
    assert spec.thresholds.minimum_cohort == 30 and spec.thresholds.minimum_expected == 5
    assert {fit.target for fit in spec.recovery.fits} == set(spec.recovery.spearman_minimum)
    # The fixed levels are the vocabulary's, in the specification's own order.
    severity = spec.feature("lead_severity")
    assert set(severity.fixed_levels) == set(vocabulary.values("severity"))
    assert severity.reference == "misdemeanor_b"
    category = spec.feature("lead_category")
    assert set(category.fixed_levels) == set(vocabulary.values("offense_category"))
    assert category.reference == "public_order"
    # Version 2 adds vocabulary 3's levels and keeps every version-1 level in its
    # version-1 order, so a source without the new levels encodes as before.
    assert [level for level in severity.fixed_levels if level in V1_SEVERITY] == list(V1_SEVERITY)
    assert [level for level in category.fixed_levels if level in V1_CATEGORY] == list(V1_CATEGORY)
    assert spec.feature("prior_cases").fixed_levels == ("0", "1", "2", "3+", "unrecorded")
    assert spec.feature("court").data_levels and spec.feature("calendar_year").unseen == "latest"
    # Every restricted attribute is excluded through the vocabulary.
    excluded = {name for entry in spec.excluded for name in entry.names}
    assert set(vocabulary.values(RESTRICTED_KIND)) <= excluded
    assert {"judge", "release_terms", "propensity", "after_the_index"} <= excluded


@pytest.mark.parametrize("attribute", vocabulary.values(RESTRICTED_KIND))
def test_a_restricted_attribute_is_rejected_as_a_feature(attribute: str) -> None:
    named = _payload()
    named["features"].append({**_feature(named, "court"), "name": attribute})
    with pytest.raises(SpecError, match="restricted attribute"):
        parse_spec(named, DEFAULT_PATH)

    by_vocabulary = _payload()
    severity = _feature(by_vocabulary, "lead_severity")
    by_vocabulary["features"][0] = {**severity, "vocabulary": attribute}
    with pytest.raises(SpecError, match="restricted attribute"):
        parse_spec(by_vocabulary, DEFAULT_PATH)

    by_column = _payload()
    by_column["features"][0] = {**severity, "source": ["charges.severity", f"cases.{attribute}"]}
    with pytest.raises(SpecError, match="restricted attribute"):
        parse_spec(by_column, DEFAULT_PATH)


def test_an_excluded_or_unknown_field_is_rejected() -> None:
    # An excluded variable named as a feature.
    for name in ("judge", "release_terms", "propensity"):
        payload = _payload()
        payload["features"].append({**_feature(payload, "court"), "name": name})
        with pytest.raises(SpecError, match="excluded"):
            parse_spec(payload, DEFAULT_PATH)
    # An excluded column read by a feature.
    for column in ("decisions.judge_id", "decisions.release_type", "decisions.detained_flag"):
        payload = _payload()
        court = _feature(payload, "court")
        payload["features"] = [
            {**court, "source": ["cases.court_id", column]} if entry["name"] == "court" else entry
            for entry in payload["features"]
        ]
        with pytest.raises(SpecError, match="excluded column"):
            parse_spec(payload, DEFAULT_PATH)
    # An unknown field, at the top, in a feature, and in a block.
    top = _payload()
    top["notes"] = "x"
    with pytest.raises(SpecError, match="'notes' is not a specification field"):
        parse_spec(top, DEFAULT_PATH)
    in_feature = _payload()
    in_feature["features"][0] = {**_feature(in_feature, "lead_severity"), "weight": 2}
    with pytest.raises(SpecError, match="feature 'lead_severity': field 'weight'"):
        parse_spec(in_feature, DEFAULT_PATH)
    in_model = _payload()
    in_model["model"]["momentum"] = 0.9
    with pytest.raises(SpecError, match="model: field 'momentum'"):
        parse_spec(in_model, DEFAULT_PATH)
    # A feature the code does not implement, and a missing required field.
    invented = _payload()
    invented["features"].append({**_feature(invented, "court"), "name": "zip_code"})
    with pytest.raises(SpecError, match="is not a feature the model implements"):
        parse_spec(invented, DEFAULT_PATH)
    missing = _payload()
    entry = _feature(missing, "charge_count")
    del entry["missing"]
    missing["features"] = [entry if e["name"] == "charge_count" else e for e in missing["features"]]
    with pytest.raises(SpecError, match="'missing' is required"):
        parse_spec(missing, DEFAULT_PATH)


def test_every_feature_states_known_at_and_leakage() -> None:
    spec = load_spec()
    for feature in spec.features:
        assert feature.known_at in KNOWN_AT, feature.name
        assert feature.known_at == FEATURE_CONTRACTS[feature.name].known_at, feature.name
        assert set(feature.source) == FEATURE_CONTRACTS[feature.name].reads, feature.name
        assert len(feature.leakage.split()) >= 8, feature.name
        assert feature.description, feature.name
    # Every history feature is evaluated at the index case's filing.
    for name in HISTORY_FEATURES:
        assert spec.feature(name).known_at == FILED_AT, name
    # A feature misstating its instant or its columns is rejected.
    payload = _payload()
    payload["features"] = [
        {**entry, "known_at": "index_at"} if entry["name"] == "prior_cases" else entry
        for entry in payload["features"]
    ]
    with pytest.raises(SpecError, match="'known_at' must be 'filed_at'"):
        parse_spec(payload, DEFAULT_PATH)
    payload = _payload()
    payload["features"] = [
        {**entry, "leakage": ""} if entry["name"] == "prior_cases" else entry
        for entry in payload["features"]
    ]
    with pytest.raises(SpecError, match="'leakage' must be a non-empty string"):
        parse_spec(payload, DEFAULT_PATH)
    payload = _payload()
    payload["features"] = [
        {**entry, "source": ["cases.filed_at"]} if entry["name"] == "prior_cases" else entry
        for entry in payload["features"]
    ]
    with pytest.raises(SpecError, match="'source' must list exactly"):
        parse_spec(payload, DEFAULT_PATH)


def test_levels_are_checked_against_the_vocabulary() -> None:
    payload = _payload()
    payload["features"] = [
        {**entry, "levels": [*entry["levels"][:-1], "felony_9"]}
        if entry["name"] == "lead_severity"
        else entry
        for entry in payload["features"]
    ]
    with pytest.raises(SpecError, match="must list every severity value exactly once"):
        parse_spec(payload, DEFAULT_PATH)
    payload = _payload()
    payload["features"] = [
        {**entry, "reference": "2"} if entry["name"] == "charge_count" else entry
        for entry in payload["features"]
    ]
    parse_spec(payload, DEFAULT_PATH)  # a band label is a valid reference
    payload["features"] = [
        {**entry, "reference": "9"} if entry["name"] == "charge_count" else entry
        for entry in payload["features"]
    ]
    with pytest.raises(SpecError, match="is not one of the bands"):
        parse_spec(payload, DEFAULT_PATH)


def test_targets_are_tied_to_the_registry() -> None:
    payload = _payload()
    payload["targets"][1] = {**payload["targets"][1], "population": "failure_to_appear_rate"}
    with pytest.raises(SpecError, match="windowed rate of 'new_case'"):
        parse_spec(payload, DEFAULT_PATH)
    payload = _payload()
    payload["targets"][0] = {**payload["targets"][0], "windows_days": [30]}
    with pytest.raises(SpecError, match="must be null for a decision index"):
        parse_spec(payload, DEFAULT_PATH)
    payload = _payload()
    payload["recovery"]["fits"][1] = {"target": "new_case", "window_days": 45}
    with pytest.raises(SpecError, match="45 is not a window of new_case"):
        parse_spec(payload, DEFAULT_PATH)


# --- specification version 3: availability (Phase 5 Step 5) ---------------------------------

PERSON_HISTORY = ("prior_cases", "prior_convictions", "prior_failures_to_appear", "pending_case")


def _source(
    gates: tuple[str, ...], scope: str | None, outcomes: set[str], name: str = "source"
) -> SourceRow:
    return SourceRow(
        id="00000000-0000-0000-0000-000000000001",
        name=name,
        source_type="fixture",
        coverage_start=date(2020, 1, 1),
        coverage_end=date(2020, 12, 31),
        observable_outcomes=frozenset(outcomes),
        capabilities=SourceCapabilities(gates, scope, ()),
    )


def test_specification_three_declares_availability_and_the_person_history_features() -> None:
    spec = load_spec()
    assert spec.person_history_features == PERSON_HISTORY
    for feature in spec.features:
        assert feature.person_history == FEATURE_CONTRACTS[feature.name].person_history
    availability = spec.availability
    assert "assignment gate" in availability.gate
    assert "outcome" in availability.outcome
    assert "person key" in availability.person_key


def test_a_misdeclared_person_history_or_a_missing_availability_is_rejected() -> None:
    hidden = _payload()
    del _feature_entry(hidden, "prior_cases")["person_history"]
    with pytest.raises(SpecError, match=r"feature 'prior_cases': field 'person_history'"):
        parse_spec(hidden, DEFAULT_PATH)
    claimed = _payload()
    _feature_entry(claimed, "court")["person_history"] = True
    with pytest.raises(SpecError, match=r"feature 'court': field 'person_history'"):
        parse_spec(claimed, DEFAULT_PATH)
    missing = _payload()
    del missing["availability"]
    with pytest.raises(SpecError, match="availability"):
        parse_spec(missing, DEFAULT_PATH)
    unknown = _payload()
    unknown["availability"]["registry"] = "x"
    with pytest.raises(SpecError, match="availability"):
        parse_spec(unknown, DEFAULT_PATH)


def test_the_first_failing_condition_is_the_reason_a_target_is_unavailable() -> None:
    spec = load_spec()
    release, new_case = spec.target("pretrial_release"), spec.target("new_case")
    synthetic = _source(JUDGE_GATES, CROSS_CASE, {"new_case", "failure_to_appear"})
    assert unavailable_reason(spec, release, synthetic) is None
    assert unavailable_reason(spec, new_case, synthetic) is None
    cook = _source(("disposing_judge", "sentencing_judge"), CASE, {"revocation"})
    for target in spec.targets:
        assert unavailable_reason(spec, target, cook) == spec.availability.gate
    unobserved = _source(JUDGE_GATES, CROSS_CASE, set())
    assert unavailable_reason(spec, new_case, unobserved) == spec.availability.outcome
    # The release target's outcome is the decision itself: always documented.
    assert unavailable_reason(spec, release, unobserved) is None
    per_case = _source(JUDGE_GATES, CASE, {"new_case", "failure_to_appear"})
    assert unavailable_reason(spec, release, per_case) == spec.availability.person_key
    assert unavailable_reason(spec, new_case, per_case) == spec.availability.person_key


def test_an_unavailable_model_reads_back_as_unfitted_parameters() -> None:
    model = UnavailableModel(
        source="cook_sao",
        target="new_case",
        window_days=365,
        seed=1,
        spec_version=3,
        model_version="expected-logit-v1",
        reason="the reason",
    )
    data = model.render(snapshot="a" * 64, code_version="test")
    parameters = ModelParameters.from_artifact(json.loads(data), content_hash(data))
    assert parameters.status == UNAVAILABLE and not parameters.fitted
    assert parameters.columns == () and parameters.coefficients is None
    assert model.diagnostics_row() == {"status": UNAVAILABLE, "reason": "the reason"}
    assert model.coefficient_rows() is None and model_rows(model) == (0, 0)
    assert model.split.train_rows == model.split.test_rows == 0
