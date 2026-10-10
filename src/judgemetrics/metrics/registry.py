# src/judgemetrics/metrics/registry.py
"""The versioned metric registry (``data/reference/metric_registry.yaml``).

The file is the contract every published number is computed against:
``load_registry`` reads it once per process with ``yaml.safe_load`` and
validates every entry on load — slugs unique and snake_case, ``kind``,
``subject_types``, ``population``, ``unit``, and the assignment gate in
their fixed enumerations, every ``attribution`` value, ``outcome``, and
``counted`` value in the case vocabulary, ``index_event`` and ``dimension``
in their enumerations, every ``windowed_rate`` and ``survival`` carrying
both an index event and an outcome with the brief's six windows, and every
other kind carrying none — raising ``RegistryError`` naming the slug and
the field on any violation, so a misread definition never reaches a
computation.

Registry version 2 (Phase 4 Step 3) adds the kind ``observed_expected``
(unit ``ratio``): an observed count over the expected count of the outcome
model (``data/reference/outcome_model.yaml``), partially pooled. Its entry
carries the field ``adjustment`` — ``target``, the specification target it
reads, and ``minimum_expected``, the expected count below which the ratio
is withheld — which every other kind must not carry; it is a judge-level
measure (``subject_types: [judge]``) over the release target's decisions
(no window) or a windowed target's pretrial-release cohort (an index
event, an outcome, and the brief's six windows).

Registry version 3 (Phase 5 Step 5, methodology 1.1) adds the assignment gate
``disposing_judge`` (the judge the source records on the charge whose
disposition it is), two top-level blocks, and the threshold rationale:

- ``periods``: the whole coverage window every metric publishes, and the
  calendar years (UTC) the descriptive kinds publish beside it, each over the
  rows whose *anchor* — ``POPULATION_ANCHORS``, which the block must state
  exactly — falls in the year;
- ``revocation_scopes``: what a revocation is after each index event (a
  revoked pretrial ``release``; a revoked ``supervision`` a sentence imposed),
  carried on every revocation metric as ``revocation_scope``, so a source that
  documents only one scope observes only the metrics of that scope;
- ``suppression.thresholds`` (every metric exactly once, with the threshold its
  entry carries and the reason), ``suppression.measurements`` (the cohort sizes
  the thresholds were decided against, as quantiles — never a subject), and
  ``suppression.eligible_count``, the answer to Phase 3 finding 3.5.

``sync_definitions(session)`` mirrors the registry into
``metric_definition`` on ``(slug, version)``: new versions are inserted,
rows whose substantive columns changed are updated, unchanged rows are not
written, and nothing is ever deleted (an old version stays as the history
of the observations that cite it). The row carries the published fields;
``population``, ``counted``, and ``measure`` steer the compute functions
and live in the file only.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import sqlalchemy as sa
import yaml
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from judgemetrics.config import REPO_ROOT
from judgemetrics.normalization import vocabulary

DEFAULT_PATH = REPO_ROOT / "data" / "reference" / "metric_registry.yaml"

# The brief's observation windows (<outcome_definitions>), in days.
WINDOWS_DAYS: tuple[int, ...] = (30, 90, 180, 365, 730, 1095)
OBSERVED_EXPECTED = "observed_expected"
KINDS: tuple[str, ...] = (
    "count",
    "share",
    "windowed_rate",
    "survival",
    "distribution",
    "median",
    OBSERVED_EXPECTED,
)
# The Phase 3 kinds: descriptive figures computed from the frame alone (pipeline step 13
# recomputes these; an adjusted figure needs a model fitted over every judge).
DESCRIPTIVE_KINDS: frozenset[str] = frozenset(KINDS) - {OBSERVED_EXPECTED}
WINDOWED_KINDS: frozenset[str] = frozenset({"windowed_rate", "survival"})
SUBJECT_TYPES: tuple[str, ...] = ("judge", "court")
POPULATIONS: tuple[str, ...] = (
    "cases",
    "defendants",
    "pretrial_decisions",
    "disposed_charges",
    "disposed_cases",
    "sentences",
    "index_events",
)
ASSIGNMENT_GATES: tuple[str, ...] = (
    "deciding_judge",
    "assigned_at_time",
    "assigned_ever",
    "sentencing_judge",
    "disposing_judge",
    "court_of_case",
)
COURT_OF_CASE = "court_of_case"
# The gates that tie a row to a judge (a source records some of them: capabilities).
JUDGE_GATES: tuple[str, ...] = tuple(gate for gate in ASSIGNMENT_GATES if gate != COURT_OF_CASE)
INDEX_EVENTS: tuple[str, ...] = ("pretrial_release", "disposition", "sentence")
DIMENSIONS: tuple[str, ...] = ("disposition", "offense_category")
UNITS: tuple[str, ...] = ("count", "share", "days", "ratio")
MEASURES: tuple[str, ...] = ("days_to_disposition", "incarceration_days", "probation_days")
# The anchor of each population: the instant whose calendar year (UTC) places a row in a
# calendar-year period, and which must fall inside the source's coverage window for the
# row to enter any period (`periods.calendar_year.anchors` must state exactly these).
POPULATION_ANCHORS: Mapping[str, str] = MappingProxyType(
    {
        "cases": "filed_at",
        "defendants": "filed_at",
        "pretrial_decisions": "decision_at",
        "disposed_charges": "disposed_at",
        "disposed_cases": "disposition_at",
        "sentences": "sentence_at",
        "index_events": "index_at",
    }
)
WHOLE_WINDOW = "whole_window"
CALENDAR_YEAR = "calendar_year"
PERIOD_TYPES: tuple[str, ...] = (WHOLE_WINDOW, CALENDAR_YEAR)
REVOCATION = "revocation"
REVOCATION_SCOPES: tuple[str, ...] = ("release", "supervision")
# The quantiles every cohort-size measurement records (nearest rank).
QUANTILE_FIELDS: tuple[str, ...] = ("p10", "p25", "p50", "p75", "p90")
MEASUREMENT_FIELDS: tuple[str, ...] = (
    "source",
    "subject_type",
    "period",
    "window_days",
    "cohorts",
    *QUANTILE_FIELDS,
    "under_threshold",
)
# `counted` conditions: the column and the vocabulary kind its value must
# belong to (`None` for a boolean flag).
COUNTED_COLUMNS: Mapping[str, str | None] = MappingProxyType(
    {"detained_flag": None, "disposition": "charge_disposition", "disposition_actor": "actor_type"}
)
SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
REQUIRED_FIELDS: tuple[str, ...] = (
    "slug",
    "name",
    "kind",
    "subject_types",
    "population",
    "description",
    "numerator",
    "denominator",
    "eligibility",
    "attribution",
    "index_event",
    "outcome",
    "windows_days",
    "dimension",
    "suppression_threshold",
    "unit",
    "version",
)
OPTIONAL_FIELDS: tuple[str, ...] = ("counted", "measure", "truth_note", "adjustment")
ATTRIBUTION_FIELDS: tuple[str, ...] = (
    "decision_type",
    "actor_types",
    "discretion",
    "assignment_gate",
)
ADJUSTMENT_FIELDS: tuple[str, ...] = ("target", "minimum_expected")
# The populations an adjusted figure is defined over: the release target's
# decisions, or a windowed target's pretrial-release index events.
ADJUSTED_POPULATIONS: tuple[str, ...] = ("pretrial_decisions", "index_events")


class RegistryError(ValueError):
    """The registry file is missing, malformed, or states an invalid definition."""


@dataclass(frozen=True, slots=True)
class AttributionSpec:
    """A metric's structured inclusion rule (docs/METHODOLOGY.md "Attribution")."""

    decision_type: str | None
    actor_types: tuple[str, ...] | None
    discretion: tuple[str, ...] | None
    assignment_gate: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision_type": self.decision_type,
            "actor_types": None if self.actor_types is None else list(self.actor_types),
            "discretion": None if self.discretion is None else list(self.discretion),
            "assignment_gate": self.assignment_gate,
        }


