# src/judgemetrics/ingest/cook_sao/connector.py
"""``CookSaoConnector``: the Cook County State's Attorney case-level datasets.

Parser version ``0`` fetches and stores; it parses nothing (Phase 5 Step 4
bumps the version and adds the mapping, after Step 3's rule tables).

``discover`` lists the five current datasets from constants and makes no
network call (the runner calls it in fixture mode too). ``fetch`` first
reads the dataset's portal metadata — the rows-updated time, the license,
the attribution, the column list — into the artifact's response metadata,
which the runner records on the ``source_record``. When the rows-updated
time equals the one the previous record carries (the runner forwards it
as ``previous_rows_updated_at`` beside the previous digest), the export is
unchanged and nothing is downloaded. Otherwise the export streams to a
temporary file in the run's work directory under ``MAX_EXPORT_BYTES``,
hashed while it is written, with the previous ``ETag`` and
``Last-Modified`` sent so a ``304`` also short-circuits. Validation reads
the header row only and checks it, and the metadata's column list, against
the verified headers (missing → error naming the header, extra → warning).

Nothing here logs a participant id, a case id, or a restricted value: the
fetch logs dataset names, sizes, and digests only.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from judgemetrics.ingest.base import (
    HEADER_ROWS_UPDATED_AT,
    PREVIOUS_ETAG,
    PREVIOUS_LAST_MODIFIED,
    PREVIOUS_ROWS_UPDATED_AT,
    PREVIOUS_SHA256,
    CanonicalRecord,
    FetchError,
    RawArtifact,
    SourceArtifact,
    SourceInfo,
    SourceRecordDraft,
    ValidationResult,
    utc_now,
)
from judgemetrics.ingest.cook_sao import sources
from judgemetrics.ingest.cook_sao.schema import VERIFIED_HEADERS
from judgemetrics.ingest.http import (
    DEFAULT_RETRIES,
    Sleep,
    download,
    download_to_file,
    make_client,
)
from judgemetrics.ingest.registry import register
from judgemetrics.logging import get_logger

log = get_logger(__name__)

ClientFactory = Callable[[], httpx.AsyncClient]

# The largest export measured on 2026-10-05 is Initiation's, 512,058,076
# bytes (the five total 1,221,648,291); the cap, 1.5 GiB, is more than twice
# it, so a modest growth never fails a run and a runaway body still stops.
MAX_EXPORT_BYTES = 3 * 512 * 1024 * 1024
# A dataset's metadata document is about 80 KB.
MAX_METADATA_BYTES = 5 * 1024 * 1024
# The portal builds an export on the fly; allow a longer pause between reads.
EXPORT_TIMEOUT_SECONDS = 120.0

# Keys this connector adds to ``RawArtifact.response_headers`` (recorded in
# ``source_record.metadata``) besides ``rows_updated_at``.
META_PORTAL_ID = "portal_id"
META_LICENSE = "license"
META_ATTRIBUTION = "attribution"
META_COLUMNS = "columns"
META_METADATA_URL = "metadata_url"
COLUMN_SEPARATOR = ","

REDISTRIBUTION = {
    "aggregates": "yes",
    "record_level": "unverified",
    "commercial": "unverified",
}


@dataclass(frozen=True, slots=True)
class PortalMetadata:
    """What the portal's metadata document says about one dataset."""

    portal_id: str
    rows_updated_at: str
    license: str
    attribution: str
    columns: tuple[str, ...]

    def as_headers(self, metadata_url: str) -> dict[str, str]:
        return {
            META_PORTAL_ID: self.portal_id,
            HEADER_ROWS_UPDATED_AT: self.rows_updated_at,
            META_LICENSE: self.license,
            META_ATTRIBUTION: self.attribution,
            META_COLUMNS: COLUMN_SEPARATOR.join(self.columns),
            META_METADATA_URL: metadata_url,
        }


