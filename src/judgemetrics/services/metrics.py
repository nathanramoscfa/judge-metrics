# src/judgemetrics/services/metrics.py
"""Metric responses: the registry, a subject's observations, the compare table, and
the provenance chain of one observation.

Every ``Observation`` is built by ``observation_from_row`` from one joined
row (the observation, its definition, its source, its snapshot hash):
``numerator`` is ``observed_count``, ``denominator`` is ``cohort_size``,
``rate`` is ``observed_rate``, the interval method follows the kind, the
coverage block comes from the source, and the methodology link is
``Settings.methodology_url_for(slug)``. Suppression is applied by the
schema itself (``schemas.metrics.SuppressibleFigures``), so this module
never decides what to withhold. The registry response is built from
``metrics.registry.load_registry`` alone — no database — plus the
methodology prose constants of ``metrics.methodology`` (how to read a
number, the index-event semantics, the attribution notes, the changelog),
so the web methodology page shows the text ``docs/METHODOLOGY.md`` is
rendered from rather than a second copy. The compare
service validates the metric and window against the registry before any
query and turns ``repositories.metrics.compare_page`` rows into
``CompareRow``s with their ``coverage_warning``. The provenance service
runs ``metrics.provenance.trace`` and maps the chain onto
``ObservationProvenance``, answering ``None`` (a 404) for an unknown or
superseded observation and withholding the snapshot's storage URI and any
non-public artifact URI the way ``raw_object_path`` is never returned.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Row
from sqlalchemy.orm import Session

from judgemetrics.api.errors import ApiError
from judgemetrics.config import Settings
from judgemetrics.metrics.methodology import (
    ATTRIBUTION_TEXT,
    CHANGELOG,
    GATE_TEXT,
    HOW_TO_READ,
    SEMANTICS,
)
from judgemetrics.metrics.provenance import TraceError, trace
from judgemetrics.metrics.registry import (
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
from judgemetrics.schemas.judges import CourtRef
from judgemetrics.schemas.metrics import (
    AttributionOut,
    CompareCohort,
    ComparePage,
    CompareRow,
    MemberGroup,
    MethodologyChange,
    MethodologyTerm,
    MetricDefinitionOut,
    Observation,
    ObservationCoverage,
    ObservationProvenance,
    SnapshotOut,
    SourceOut,
    SourceRecordOut,
    SubjectMetrics,
    SubjectSummary,
    SuppressionOut,
    TracedObservation,
    interval_method_for,
)
from judgemetrics.schemas.metrics import Registry as RegistryOut


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _observable(outcome: str | None, observable_outcomes: Any) -> bool:
    if outcome is None:
        return True
    return outcome in {str(item) for item in (observable_outcomes or [])}


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
        definitions=[definition_out(item, settings) for item in registry.metrics.values()],
    )


# --- observations ---------------------------------------------------------------------------


def observation_from_row(row: Row[Any], settings: Settings) -> Observation:
    """One joined repository row → the presentation shape (suppression applied by the schema)."""
    observation = row[0]
    return Observation(
        id=observation.id,
        slug=str(row.slug),
        name=str(row.name),
        kind=str(row.kind),
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
        numerator=int(observation.observed_count),
        denominator=int(observation.cohort_size),
        rate=_float(observation.observed_rate),
        value=_float(observation.value),
        distribution=(
            None
            if observation.distribution is None
            else {str(k): int(v) for k, v in dict(observation.distribution).items()}
        ),
        lower=_float(observation.lower_confidence_bound),
        upper=_float(observation.upper_confidence_bound),
        interval_method=interval_method_for(str(row.kind)),
        suppressed=bool(observation.suppressed_flag),
        suppression_threshold=int(row.suppression_threshold),
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
    for row in subject_observations(session, subject_type, subject_id):
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
    """The registry entry for ``slug`` once ``window_days`` fits its kind, else a 422."""
    definition = registry.metrics.get(slug)
    if definition is None:
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
    sort: CompareSortKey,
    order: str,
    limit: int,
    offset: int,
) -> ComparePage | None:
    """One metric, one window, one cohort: sorted, paginated; ``None`` when the cohort is unknown."""
    registry = load_registry()
    definition = validate_compare_metric(registry, slug, window_days)
    page = compare_page(
        session,
        slug=definition.slug,
        version=definition.version,
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
            numerator=int(row.observed_count),
            denominator=int(row.cohort_size),
            rate=_float(row.observed_rate),
            value=_float(row.value),
            distribution=(
                None
                if row.distribution is None
                else {str(k): int(v) for k, v in dict(row.distribution).items()}
            ),
            lower=_float(row.lower_confidence_bound),
            upper=_float(row.upper_confidence_bound),
            interval_method=interval_method_for(definition.kind),
            suppressed=bool(row.suppressed_flag),
            suppression_threshold=int(row.suppression_threshold),
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


def observation_provenance(
    session: Session, settings: Settings, observation_id: uuid.UUID
) -> ObservationProvenance | None:
    """The chain behind a current observation, or ``None`` for an unknown or superseded id."""
    try:
        traced = trace(session, observation_id)
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
        numerator=o.observed_count,
        denominator=o.cohort_size,
        rate=_float(o.observed_rate),
        value=_float(o.value),
        distribution=o.distribution,
        lower=_float(o.lower),
        upper=_float(o.upper),
        interval_method=interval_method_for(o.kind),
        suppressed=o.suppressed,
        suppression_threshold=o.suppression_threshold,
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