@dataclass(frozen=True, slots=True)
class AdjustmentSpec:
    """An ``observed_expected`` metric's model target and its minimum expected count."""

    target: str
    minimum_expected: float

    def as_dict(self) -> dict[str, Any]:
        return {"target": self.target, "minimum_expected": self.minimum_expected}


@dataclass(frozen=True, slots=True)
class MetricDefinitionSpec:
    """One registry entry, validated."""

    slug: str
    name: str
    kind: str
    subject_types: tuple[str, ...]
    population: str
    description: str
    numerator: str
    denominator: str
    eligibility: str
    attribution: AttributionSpec
    index_event: str | None
    outcome: str | None
    windows_days: tuple[int, ...] | None
    dimension: str | None
    suppression_threshold: int
    unit: str
    version: str
    counted: tuple[tuple[str, str | bool], ...] = ()
    measure: str | None = None
    truth_note: str | None = None
    adjustment: AdjustmentSpec | None = None
    # A revocation metric's scope after its index event (`revocation_scopes`); else null.
    revocation_scope: str | None = None

    @property
    def is_windowed(self) -> bool:
        """Whether the metric has follow-up windows (an adjusted ratio over a cohort has)."""
        return self.kind in WINDOWED_KINDS or (
            self.kind == OBSERVED_EXPECTED and self.windows_days is not None
        )

    @property
    def is_adjusted(self) -> bool:
        return self.kind == OBSERVED_EXPECTED

    @property
    def counted_conditions(self) -> dict[str, str | bool]:
        return dict(self.counted)

    def as_row(self, registry_version: int, methodology_version: str) -> dict[str, Any]:
        """The ``metric_definition`` row of this entry."""
        return {
            "slug": self.slug,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "numerator_definition": self.numerator,
            "denominator_definition": self.denominator,
            "eligibility_definition": self.eligibility,
            "kind": self.kind,
            "subject_types": list(self.subject_types),
            "attribution": self.attribution.as_dict(),
            "index_event": self.index_event,
            "outcome": self.outcome,
            "windows_days": None if self.windows_days is None else list(self.windows_days),
            "dimension": self.dimension,
            "suppression_threshold": self.suppression_threshold,
            "unit": self.unit,
            "registry_version": registry_version,
            "methodology_version": methodology_version,
        }


