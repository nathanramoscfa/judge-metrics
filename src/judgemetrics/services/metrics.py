# src/judgemetrics/services/metrics.py
"""Metric responses: the registry, a subject's observations, the compare table, and
the provenance chain of one observation.

Every ``Observation`` is built by ``observation_from_row`` from one joined
row (the observation, its definition, its source, its snapshot hash, and
the outcome model it cites): ``numerator`` is ``observed_count``,
``denominator`` is ``cohort_size``, ``rate`` is ``observed_rate``, the
figures of an ``observed_expected`` row are mapped by ``figures`` (``expected``
from ``expected_count``, ``ratio`` from ``standardized_ratio``, its bootstrap
interval from the two bounds into ``ratio_lower``/``ratio_upper`` while
``lower``/``upper`` stay null), the interval method follows the kind, the
coverage block comes from the source, and the methodology link is
``Settings.methodology_url_for(slug)``. Suppression is applied by the
schema itself (``schemas.metrics.SuppressibleFigures``), so this module
never decides what to withhold. The registry response is built from
``metrics.registry.load_registry`` alone — no database — plus the
methodology prose constants of ``metrics.methodology`` (how to read a
number, the index-event semantics, the attribution notes, the changelog,
and — methodology 1.0 — the adjusted statistics' prose from
``adjustment_prose``), so the web methodology page shows the text
``docs/METHODOLOGY.md`` is rendered from rather than a second copy. The compare
service validates the metric and window against the registry before any
query and turns ``repositories.metrics.compare_page`` rows into
``CompareRow``s with their ``coverage_warning``. The provenance service
runs ``metrics.provenance.trace`` and maps the chain onto
``ObservationProvenance``, answering ``None`` (a 404) for an unknown or
superseded observation and withholding the snapshot's storage URI and any
non-public artifact URI the way ``raw_object_path`` is never returned.

``SERVED_KINDS`` is every kind a public metrics response carries. Phase 4
Step 3 held ``observed_expected`` out of it (the registry response, the
subject statements, compare, and the provenance route all filter by it in
SQL with bound parameters) until methodology 1.0 published the estimator's
validation; Phase 4 Step 5 serves it with its schema, so the set is every
registry kind and the filters stay as the place a future kind is held out.
The compare route sorts an adjusted metric by its pooled ratio unless asked
otherwise (``default_sort``), and the provenance trace of an adjusted
observation checks its model's artifact under the configured snapshot
directory (``settings``), naming the model in the body. ``model_card`` is the
model card of ``GET /models/{id}`` (docs/API.md "Models").
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Row
from sqlalchemy.orm import Session

from judgemetrics.api import API_PREFIX
from judgemetrics.api.errors import ApiError
from judgemetrics.config import Settings
from judgemetrics.metrics.methodology import (
    ATTRIBUTION_TEXT,
    CHANGELOG,
    GATE_TEXT,
    HOW_TO_READ,
    SEMANTICS,
    adjustment_prose,
)
from judgemetrics.metrics.provenance import TracedModel, TraceError, trace
from judgemetrics.metrics.registry import (
    OBSERVED_EXPECTED,
    WINDOWS_DAYS,
    MetricDefinitionSpec,
    Registry,
    load_registry,
)
from judgemetrics.repositories.metrics import (
    CompareSortKey,
    compare_page,
    get_subject,
    subject_observations,
)
from judgemetrics.repositories.models import model_card_row
from judgemetrics.schemas.judges import CourtRef
from judgemetrics.schemas.metrics import (
    AdjustmentFeatureOut,
    AdjustmentOut,
    AttributionOut,
    CalibrationBinOut,
    CoefficientOut,
    CompareCohort,
    ComparePage,
    CompareRow,
    DefinitionAdjustmentOut,
    MemberGroup,
    MethodologyChange,
    MethodologyTerm,
    MetricDefinitionOut,
    ModelCard,
    ModelRef,
    ModelValidationOut,
    Observation,
    ObservationCoverage,
    ObservationProvenance,
    ProvenanceModel,
    SnapshotOut,
    SourceOut,
    SourceRecordOut,
    SubjectMetrics,
    SubjectSummary,
    SuppressionOut,
    TracedObservation,
    TrainingOut,
    interval_method_for,
)
from judgemetrics.schemas.metrics import Registry as RegistryOut

# The registry kinds a public metrics response serves (see the module docstring).
SERVED_KINDS: frozenset[str] = frozenset(
    {"count", "share", "windowed_rate", "survival", "distribution", "median", OBSERVED_EXPECTED}
)
# The methodology section the model card links to.
ADJUSTED_ANCHOR = "adjusted-statistics"


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _observable(outcome: str | None, observable_outcomes: Any) -> bool:
    if outcome is None:
        return True
    return outcome in {str(item) for item in (observable_outcomes or [])}


def model_url(model_id: uuid.UUID) -> str:
    """The model card's API path."""
    return f"{API_PREFIX}/models/{model_id}"


