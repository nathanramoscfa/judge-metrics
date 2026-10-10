# src/judgemetrics/metrics/engine.py
"""``compute_and_publish``: export a snapshot, fit, compute, publish — one call, one transaction.

The CLI's ``metrics compute`` and pipeline step 13 share this entry
point: ``export_snapshot`` through the caller's session (inside the
ingest transaction at step 13, so the run's own rows are included),
``open_snapshot``, ``compute_all`` for every subject or the given ones,
``publish``. The caller owns the transaction: the CLI commits on
success and rolls back on ``ProvenanceError``; the runner commits the
whole ingest or rolls it back on any failure. The result carries the
snapshot reference, the fitted models, the compute counts, the publish
counts, and the coverage statistics; the snapshot is closed before
returning.

``kinds`` names the registry kinds the call computes and publishes (every
kind by default). When it includes ``observed_expected`` (Phase 4 Step 3),
the snapshot's ``metric_snapshot`` row is recorded first and the
snapshot's missing expected-outcome models are fitted and recorded
(``adjustment.catalog.fit_snapshot``: only those of the current
specification version and seed the snapshot lacks, so a second run on the
same snapshot fits nothing), then every model is read back from its
artifact (``catalog.snapshot_parameters``) — the very bytes the catalogue
records, which is what ``metrics verify`` reads too. Pipeline step 13
passes the descriptive kinds only: an adjusted figure depends on a model
and a shape fitted over every judge, so the full ``metrics compute``
recomputes it, and ``publish`` leaves the kinds a run does not compute in
place.

Phase 5 Step 5: ``sources`` (register names; the CLI's ``--source``)
restricts the fit and the compute to those sources' frames — the snapshot
still exports every source, as provenance requires, and the catalogue still
records every source's unavailable targets (they need no frame). Every call
computes and stores the coverage statistics of every source the snapshot
holds (``metrics.coverage``), whatever ``sources`` scopes.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.logging import get_logger
from judgemetrics.metrics.attribution import Subject
from judgemetrics.metrics.compute import ComputeError, ComputeResult, compute_all
from judgemetrics.metrics.coverage import CoverageResult, compute_statistics, publish_statistics
from judgemetrics.metrics.publish import PublishResult, publish, upsert_snapshot
from judgemetrics.metrics.registry import KINDS, OBSERVED_EXPECTED, Registry, load_registry
from judgemetrics.metrics.snapshot import Snapshot, SnapshotRef, export_snapshot, open_snapshot

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EngineResult:
    snapshot: SnapshotRef
    computed: ComputeResult
    published: PublishResult
    # The models this call fitted and recorded (0 when the snapshot had them all, or
    # when the call computed no adjusted kind); the models the compute read.
    models_fitted: int = 0
    models_read: int = 0
    coverage: CoverageResult | None = None


def source_ids(snapshot: Snapshot, names: Collection[str]) -> frozenset[str]:
    """The ids of the snapshot's sources registered under ``names`` (absent ones skipped)."""
    wanted = set(names)
    return frozenset(source.id for source in snapshot.sources() if source.name in wanted)


def compute_and_publish(
    session: Session,
    settings: Settings,
    *,
    subjects: Sequence[Subject] | None = None,
    label: str | None = None,
    registry: Registry | None = None,
    kinds: Collection[str] | None = None,
    sources: Collection[str] | None = None,
) -> EngineResult:
    """Export, fit (when adjusted kinds are wanted), compute, and publish; the caller commits."""
    registry = registry or load_registry()
    wanted = frozenset(KINDS) if kinds is None else frozenset(kinds)
    unknown = wanted - set(KINDS)
    if unknown:
        msg = f"unknown metric kinds {sorted(unknown)}"
        raise ComputeError(msg)
    adjusted = OBSERVED_EXPECTED in wanted and bool(registry.of_kind(OBSERVED_EXPECTED))
    ref = export_snapshot(session, settings, label)
    fitted = 0
    read = 0
    with open_snapshot(settings, ref.content_hash) as snapshot:
        selected = None if sources is None else source_ids(snapshot, sources)
        snapshot_id = upsert_snapshot(session, snapshot, registry, settings, label)
        models = None
        if adjusted:
            from judgemetrics.metrics.adjustment.artifacts import ArtifactError
            from judgemetrics.metrics.adjustment.catalog import (
                CatalogError,
                fit_snapshot,
                snapshot_parameters,
            )
            from judgemetrics.metrics.adjustment.fit import FitError
            from judgemetrics.metrics.adjustment.spec import SpecError, load_spec

            try:
                spec = load_spec()
                summary = fit_snapshot(
                    session,
                    settings,
                    snapshot_hash=ref.content_hash,
                    spec=spec,
                    sources=None if sources is None else frozenset(sources),
                    opened=snapshot,
                )
                models = snapshot_parameters(
                    session,
                    settings,
                    snapshot_id=snapshot_id,
                    snapshot_hash=ref.content_hash,
                    spec=spec,
                )
            except (ArtifactError, CatalogError, FitError, SpecError) as exc:
                msg = f"the snapshot's outcome models cannot be fitted or read: {exc}"
                raise ComputeError(msg) from exc
            fitted = len(summary.fitted)
            read = sum(len(by_target) for by_target in models.values())
        computed = compute_all(
            snapshot, registry, subjects, kinds=wanted, models=models, sources=selected
        )
        published = publish(
            session,
            snapshot,
            computed.drafts,
            registry,
            settings,
            not_observable=computed.not_observable,
            not_attributable=computed.not_attributable,
            label=label,
            kinds=wanted,
        )
        coverage = publish_statistics(
            session, snapshot_id, compute_statistics(snapshot), registry.methodology_version
        )
    log.info(
        "metrics.compute_and_publish",
        reused=ref.reused,
        subjects=len(computed.subjects),
        sources_skipped=len(computed.sources_skipped),
        models_fitted=fitted,
        models_read=read,
        **published.as_log(),
        **coverage.as_log(),
    )
    return EngineResult(
        snapshot=ref,
        computed=computed,
        published=published,
        models_fitted=fitted,
        models_read=read,
        coverage=coverage,
    )