@dataclass(frozen=True, slots=True)
class ThresholdGroup:
    """Metrics sharing one suppression threshold, and why it is that number."""

    threshold: int
    metrics: tuple[str, ...]
    rationale: str


@dataclass(frozen=True, slots=True)
class CohortMeasurement:
    """The measured sizes of one denominator over one source, subject type, and period.

    ``cohorts`` is the number of (subject, period) cohorts measured, the
    quantiles are nearest-rank cohort sizes, and ``under_threshold`` is the
    share of those cohorts below the threshold ``metrics`` share.
    """

    name: str
    metrics: tuple[str, ...]
    source: str
    subject_type: str
    period: str
    window_days: int | None
    cohorts: int
    quantiles: tuple[tuple[str, int], ...]
    under_threshold: float


@dataclass(frozen=True, slots=True)
class SuppressionSpec:
    default_threshold: int
    rule: str
    rationale: str
    eligible_count: str = ""
    thresholds: tuple[ThresholdGroup, ...] = ()
    measured_on: str = ""
    measurement_method: str = ""
    measurements: tuple[CohortMeasurement, ...] = ()

    def group_of(self, slug: str) -> ThresholdGroup | None:
        """The threshold group that lists ``slug`` (every metric is in exactly one)."""
        for group in self.thresholds:
            if slug in group.metrics:
                return group
        return None


@dataclass(frozen=True, slots=True)
class PeriodSpec:
    """The periods observations are published over (``periods``)."""

    whole_window: str
    calendar_year: str
    calendar_year_kinds: frozenset[str]
    anchors: Mapping[str, str]

    def has_calendar_years(self, kind: str) -> bool:
        return kind in self.calendar_year_kinds


@dataclass(frozen=True, slots=True)
class RevocationScopeSpec:
    """What a revocation is after each index event (``revocation_scopes``)."""

    definitions: Mapping[str, str]
    by_index_event: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class Registry:
    """The loaded registry: versions, the brief's warnings, suppression, metrics by slug."""

    version: int
    methodology_version: str
    known_limitations: tuple[str, ...]
    suppression: SuppressionSpec
    metrics: Mapping[str, MetricDefinitionSpec]
    path: Path
    periods: PeriodSpec
    revocation_scopes: RevocationScopeSpec

    def __getitem__(self, slug: str) -> MetricDefinitionSpec:
        return self.metrics[slug]

    def of_kind(self, kind: str) -> tuple[MetricDefinitionSpec, ...]:
        return tuple(metric for metric in self.metrics.values() if metric.kind == kind)

    def for_subject(self, subject_type: str) -> tuple[MetricDefinitionSpec, ...]:
        return tuple(m for m in self.metrics.values() if subject_type in m.subject_types)


# --- loading and validation -------------------------------------------------------------


def _fail(slug: str | None, field_name: str, problem: str) -> RegistryError:
    where = f"metric {slug!r}: " if slug else ""
    return RegistryError(f"{where}field {field_name!r} {problem}")


def _string(entry: Mapping[str, Any], slug: str | None, field_name: str) -> str:
    value = entry.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise _fail(slug, field_name, "must be a non-empty string")
    return value.strip()


def _optional_string(entry: Mapping[str, Any], slug: str, field_name: str) -> str | None:
    value = entry.get(field_name)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _fail(slug, field_name, "must be a non-empty string or null")
    return value.strip()