def figures(
    kind: str,
    *,
    observed_count: Any,
    cohort_size: Any,
    observed_rate: Any,
    value: Any,
    distribution: Any,
    lower: Any,
    upper: Any,
    expected_count: Any = None,
    expected_rate: Any = None,
    standardized_ratio: Any = None,
    pooling_weight: Any = None,
) -> dict[str, Any]:
    """The stored columns → the suppressible figures of the response, by kind.

    An adjusted ratio's two stored bounds are the pooled ratio's bootstrap
    interval (``ratio_lower``/``ratio_upper``, unbounded above), never the
    ``lower``/``upper`` of a share; every adjusted field is null for a
    descriptive kind. Suppression is the schema's business.
    """
    adjusted = kind == OBSERVED_EXPECTED
    return {
        "numerator": int(observed_count),
        "denominator": int(cohort_size),
        "rate": _float(observed_rate),
        "value": _float(value),
        "distribution": (
            None
            if distribution is None
            else {str(k): int(v) for k, v in dict(distribution).items()}
        ),
        "lower": None if adjusted else _float(lower),
        "upper": None if adjusted else _float(upper),
        "expected": _float(expected_count) if adjusted else None,
        "expected_rate": _float(expected_rate) if adjusted else None,
        "ratio": _float(standardized_ratio) if adjusted else None,
        "ratio_lower": _float(lower) if adjusted else None,
        "ratio_upper": _float(upper) if adjusted else None,
        "pooling_weight": _float(pooling_weight) if adjusted else None,
    }


def model_ref(row: Row[Any]) -> ModelRef | None:
    """The cited model of a joined row (``repositories.metrics``), or ``None``."""
    if row.model_id is None:
        return None
    return ModelRef(
        id=row.model_id,
        content_hash=str(row.model_hash),
        model_version=str(row.model_version),
        spec_version=int(row.model_spec_version),
        url=model_url(row.model_id),
    )


# --- the registry ---------------------------------------------------------------------------


def definition_out(definition: MetricDefinitionSpec, settings: Settings) -> MetricDefinitionOut:
    return MetricDefinitionOut(
        slug=definition.slug,
        name=definition.name,
        kind=definition.kind,
        subject_types=list(definition.subject_types),
        description=definition.description,
        numerator=definition.numerator,
        denominator=definition.denominator,
        eligibility=definition.eligibility,
        attribution=AttributionOut(**definition.attribution.as_dict()),
        index_event=definition.index_event,
        outcome=definition.outcome,
        windows_days=None if definition.windows_days is None else list(definition.windows_days),
        dimension=definition.dimension,
        suppression_threshold=definition.suppression_threshold,
        unit=definition.unit,
        version=definition.version,
        methodology_url=settings.methodology_url_for(definition.slug),
        adjustment=(
            None
            if definition.adjustment is None
            else DefinitionAdjustmentOut(
                target=definition.adjustment.target,
                minimum_expected=definition.adjustment.minimum_expected,
            )
        ),
    )


def adjustment_out(registry: Registry) -> AdjustmentOut:
    """The adjusted statistics' methodology from ``metrics.methodology.adjustment_prose``."""
    prose = adjustment_prose(registry=registry)

    def terms(items: tuple[tuple[str, str], ...]) -> list[MethodologyTerm]:
        return [MethodologyTerm(term=term, text=text) for term, text in items]

    return AdjustmentOut(
        specification_version=prose.specification_version,
        model_version=prose.model_version,
        intro=prose.intro,
        interpretation=prose.interpretation,
        model=prose.model,
        targets=terms(prose.targets),
        features=[
            AdjustmentFeatureOut(
                name=feature.name,
                description=feature.description,
                levels=feature.levels,
                known_at=feature.known_at,
                missing=feature.missing,
                leakage=feature.leakage,
            )
            for feature in prose.features
        ],
        exclusions=terms(prose.exclusions),
        expected_count=prose.expected_count,
        pooling=prose.pooling,
        interval=prose.interval,
        thresholds=terms(prose.thresholds),
        controls=terms(prose.controls),
        limitations=list(prose.limitations),
        validation=prose.validation,
    )


