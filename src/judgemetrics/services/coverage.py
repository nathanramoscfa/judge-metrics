# src/judgemetrics/services/coverage.py
"""Coverage assembled from the per-source counts, the latest runs, and the latest snapshots."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from judgemetrics.metrics.registry import load_registry
from judgemetrics.repositories.coverage import last_runs, latest_snapshots, source_counts
from judgemetrics.schemas.coverage import Coverage, CoverageSource, LastIngest, LatestSnapshotOut


def coverage(session: Session) -> Coverage:
    """Every registered source with its counts, windows, last run, and snapshot: three statements.

    ``synthetic_present`` is true when a synthetic source has rows in any
    canonical table — a source registered by a refused run contributes
    nothing and raises no banner. The registry versions come from the
    registry file, not the database.
    """
    registry = load_registry()
    runs = last_runs(session)
    snapshots = latest_snapshots(session)
    sources: list[CoverageSource] = []
    synthetic_present = False
    for counts in source_counts(session):
        run = runs.get(counts.source)
        snapshot = snapshots.get(counts.source)
        populated = any(
            (counts.jurisdictions, counts.courts, counts.judges, counts.cases, counts.persons)
        )
        synthetic_present = synthetic_present or (counts.synthetic and populated)
        sources.append(
            CoverageSource(
                **counts._asdict(),
                last_ingest=(
                    None
                    if run is None
                    else LastIngest(
                        run_id=run.run_id, completed_at=run.completed_at, status=run.status
                    )
                ),
                latest_snapshot=(
                    None
                    if snapshot is None
                    else LatestSnapshotOut(
                        content_hash=snapshot.content_hash, exported_at=snapshot.exported_at
                    )
                ),
                methodology_version=None if snapshot is None else snapshot.methodology_version,
            )
        )
    return Coverage(
        sources=sources,
        synthetic_present=synthetic_present,
        registry_version=registry.version,
        methodology_version=registry.methodology_version,
        generated_at=datetime.now(UTC),
    )