def _choice(value: Any, slug: str, field_name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _fail(slug, field_name, f"must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _vocabulary_value(value: Any, slug: str, field_name: str, kind: str) -> str:
    if not isinstance(value, str) or not vocabulary.is_known(kind, value):
        raise _fail(slug, field_name, f"{value!r} is not a {kind} value in the case vocabulary")
    return value


def _vocabulary_list(value: Any, slug: str, field_name: str, kind: str) -> tuple[str, ...] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value:
        raise _fail(slug, field_name, "must be a non-empty list or null")
    values = tuple(_vocabulary_value(item, slug, field_name, kind) for item in value)
    if len(set(values)) != len(values):
        raise _fail(slug, field_name, "lists a value twice")
    return values


def _attribution(entry: Mapping[str, Any], slug: str) -> AttributionSpec:
    block = entry.get("attribution")
    if not isinstance(block, dict):
        raise _fail(slug, "attribution", "must be a mapping")
    unknown = set(block) - set(ATTRIBUTION_FIELDS)
    missing = set(ATTRIBUTION_FIELDS) - set(block)
    if unknown or missing:
        raise _fail(
            slug,
            "attribution",
            f"must carry exactly {', '.join(ATTRIBUTION_FIELDS)}"
            f" (missing {sorted(missing)}, unknown {sorted(unknown)})",
        )
    decision_type = block["decision_type"]
    if decision_type is not None:
        decision_type = _vocabulary_value(
            decision_type, slug, "attribution.decision_type", "decision_type"
        )
    return AttributionSpec(
        decision_type=decision_type,
        actor_types=_vocabulary_list(
            block["actor_types"], slug, "attribution.actor_types", "actor_type"
        ),
        discretion=_vocabulary_list(
            block["discretion"],
            slug,
            "attribution.discretion",
            "judicial_discretion_classification",
        ),
        assignment_gate=_choice(
            block["assignment_gate"], slug, "attribution.assignment_gate", ASSIGNMENT_GATES
        ),
    )


def _counted(entry: Mapping[str, Any], slug: str) -> tuple[tuple[str, str | bool], ...]:
    block = entry.get("counted")
    if block is None:
        return ()
    if not isinstance(block, dict) or not block:
        raise _fail(slug, "counted", "must be a non-empty mapping or absent")
    conditions: list[tuple[str, str | bool]] = []
    for column, value in block.items():
        if column not in COUNTED_COLUMNS:
            raise _fail(slug, "counted", f"{column!r} is not a countable column")
        kind = COUNTED_COLUMNS[column]
        if kind is None:
            if not isinstance(value, bool):
                raise _fail(slug, f"counted.{column}", "must be a boolean")
            conditions.append((column, value))
        else:
            conditions.append((column, _vocabulary_value(value, slug, f"counted.{column}", kind)))
    return tuple(conditions)


def _windows(value: Any, slug: str) -> tuple[int, ...] | None:
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in value)
        or tuple(value) != WINDOWS_DAYS
    ):
        raise _fail(slug, "windows_days", f"must be the brief's windows {list(WINDOWS_DAYS)}")
    return tuple(value)