def registry_response(settings: Settings, registry: Registry | None = None) -> RegistryOut:
    """The registry as the API serves it: definitions, versions, thresholds, known limitations."""
    registry = registry or load_registry()
    return RegistryOut(
        registry_version=registry.version,
        methodology_version=registry.methodology_version,
        methodology_url=settings.methodology_url,
        windows_days=list(WINDOWS_DAYS),
        known_limitations=list(registry.known_limitations),
        suppression=SuppressionOut(
            default_threshold=registry.suppression.default_threshold,
            rule=registry.suppression.rule,
            rationale=registry.suppression.rationale,
        ),
        how_to_read=[MethodologyTerm(term=term, text=text) for term, text in HOW_TO_READ],
        semantics=[MethodologyTerm(term=term, text=text) for term, text in SEMANTICS],
        attribution_notes=list(ATTRIBUTION_TEXT),
        gate_descriptions=dict(GATE_TEXT),
        changelog=[MethodologyChange(version=version, text=text) for version, text in CHANGELOG],
        adjustment=adjustment_out(registry),
        definitions=[
            definition_out(item, settings)
            for item in registry.metrics.values()
            if item.kind in SERVED_KINDS
        ],
    )


# --- observations ---------------------------------------------------------------------------


def observation_from_row(row: Row[Any], settings: Settings) -> Observation:
    """One joined repository row → the presentation shape (suppression applied by the schema)."""
    observation = row[0]
    kind = str(row.kind)
    return Observation(
        id=observation.id,
        slug=str(row.slug),
        name=str(row.name),
        kind=kind,
        unit=str(row.unit),
        version=str(row.definition_version),
        subject_type=observation.subject_type.value,
        subject_id=observation.subject_id,
        source=str(row.source_name),
        synthetic=bool(row.synthetic),
        period_start=observation.period_start,
        period_end=observation.period_end,
        window_days=observation.window_days,
        dimension_value=observation.dimension_value,
        eligible_count=int(observation.eligible_count),
        **figures(
            kind,
            observed_count=observation.observed_count,
            cohort_size=observation.cohort_size,
            observed_rate=observation.observed_rate,
            value=observation.value,
            distribution=observation.distribution,
            lower=observation.lower_confidence_bound,
            upper=observation.upper_confidence_bound,
            expected_count=observation.expected_count,
            expected_rate=observation.expected_rate,
            standardized_ratio=observation.standardized_ratio,
            pooling_weight=observation.pooling_weight,
        ),
        model=model_ref(row),
        interval_method=interval_method_for(kind),
        suppressed=bool(observation.suppressed_flag),
        suppression_threshold=int(row.suppression_threshold),
        suppression_reason=observation.suppression_reason,
        coverage=ObservationCoverage(
            coverage_start=row.coverage_start,
            coverage_end=row.coverage_end,
            observable=_observable(row.outcome, row.observable_outcomes),
        ),
        methodology_version=str(observation.methodology_version),
        methodology_url=settings.methodology_url_for(str(row.slug)),
        snapshot_hash=str(row.snapshot_hash),
        computed_at=observation.computed_at,
    )


def subject_metrics(
    session: Session, settings: Settings, subject_type: str, subject_id: uuid.UUID
) -> SubjectMetrics | None:
    """Every current observation of the subject grouped by slug, or ``None`` when it does not exist.

    Two statements: the subject, then its observations.
    """
    subject = get_subject(session, subject_type, subject_id)
    if subject is None:
        return None
    registry = load_registry()
    grouped: dict[str, list[Observation]] = {}
    total = 0
    for row in subject_observations(session, subject_type, subject_id, kinds=SERVED_KINDS):
        item = observation_from_row(row, settings)
        grouped.setdefault(item.slug, []).append(item)
        total += 1
    return SubjectMetrics(
        subject=SubjectSummary(
            subject_type=subject.subject_type,
            id=subject.id,
            canonical_name=subject.canonical_name,
            synthetic=subject.synthetic,
        ),
        registry_version=registry.version,
        methodology_version=registry.methodology_version,
        methodology_url=settings.methodology_url,
        total=total,
        observations=grouped,
    )


