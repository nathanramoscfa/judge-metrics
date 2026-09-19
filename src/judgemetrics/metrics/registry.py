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
from dataclasses import dataclass
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
KINDS: tuple[str, ...] = ("count", "share", "windowed_rate", "survival", "distribution", "median")
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
    "court_of_case",
)
INDEX_EVENTS: tuple[str, ...] = ("pretrial_release", "disposition", "sentence")
DIMENSIONS: tuple[str, ...] = ("disposition", "offense_category")
UNITS: tuple[str, ...] = ("count", "share", "days")
MEASURES: tuple[str, ...] = ("days_to_disposition", "incarceration_days", "probation_days")
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
OPTIONAL_FIELDS: tuple[str, ...] = ("counted", "measure", "truth_note")
ATTRIBUTION_FIELDS: tuple[str, ...] = (
    "decision_type",
    "actor_types",
    "discretion",
    "assignment_gate",
)


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

    @property
    def is_windowed(self) -> bool:
        return self.kind in WINDOWED_KINDS

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
class SuppressionSpec:
    default_threshold: int
    rule: str
    rationale: str


@dataclass(frozen=True, slots=True)
class Registry:
    """The loaded registry: versions, the brief's warnings, suppression, metrics by slug."""

    version: int
    methodology_version: str
    known_limitations: tuple[str, ...]
    suppression: SuppressionSpec
    metrics: Mapping[str, MetricDefinitionSpec]
    path: Path

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
    if kind in WINDOWED_KINDS:
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
    return MetricDefinitionSpec(
        slug=slug,
        name=_string(entry, slug, "name"),
        kind=kind,
        subject_types=_subject_types(entry["subject_types"], slug),
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
        unit=_choice(entry["unit"], slug, "unit", UNITS),
        version=_string(entry, slug, "version"),
        counted=_counted(entry, slug),
        measure=measure,
        truth_note=_optional_string(entry, slug, "truth_note"),
    )


def parse_registry(payload: Any, path: Path) -> Registry:
    """Validate a loaded YAML payload into a ``Registry``."""
    if not isinstance(payload, dict):
        raise RegistryError(f"{path}: expected a mapping at the top level")
    for name in ("version", "methodology_version", "known_limitations", "suppression", "metrics"):
        if name not in payload:
            raise RegistryError(f"{path}: `{name}` is required")
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
    suppression_spec = SuppressionSpec(
        default_threshold=threshold,
        rule=_string(suppression, None, "rule"),
        rationale=_string(suppression, None, "rationale"),
    )
    entries = payload["metrics"]
    if not isinstance(entries, list) or not entries:
        raise RegistryError(f"{path}: `metrics` must be a non-empty list")
    metrics: dict[str, MetricDefinitionSpec] = {}
    for entry in entries:
        metric = parse_metric(entry)
        if metric.slug in metrics:
            raise _fail(metric.slug, "slug", "is listed twice")
        metrics[metric.slug] = metric
    return Registry(
        version=version,
        methodology_version=methodology_version,
        known_limitations=tuple(item.strip() for item in limitations),
        suppression=suppression_spec,
        metrics=MappingProxyType(metrics),
        path=path,
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