def _subject_types(value: Any, slug: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value:
        raise _fail(slug, "subject_types", "must be a non-empty list")
    types = tuple(_choice(item, slug, "subject_types", SUBJECT_TYPES) for item in value)
    if len(set(types)) != len(types):
        raise _fail(slug, "subject_types", "lists a subject type twice")
    return types


def _threshold(value: Any, slug: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise _fail(slug, "suppression_threshold", "must be a non-negative integer")
    return value


def _adjustment(entry: Mapping[str, Any], slug: str, kind: str) -> AdjustmentSpec | None:
    """``adjustment`` is required for an ``observed_expected`` metric and rejected otherwise."""
    block = entry.get("adjustment")
    if kind != OBSERVED_EXPECTED:
        if block is not None:
            raise _fail(slug, "adjustment", f"is only allowed on an {OBSERVED_EXPECTED}")
        return None
    if not isinstance(block, dict):
        raise _fail(slug, "adjustment", f"is required for an {OBSERVED_EXPECTED} (a mapping)")
    unknown = set(block) - set(ADJUSTMENT_FIELDS)
    missing = set(ADJUSTMENT_FIELDS) - set(block)
    if unknown or missing:
        raise _fail(
            slug,
            "adjustment",
            f"must carry exactly {', '.join(ADJUSTMENT_FIELDS)}"
            f" (missing {sorted(missing)}, unknown {sorted(unknown)})",
        )
    target = block["target"]
    if not isinstance(target, str) or not SLUG_PATTERN.match(target):
        raise _fail(slug, "adjustment.target", "must name a specification target (snake_case)")
    minimum = block["minimum_expected"]
    if isinstance(minimum, bool) or not isinstance(minimum, int | float) or minimum < 0:
        raise _fail(slug, "adjustment.minimum_expected", "must be a non-negative number")
    return AdjustmentSpec(target=target, minimum_expected=float(minimum))


def _check_adjusted(
    slug: str,
    population: str,
    subject_types: tuple[str, ...],
    unit: str,
    index_event: str | None,
    outcome: str | None,
    windows: tuple[int, ...] | None,
) -> None:
    """An adjusted ratio is a judge measure over decisions (no window) or a release cohort."""
    if subject_types != ("judge",):
        raise _fail(slug, "subject_types", "must be [judge]: an adjusted ratio compares judges")
    if unit != "ratio":
        raise _fail(slug, "unit", f"must be ratio for an {OBSERVED_EXPECTED}")
    if population not in ADJUSTED_POPULATIONS:
        raise _fail(slug, "population", f"must be one of {', '.join(ADJUSTED_POPULATIONS)}")
    windowed = population == "index_events"
    for field_name, value in (
        ("index_event", index_event),
        ("outcome", outcome),
        ("windows_days", windows),
    ):
        if windowed and value is None:
            raise _fail(slug, field_name, "is required for an adjusted ratio over index events")
        if not windowed and value is not None:
            raise _fail(slug, field_name, "must be null for an adjusted ratio over decisions")
    if windowed and index_event != "pretrial_release":
        raise _fail(slug, "index_event", "must be pretrial_release for an adjusted ratio")


def parse_metric(entry: Any) -> MetricDefinitionSpec:
    """Validate one ``metrics:`` entry (a mapping) into a spec."""
    if not isinstance(entry, dict):
        raise RegistryError("every metric entry must be a mapping")
    slug = _string(entry, None, "slug")
    if not SLUG_PATTERN.match(slug):
        raise _fail(slug, "slug", "must be snake_case")
    unknown = set(entry) - set(REQUIRED_FIELDS) - set(OPTIONAL_FIELDS)
    if unknown:
        raise _fail(slug, ", ".join(sorted(unknown)), "is not a registry field")
    missing = [name for name in REQUIRED_FIELDS if name not in entry]
    if missing:
        raise _fail(slug, ", ".join(missing), "is required")
    kind = _choice(entry["kind"], slug, "kind", KINDS)
    index_event = entry["index_event"]
    if index_event is not None:
        index_event = _choice(index_event, slug, "index_event", INDEX_EVENTS)
    outcome = entry["outcome"]
    if outcome is not None:
        outcome = _vocabulary_value(outcome, slug, "outcome", "justice_event_type")
    windows = _windows(entry["windows_days"], slug)
    dimension = entry["dimension"]
    if dimension is not None:
        dimension = _choice(dimension, slug, "dimension", DIMENSIONS)
    measure = entry.get("measure")
    if measure is not None:
        measure = _choice(measure, slug, "measure", MEASURES)
    population = _choice(entry["population"], slug, "population", POPULATIONS)
    subject_types = _subject_types(entry["subject_types"], slug)
    unit = _choice(entry["unit"], slug, "unit", UNITS)
    if kind == OBSERVED_EXPECTED:
        _check_adjusted(slug, population, subject_types, unit, index_event, outcome, windows)
    elif unit == "ratio":
        raise _fail(slug, "unit", f"ratio is only allowed on an {OBSERVED_EXPECTED}")
    elif kind in WINDOWED_KINDS:
        if index_event is None:
            raise _fail(slug, "index_event", f"is required for a {kind}")
        if outcome is None:
            raise _fail(slug, "outcome", f"is required for a {kind}")
        if windows is None:
            raise _fail(slug, "windows_days", f"is required for a {kind}")
        if population != "index_events":
            raise _fail(slug, "population", f"must be index_events for a {kind}")
    else:
        for field_name, value in (
            ("index_event", index_event),
            ("outcome", outcome),
            ("windows_days", windows),
        ):
            if value is not None:
                raise _fail(slug, field_name, f"must be null for a {kind}")
        if population == "index_events":
            raise _fail(slug, "population", f"cannot be index_events for a {kind}")
    if kind == "distribution" and dimension is None:
        raise _fail(slug, "dimension", "is required for a distribution")
    if kind == "median" and measure is None:
        raise _fail(slug, "measure", "is required for a median")
    if kind != "median" and measure is not None:
        raise _fail(slug, "measure", "is only allowed on a median")
    if kind == OBSERVED_EXPECTED and (dimension is not None or entry.get("counted") is not None):
        raise _fail(slug, "dimension", f"an {OBSERVED_EXPECTED} has no dimension or counted rows")
    adjustment = _adjustment(entry, slug, kind)
    return MetricDefinitionSpec(
        slug=slug,
        name=_string(entry, slug, "name"),
        kind=kind,
        subject_types=subject_types,
        population=population,
        description=_string(entry, slug, "description"),
        numerator=_string(entry, slug, "numerator"),
        denominator=_string(entry, slug, "denominator"),
        eligibility=_string(entry, slug, "eligibility"),
        attribution=_attribution(entry, slug),
        index_event=index_event,
        outcome=outcome,
        windows_days=windows,
        dimension=dimension,
        suppression_threshold=_threshold(entry["suppression_threshold"], slug),
        unit=unit,
        version=_string(entry, slug, "version"),
        counted=_counted(entry, slug),
        measure=measure,
        truth_note=_optional_string(entry, slug, "truth_note"),
        adjustment=adjustment,
    )


# Populations the disposing-judge gate can attribute (a charge's disposition, a case's).
DISPOSING_POPULATIONS: tuple[str, ...] = ("disposed_charges", "disposed_cases")


def _check_gate(metric: MetricDefinitionSpec) -> None:
    """``disposing_judge`` attributes dispositions only (a charge's, a case's, the index's)."""
    if metric.attribution.assignment_gate != "disposing_judge":
        return
    disposition_index = metric.population == "index_events" and metric.index_event == "disposition"
    if metric.population not in DISPOSING_POPULATIONS and not disposition_index:
        raise _fail(
            metric.slug,
            "attribution.assignment_gate",
            "disposing_judge attributes disposed charges, disposed cases, or a disposition"
            " index event only",
        )


def _top_string(block: Mapping[str, Any], path: Path, where: str, name: str) -> str:
    value = block.get(name)
    if not isinstance(value, str) or not value.strip():
        raise RegistryError(f"{path}: `{where}.{name}` must be a non-empty string")
    return value.strip()


def _exact_keys(block: Any, path: Path, where: str, keys: tuple[str, ...]) -> Mapping[str, Any]:
    if not isinstance(block, dict):
        raise RegistryError(f"{path}: `{where}` must be a mapping")
    unknown = sorted(set(block) - set(keys))
    missing = sorted(set(keys) - set(block))
    if unknown or missing:
        raise RegistryError(
            f"{path}: `{where}` must carry exactly {', '.join(keys)}"
            f" (missing {missing}, unknown {unknown})"
        )
    return block


def parse_periods(block: Any, path: Path) -> PeriodSpec:
    """``periods``: the whole window's rule and the calendar years' kinds, anchors, rule."""
    periods = _exact_keys(block, path, "periods", PERIOD_TYPES)
    calendar = _exact_keys(
        periods[CALENDAR_YEAR], path, "periods.calendar_year", ("kinds", "anchors", "rule")
    )
    kinds = calendar["kinds"]
    if not isinstance(kinds, list) or not kinds or len(set(kinds)) != len(kinds):
        raise RegistryError(f"{path}: `periods.calendar_year.kinds` must list kinds once each")
    for kind in kinds:
        if kind not in DESCRIPTIVE_KINDS:
            raise RegistryError(
                f"{path}: `periods.calendar_year.kinds` lists {kind!r}, not a descriptive kind"
                f" (an {OBSERVED_EXPECTED} is published over the whole window only)"
            )
    anchors = calendar["anchors"]
    if not isinstance(anchors, dict) or dict(anchors) != dict(POPULATION_ANCHORS):
        raise RegistryError(
            f"{path}: `periods.calendar_year.anchors` must state the engine's anchors"
            f" {dict(POPULATION_ANCHORS)}"
        )
    whole = periods[WHOLE_WINDOW]
    if not isinstance(whole, str) or not whole.strip():
        raise RegistryError(f"{path}: `periods.whole_window` must be a non-empty string")
    return PeriodSpec(
        whole_window=whole.strip(),
        calendar_year=_top_string(calendar, path, "periods.calendar_year", "rule"),
        calendar_year_kinds=frozenset(kinds),
        anchors=MappingProxyType(dict(POPULATION_ANCHORS)),
    )


def parse_revocation_scopes(block: Any, path: Path) -> RevocationScopeSpec:
    """``revocation_scopes``: each scope's definition and the scope after each index event."""
    scopes = _exact_keys(block, path, "revocation_scopes", ("definitions", "by_index_event"))
    definitions = _exact_keys(
        scopes["definitions"], path, "revocation_scopes.definitions", REVOCATION_SCOPES
    )
    texts: dict[str, str] = {}
    for scope in REVOCATION_SCOPES:
        texts[scope] = _top_string(definitions, path, "revocation_scopes.definitions", scope)
    by_index = _exact_keys(
        scopes["by_index_event"], path, "revocation_scopes.by_index_event", INDEX_EVENTS
    )
    for index_event, scope in by_index.items():
        if scope not in REVOCATION_SCOPES:
            raise RegistryError(
                f"{path}: `revocation_scopes.by_index_event.{index_event}` must be one of"
                f" {', '.join(REVOCATION_SCOPES)}"
            )
    return RevocationScopeSpec(
        definitions=MappingProxyType(texts),
        by_index_event=MappingProxyType({key: str(by_index[key]) for key in INDEX_EVENTS}),
    )


def _slug_list(value: Any, path: Path, where: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) for item in value)
        or len(set(value)) != len(value)
    ):
        raise RegistryError(f"{path}: `{where}` must list metric slugs once each")
    return tuple(value)