# --- compare ---------------------------------------------------------------------------------


def _validation_error(message: str) -> ApiError:
    return ApiError(status_code=422, code="validation_error", message=message)


def validate_compare_metric(
    registry: Registry, slug: str, window_days: int | None
) -> MetricDefinitionSpec:
    """The registry entry for ``slug`` once ``window_days`` fits its kind, else a 422.

    A metric of a kind the API does not serve is answered as unknown.
    """
    definition = registry.metrics.get(slug)
    if definition is None or definition.kind not in SERVED_KINDS:
        raise _validation_error(f"metric: {slug!r} is not a registry metric")
    if "judge" not in definition.subject_types:
        raise _validation_error(f"metric: {slug!r} has no judge-level observations")
    if definition.windows_days is None:
        if window_days is not None:
            raise _validation_error(f"window: {slug!r} has no follow-up windows")
    elif window_days is None:
        raise _validation_error(
            f"window: required for {slug!r}; one of {list(definition.windows_days)}"
        )
    elif window_days not in definition.windows_days:
        raise _validation_error(
            f"window: {window_days} is not one of {list(definition.windows_days)} for {slug!r}"
        )
    return definition


def default_sort(definition: MetricDefinitionSpec) -> CompareSortKey:
    """The figure a metric's compare table is ordered by when no sort is asked for."""
    return "ratio" if definition.kind == OBSERVED_EXPECTED else "rate"


def _coverage_warning(
    row: Row[Any], definition: MetricDefinitionSpec, reference: tuple[date, date] | None
) -> str | None:
    warnings: list[str] = []
    if reference is not None and (row.period_start, row.period_end) != reference:
        warnings.append(
            f"coverage window {row.period_start} to {row.period_end} differs from the "
            f"cohort's {reference[0]} to {reference[1]}"
        )
    if not _observable(definition.outcome, row.observable_outcomes):
        warnings.append(
            f"outcome {definition.outcome} is not observable in source {row.source_name}"
        )
    return "; ".join(warnings) or None


def compare(
    session: Session,
    settings: Settings,
    *,
    slug: str,
    window_days: int | None,
    court_id: uuid.UUID | None,
    jurisdiction_id: uuid.UUID | None,
    period_start: date | None,
    period_end: date | None,
    sort: CompareSortKey | None,
    order: str,
    limit: int,
    offset: int,
) -> ComparePage | None:
    """One metric, one window, one cohort: sorted, paginated; ``None`` when the cohort is unknown.

    ``sort=None`` is the metric's ``default_sort`` (the pooled ratio for an adjusted metric).
    """
    registry = load_registry()
    definition = validate_compare_metric(registry, slug, window_days)
    sort = sort or default_sort(definition)
    page = compare_page(
        session,
        slug=definition.slug,
        version=definition.version,
        kinds=SERVED_KINDS,
        window_days=window_days,
        court_id=court_id,
        jurisdiction_id=jurisdiction_id,
        period_start=period_start,
        period_end=period_end,
        sort=sort,
        descending=order == "desc",
        limit=limit,
        offset=offset,
    )
    if page is None:
        return None
    reference: tuple[date, date] | None = None
    if period_start is not None and period_end is not None:
        reference = (period_start, period_end)
    elif page.rows:
        reference = (page.rows[0].cohort_start, page.rows[0].cohort_end)
    items = [
        CompareRow(
            subject_id=row.judge_id,
            name=str(row.judge_name),
            court=CourtRef(
                id=row.court_id, canonical_name=str(row.court_name), court_type=str(row.court_type)
            ),
            synthetic=bool(row.synthetic),
            observation_id=row.observation_id,
            source=str(row.source_name),
            period_start=row.period_start,
            period_end=row.period_end,
            window_days=row.window_days,
            dimension_value=row.dimension_value,
            eligible_count=int(row.eligible_count),
            **figures(
                definition.kind,
                observed_count=row.observed_count,
                cohort_size=row.cohort_size,
                observed_rate=row.observed_rate,
                value=row.value,
                distribution=row.distribution,
                lower=row.lower_confidence_bound,
                upper=row.upper_confidence_bound,
                expected_count=row.expected_count,
                expected_rate=row.expected_rate,
                standardized_ratio=row.standardized_ratio,
                pooling_weight=row.pooling_weight,
            ),
            model=model_ref(row),
            interval_method=interval_method_for(definition.kind),
            suppressed=bool(row.suppressed_flag),
            suppression_threshold=int(row.suppression_threshold),
            suppression_reason=row.suppression_reason,
            coverage_warning=_coverage_warning(row, definition, reference),
        )
        for row in page.rows
    ]
    cohort = CompareCohort(
        metric=definition.slug,
        version=definition.version,
        window_days=window_days,
        court_id=page.cohort.court_id,
        jurisdiction_id=page.cohort.jurisdiction_id,
        name=page.cohort.name,
        period_start=None if reference is None else reference[0],
        period_end=None if reference is None else reference[1],
        sort=sort,
        order=order,
    )
    following = offset + limit
    return ComparePage(
        items=items,
        total=page.total,
        limit=limit,
        offset=offset,
        next_offset=following if following < page.total else None,
        cohort=cohort,
        methodology_version=registry.methodology_version,
        methodology_url=settings.methodology_url_for(definition.slug),
    )


