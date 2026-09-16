# src/judgemetrics/ingest/fjc/connector.py
"""``FjcConnector``: the Federal Judicial Center Biographical Directory export.

Two artifacts (``judges.csv`` and ``federal-judicial-service.csv``) are
downloaded over HTTPS with a 30-second timeout, three retries with backoff,
a 200 MB size cap, and ``If-None-Match`` / ``If-Modified-Since`` when the
runner supplies the validators of the previous retrieval (the FJC server
sends ``ETag`` and ``Last-Modified``; verified 2026-09-16). Validation
checks for a non-empty CSV with a header row containing every expected
header and warns about headers outside the verified set.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable

import httpx
import polars as pl

from judgemetrics.ingest.base import (
    PREVIOUS_ETAG,
    PREVIOUS_LAST_MODIFIED,
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
from judgemetrics.ingest.fjc import sources
from judgemetrics.ingest.fjc.normalize import normalize_record
from judgemetrics.ingest.fjc.parse import parse_judges, parse_service, read_headers
from judgemetrics.ingest.fjc.schema import EXPECTED_HEADERS, VERIFIED_HEADERS
from judgemetrics.ingest.http import (
    DEFAULT_MAX_BYTES,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    Sleep,
    download,
    make_client,
)
from judgemetrics.ingest.registry import register

ClientFactory = Callable[[], httpx.AsyncClient]


@register
class FjcConnector:
    source_id = "fjc"
    parser_version = "2026.09.1"
    source_info = SourceInfo(
        owner="Federal Judicial Center (United States federal government)",
        source_type="government_directory",
        access_method="https_download",
        terms_metadata={
            "export_page": sources.EXPORT_PAGE_URL,
            "terms": "Work of the United States federal government; cite the FJC as the source.",
            "redistribution": {"aggregates": "yes", "record_level": "yes", "commercial": "yes"},
            "files": [sources.JUDGES_FILE, sources.SERVICE_FILE],
        },
    )

    def __init__(
        self,
        client_factory: ClientFactory | None = None,
        *,
        max_bytes: int = DEFAULT_MAX_BYTES,
        retries: int = DEFAULT_RETRIES,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._client_factory = client_factory or (lambda: make_client(DEFAULT_TIMEOUT_SECONDS))
        self._max_bytes = max_bytes
        self._retries = retries
        self._sleep = sleep

    async def discover(self) -> list[SourceArtifact]:
        return [
            SourceArtifact(
                source_id=self.source_id,
                external_id=name,
                uri=url,
                content_type="text/csv",
                metadata={"export_page": sources.EXPORT_PAGE_URL},
            )
            for name, url in sources.ARTIFACT_URLS.items()
        ]

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact:
        async with self._client_factory() as client:
            result = await download(
                client,
                artifact.uri,
                etag=artifact.metadata.get(PREVIOUS_ETAG),
                last_modified=artifact.metadata.get(PREVIOUS_LAST_MODIFIED),
                max_bytes=self._max_bytes,
                retries=self._retries,
                sleep=self._sleep,
            )
        retrieved_at = utc_now()
        if result.not_modified:
            previous_sha256 = artifact.metadata.get(PREVIOUS_SHA256)
            if not previous_sha256:
                msg = f"{artifact.external_id}: 304 Not Modified without a previous sha256"
                raise FetchError(msg)
            return RawArtifact.unchanged(
                artifact,
                sha256=previous_sha256,
                retrieved_at=retrieved_at,
                response_headers=result.headers,
            )
        return RawArtifact.from_bytes(
            artifact, result.data, retrieved_at=retrieved_at, response_headers=result.headers
        )

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult:
        if artifact.not_modified:
            return ValidationResult.passed()
        name = artifact.artifact.external_id
        expected = EXPECTED_HEADERS.get(name)
        if expected is None:
            return ValidationResult.failed([f"{name}: not an FJC artifact"])
        data = artifact.read_bytes()
        if not data.strip():
            return ValidationResult.failed([f"{name}: the file is empty"])
        try:
            headers = read_headers(data)
        except pl.exceptions.PolarsError as exc:
            return ValidationResult.failed([f"{name}: no readable CSV header row ({exc})"])
        if not headers:
            return ValidationResult.failed([f"{name}: no header row"])
        present = set(headers)
        errors = [
            f"{name}: missing expected header {header!r}"
            for header in expected
            if header not in present
        ]
        verified = set(VERIFIED_HEADERS[name])
        warnings = [
            f"{name}: header {header!r} is not in the verified set"
            for header in headers
            if header not in verified
        ]
        if errors:
            return ValidationResult.failed(errors, warnings)
        return ValidationResult.passed(warnings)

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]:
        if artifact.not_modified:
            return []
        name = artifact.artifact.external_id
        if name == sources.JUDGES_FILE:
            return parse_judges(artifact.read_bytes())
        if name == sources.SERVICE_FILE:
            return parse_service(artifact.read_bytes())
        msg = f"{name}: not an FJC artifact"
        raise FetchError(msg)

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]:
        return normalize_record(record)
