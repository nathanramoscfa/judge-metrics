# src/judgemetrics/metrics/engine.py
"""``compute_and_publish``: export a snapshot, compute, publish — one call, one transaction.

The CLI's ``metrics compute`` and pipeline step 13 share this entry
point: ``export_snapshot`` through the caller's session (inside the
ingest transaction at step 13, so the run's own rows are included),
``open_snapshot``, ``compute_all`` for every subject or the given ones,
``publish``. The caller owns the transaction: the CLI commits on
success and rolls back on ``ProvenanceError``; the runner commits the
whole ingest or rolls it back on any failure. The result carries the
snapshot reference, the compute counts, and the publish counts; the
snapshot is closed before returning.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from judgemetrics.config import Settings
from judgemetrics.logging import get_logger
from judgemetrics.metrics.attribution import Subject
from judgemetrics.metrics.compute import ComputeResult, compute_all
from judgemetrics.metrics.publish import PublishResult, publish
from judgemetrics.metrics.registry import Registry, load_registry
from judgemetrics.metrics.snapshot import SnapshotRef, export_snapshot, open_snapshot

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EngineResult:
    snapshot: SnapshotRef
    computed: ComputeResult
    published: PublishResult


def compute_and_publish(
    session: Session,
    settings: Settings,
    *,
    subjects: Sequence[Subject] | None = None,
    label: str | None = None,
    registry: Registry | None = None,
) -> EngineResult:
    """Export, compute (every subject or ``subjects``), and publish; the caller commits."""
    registry = registry or load_registry()
    ref = export_snapshot(session, settings, label)
    with open_snapshot(settings, ref.content_hash) as snapshot:
        computed = compute_all(snapshot, registry, subjects)
        published = publish(
            session,
            snapshot,
            computed.drafts,
            registry,
            settings,
            not_observable=computed.not_observable,
            label=label,
        )
    log.info(
        "metrics.compute_and_publish",
        reused=ref.reused,
        subjects=len(computed.subjects),
        sources_skipped=len(computed.sources_skipped),
        **published.as_log(),
    )
    return EngineResult(snapshot=ref, computed=computed, published=published)
