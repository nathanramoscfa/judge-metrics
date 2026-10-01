# src/judgemetrics/metrics/adjustment/spec.py
"""The expected-outcome model specification (``data/reference/outcome_model.yaml``).

``load_spec`` reads the file once per process with ``yaml.safe_load`` and
validates it the way ``metrics.registry`` validates the metric registry:
every field is required or optional by name and an unknown field is
rejected; every target's population is a registry metric whose attribution
rule is the gate (``pretrial_decisions`` for the release target, the
windowed rates for the others); every feature names a builder the code
implements (``FEATURE_CONTRACTS``) and states that builder's kind, the frame
columns it reads, and its known-at instant, so the file cannot describe a
feature differently from what ``features.py`` computes; every fixed level is
checked against the case vocabulary. A feature that names a restricted
attribute — any value of the vocabulary's ``restricted_attribute`` kind, read
from the vocabulary so that no module under ``metrics/`` names one — or an
excluded variable or column is rejected first, with ``SpecError`` naming the
feature and the field.

The known-at instants (``KNOWN_AT``): ``filed_at`` is the index case's
filing (00:00 UTC of its filing date, the frame's ``cases.filed_at``), which
precedes every index event of the case and is the instant the synthetic
generator's risk index reads; ``decision_at`` is the pretrial decision of
the index event; ``index_at`` the index event itself. Every history feature
is evaluated at ``filed_at``.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from judgemetrics.config import REPO_ROOT
from judgemetrics.metrics.frame import SCHEMAS
from judgemetrics.metrics.registry import WINDOWS_DAYS, load_registry
from judgemetrics.normalization import vocabulary

DEFAULT_PATH = REPO_ROOT / "data" / "reference" / "outcome_model.yaml"

KINDS: tuple[str, ...] = ("categorical", "binary", "banded_count")
FILED_AT = "filed_at"
DECISION_AT = "decision_at"
INDEX_AT = "index_at"
KNOWN_AT: tuple[str, ...] = (FILED_AT, DECISION_AT, INDEX_AT)
EXCLUDE = "exclude"
LEVEL = "level"
MISSING_RULES: tuple[str, ...] = (EXCLUDE, LEVEL)
DECISION = "decision"
RELEASE = "release"
INDEX_KINDS: tuple[str, ...] = (DECISION, RELEASE)
RELEASED = "released"
DATA_LEVELS = "data"
MOST_FREQUENT = "most_frequent"
UNSEEN_REFERENCE = "reference"
UNSEEN_LATEST = "latest"
BINARY_LEVELS: tuple[str, ...] = ("false", "true")
RESTRICTED_KIND = "restricted_attribute"
NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
MODEL_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*$")

TOP_FIELDS: tuple[str, ...] = (
    "version",
    "model_version",
    "targets",
    "features",
    "excluded",
    "model",
    "temporal_split",
    "seed",
    "bootstrap",
    "pooling",
    "thresholds",
    "recovery",
)
TARGET_FIELDS: tuple[str, ...] = (
    "name",
    "description",
    "population",
    "index",
    "outcome",
    "windows_days",
)
FEATURE_REQUIRED: tuple[str, ...] = (
    "name",
    "description",
    "source",
    "kind",
    "reference",
    "known_at",
    "missing",
    "leakage",
)
FEATURE_OPTIONAL: tuple[str, ...] = (
    "vocabulary",
    "levels",
    "bands",
    "missing_level",
    "unseen",
    "lookback_days",
    "requires_outcome",
)
EXCLUSION_REQUIRED: tuple[str, ...] = ("name", "reason")
EXCLUSION_OPTIONAL: tuple[str, ...] = ("columns", "from_vocabulary")
MODEL_FIELDS: tuple[str, ...] = (
    "family",
    "penalty",
    "lambda",
    "penalize_intercept",
    "max_iterations",
    "tolerance",
    "step_halvings",
)
SPLIT_FIELDS: tuple[str, ...] = ("test_quantile", "quantile_method")
BOOTSTRAP_FIELDS: tuple[str, ...] = ("replicates", "cluster", "interval", "level")
POOLING_FIELDS: tuple[str, ...] = ("family", "shape_bounds", "shape_grid")
THRESHOLD_FIELDS: tuple[str, ...] = (
    "minimum_events_per_column",
    "minimum_cohort",
    "minimum_expected",
)
RECOVERY_FIELDS: tuple[str, ...] = (
    "fits",
    "minimum_followed_cohort",
    "spearman_minimum",
    "sign_agreement_above",
    "expected_correlation_minimum",
    "interval_coverage_minimum",
    "negative_control_band",
)


class SpecError(ValueError):
    """The specification file is missing, malformed, or states an invalid value."""


@dataclass(frozen=True, slots=True)
class FeatureContract:
    """What a feature builder in ``features.py`` computes: the spec must state the same.

    ``parameters`` are the optional fields the feature must carry (and the
    only ones it may carry beyond the levels and the missing rule);
    ``data_levels`` marks a feature whose levels are the data's (``levels:
    data``); ``ordered`` one whose data levels have a natural order, so an
    unseen level may be scored at the latest seen one.
    """

    kind: str
    known_at: str
    reads: frozenset[str]
    parameters: tuple[str, ...] = ()
    data_levels: bool = False
    ordered: bool = False


# The features the code implements, keyed by name (features.FEATURE_BUILDERS has the
# same keys). The spec states each one's kind, known-at instant, and frame columns.
FEATURE_CONTRACTS: Mapping[str, FeatureContract] = MappingProxyType(
    {
        "lead_severity": FeatureContract(
            "categorical", DECISION_AT, frozenset({"charges.filed_at", "charges.severity"})
        ),
        "lead_category": FeatureContract(
            "categorical",
            DECISION_AT,
            frozenset(
                {
                    "charges.filed_at",
                    "charges.offense_category",
                    "charges.severity",
                    "charges.source_row_id",
                }
            ),
        ),
        "charge_count": FeatureContract(
            "banded_count", DECISION_AT, frozenset({"charges.filed_at", "charges.id"})
        ),
        "prior_cases": FeatureContract(
            "banded_count",
            FILED_AT,
            frozenset({"cases.filed_at", "charges.case_id", "charges.person_id"}),
        ),
        "prior_convictions": FeatureContract(
            "banded_count",
            FILED_AT,
            frozenset(
                {
                    "cases.filed_at",
                    "charges.disposed_at",
                    "charges.disposition",
                    "charges.filed_at",
                }
            ),
        ),
        "prior_failures_to_appear": FeatureContract(
            "banded_count",
            FILED_AT,
            frozenset({"justice_events.event_at", "justice_events.event_type"}),
            parameters=("requires_outcome",),
        ),
        "pending_case": FeatureContract(
            "binary",
            FILED_AT,
            frozenset(
                {
                    "cases.filed_at",
                    "charges.disposed_at",
                    "charges.disposition",
                    "charges.filed_at",
                }
            ),
        ),
        "history_truncated": FeatureContract(
            "binary", FILED_AT, frozenset({"cases.filed_at"}), parameters=("lookback_days",)
        ),
        "court": FeatureContract(
            "categorical",
            FILED_AT,
            frozenset({"cases.court_id"}),
            parameters=("unseen",),
            data_levels=True,
        ),
        "jurisdiction": FeatureContract(
            "categorical",
            FILED_AT,
            frozenset({"courts.jurisdiction_id"}),
            parameters=("unseen",),
            data_levels=True,
        ),
        "calendar_year": FeatureContract(
            "categorical",
            INDEX_AT,
            frozenset({"decisions.decision_at", "decisions.release_at"}),
            parameters=("unseen",),
            data_levels=True,
            ordered=True,
        ),
    }
)


@dataclass(frozen=True, slots=True)
class TargetSpec:
    """One modelled outcome: its population (a registry metric), index, outcome, windows."""

    name: str
    description: str
    population: str
    index: str
    outcome: str
    windows_days: tuple[int, ...] | None

    @property
    def windows(self) -> tuple[int | None, ...]:
        """The windows one model is fitted per (``(None,)`` for the release target)."""
        return (None,) if self.windows_days is None else self.windows_days


def band_labels(bands: tuple[int, ...]) -> tuple[str, ...]:
    """The labels of a banded count's bands: ``0``, ``1``, ..., the last one open (``3+``)."""
    return tuple(
        f"{low}+" if position == len(bands) - 1 else str(low) for position, low in enumerate(bands)
    )


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    """One feature, validated against its builder's contract."""

    name: str
    description: str
    source: tuple[str, ...]
    kind: str
    reference: str
    known_at: str
    missing: str
    leakage: str
    levels: tuple[str, ...] | None = None
    data_levels: bool = False
    bands: tuple[int, ...] | None = None
    vocabulary: str | None = None
    missing_level: str | None = None
    unseen: str | None = None
    lookback_days: int | None = None
    requires_outcome: str | None = None

    @property
    def fixed_levels(self) -> tuple[str, ...]:
        """The specification's level order (empty for data levels), missing level last."""
        if self.data_levels:
            base: tuple[str, ...] = ()
        elif self.kind == "binary":
            base = BINARY_LEVELS
        elif self.kind == "banded_count":
            base = self.band_labels
        else:
            base = self.levels or ()
        return base if self.missing_level is None else (*base, self.missing_level)

    @property
    def band_labels(self) -> tuple[str, ...]:
        """``0``, ``1``, ..., the last band open (``3+``)."""
        return band_labels(self.bands or ())

    def band_of(self, value: int) -> str:
        """The label of the band ``value`` falls in (the largest lower bound at or below it)."""
        bands = self.bands or ()
        labels = self.band_labels
        chosen = labels[0]
        for low, label in zip(bands, labels, strict=True):
            if value >= low:
                chosen = label
        return chosen