def parse_thresholds(
    block: Any, path: Path, metrics: Mapping[str, MetricDefinitionSpec]
) -> tuple[ThresholdGroup, ...]:
    """``suppression.thresholds``: every metric exactly once, at the threshold it carries."""
    if not isinstance(block, list) or not block:
        raise RegistryError(f"{path}: `suppression.thresholds` must be a non-empty list")
    groups: list[ThresholdGroup] = []
    seen: dict[str, int] = {}
    for index, entry in enumerate(block):
        where = f"suppression.thresholds[{index}]"
        group = _exact_keys(entry, path, where, ("threshold", "metrics", "rationale"))
        threshold = group["threshold"]
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
            raise RegistryError(f"{path}: `{where}.threshold` must be a non-negative integer")
        slugs = _slug_list(group["metrics"], path, f"{where}.metrics")
        for slug in slugs:
            if slug not in metrics:
                raise RegistryError(f"{path}: `{where}` lists {slug!r}, not a registry metric")
            if slug in seen:
                raise RegistryError(f"{path}: `suppression.thresholds` lists {slug!r} twice")
            if metrics[slug].suppression_threshold != threshold:
                raise RegistryError(
                    f"{path}: `{where}` puts {slug!r} at {threshold}, but its entry carries"
                    f" suppression_threshold {metrics[slug].suppression_threshold}"
                )
            seen[slug] = threshold
        groups.append(
            ThresholdGroup(threshold, slugs, _top_string(group, path, where, "rationale"))
        )
    missing = sorted(set(metrics) - set(seen))
    if missing:
        raise RegistryError(f"{path}: `suppression.thresholds` does not list {missing}")
    return tuple(groups)


