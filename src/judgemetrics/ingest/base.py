# src/judgemetrics/ingest/base.py
"""The connector protocol and the value types that flow through the pipeline.

The brief's ``SourceConnector`` interface is reproduced exactly (``discover``,
``fetch``, ``validate_raw``, ``parse``, ``normalize``); ``source_id``,
``parser_version``, and ``source_info`` identify the connector, and the
optional ``SupportsCheckpoint`` protocol carries incremental state for
cursoring sources. Everything a connector produces is a frozen dataclass:

- ``SourceArtifact`` — something discoverable at the source (one file, one
  API page); ``RawArtifact`` — the retrieved bytes with their sha256;
- ``SourceRecordDraft`` — one parsed source row (the database
  ``source_record`` is per *artifact*; rows are attributed to it);
- the ``CanonicalRecord`` drafts, each with a ``natural_key`` the runner
  deduplicates and upserts on. Case-level drafts arrive in Phase 2.

Source-specific parsing stays in the connectors; the drafts speak the
canonical domain only.
"""

from __future__ import annotations

import dataclasses
import hashlib
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

NaturalKey = tuple[str, ...]
Checkpoint = dict[str, Any]

# Keys the runner adds to ``SourceArtifact.metadata`` before ``fetch`` so a
# connector can issue a conditional request; the values come from the
# artifact's latest ``source_record``.
PREVIOUS_ETAG = "previous_etag"
PREVIOUS_LAST_MODIFIED = "previous_last_modified"
PREVIOUS_SHA256 = "previous_sha256"

# Keys of the ``RawArtifact.response_headers`` subset (lower-case).
HEADER_ETAG = "etag"
HEADER_LAST_MODIFIED = "last_modified"
HEADER_CONTENT_TYPE = "content_type"
HEADER_CONTENT_LENGTH = "content_length"
HEADER_FINAL_URL = "final_url"


class IngestError(Exception):
    """Base class for every error the ingest framework raises."""


class FetchError(IngestError):
    """An artifact could not be retrieved."""


class NormalizationError(IngestError):
    """A source row could not be mapped to canonical drafts (the row is rejected)."""


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    """One discoverable unit at the source, e.g. a downloadable file."""

    source_id: str
    external_id: str
    uri: str
    content_type: str
    metadata: Mapping[str, str] = field(default_factory=dict)

    def with_metadata(self, **extra: str) -> SourceArtifact:
        return dataclasses.replace(self, metadata={**self.metadata, **extra})


@dataclass(frozen=True, slots=True)
class RawArtifact:
    """Retrieved bytes (or a path to them) with their digest and retrieval facts."""

    artifact: SourceArtifact
    path_or_bytes: Path | bytes
    sha256: str
    retrieved_at: datetime
    size_bytes: int
    response_headers: Mapping[str, str] = field(default_factory=dict)
    # True when the server answered a conditional request with 304: the
    # bytes are the ones already in the lake under ``sha256``.
    not_modified: bool = False

    @classmethod
    def from_bytes(
        cls,
        artifact: SourceArtifact,
        data: bytes,
        *,
        retrieved_at: datetime,
        response_headers: Mapping[str, str] | None = None,
    ) -> RawArtifact:
        return cls(
            artifact=artifact,
            path_or_bytes=data,
            sha256=sha256_hex(data),
            retrieved_at=retrieved_at,
            size_bytes=len(data),
            response_headers=dict(response_headers or {}),
        )

    @classmethod
    def from_path(
        cls,
        artifact: SourceArtifact,
        path: Path,
        *,
        retrieved_at: datetime,
        response_headers: Mapping[str, str] | None = None,
    ) -> RawArtifact:
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                digest.update(chunk)
                size += len(chunk)
        return cls(
            artifact=artifact,
            path_or_bytes=path,
            sha256=digest.hexdigest(),
            retrieved_at=retrieved_at,
            size_bytes=size,
            response_headers=dict(response_headers or {}),
        )

    @classmethod
    def unchanged(
        cls,
        artifact: SourceArtifact,
        *,
        sha256: str,
        retrieved_at: datetime,
        response_headers: Mapping[str, str] | None = None,
    ) -> RawArtifact:
        return cls(
            artifact=artifact,
            path_or_bytes=b"",
            sha256=sha256,
            retrieved_at=retrieved_at,
            size_bytes=0,
            response_headers=dict(response_headers or {}),
            not_modified=True,
        )

    def read_bytes(self) -> bytes:
        if isinstance(self.path_or_bytes, Path):
            return self.path_or_bytes.read_bytes()
        return self.path_or_bytes