@dataclass(frozen=True, slots=True)
class ExclusionSpec:
    """A variable the model must never read, with the reason Step 4 publishes."""

    name: str
    reason: str
    columns: tuple[str, ...] = ()
    from_vocabulary: str | None = None

    @property
    def names(self) -> tuple[str, ...]:
        """The excluded names: the entry's own and, for a vocabulary entry, its values."""
        if self.from_vocabulary is None:
            return (self.name,)
        return (self.name, *vocabulary.values(self.from_vocabulary))


@dataclass(frozen=True, slots=True)
class ModelSettings:
    family: str
    penalty: str
    lam: float
    penalize_intercept: bool
    max_iterations: int
    tolerance: float
    step_halvings: int


@dataclass(frozen=True, slots=True)
class SplitSpec:
    test_quantile: float
    quantile_method: str


@dataclass(frozen=True, slots=True)
class BootstrapSpec:
    replicates: int
    cluster: str
    interval: str
    level: float


@dataclass(frozen=True, slots=True)
class PoolingSpec:
    family: str
    shape_bounds: tuple[float, float]
    shape_grid: int


@dataclass(frozen=True, slots=True)
class ThresholdSpec:
    minimum_events_per_column: int
    minimum_cohort: int
    minimum_expected: float


@dataclass(frozen=True, slots=True)
class RecoveryFit:
    target: str
    window_days: int | None