def _count(value: Any, path: Path, where: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RegistryError(f"{path}: `{where}` must be a non-negative integer")
    return value


def parse_measurements(
    block: Any, path: Path, metrics: Mapping[str, MetricDefinitionSpec]
) -> tuple[str, str, tuple[CohortMeasurement, ...]]:
    """``suppression.measurements``: the date, the method, and the measured cohorts."""
    measured = _exact_keys(
        block, path, "suppression.measurements", ("measured_on", "method", "cohorts")
    )
    day = measured["measured_on"]
    if not isinstance(day, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise RegistryError(f"{path}: `suppression.measurements.measured_on` must be a date")
    entries = measured["cohorts"]
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{path}: `suppression.measurements.cohorts` must be a list")
    result: list[CohortMeasurement] = []
    for index, entry in enumerate(entries):
        where = f"suppression.measurements.cohorts[{index}]"
        cohort = _exact_keys(entry, path, where, ("name", "metrics", "sizes"))
        name = cohort["name"]
        if not isinstance(name, str) or not SLUG_PATTERN.match(name):
            raise RegistryError(f"{path}: `{where}.name` must be snake_case")
        slugs = _slug_list(cohort["metrics"], path, f"{where}.metrics")
        thresholds = set()
        for slug in slugs:
            if slug not in metrics:
                raise RegistryError(f"{path}: `{where}` lists {slug!r}, not a registry metric")
            thresholds.add(metrics[slug].suppression_threshold)
        if len(thresholds) != 1:
            raise RegistryError(f"{path}: `{where}.metrics` must share one threshold")
        sizes = cohort["sizes"]
        if not isinstance(sizes, list) or not sizes:
            raise RegistryError(f"{path}: `{where}.sizes` must be a non-empty list")
        for position, size in enumerate(sizes):
            at = f"{where}.sizes[{position}]"
            row = _exact_keys(size, path, at, MEASUREMENT_FIELDS)
            source = row["source"]
            if not isinstance(source, str) or not SLUG_PATTERN.match(source):
                raise RegistryError(f"{path}: `{at}.source` must be a source register name")
            if row["subject_type"] not in SUBJECT_TYPES:
                raise RegistryError(f"{path}: `{at}.subject_type` must be judge or court")
            if row["period"] not in PERIOD_TYPES:
                raise RegistryError(f"{path}: `{at}.period` must be one of {PERIOD_TYPES}")
            window = row["window_days"]
            if window is not None and window not in WINDOWS_DAYS:
                raise RegistryError(f"{path}: `{at}.window_days` must be a window or null")
            quantiles = tuple(
                (name, _count(row[name], path, f"{at}.{name}")) for name in QUANTILE_FIELDS
            )
            values = [value for _, value in quantiles]
            if values != sorted(values):
                raise RegistryError(f"{path}: `{at}` quantiles must not decrease")
            under = row["under_threshold"]
            if (
                isinstance(under, bool)
                or not isinstance(under, int | float)
                or not 0.0 <= float(under) <= 1.0
            ):
                raise RegistryError(f"{path}: `{at}.under_threshold` must be a share")
            result.append(
                CohortMeasurement(
                    name=name,
                    metrics=slugs,
                    source=source,
                    subject_type=str(row["subject_type"]),
                    period=str(row["period"]),
                    window_days=window,
                    cohorts=_count(row["cohorts"], path, f"{at}.cohorts"),
                    quantiles=quantiles,
                    under_threshold=float(under),
                )
            )
    unmeasured = sorted(
        slug
        for slug, metric in metrics.items()
        if metric.suppression_threshold > 0 and not any(slug in item.metrics for item in result)
    )
    if unmeasured:
        raise RegistryError(
            f"{path}: a suppressed metric's threshold carries no measured cohort: {unmeasured}"
        )
    method = measured["method"]
    if not isinstance(method, str) or not method.strip():
        raise RegistryError(f"{path}: `suppression.measurements.method` must be prose")
    return day, method.strip(), tuple(result)


def _with_revocation_scope(
    metric: MetricDefinitionSpec, scopes: RevocationScopeSpec
) -> MetricDefinitionSpec:
    """A revocation metric carries its index event's revocation scope."""
    if metric.outcome != REVOCATION or metric.index_event is None:
        return metric
    return replace(metric, revocation_scope=scopes.by_index_event[metric.index_event])


def parse_registry(payload: Any, path: Path) -> Registry:
    """Validate a loaded YAML payload into a ``Registry``."""
    if not isinstance(payload, dict):
        raise RegistryError(f"{path}: expected a mapping at the top level")
    top = (
        "version",
        "methodology_version",
        "known_limitations",
        "periods",
        "revocation_scopes",
        "suppression",
        "metrics",
    )
    for name in top:
        if name not in payload:
            raise RegistryError(f"{path}: `{name}` is required")
    unknown_top = sorted(set(payload) - set(top))
    if unknown_top:
        raise RegistryError(f"{path}: {unknown_top} are not registry fields")
    version = payload["version"]
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise RegistryError(f"{path}: `version` must be a positive integer")
    methodology_version = payload["methodology_version"]
    if not isinstance(methodology_version, str) or not re.fullmatch(
        r"\d+\.\d+", methodology_version
    ):
        raise RegistryError(f"{path}: `methodology_version` must be a `major.minor` string")
    limitations = payload["known_limitations"]
    if (
        not isinstance(limitations, list)
        or not limitations
        or not all(isinstance(item, str) and item.strip() for item in limitations)
    ):
        raise RegistryError(f"{path}: `known_limitations` must be a list of non-empty strings")
    suppression = payload["suppression"]
    if not isinstance(suppression, dict):
        raise RegistryError(f"{path}: `suppression` must be a mapping")
    threshold = suppression.get("default_threshold")
    if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 0:
        raise RegistryError(
            f"{path}: `suppression.default_threshold` must be a non-negative integer"
        )
    suppression_keys = (
        "default_threshold",
        "rule",
        "rationale",
        "eligible_count",
        "thresholds",
        "measurements",
    )
    unknown_suppression = sorted(set(suppression) - set(suppression_keys))
    if unknown_suppression:
        raise RegistryError(f"{path}: `suppression` carries unknown keys {unknown_suppression}")
    entries = payload["metrics"]
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{path}: `metrics` must be a non-empty list")
    periods = parse_periods(payload["periods"], path)
    scopes = parse_revocation_scopes(payload["revocation_scopes"], path)
    metrics: dict[str, MetricDefinitionSpec] = {}
    for entry in entries:
        metric = _with_revocation_scope(parse_metric(entry), scopes)
        if metric.slug in metrics:
            raise _fail(metric.slug, "slug", "is listed twice")
        _check_gate(metric)
        metrics[metric.slug] = metric
    for name in ("eligible_count", "thresholds", "measurements"):
        if name not in suppression:
            raise RegistryError(f"{path}: `suppression.{name}` is required")
    thresholds = parse_thresholds(suppression["thresholds"], path, metrics)
    measured_on, method, measurements = parse_measurements(
        suppression["measurements"], path, metrics
    )
    suppression_spec = SuppressionSpec(
        default_threshold=threshold,
        rule=_string(suppression, None, "rule"),
        rationale=_string(suppression, None, "rationale"),
        eligible_count=_string(suppression, None, "eligible_count"),
        thresholds=thresholds,
        measured_on=measured_on,
        measurement_method=method,
        measurements=measurements,
    )
    return Registry(
        version=version,
        methodology_version=methodology_version,
        known_limitations=tuple(item.strip() for item in limitations),
        suppression=suppression_spec,
        metrics=MappingProxyType(metrics),
        path=path,
        periods=periods,
        revocation_scopes=scopes,
    )


@lru_cache(maxsize=4)
def load_registry(path: Path = DEFAULT_PATH) -> Registry:
    """The registry at ``path`` (``yaml.safe_load``), validated; cached per path."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise RegistryError(f"cannot read the metric registry at {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise RegistryError(f"{path}: not valid YAML ({exc.__class__.__name__})") from exc
    return parse_registry(payload, path)


# --- metric_definition sync -------------------------------------------------------------

# Columns whose change updates an existing (slug, version) row.
SUBSTANTIVE_COLUMNS: tuple[str, ...] = (
    "name",
    "description",
    "numerator_definition",
    "denominator_definition",
    "eligibility_definition",
    "kind",
    "subject_types",
    "attribution",
    "index_event",
    "outcome",
    "windows_days",
    "dimension",
    "suppression_threshold",
    "unit",
    "registry_version",
    "methodology_version",
)
_INSERTED = sa.literal_column("(xmax = 0)", type_=sa.Boolean).label("inserted")


@dataclass(frozen=True, slots=True)
class SyncResult:
    """What ``sync_definitions`` did: rows inserted, updated, left unchanged."""

    inserted: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.inserted + self.updated + self.unchanged


def sync_definitions(session: Session, registry: Registry | None = None) -> SyncResult:
    """Upsert every registry metric into ``metric_definition`` on ``(slug, version)``.

    Inserts new versions, updates only rows whose substantive columns
    changed (``IS DISTINCT FROM`` guards), never deletes, and returns the
    counts; a rerun over an unchanged registry writes nothing.
    """
    from judgemetrics.db.models import Base

    registry = registry or load_registry()
    table = Base.metadata.tables["metric_definition"]
    rows = [
        metric.as_row(registry.version, registry.methodology_version)
        for metric in registry.metrics.values()
    ]
    stmt = insert(table).values(rows)
    excluded = stmt.excluded
    set_: dict[str, Any] = {column: excluded[column] for column in SUBSTANTIVE_COLUMNS}
    set_["updated_at"] = sa.func.now()
    upsert = stmt.on_conflict_do_update(
        constraint="metric_definition_slug_version",
        set_=set_,
        where=sa.or_(
            *(table.c[column].is_distinct_from(excluded[column]) for column in SUBSTANTIVE_COLUMNS)
        ),
    ).returning(table.c.id, _INSERTED)
    written = session.execute(upsert).all()
    inserted = sum(1 for row in written if row.inserted)
    updated = len(written) - inserted
    return SyncResult(inserted=inserted, updated=updated, unchanged=len(rows) - len(written))
