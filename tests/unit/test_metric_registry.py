# tests/unit/test_metric_registry.py
"""The versioned metric registry: it loads, it validates, and its text is the contract.

The committed ``data/reference/metric_registry.yaml`` loads through
``load_registry``; a tampered copy with an unlisted actor, outcome, or
window fails with ``RegistryError`` naming the slug and the field; its
``known_limitations`` equal the brief's ``<important_statistical_warnings>``
verbatim (parsed from the XML with whitespace normalized); and the
pretrial and dismissal entries' prose equals the corresponding
``definitions`` text of the golden fixture's ``truth/metrics.json`` unless
the entry states the difference in ``truth_note``.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET  # noqa: S405 - the brief is a repository file, not untrusted input
from pathlib import Path
from typing import Any

import pytest
import yaml

from judgemetrics.config import REPO_ROOT
from judgemetrics.metrics import registry as registry_module
from judgemetrics.metrics.registry import (
    ASSIGNMENT_GATES,
    DEFAULT_PATH,
    KINDS,
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
    assert registry.version == 1
    assert registry.methodology_version == "0.1"
    assert REQUIRED_SLUGS <= set(registry.metrics)
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
        assert metric.version == "1"
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
    assert row["registry_version"] == 1 and row["methodology_version"] == "0.1"
    assert "population" not in row and "counted" not in row and "truth_note" not in row
    assert set(row) == {"slug", "version", *registry_module.SUBSTANTIVE_COLUMNS}