@dataclass(frozen=True, slots=True)
class ValidationResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def passed(cls, warnings: Iterable[str] = ()) -> ValidationResult:
        return cls(ok=True, warnings=list(warnings))

    @classmethod
    def failed(cls, errors: Iterable[str], warnings: Iterable[str] = ()) -> ValidationResult:
        return cls(ok=False, errors=list(errors), warnings=list(warnings))


@dataclass(frozen=True, slots=True)
class SourceRecordDraft:
    """One parsed source row. ``record_type`` tells ``normalize`` which mapping applies."""

    external_record_id: str
    effective_at: datetime | None
    payload: Mapping[str, Any]
    record_type: str = ""


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """What the ``source`` row records about a connector's source."""

    owner: str
    source_type: str
    access_method: str
    terms_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class JurisdictionDraft:
    name: str
    type: str
    state_code: str | None = None
    fips_code: str | None = None

    @property
    def natural_key(self) -> NaturalKey:
        return ("jurisdiction", self.name, self.type)


@dataclass(frozen=True, slots=True)
class CourtDraft:
    canonical_name: str
    court_type: str
    jurisdiction_key: NaturalKey
    external_ids: Mapping[str, str] = field(default_factory=dict)
    state_code: str | None = None
    active_from: date | None = None
    active_to: date | None = None

    @property
    def natural_key(self) -> NaturalKey:
        return ("court", self.canonical_name, self.court_type)


@dataclass(frozen=True, slots=True)
class JudgeDraft:
    canonical_name: str
    normalized_name: str
    # (identifier system, value), e.g. ("fjc_nid", "1377101"); the pair must
    # also appear in ``external_ids`` and is the exact-match resolution key.
    identity_key: tuple[str, str]
    external_ids: Mapping[str, str] = field(default_factory=dict)
    status: str = "active"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def natural_key(self) -> NaturalKey:
        return ("judge", *self.identity_key)


@dataclass(frozen=True, slots=True)
class JudgeServiceDraft:
    judge_key: NaturalKey
    court_key: NaturalKey
    position_type: str
    start_date: date | None
    end_date: date | None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @property
    def natural_key(self) -> NaturalKey:
        start = self.start_date.isoformat() if self.start_date else ""
        return (
            "judge_service",
            *self.judge_key[1:],
            *self.court_key[1:],
            self.position_type,
            start,
        )


CanonicalRecord = JurisdictionDraft | CourtDraft | JudgeDraft | JudgeServiceDraft


@dataclass(frozen=True, slots=True)
class Provenance:
    """The source record a draft was derived from."""

    source_record_id: uuid.UUID
    raw_sha256: str


@dataclass(frozen=True, slots=True)
class TaggedRecord:
    """A canonical draft together with its provenance (assigned by the runner)."""

    record: CanonicalRecord
    provenance: Provenance | None


class SourceConnector(Protocol):
    """The brief's connector interface, plus the identifying attributes."""

    source_id: str
    parser_version: str
    source_info: SourceInfo

    async def discover(self) -> list[SourceArtifact]: ...

    async def fetch(self, artifact: SourceArtifact) -> RawArtifact: ...

    def validate_raw(self, artifact: RawArtifact) -> ValidationResult: ...

    def parse(self, artifact: RawArtifact) -> Iterable[SourceRecordDraft]: ...

    def normalize(self, record: SourceRecordDraft) -> Iterable[CanonicalRecord]: ...


@runtime_checkable
class SupportsCheckpoint(Protocol):
    """Optional hook for incremental sources (cursors, modified timestamps).

    The runner calls ``restore_checkpoint`` with the checkpoint recorded by
    the source's last successful run before ``discover`` and stores the
    value of ``checkpoint()`` on the run afterwards.
    """

    def restore_checkpoint(self, checkpoint: Checkpoint | None) -> None: ...

    def checkpoint(self) -> Checkpoint | None: ...