# --- provenance ---------------------------------------------------------------------------


def _model_ref(model: TracedModel) -> ModelRef:
    return ModelRef(
        id=model.id,
        content_hash=model.content_hash,
        model_version=model.model_version,
        spec_version=model.spec_version,
        url=model_url(model.id),
    )


def _provenance_model(model: TracedModel) -> ProvenanceModel:
    return ProvenanceModel(
        **_model_ref(model).model_dump(),
        target=model.target,
        window_days=model.window_days,
        status=model.status,
        training=TrainingOut(
            index_events=model.index_events,
            events=model.events,
            start=model.train_start,
            end=model.train_end,
        ),
        artifact_ok=model.artifact_ok,
    )


def observation_provenance(
    session: Session, settings: Settings, observation_id: uuid.UUID
) -> ObservationProvenance | None:
    """The chain behind a current observation of a served kind, else ``None`` (a 404).

    ``settings`` locate an adjusted observation's model artifact, which the
    chain's ``complete`` requires.
    """
    try:
        traced = trace(session, observation_id, settings=settings, kinds=SERVED_KINDS)
    except TraceError:
        return None
    if traced.observation.superseded_at is not None:
        return None
    o = traced.observation
    # The trace always lists the observation's own source first.
    own_source = next(s for s in traced.sources if s.source == o.source)
    observation = TracedObservation(
        id=o.id,
        slug=o.slug,
        name=o.name,
        kind=o.kind,
        unit=o.unit,
        version=o.version,
        subject_type=o.subject_type,
        subject_id=o.subject_id,
        source=o.source,
        synthetic=o.synthetic,
        period_start=o.period_start,
        period_end=o.period_end,
        window_days=o.window_days,
        dimension_value=o.dimension_value,
        eligible_count=o.eligible_count,
        **figures(
            o.kind,
            observed_count=o.observed_count,
            cohort_size=o.cohort_size,
            observed_rate=o.observed_rate,
            value=o.value,
            distribution=o.distribution,
            lower=o.lower,
            upper=o.upper,
            expected_count=o.expected_count,
            expected_rate=o.expected_rate,
            standardized_ratio=o.standardized_ratio,
            pooling_weight=o.pooling_weight,
        ),
        model=None if traced.model is None else _model_ref(traced.model),
        interval_method=interval_method_for(o.kind),
        suppressed=o.suppressed,
        suppression_threshold=o.suppression_threshold,
        suppression_reason=o.suppression_reason,
        coverage=ObservationCoverage(
            coverage_start=own_source.coverage_start,
            coverage_end=own_source.coverage_end,
            observable=_observable(o.outcome, own_source.observable_outcomes),
        ),
        methodology_version=o.methodology_version,
        methodology_url=settings.methodology_url_for(o.slug),
        snapshot_hash=traced.snapshot.content_hash,
        computed_at=o.computed_at,
        registry_version=o.registry_version,
        code_version=o.code_version,
        superseded_at=o.superseded_at,
    )
    return ObservationProvenance(
        observation=observation,
        snapshot=SnapshotOut(
            content_hash=traced.snapshot.content_hash,
            label=traced.snapshot.label,
            exported_at=traced.snapshot.exported_at,
            code_version=traced.snapshot.code_version,
            registry_version=traced.snapshot.registry_version,
            methodology_version=traced.snapshot.methodology_version,
            row_counts=dict(traced.snapshot.row_counts),
        ),
        model=None if traced.model is None else _provenance_model(traced.model),
        members=[
            MemberGroup(
                member_kind=group.kind,
                members=group.members,
                counted=group.counted,
                followed=group.followed,
                resolved=group.resolved,
                case_ids=list(group.case_ids),
            )
            for group in traced.groups
        ],
        source_records=[
            SourceRecordOut(
                id=record.id,
                source=record.source,
                external_record_id=record.external_record_id,
                raw_sha256=record.raw_sha256,
                retrieved_at=record.retrieved_at,
                parser_version=record.parser_version,
                ingest_run_id=record.ingest_run_id,
                artifact_uri=record.public_artifact_uri,
            )
            for record in traced.source_records
        ],
        sources=[
            SourceOut(
                source=source.source,
                owner=source.owner,
                source_type=source.source_type,
                synthetic=source.synthetic,
                coverage_start=source.coverage_start,
                coverage_end=source.coverage_end,
                observable_outcomes=list(source.observable_outcomes),
            )
            for source in traced.sources
        ],
        complete=traced.complete,
    )