@dataclass(frozen=True, slots=True)
class RecoverySpec:
    fits: tuple[RecoveryFit, ...]
    minimum_followed_cohort: int
    spearman_minimum: Mapping[str, float]
    sign_agreement_above: float
    expected_correlation_minimum: float
    interval_coverage_minimum: float
    negative_control_band: tuple[float, float]


@dataclass(frozen=True, slots=True)
class OutcomeModelSpec:
    """The loaded specification."""

    version: int
    model_version: str
    targets: tuple[TargetSpec, ...]
    features: tuple[FeatureSpec, ...]
    excluded: tuple[ExclusionSpec, ...]
    model: ModelSettings
    temporal_split: SplitSpec
    seed: int
    bootstrap: BootstrapSpec
    pooling: PoolingSpec
    thresholds: ThresholdSpec
    recovery: RecoverySpec
    path: Path

    def target(self, name: str) -> TargetSpec:
        for target in self.targets:
            if target.name == name:
                return target
        msg = f"the specification has no target {name!r}"
        raise SpecError(msg)

    def feature(self, name: str) -> FeatureSpec:
        for feature in self.features:
            if feature.name == name:
                return feature
        msg = f"the specification has no feature {name!r}"
        raise SpecError(msg)


# --- validation helpers ------------------------------------------------------------------


