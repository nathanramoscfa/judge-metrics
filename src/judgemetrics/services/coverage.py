# src/judgemetrics/services/coverage.py
"""Coverage v0 assembled from the per-source counts and the latest runs."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from judgemetrics.repositories.coverage import last_runs, source_counts
from judgemetrics.schemas.coverage import Coverage, CoverageSource, LastIngest


def coverage(session: Session) -> Coverage:
    """Every registered source with its counts, window, and last completed run: two statements.

    ``synthetic_present`` is true when a synthetic source has rows in any
    canonical table — a source registered by a refused run contributes
    nothing and raises no banner.
    """
    runs = last_runs(session)
    sources: list[CoverageSource] = []
    synthetic_present = False
    for counts in source_counts(session):
        run = runs.get(counts.source)
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
            )
        )
    return Coverage(
        sources=sources, synthetic_present=synthetic_present, generated_at=datetime.now(UTC)
    )
