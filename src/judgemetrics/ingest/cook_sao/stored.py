# src/judgemetrics/ingest/cook_sao/stored.py
"""The five Cook County artifacts as local files, for the profile and the excerpt.

``lake_artifacts`` reads the latest stored record of each dataset (the
records every succeeded ``ingest run cook_sao`` left; a rerun over an
unchanged export records none, so the latest record is the current
export) and streams its object out of the raw lake into a directory the
caller owns, verified against the record's digest — never the canonical
tables, and never another source. ``fixture_artifacts`` reads a directory
of the five CSVs (``<dir>/<external id>``), as the committed fixture is
laid out. The paths come from the module's constants, never from data.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from judgemetrics.db.models import IngestRun, IngestRunStatus, Source, SourceRecord
from judgemetrics.ingest.base import HEADER_ROWS_UPDATED_AT, sha256_file
from judgemetrics.ingest.cook_sao.sources import DATASETS, SOURCE_ID
from judgemetrics.ingest.store import RawObjectStore


class ArtifactsError(Exception):
    """The artifacts cannot be read (not ingested yet, missing, or altered)."""


@dataclass(frozen=True, slots=True)
class LocalArtifact:
    """One dataset's export as a local file, with what its record says about it."""

    external_id: str
    path: Path
    sha256: str
    size_bytes: int
    rows_updated_at: str | None
    retrieved_at: str | None


def fixture_artifacts(directory: Path) -> list[LocalArtifact]:
    """The five CSVs of ``directory`` in dependency order (no record facts)."""
    artifacts: list[LocalArtifact] = []
    for dataset in DATASETS:
        path = directory / dataset.external_id
        if not path.is_file():
            msg = f"{dataset.external_id} is missing from {directory}"
            raise ArtifactsError(msg)
        digest, size = sha256_file(path)
        artifacts.append(
            LocalArtifact(
                external_id=dataset.external_id,
                path=path,
                sha256=digest,
                size_bytes=size,
                rows_updated_at=None,
                retrieved_at=None,
            )
        )
    return artifacts


def lake_artifacts(session: Session, store: RawObjectStore, work_dir: Path) -> list[LocalArtifact]:
    """The latest stored export of each dataset, streamed into ``work_dir`` and verified."""
    source_id = session.scalar(select(Source.id).where(Source.name == SOURCE_ID))
    if source_id is None:
        msg = f"no {SOURCE_ID} source is recorded; run `judgemetrics ingest run {SOURCE_ID}` first"
        raise ArtifactsError(msg)
    artifacts: list[LocalArtifact] = []
    for dataset in DATASETS:
        record = session.scalar(
            select(SourceRecord)
            .join(IngestRun, IngestRun.id == SourceRecord.ingest_run_id)
            .where(
                SourceRecord.source_id == source_id,
                SourceRecord.external_record_id == dataset.external_id,
                IngestRun.status == IngestRunStatus.SUCCEEDED,
            )
            .order_by(SourceRecord.retrieved_at.desc())
            .limit(1)
        )
        if record is None:
            msg = f"no stored artifact for {dataset.external_id}; run the ingest first"
            raise ArtifactsError(msg)
        dest = work_dir / dataset.external_id
        try:
            ref = store.get_file(record.raw_object_path, dest)
        except KeyError as exc:
            msg = f"{dataset.external_id}: the raw lake has no object for the recorded artifact"
            raise ArtifactsError(msg) from exc
        if ref.sha256 != record.raw_sha256:
            msg = f"{dataset.external_id}: the stored object does not match its record"
            raise ArtifactsError(msg)
        rows_updated = record.metadata_.get(HEADER_ROWS_UPDATED_AT)
        artifacts.append(
            LocalArtifact(
                external_id=dataset.external_id,
                path=dest,
                sha256=ref.sha256,
                size_bytes=ref.size_bytes,
                rows_updated_at=rows_updated if isinstance(rows_updated, str) else None,
                retrieved_at=record.retrieved_at.astimezone(UTC).isoformat(),
            )
        )
    return artifacts


def by_external_id(artifacts: Sequence[LocalArtifact]) -> dict[str, LocalArtifact]:
    return {artifact.external_id: artifact for artifact in artifacts}