def parse_portal_metadata(data: bytes, *, portal_id: str) -> PortalMetadata:
    """The Socrata ``/api/views/<id>.json`` document → ``PortalMetadata``.

    ``rowsUpdatedAt`` (epoch seconds) becomes ISO 8601 UTC; the column list
    is the display names the export's header row carries, without the
    portal's ``:``-prefixed system columns.
    """
    try:
        document: Any = json.loads(data)
        if document.get("id") != portal_id:
            msg = f"metadata of {document.get('id')!r} where {portal_id!r} was requested"
            raise FetchError(msg)
        rows_updated = datetime.fromtimestamp(int(document["rowsUpdatedAt"]), UTC)
        license_name = str((document.get("license") or {}).get("name") or "")
        columns = tuple(
            str(column["name"])
            for column in document["columns"]
            if not str(column.get("fieldName", "")).startswith(":")
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        msg = f"unreadable portal metadata for {portal_id}: {type(exc).__name__}"
        raise FetchError(msg) from exc
    return PortalMetadata(
        portal_id=portal_id,
        rows_updated_at=rows_updated.isoformat(),
        license=license_name,
        attribution=str(document.get("attribution") or ""),
        columns=columns,
    )


def read_header(raw: RawArtifact) -> list[str]:
    """The header row of a CSV artifact, reading its first line only."""
    if isinstance(raw.path_or_bytes, Path):
        with raw.path_or_bytes.open(encoding="utf-8-sig", newline="") as handle:
            return next(csv.reader(handle), [])
    text = raw.path_or_bytes.decode("utf-8-sig")
    return next(csv.reader(io.StringIO(text)), [])


def _header_problems(
    name: str, origin: str, headers: Iterable[str], verified: tuple[str, ...]
) -> tuple[list[str], list[str]]:
    present = list(headers)
    errors = [
        f"{name}: verified header {header!r} is missing from the {origin}"
        for header in verified
        if header not in present
    ]
    warnings = [
        f"{name}: {origin} header {header!r} is not in the verified set"
        for header in present
        if header not in verified
    ]
    return errors, warnings


@register
class CookSaoConnector:
    source_id = sources.SOURCE_ID
    parser_version = "0"
    source_info = SourceInfo(
        owner="Cook County State's Attorney's Office",
        source_type="government_open_data",
        access_method="socrata_bulk_export",
        terms_metadata={
            "portal": sources.PORTAL_URL,
            "terms": sources.TERMS_URL,
            "license": "Public Domain",
            "attribution": sources.ATTRIBUTION,
            "attribution_url": sources.ATTRIBUTION_URL,
            "documentation": [sources.GLOSSARY_URL, sources.FLOWCHART_URL],
            "redistribution": REDISTRIBUTION,
            "datasets": {d.external_id: d.portal_id for d in sources.DATASETS},
        },
        observable_outcomes=(),
    )

    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        *,
        max_bytes: int = MAX_EXPORT_BYTES,
        retries: int = DEFAULT_RETRIES,
        sleep: Sleep = asyncio.sleep,
        work_dir: Path | None = None,
    ) -> None:
        self._client_factory = client_factory or (lambda: make_client(EXPORT_TIMEOUT_SECONDS))
        self._max_bytes = max_bytes
        self._retries = retries
        self._sleep = sleep
        self._work_dir = work_dir

    def use_work_dir(self, directory: Path) -> None:
        self._work_dir = directory

    async def discover(self) -> list[SourceArtifact]:
        return [
            SourceArtifact(
                source_id=self.source_id,
                external_id=dataset.external_id,
                uri=dataset.export_url,
                content_type="text/csv",
                metadata={"dataset": dataset.name, META_PORTAL_ID: dataset.portal_id},
            )
            for dataset in sources.DATASETS
        ]

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:
        dataset = sources.DATASETS_BY_EXTERNAL_ID.get(artifact.external_id)
        if dataset is None:
            msg = f"{artifact.external_id}: not a Cook County SAO artifact"
            raise FetchError(msg)
        if self._work_dir is None:
            msg = "the Cook County connector streams to a work directory; none was set"
            raise FetchError(msg)
        bound = log.bind(source=self.source_id, dataset=dataset.name)
        async with self._client_factory() as client:
            answer = await download(
                client,
                dataset.metadata_url,
                max_bytes=MAX_METADATA_BYTES,
                retries=self._retries,
                sleep=self._sleep,
            )
            portal = parse_portal_metadata(answer.data, portal_id=dataset.portal_id)
            headers = portal.as_headers(dataset.metadata_url)
            previous_sha256 = artifact.metadata.get(PREVIOUS_SHA256)
            previous_rows = artifact.metadata.get(PREVIOUS_ROWS_UPDATED_AT)
            if previous_sha256 and previous_rows == portal.rows_updated_at:
                bound.info("cook_sao.export.unchanged", rows_updated_at=portal.rows_updated_at)
                return RawArtifact.unchanged(
                    artifact,
                    sha256=previous_sha256,
                    retrieved_at=utc_now(),
                    response_headers=headers,
                )
            bound.info("cook_sao.export.downloading", rows_updated_at=portal.rows_updated_at)
            result = await download_to_file(
                client,
                dataset.export_url,
                directory=self._work_dir,
                etag=artifact.metadata.get(PREVIOUS_ETAG),
                last_modified=artifact.metadata.get(PREVIOUS_LAST_MODIFIED),
                max_bytes=self._max_bytes,
                retries=self._retries,
                sleep=self._sleep,
            )
        retrieved_at = utc_now()
        if result.not_modified or result.path is None or result.sha256 is None:
            if not previous_sha256:
                msg = f"{artifact.external_id}: 304 Not Modified without a previous sha256"
                raise FetchError(msg)
            return RawArtifact.unchanged(
                artifact,
                sha256=previous_sha256,
                retrieved_at=retrieved_at,
                response_headers={**result.headers, **headers},
            )
        bound.info("cook_sao.export.downloaded", size_bytes=result.size_bytes, sha256=result.sha256)
        return RawArtifact.from_path(
            artifact,
            result.path,
            retrieved_at=retrieved_at,
            response_headers={**result.headers, **headers},
            sha256=result.sha256,
            size_bytes=result.size_bytes,
        )

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:
        if artifact.not_modified:
            return ValidationResult.passed()
        name = artifact.artifact.external_id
        verified = VERIFIED_HEADERS.get(name)
        if verified is None:
            return ValidationResult.failed([f"{name}: not a Cook County SAO artifact"])
        try:
            headers = read_header(artifact)
        except (UnicodeDecodeError, csv.Error) as exc:
            return ValidationResult.failed([f"{name}: no readable CSV header row ({exc})"])
        if not headers or not any(header.strip() for header in headers):
            return ValidationResult.failed([f"{name}: the file is empty or has no header row"])
        errors, warnings = _header_problems(name, "export", headers, verified)
        columns = artifact.response_headers.get(META_COLUMNS)
        if columns:
            meta_errors, meta_warnings = _header_problems(
                name, "portal metadata", columns.split(COLUMN_SEPARATOR), verified
            )
            errors += meta_errors
            warnings += meta_warnings
        if errors:
            return ValidationResult.failed(errors, warnings)
        return ValidationResult.passed(warnings)

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:
        """Parser version ``0`` parses nothing.

        Phase 5 Step 4 bumps ``parser_version`` and maps the five datasets
        through Step 3's rule tables; the runner then re-parses every stored
        artifact from the lake under the new version.
        """
        return []

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:
        return []