def _fail(where: str, field_name: str, problem: str) -> SpecError:
    return SpecError(f"{where}: field {field_name!r} {problem}")


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise SpecError(f"{where}: must be a mapping")
    return value


def _fields(
    block: Mapping[str, Any], where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> None:
    unknown = sorted(set(block) - set(required) - set(optional))
    if unknown:
        raise _fail(where, ", ".join(unknown), "is not a specification field")
    missing = [name for name in required if name not in block]
    if missing:
        raise _fail(where, ", ".join(missing), "is required")


def _string(block: Mapping[str, Any], where: str, field_name: str) -> str:
    value = block.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise _fail(where, field_name, "must be a non-empty string")
    return value.strip()


def _integer(value: Any, where: str, field_name: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise _fail(where, field_name, f"must be an integer >= {minimum}")
    return value


def _number(value: Any, where: str, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise _fail(where, field_name, "must be a number")
    return float(value)


def _choice(value: Any, where: str, field_name: str, allowed: tuple[str, ...]) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise _fail(where, field_name, f"must be one of {', '.join(allowed)}; got {value!r}")
    return value


def _string_list(value: Any, where: str, field_name: str) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or not all(isinstance(item, str) and item for item in value)
    ):
        raise _fail(where, field_name, "must be a non-empty list of strings")
    if len(set(value)) != len(value):
        raise _fail(where, field_name, "lists a value twice")
    return tuple(value)


def _frame_column(value: str, where: str, field_name: str) -> str:
    table, _, column = value.partition(".")
    if table not in SCHEMAS or column not in SCHEMAS[table]:
        raise _fail(where, field_name, f"{value!r} is not a column of the analytic frame")
    return value


def restricted_names() -> frozenset[str]:
    """Every restricted attribute the vocabulary lists (never spelled out in this package)."""
    return frozenset(vocabulary.values(RESTRICTED_KIND))


# --- blocks ---------------------------------------------------------------------------------


def parse_target(entry: Any) -> TargetSpec:
    block = _mapping(entry, "target")
    name = _string(block, "target", "name")
    where = f"target {name!r}"
    _fields(block, where, TARGET_FIELDS)
    if not NAME_PATTERN.match(name):
        raise _fail(where, "name", "must be snake_case")
    index = _choice(block["index"], where, "index", INDEX_KINDS)
    population = _string(block, where, "population")
    registry = load_registry()
    if population not in registry.metrics:
        raise _fail(where, "population", f"{population!r} is not a registry metric")
    metric = registry[population]
    outcome = _string(block, where, "outcome")
    windows = block["windows_days"]
    if index == DECISION:
        if metric.population != "pretrial_decisions":
            raise _fail(where, "population", "must be a metric over pretrial_decisions")
        if outcome != RELEASED:
            raise _fail(where, "outcome", f"must be {RELEASED!r} for a decision index")
        if windows is not None:
            raise _fail(where, "windows_days", "must be null for a decision index")
        return TargetSpec(
            name, _string(block, where, "description"), population, index, outcome, None
        )
    if not vocabulary.is_known("justice_event_type", outcome):
        raise _fail(where, "outcome", f"{outcome!r} is not a justice_event_type value")
    if (
        metric.kind != "windowed_rate"
        or metric.index_event != "pretrial_release"
        or metric.outcome != outcome
    ):
        raise _fail(
            where,
            "population",
            f"must be the pretrial-release windowed rate of {outcome!r}",
        )
    if (
        not isinstance(windows, list)
        or any(isinstance(item, bool) or not isinstance(item, int) for item in windows)
        or tuple(windows) != WINDOWS_DAYS
    ):
        raise _fail(where, "windows_days", f"must be the brief's windows {list(WINDOWS_DAYS)}")
    return TargetSpec(
        name, _string(block, where, "description"), population, index, outcome, tuple(windows)
    )


def _refuse_restricted(block: Mapping[str, Any], where: str) -> None:
    """A feature naming a restricted attribute anywhere is rejected before anything else."""
    restricted = restricted_names()
    name = block.get("name")
    if isinstance(name, str) and name in restricted:
        raise _fail(where, "name", f"{name!r} is a restricted attribute")
    kind = block.get("vocabulary")
    if isinstance(kind, str) and (kind in restricted or kind == RESTRICTED_KIND):
        raise _fail(where, "vocabulary", f"{kind!r} is a restricted attribute")
    source = block.get("source")
    for item in source if isinstance(source, list) else ():
        if isinstance(item, str) and restricted & set(re.split(r"[.]", item)):
            raise _fail(where, "source", f"{item!r} names a restricted attribute")


def _refuse_excluded(
    block: Mapping[str, Any], where: str, excluded: tuple[ExclusionSpec, ...]
) -> None:
    name = block.get("name")
    columns = {column for entry in excluded for column in entry.columns}
    for entry in excluded:
        if isinstance(name, str) and name in entry.names:
            raise _fail(where, "name", f"{name!r} is excluded ({entry.name})")
    source = block.get("source")
    for item in source if isinstance(source, list) else ():
        if item in columns:
            raise _fail(where, "source", f"{item!r} is an excluded column")


def _levels(block: Mapping[str, Any], where: str, contract: FeatureContract) -> dict[str, Any]:
    """The level fields of a feature, checked against its kind and the vocabulary."""
    kind = contract.kind
    levels = block.get("levels")
    bands = block.get("bands")
    vocabulary_kind = block.get("vocabulary")
    reference = block.get("reference")
    values: dict[str, Any] = {}
    if kind == "categorical":
        if bands is not None:
            raise _fail(where, "bands", "is only allowed on a banded_count")
        if contract.data_levels:
            if levels != DATA_LEVELS:
                raise _fail(where, "levels", f"must be {DATA_LEVELS!r} (the data's levels)")
            if vocabulary_kind is not None:
                raise _fail(where, "vocabulary", "is not allowed with data levels")
            if reference != MOST_FREQUENT:
                raise _fail(where, "reference", f"must be {MOST_FREQUENT!r} with data levels")
            unseen = _choice(
                block.get("unseen"),
                where,
                "unseen",
                (UNSEEN_REFERENCE, UNSEEN_LATEST) if contract.ordered else (UNSEEN_REFERENCE,),
            )
            values.update(data_levels=True, unseen=unseen, reference=MOST_FREQUENT)
            return values
        if not isinstance(vocabulary_kind, str) or vocabulary_kind not in vocabulary.kinds():
            raise _fail(where, "vocabulary", "must name a case vocabulary kind")
        fixed = _string_list(levels, where, "levels")
        listed = set(vocabulary.values(vocabulary_kind))
        if set(fixed) != listed:
            raise _fail(
                where,
                "levels",
                f"must list every {vocabulary_kind} value exactly once"
                f" (missing {sorted(listed - set(fixed))}, unknown {sorted(set(fixed) - listed)})",
            )
        if reference not in fixed:
            raise _fail(where, "reference", f"{reference!r} is not one of the levels")
        values.update(levels=fixed, vocabulary=vocabulary_kind, reference=reference)
        return values
    if levels is not None or vocabulary_kind is not None:
        raise _fail(where, "levels", f"is not allowed on a {kind}")
    if kind == "binary":
        if bands is not None:
            raise _fail(where, "bands", "is only allowed on a banded_count")
        if reference != BINARY_LEVELS[0]:
            raise _fail(where, "reference", f"must be {BINARY_LEVELS[0]!r} for a binary")
        values.update(reference=reference)
        return values
    if (
        not isinstance(bands, list)
        or not bands
        or any(isinstance(item, bool) or not isinstance(item, int) or item < 0 for item in bands)
        or any(later <= earlier for earlier, later in zip(bands, bands[1:], strict=False))
    ):
        raise _fail(where, "bands", "must be strictly increasing non-negative integers")
    labels = band_labels(tuple(bands))
    if reference not in labels:
        raise _fail(where, "reference", f"{reference!r} is not one of the bands {list(labels)}")
    values.update(bands=tuple(bands), reference=reference)
    return values


def parse_feature(entry: Any, excluded: tuple[ExclusionSpec, ...]) -> FeatureSpec:
    block = _mapping(entry, "feature")
    raw_name = block.get("name")
    where = f"feature {raw_name!r}"
    _refuse_restricted(block, where)
    _refuse_excluded(block, where, excluded)
    _fields(block, where, FEATURE_REQUIRED, FEATURE_OPTIONAL)
    name = _string(block, where, "name")
    contract = FEATURE_CONTRACTS.get(name)
    if contract is None:
        raise _fail(where, "name", "is not a feature the model implements")
    kind = _choice(block["kind"], where, "kind", KINDS)
    if kind != contract.kind:
        raise _fail(where, "kind", f"must be {contract.kind!r} (what the builder computes)")
    known_at = _choice(block["known_at"], where, "known_at", KNOWN_AT)
    if known_at != contract.known_at:
        raise _fail(where, "known_at", f"must be {contract.known_at!r} (what the builder reads)")
    source = tuple(
        _frame_column(item, where, "source")
        for item in _string_list(block["source"], where, "source")
    )
    if set(source) != contract.reads:
        raise _fail(where, "source", f"must list exactly {sorted(contract.reads)}")
    level_fields = _levels(block, where, contract)
    if not contract.data_levels and "unseen" in block:
        raise _fail(where, "unseen", "is only allowed with data levels")
    missing = _choice(block["missing"], where, "missing", MISSING_RULES)
    missing_level: str | None = None
    if missing == LEVEL:
        missing_level = _string(block, where, "missing_level")
        labels = set(
            level_fields.get("levels") or band_labels(level_fields.get("bands") or ())
        ) | set(BINARY_LEVELS)
        # Data levels are ranks and years: a label of digits could collide with one.
        if missing_level in labels or missing_level.isdigit():
            raise _fail(where, "missing_level", "must differ from every level")
    elif "missing_level" in block:
        raise _fail(where, "missing_level", "is only allowed with missing: level")
    for parameter in ("lookback_days", "requires_outcome"):
        if parameter in contract.parameters and parameter not in block:
            raise _fail(where, parameter, "is required for this feature")
        if parameter not in contract.parameters and parameter in block:
            raise _fail(where, parameter, "is not a parameter of this feature")
    lookback = (
        _integer(block["lookback_days"], where, "lookback_days", minimum=1)
        if "lookback_days" in block
        else None
    )
    requires = block.get("requires_outcome")
    if requires is not None and (
        not isinstance(requires, str) or not vocabulary.is_known("justice_event_type", requires)
    ):
        raise _fail(where, "requires_outcome", "must be a justice_event_type value")
    return FeatureSpec(
        name=name,
        description=_string(block, where, "description"),
        source=source,
        kind=kind,
        known_at=known_at,
        missing=missing,
        missing_level=missing_level,
        leakage=_string(block, where, "leakage"),
        lookback_days=lookback,
        requires_outcome=requires,
        **level_fields,
    )


def parse_exclusion(entry: Any) -> ExclusionSpec:
    block = _mapping(entry, "excluded entry")
    name = _string(block, "excluded entry", "name")
    where = f"excluded entry {name!r}"
    _fields(block, where, EXCLUSION_REQUIRED, EXCLUSION_OPTIONAL)
    columns: tuple[str, ...] = ()
    if "columns" in block:
        columns = tuple(
            _frame_column(item, where, "columns")
            for item in _string_list(block["columns"], where, "columns")
        )
    source = block.get("from_vocabulary")
    if source is not None and (not isinstance(source, str) or source not in vocabulary.kinds()):
        raise _fail(where, "from_vocabulary", "must name a case vocabulary kind")
    return ExclusionSpec(
        name=name, reason=_string(block, where, "reason"), columns=columns, from_vocabulary=source
    )


def parse_model(value: Any) -> ModelSettings:
    block = _mapping(value, "model")
    _fields(block, "model", MODEL_FIELDS)
    lam = _number(block["lambda"], "model", "lambda")
    tolerance = _number(block["tolerance"], "model", "tolerance")
    if lam < 0:
        raise _fail("model", "lambda", "must be >= 0")
    if tolerance <= 0:
        raise _fail("model", "tolerance", "must be > 0")
    if block["penalize_intercept"] is not False:
        raise _fail("model", "penalize_intercept", "must be false (the intercept is unpenalized)")
    return ModelSettings(
        family=_choice(block["family"], "model", "family", ("logistic",)),
        penalty=_choice(block["penalty"], "model", "penalty", ("l2",)),
        lam=lam,
        penalize_intercept=False,
        max_iterations=_integer(block["max_iterations"], "model", "max_iterations", minimum=1),
        tolerance=tolerance,
        step_halvings=_integer(block["step_halvings"], "model", "step_halvings"),
    )


def parse_split(value: Any) -> SplitSpec:
    block = _mapping(value, "temporal_split")
    _fields(block, "temporal_split", SPLIT_FIELDS)
    quantile = _number(block["test_quantile"], "temporal_split", "test_quantile")
    if not 0.0 < quantile < 1.0:
        raise _fail("temporal_split", "test_quantile", "must lie strictly between 0 and 1")
    method = _choice(
        block["quantile_method"], "temporal_split", "quantile_method", ("nearest_rank",)
    )
    return SplitSpec(test_quantile=quantile, quantile_method=method)


def parse_bootstrap(value: Any) -> BootstrapSpec:
    block = _mapping(value, "bootstrap")
    _fields(block, "bootstrap", BOOTSTRAP_FIELDS)
    level = _number(block["level"], "bootstrap", "level")
    if not 0.0 < level < 1.0:
        raise _fail("bootstrap", "level", "must lie strictly between 0 and 1")
    return BootstrapSpec(
        replicates=_integer(block["replicates"], "bootstrap", "replicates", minimum=1),
        cluster=_choice(block["cluster"], "bootstrap", "cluster", ("person",)),
        interval=_choice(block["interval"], "bootstrap", "interval", ("percentile",)),
        level=level,
    )


def parse_pooling(value: Any) -> PoolingSpec:
    block = _mapping(value, "pooling")
    _fields(block, "pooling", POOLING_FIELDS)
    bounds = block["shape_bounds"]
    if (
        not isinstance(bounds, list)
        or len(bounds) != 2
        or not all(isinstance(b, int | float) and not isinstance(b, bool) for b in bounds)
        or not 0 < bounds[0] < bounds[1]
    ):
        raise _fail("pooling", "shape_bounds", "must be [low, high] with 0 < low < high")
    return PoolingSpec(
        family=_choice(block["family"], "pooling", "family", ("gamma_poisson",)),
        shape_bounds=(float(bounds[0]), float(bounds[1])),
        shape_grid=_integer(block["shape_grid"], "pooling", "shape_grid", minimum=2),
    )


def parse_thresholds(value: Any) -> ThresholdSpec:
    block = _mapping(value, "thresholds")
    _fields(block, "thresholds", THRESHOLD_FIELDS)
    expected = _number(block["minimum_expected"], "thresholds", "minimum_expected")
    if expected < 0:
        raise _fail("thresholds", "minimum_expected", "must be >= 0")
    return ThresholdSpec(
        minimum_events_per_column=_integer(
            block["minimum_events_per_column"], "thresholds", "minimum_events_per_column"
        ),
        minimum_cohort=_integer(block["minimum_cohort"], "thresholds", "minimum_cohort"),
        minimum_expected=expected,
    )


def _unit(value: Any, where: str, field_name: str, low: float = 0.0) -> float:
    number = _number(value, where, field_name)
    if not low <= number <= 1.0:
        raise _fail(where, field_name, f"must lie in [{low:g}, 1]")
    return number


def parse_recovery(value: Any, targets: tuple[TargetSpec, ...]) -> RecoverySpec:
    block = _mapping(value, "recovery")
    _fields(block, "recovery", RECOVERY_FIELDS)
    by_name = {target.name: target for target in targets}
    raw_fits = block["fits"]
    if not isinstance(raw_fits, list) or not raw_fits:
        raise _fail("recovery", "fits", "must be a non-empty list")
    fits: list[RecoveryFit] = []
    for entry in raw_fits:
        fit = _mapping(entry, "recovery fit")
        _fields(fit, "recovery fit", ("target", "window_days"))
        target = by_name.get(str(fit["target"]))
        if target is None:
            raise _fail("recovery", "fits", f"{fit['target']!r} is not a target")
        window = fit["window_days"]
        if window not in target.windows:
            raise _fail("recovery", "fits", f"{window!r} is not a window of {target.name}")
        fits.append(RecoveryFit(target=target.name, window_days=window))
    minima = _mapping(block["spearman_minimum"], "recovery.spearman_minimum")
    if set(minima) != {fit.target for fit in fits}:
        raise _fail("recovery", "spearman_minimum", "must name exactly the fitted targets")
    band = block["negative_control_band"]
    if (
        not isinstance(band, list)
        or len(band) != 2
        or not all(isinstance(b, int | float) and not isinstance(b, bool) for b in band)
        or not 0 < band[0] <= 1 <= band[1]
    ):
        raise _fail("recovery", "negative_control_band", "must be [low, high] around 1")
    return RecoverySpec(
        fits=tuple(fits),
        minimum_followed_cohort=_integer(
            block["minimum_followed_cohort"], "recovery", "minimum_followed_cohort"
        ),
        spearman_minimum=MappingProxyType(
            {
                str(name): _unit(minimum, "recovery", "spearman_minimum", low=-1.0)
                for name, minimum in minima.items()
            }
        ),
        sign_agreement_above=_number(
            block["sign_agreement_above"], "recovery", "sign_agreement_above"
        ),
        expected_correlation_minimum=_unit(
            block["expected_correlation_minimum"], "recovery", "expected_correlation_minimum", -1.0
        ),
        interval_coverage_minimum=_unit(
            block["interval_coverage_minimum"], "recovery", "interval_coverage_minimum"
        ),
        negative_control_band=(float(band[0]), float(band[1])),
    )


def parse_spec(payload: Any, path: Path) -> OutcomeModelSpec:
    """Validate a loaded YAML payload into an ``OutcomeModelSpec``."""
    if not isinstance(payload, dict):
        raise SpecError(f"{path}: expected a mapping at the top level")
    _fields(payload, str(path), TOP_FIELDS)
    version = _integer(payload["version"], str(path), "version", minimum=1)
    model_version = _string(payload, str(path), "model_version")
    if not MODEL_VERSION_PATTERN.match(model_version):
        raise _fail(str(path), "model_version", "must be lowercase letters, digits, dots, dashes")
    raw_targets = payload["targets"]
    if not isinstance(raw_targets, list) or not raw_targets:
        raise _fail(str(path), "targets", "must be a non-empty list")
    targets = tuple(parse_target(entry) for entry in raw_targets)
    if len({target.name for target in targets}) != len(targets):
        raise _fail(str(path), "targets", "lists a target twice")
    raw_excluded = payload["excluded"]
    if not isinstance(raw_excluded, list) or not raw_excluded:
        raise _fail(str(path), "excluded", "must be a non-empty list")
    excluded = tuple(parse_exclusion(entry) for entry in raw_excluded)
    if not any(entry.from_vocabulary == RESTRICTED_KIND for entry in excluded):
        raise _fail(str(path), "excluded", f"must exclude the {RESTRICTED_KIND} vocabulary")
    raw_features = payload["features"]
    if not isinstance(raw_features, list) or not raw_features:
        raise _fail(str(path), "features", "must be a non-empty list")
    features = tuple(parse_feature(entry, excluded) for entry in raw_features)
    if len({feature.name for feature in features}) != len(features):
        raise _fail(str(path), "features", "lists a feature twice")
    return OutcomeModelSpec(
        version=version,
        model_version=model_version,
        targets=targets,
        features=features,
        excluded=excluded,
        model=parse_model(payload["model"]),
        temporal_split=parse_split(payload["temporal_split"]),
        seed=_integer(payload["seed"], str(path), "seed"),
        bootstrap=parse_bootstrap(payload["bootstrap"]),
        pooling=parse_pooling(payload["pooling"]),
        thresholds=parse_thresholds(payload["thresholds"]),
        recovery=parse_recovery(payload["recovery"], targets),
        path=path,
    )


@lru_cache(maxsize=4)
def load_spec(path: Path = DEFAULT_PATH) -> OutcomeModelSpec:
    """The specification at ``path`` (``yaml.safe_load``), validated; cached per path."""
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise SpecError(f"cannot read the outcome model specification at {path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise SpecError(f"{path}: not valid YAML ({exc.__class__.__name__})") from exc
    return parse_spec(payload, path)