# --- the model card -----------------------------------------------------------------------


def model_card(session: Session, settings: Settings, model_id: uuid.UUID) -> ModelCard | None:
    """The model card from the catalogue row, or ``None`` (a 404): one statement, no artifact."""
    row = model_card_row(session, model_id)
    if row is None:
        return None
    diagnostics: dict[str, Any] = dict(row.diagnostics or {})
    return ModelCard(
        id=row.id,
        content_hash=str(row.content_hash),
        snapshot_hash=str(row.snapshot_hash),
        source=str(row.source_name),
        synthetic=bool(row.synthetic),
        target=str(row.target),
        window_days=row.window_days,
        spec_version=int(row.spec_version),
        model_version=str(row.model_version),
        seed=int(row.seed),
        status=str(row.status),
        fitted_at=row.fitted_at,
        code_version=str(row.code_version),
        training=TrainingOut(
            index_events=int(row.n_train) + int(row.n_test),
            events=int(row.events_train) + int(row.events_test),
            start=row.train_start,
            end=row.train_end,
        ),
        validation=ModelValidationOut(
            split_cutoff=row.split_cutoff,
            train_index_events=int(row.n_train),
            train_events=int(row.events_train),
            test_index_events=int(row.n_test),
            test_events=int(row.events_test),
            base_rate_train=_float(diagnostics.get("base_rate_train")),
            brier=_float(diagnostics.get("brier")),
            brier_skill=_float(diagnostics.get("brier_skill")),
            auc=_float(diagnostics.get("auc")),
            calibration_in_the_large=_float(diagnostics.get("calibration_in_the_large")),
            calibration_slope=_float(diagnostics.get("calibration_slope")),
            bins=[
                CalibrationBinOut(
                    bin=int(item["bin"]),
                    count=int(item["count"]),
                    mean_predicted=_float(item.get("mean_predicted")),
                    observed_rate=_float(item.get("observed_rate")),
                )
                for item in diagnostics.get("bins") or []
            ],
        ),
        coefficients=[
            CoefficientOut(
                column=str(item["column"]),
                feature=None if item.get("feature") is None else str(item["feature"]),
                level=None if item.get("level") is None else str(item["level"]),
                reference=None if item.get("reference") is None else str(item["reference"]),
                estimate=_float(item.get("estimate")),
                sd=_float(item.get("sd")),
                sign_agreement=_float(item.get("sign_agreement")),
            )
            for item in row.coefficients or []
        ],
        methodology_url=f"{settings.methodology_url.rstrip('#')}#{ADJUSTED_ANCHOR}",
    )
