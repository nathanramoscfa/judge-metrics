# tests/unit/test_metric_registry.py
"""The versioned metric registry: it loads, it validates, and its text is the contract.

The committed ``data/reference/metric_registry.yaml`` (version 3,
methodology 1.1) loads through ``load_registry``; a tampered copy with an
unlisted actor, outcome, or window — or an adjusted entry without its
``adjustment``, over a court, or with windows over decisions — fails with
``RegistryError`` naming the slug and the field; each observed-to-expected
metric carries the eligibility and attribution of the descriptive metric it
adjusts and the specification's thresholds; its
``known_limitations`` equal the brief's ``<important_statistical_warnings>``
verbatim (parsed from the XML with whitespace normalized); and the
pretrial and dismissal entries' prose equals the corresponding
``definitions`` text of the golden fixture's ``truth/metrics.json`` unless
the entry states the difference in ``truth_note``. Registry version 3 (Phase 5
Step 5): the disposition family is gated on ``disposing_judge``; the periods
state the engine's anchors and leave the adjusted kind whole-window; every
metric sits in exactly one threshold group with its rationale and every
suppressed metric's threshold carries a measured cohort; every revocation
metric carries the scope of its index event.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET  # noqa: S405 - the brief is a repository file, not untrusted input
from pathlib import Path
from typing import Any

import pytest
import yaml

from judgemetrics.capabilities import JUDGE_GATES as CAPABILITY_GATES
from judgemetrics.config import REPO_ROOT
from judgemetrics.metrics import registry as registry_module
from judgemetrics.metrics.adjustment.spec import load_spec
from judgemetrics.metrics.registry import (
    ASSIGNMENT_GATES,
    DEFAULT_PATH,
    DESCRIPTIVE_KINDS,
    JUDGE_GATES,
    KINDS,
    OBSERVED_EXPECTED,
    POPULATION_ANCHORS,
    QUANTILE_FIELDS,
    WINDOWS_DAYS,
    Registry,
    RegistryError,
    load_registry,
    parse_registry,
)
from judgemetrics.synthetic import truth

pytestmark = pytest.mark.unit

BRIEF = REPO_ROOT / "docs" / "brief" / "judgemetrics-master-project-specification.xml"
GOLDEN_METRICS = REPO_ROOT / "tests" / "fixtures" / "golden" / "truth" / "metrics.json"
REQUIRED_SLUGS = {
    "eligible_cases",
    "eligible_defendants",
    "pretrial_decisions",
    "pretrial_released",
    "pretrial_detained",
    "pretrial_release_share",
    "statutory_release_count",
    "unknown_actor_pretrial_count",
    "failure_to_appear_rate",
    "new_case_rate",
    "new_charge_rate",
    "reconviction_rate",
    "release_violation_rate",
    "revocation_rate",
    "rearrest_rate",
    "failure_to_appear_survival",
    "new_case_survival",
    "reconviction_survival",
    "new_case_rate_after_disposition",
    "new_charge_rate_after_disposition",
    "reconviction_rate_after_disposition",
    "revocation_rate_after_disposition",
    "new_case_rate_after_sentence",
    "new_charge_rate_after_sentence",
    "reconviction_rate_after_sentence",
    "revocation_rate_after_sentence",
    "disposition_distribution",
    "judicial_dismissal_rate",
    "median_days_to_disposition",
    "sentence_count",
    "incarceration_days_median",
    "probation_days_median",
    "incarceration_days_median_by_offense_category",
}
# Registry version 2: each observed-to-expected metric → the descriptive metric it adjusts.
ADJUSTED_SLUGS_OF = {
    "pretrial_release_observed_expected": "pretrial_release_share",
    "new_case_observed_expected": "new_case_rate",
    "failure_to_appear_observed_expected": "failure_to_appear_rate",
}
ADJUSTED_SLUGS = set(ADJUSTED_SLUGS_OF)
# Registry version 3: the disposition family moved to the disposing-judge gate.
DISPOSITION_FAMILY = {
    "disposition_distribution",
    "judicial_dismissal_rate",
    "median_days_to_disposition",
    "new_case_rate_after_disposition",
    "new_charge_rate_after_disposition",
    "reconviction_rate_after_disposition",
    "revocation_rate_after_disposition",
}
# ... and the sentencing family counts each sentencing decision once.
SENTENCING_FAMILY = {
    "sentence_count",
    "incarceration_days_median",
    "probation_days_median",
    "incarceration_days_median_by_offense_category",
    "new_case_rate_after_sentence",
    "new_charge_rate_after_sentence",
    "reconviction_rate_after_sentence",
    "revocation_rate_after_sentence",
}
# Every entry registry version 3 changed (its own version is "2").
VERSION_TWO = DISPOSITION_FAMILY | SENTENCING_FAMILY | {"revocation_rate"}
# Registry slug → the `definitions` key of truth/metrics.json whose text it must carry.
TRUTH_DEFINITIONS = {
    "eligible_cases": "eligible_cases",
    "eligible_defendants": "eligible_defendants",
    "pretrial_decisions": "pretrial.decisions",
    "pretrial_released": "pretrial.released_count",
    "pretrial_detained": "pretrial.detained_count",
    "pretrial_release_share": "pretrial.release_share",
    "statutory_release_count": "pretrial.statutory_release_count",
    "unknown_actor_pretrial_count": "pretrial.unknown_actor_count",
    "failure_to_appear_rate": "pretrial.windows",
    "new_case_rate": "pretrial.windows",
    "reconviction_rate": "pretrial.windows",
    "judicial_dismissal_rate": "judicial_dismissal_rate",
    "disposition_distribution": "disposition_distribution",
    "median_days_to_disposition": "median_days_to_disposition",
    "sentence_count": "sentences",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _payload() -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
    return loaded


def _load_tampered(tmp_path: Path, mutate: Any) -> Registry:
    payload = _payload()
    mutate(payload)
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return load_registry(path)


def _entry(payload: dict[str, Any], slug: str) -> dict[str, Any]:
    for entry in payload["metrics"]:
        if entry["slug"] == slug:
            metric: dict[str, Any] = entry
            return metric
    raise KeyError(slug)


def test_the_committed_registry_loads_and_carries_the_required_slugs() -> None:
    registry = load_registry()
    assert registry.path == DEFAULT_PATH
    assert DEFAULT_PATH.read_text(encoding="utf-8").startswith(
        "# data/reference/metric_registry.yaml\n"
    )
    assert registry.version == 3
    assert registry.methodology_version == "1.1"
    assert REQUIRED_SLUGS | ADJUSTED_SLUGS <= set(registry.metrics)
    assert len(REQUIRED_SLUGS) == 33  # the Phase 3 slugs, every one still present
    assert {metric.kind for metric in registry.metrics.values()} == set(KINDS)
    assert registry.suppression.default_threshold == 10
    assert load_registry() is registry  # cached per path


def test_thresholds_units_and_windows_follow_the_registry_rules() -> None:
    registry = load_registry()
    assert WINDOWS_DAYS == truth.WINDOWS_DAYS
    for metric in registry.metrics.values():
        if metric.kind in {"count", "distribution"}:
            assert metric.suppression_threshold == 0, metric.slug
            assert metric.unit == "count", metric.slug
        elif metric.kind == OBSERVED_EXPECTED:
            assert metric.suppression_threshold == 30, metric.slug
            assert metric.unit == "ratio", metric.slug
        else:
            assert metric.suppression_threshold == 10, metric.slug
        if metric.kind in {"share", "windowed_rate", "survival"}:
            assert metric.unit == "share", metric.slug
        if metric.kind == "median":
            assert metric.unit == "days", metric.slug
        if metric.is_windowed:
            assert metric.windows_days == WINDOWS_DAYS, metric.slug
            assert metric.index_event is not None and metric.outcome is not None, metric.slug
        else:
            assert metric.windows_days is None and metric.outcome is None, metric.slug
        assert metric.attribution.assignment_gate in ASSIGNMENT_GATES
        assert metric.version == ("2" if metric.slug in VERSION_TWO else "1"), metric.slug
    for slug in ("statutory_release_count", "unknown_actor_pretrial_count"):
        assert registry[slug].subject_types == ("court",)
    assert registry["disposition_distribution"].dimension == "disposition"
    assert registry["incarceration_days_median_by_offense_category"].dimension == (
        "offense_category"
    )
    survival = registry.of_kind("survival")
    assert {metric.slug for metric in survival} == {
        "failure_to_appear_survival",
        "new_case_survival",
        "reconviction_survival",
    }
    assert all(metric.index_event == "pretrial_release" for metric in survival)


def test_a_tampered_copy_with_an_unlisted_actor_fails_naming_the_slug_and_field(
    tmp_path: Path,
) -> None:
    def unlisted_actor(payload: dict[str, Any]) -> None:
        _entry(payload, "pretrial_decisions")["attribution"]["actor_types"] = ["judge", "bailiff"]

    with pytest.raises(RegistryError, match=r"metric 'pretrial_decisions'.*actor_types.*bailiff"):
        _load_tampered(tmp_path, unlisted_actor)


def test_a_tampered_copy_with_an_unlisted_outcome_or_window_fails(tmp_path: Path) -> None:
    def unlisted_outcome(payload: dict[str, Any]) -> None:
        _entry(payload, "new_case_rate")["outcome"] = "recidivism"

    def wrong_windows(payload: dict[str, Any]) -> None:
        _entry(payload, "new_case_rate")["windows_days"] = [30, 90]

    def bad_gate(payload: dict[str, Any]) -> None:
        _entry(payload, "sentence_count")["attribution"]["assignment_gate"] = "any_judge"

    def duplicate_slug(payload: dict[str, Any]) -> None:
        payload["metrics"].append(dict(_entry(payload, "sentence_count")))

    def no_subjects(payload: dict[str, Any]) -> None:
        _entry(payload, "sentence_count")["subject_types"] = []

    def windowed_without_index(payload: dict[str, Any]) -> None:
        _entry(payload, "new_case_survival")["index_event"] = None

    for mutate, pattern in (
        (unlisted_outcome, r"metric 'new_case_rate': field 'outcome'.*recidivism"),
        (wrong_windows, r"metric 'new_case_rate': field 'windows_days'"),
        (bad_gate, r"metric 'sentence_count': field 'attribution.assignment_gate'"),
        (duplicate_slug, r"metric 'sentence_count': field 'slug' is listed twice"),
        (no_subjects, r"metric 'sentence_count': field 'subject_types'"),
        (windowed_without_index, r"metric 'new_case_survival': field 'index_event' is required"),
    ):
        with pytest.raises(RegistryError, match=pattern):
            _load_tampered(tmp_path, mutate)


def test_malformed_files_are_rejected(tmp_path: Path) -> None:
    with pytest.raises(RegistryError, match="cannot read"):
        load_registry(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="mapping at the top level"):
        load_registry(bad)
    with pytest.raises(RegistryError, match="`version` must be a positive integer"):
        parse_registry({**_payload(), "version": 0}, bad)
    with pytest.raises(RegistryError, match="every metric entry must be a mapping"):
        parse_registry({**_payload(), "metrics": ["x"]}, bad)


def _brief_warnings() -> list[str]:
    root = ET.parse(BRIEF).getroot()  # noqa: S314 - repository file
    node = root.find(".//important_statistical_warnings")
    assert node is not None
    return [_normalize(warning.text or "") for warning in node.findall("warning")]


def test_known_limitations_equal_the_briefs_eight_warnings_verbatim() -> None:
    warnings = _brief_warnings()
    assert len(warnings) == 8
    registry = load_registry()
    assert [_normalize(item) for item in registry.known_limitations] == warnings


def test_pretrial_and_dismissal_prose_matches_the_golden_truth_or_states_the_difference() -> None:
    definitions = json.loads(GOLDEN_METRICS.read_text(encoding="utf-8"))["definitions"]
    assert definitions == truth.DEFINITIONS
    registry = load_registry()
    checked = 0
    for slug, key in TRUTH_DEFINITIONS.items():
        metric = registry[slug]
        expected = _normalize(definitions[key])
        if metric.truth_note is None:
            assert _normalize(metric.eligibility) == expected, slug
        else:
            assert _normalize(metric.eligibility) != expected, f"{slug}: needless truth_note"
            assert "truth/metrics.json" in metric.truth_note, slug
        checked += 1
    assert checked == len(TRUTH_DEFINITIONS)


def test_definition_rows_carry_the_published_fields_only() -> None:
    registry = load_registry()
    row = registry["new_case_rate"].as_row(registry.version, registry.methodology_version)
    assert row["slug"] == "new_case_rate" and row["version"] == "1"
    assert row["attribution"] == {
        "decision_type": "pretrial_release",
        "actor_types": ["judge"],
        "discretion": ["discretionary"],
        "assignment_gate": "deciding_judge",
    }
    assert row["windows_days"] == list(WINDOWS_DAYS)
    assert row["registry_version"] == 3 and row["methodology_version"] == "1.1"
    assert "population" not in row and "counted" not in row and "truth_note" not in row
    assert set(row) == {"slug", "version", *registry_module.SUBSTANTIVE_COLUMNS}
    adjusted = registry["new_case_observed_expected"].as_row(
        registry.version, registry.methodology_version
    )
    assert "adjustment" not in adjusted and adjusted["unit"] == "ratio"


# --- registry version 2: the observed_expected kind (Phase 4 Step 3) ------------------------


def test_the_adjusted_metrics_mirror_the_descriptive_metrics_they_adjust() -> None:
    registry = load_registry()
    spec = load_spec()
    assert {metric.slug for metric in registry.of_kind(OBSERVED_EXPECTED)} == ADJUSTED_SLUGS
    for slug, descriptive in ADJUSTED_SLUGS_OF.items():
        metric = registry[slug]
        assert metric.subject_types == ("judge",) and metric.version == "1"
        assert metric.adjustment is not None and metric.adjustment.minimum_expected == 5
        target = spec.target(metric.adjustment.target)
        population = registry[target.population]
        # Eligibility and attribution exactly as the descriptive metric adjusted.
        assert metric.attribution == registry[descriptive].attribution == population.attribution
        assert metric.eligibility == registry[descriptive].eligibility
        assert metric.windows_days == registry[descriptive].windows_days
        assert metric.outcome == registry[descriptive].outcome
        assert metric.is_windowed == (metric.windows_days is not None)
    # The registry's suppression agrees with the specification's thresholds.
    for metric in registry.of_kind(OBSERVED_EXPECTED):
        assert metric.suppression_threshold == spec.thresholds.minimum_cohort
        assert metric.adjustment is not None
        assert metric.adjustment.minimum_expected == spec.thresholds.minimum_expected
    for metric in registry.metrics.values():
        assert (metric.adjustment is not None) == (metric.kind == OBSERVED_EXPECTED)


def test_a_tampered_adjusted_entry_fails_naming_the_slug_and_field(tmp_path: Path) -> None:
    def no_adjustment(payload: dict[str, Any]) -> None:
        del _entry(payload, "new_case_observed_expected")["adjustment"]

    def adjustment_on_a_share(payload: dict[str, Any]) -> None:
        _entry(payload, "pretrial_release_share")["adjustment"] = {
            "target": "pretrial_release",
            "minimum_expected": 5,
        }

    def court_subject(payload: dict[str, Any]) -> None:
        _entry(payload, "pretrial_release_observed_expected")["subject_types"] = ["judge", "court"]

    def ratio_unit_on_a_share(payload: dict[str, Any]) -> None:
        _entry(payload, "pretrial_release_share")["unit"] = "ratio"

    def windows_over_decisions(payload: dict[str, Any]) -> None:
        _entry(payload, "pretrial_release_observed_expected")["windows_days"] = list(WINDOWS_DAYS)

    def negative_minimum(payload: dict[str, Any]) -> None:
        _entry(payload, "failure_to_appear_observed_expected")["adjustment"][
            "minimum_expected"
        ] = -1

    for mutate, pattern in (
        (no_adjustment, r"'new_case_observed_expected': field 'adjustment' is required"),
        (adjustment_on_a_share, r"'pretrial_release_share': field 'adjustment' is only allowed"),
        (court_subject, r"'pretrial_release_observed_expected': field 'subject_types'"),
        (ratio_unit_on_a_share, r"'pretrial_release_share': field 'unit'"),
        (windows_over_decisions, r"'pretrial_release_observed_expected': field 'windows_days'"),
        (negative_minimum, r"field 'adjustment.minimum_expected'"),
    ):
        with pytest.raises(RegistryError, match=pattern):
            _load_tampered(tmp_path, mutate)


# --- registry version 3: real-data semantics (Phase 5 Step 5) ---------------------------------


def test_the_disposition_family_is_gated_on_the_disposing_judge() -> None:
    registry = load_registry()
    assert "disposing_judge" in ASSIGNMENT_GATES
    assert JUDGE_GATES == CAPABILITY_GATES  # the gates a source can declare it records
    gated = {
        slug
        for slug, metric in registry.metrics.items()
        if metric.attribution.assignment_gate == "disposing_judge"
    }
    assert gated == DISPOSITION_FAMILY
    for slug in DISPOSITION_FAMILY:
        metric = registry[slug]
        assert metric.version == "2", slug
        assert "disposing judge" in metric.eligibility, slug
        assert "assignment interval" not in metric.eligibility, slug
    for slug in SENTENCING_FAMILY:
        assert "amended or corrected" in registry[slug].eligibility, slug


def test_the_periods_state_the_engine_anchors_and_keep_the_adjusted_kind_whole() -> None:
    periods = load_registry().periods
    assert periods.calendar_year_kinds == DESCRIPTIVE_KINDS
    assert OBSERVED_EXPECTED not in periods.calendar_year_kinds
    assert dict(periods.anchors) == dict(POPULATION_ANCHORS)
    assert "calendar year (UTC)" in periods.calendar_year
    assert "coverage window" in periods.whole_window


def test_every_threshold_carries_its_rationale_and_its_measured_cohorts() -> None:
    registry = load_registry()
    suppression = registry.suppression
    listed = [slug for group in suppression.thresholds for slug in group.metrics]
    assert sorted(listed) == sorted(registry.metrics)  # every metric exactly once
    for group in suppression.thresholds:
        assert len(group.rationale) > 80 and "PLACEHOLDER" not in group.rationale
        for slug in group.metrics:
            assert registry[slug].suppression_threshold == group.threshold, slug
    measured = {slug for item in suppression.measurements for slug in item.metrics}
    for slug, metric in registry.metrics.items():
        if metric.suppression_threshold > 0:
            assert slug in measured, f"{slug}: a threshold without a measured cohort"
    assert {item.source for item in suppression.measurements} >= {"cook_sao", "synthetic"}
    for item in suppression.measurements:
        assert [name for name, _ in item.quantiles] == list(QUANTILE_FIELDS)
        assert 0.0 <= item.under_threshold <= 1.0
    assert "PLACEHOLDER" not in suppression.measurement_method
    # Phase 3 finding 3.5, answered: the eligible count stays published.
    assert "eligible count" in suppression.eligible_count


def test_each_revocation_metric_carries_the_scope_of_its_index_event() -> None:
    registry = load_registry()
    scopes = registry.revocation_scopes
    assert dict(scopes.by_index_event) == {
        "pretrial_release": "release",
        "disposition": "supervision",
        "sentence": "supervision",
    }
    for metric in registry.metrics.values():
        if metric.outcome == "revocation":
            assert metric.index_event is not None
            assert metric.revocation_scope == scopes.by_index_event[metric.index_event]
        else:
            assert metric.revocation_scope is None, metric.slug
    assert registry["revocation_rate"].revocation_scope == "release"


def test_tampered_version_three_blocks_fail(tmp_path: Path) -> None:
    def gate_on_sentences(payload: dict[str, Any]) -> None:
        _entry(payload, "sentence_count")["attribution"]["assignment_gate"] = "disposing_judge"

    def anchors_drift(payload: dict[str, Any]) -> None:
        payload["periods"]["calendar_year"]["anchors"]["sentences"] = "filed_at"

    def adjusted_years(payload: dict[str, Any]) -> None:
        payload["periods"]["calendar_year"]["kinds"].append(OBSERVED_EXPECTED)

    def unlisted_threshold(payload: dict[str, Any]) -> None:
        payload["suppression"]["thresholds"][0]["metrics"].remove("sentence_count")

    def wrong_threshold(payload: dict[str, Any]) -> None:
        _entry(payload, "sentence_count")["suppression_threshold"] = 5

    def unknown_scope(payload: dict[str, Any]) -> None:
        payload["revocation_scopes"]["by_index_event"]["sentence"] = "parole"

    def unmeasured(payload: dict[str, Any]) -> None:
        payload["suppression"]["measurements"]["cohorts"] = [
            cohort
            for cohort in payload["suppression"]["measurements"]["cohorts"]
            if "probation_days_median" not in cohort["metrics"]
        ]

    for mutate, pattern in (
        (gate_on_sentences, r"'sentence_count': field 'attribution.assignment_gate'"),
        (anchors_drift, r"periods.calendar_year.anchors"),
        (adjusted_years, r"periods.calendar_year.kinds"),
        (unlisted_threshold, r"suppression.thresholds` does not list \['sentence_count'\]"),
        (wrong_threshold, r"puts 'sentence_count' at 0"),
        (unknown_scope, r"revocation_scopes.by_index_event.sentence"),
        (unmeasured, r"threshold carries no measured cohort: \['probation_days_median'\]"),
    ):
        with pytest.raises(RegistryError, match=pattern):
            _load_tampered(tmp_path, mutate)
